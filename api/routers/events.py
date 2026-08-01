"""
사용자 행동 계측
POST /api/v1/events           이벤트 1건 기록 (fire-and-forget)
GET  /api/v1/events/summary   화면별 체류시간·이탈률·클릭수·근거링크 클릭률 집계
담당: 박진영 (API·DB) / 조희진 (프론트 계측 설계)

8/5 60대 사용성 테스트에서 정량 데이터를 얻기 위해 추가한다. verdict/tagging 과
달리 이 라우터는 서비스의 핵심 판단 로직과 무관한 관측용 데이터라 ?mock=1 개념이
없다 - 항상 실제로 기록한다.

★★ 개인정보 원칙 (반드시 지킬 것) ★★
- device_id 는 원문을 저장하지 않는다. 받는 즉시 SHA-256 해시로 바꿔서만 DB 에 남긴다
  (users.device_hash 와 동일한 방식 - onboarding.py 참고).
- 화면에 입력된 텍스트(붙여넣은 글, 질문 답변 자유 서술 등)는 절대 수집하지 않는다.
  target/meta 는 버튼 id·화면 이름·오류 유형처럼 짧고 정해진 값만 허용하고,
  그 외(긴 문자열, 알 수 없는 타입)는 조용히 잘라내거나 버린다 - 검증 실패를
  사용자에게 에러로 보여주지 않는다.
- 이 엔드포인트는 절대 사용자 흐름을 막으면 안 된다. 어떤 이유로든 기록에 실패해도
  200(accepted=0)을 돌려주고 서버 로그에만 남긴다.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.db import Event, get_db
from models.schemas import EventAckResponse, EventIn, EventSummaryResponse

router = APIRouter(prefix="/events", tags=["events"])
log = logging.getLogger("gyeotnun.events")

_ALLOWED_SCREENS = ("S1", "S2", "S3", "S4", "S5")
_ALLOWED_EVENT_TYPES = {"screen_enter", "screen_leave", "click", "evidence_link_click", "error"}
_MAX_TARGET_LEN = 64
_MAX_META_KEYS = 5
_MAX_META_VALUE_LEN = 64
# 체류시간/첫클릭시간 계산에 쓰는 시간차가 이보다 크면 표본에서 뺀다 - 탭을 열어
# 두고 자리를 비운 세션이 평균을 왜곡하는 것을 막는다(정상적인 화면 체류는
# 몇 초~몇 분 수준이라 1시간이면 넉넉한 상한이다).
_MAX_PLAUSIBLE_GAP_SEC = 3600


def _hash_device(device_id: str) -> str:
    return hashlib.sha256((device_id or "").encode()).hexdigest()


def _sanitize_target(value: str | None) -> str | None:
    """자유 텍스트 유입 방지 - 길이만 제한한다(내용 검열은 하지 않는다,
    프론트가 어차피 버튼 id 같은 정해진 값만 보내도록 설계돼 있다)."""
    if not value:
        return None
    return str(value)[:_MAX_TARGET_LEN]


def _sanitize_meta(meta: dict | None) -> dict:
    """소량의 구조화된 값만 통과시킨다. 자유 텍스트가 실려 오는 것을 막는 최후 방어선."""
    if not isinstance(meta, dict):
        return {}
    out: dict = {}
    for k, v in list(meta.items())[:_MAX_META_KEYS]:
        key = str(k)[:32]
        if isinstance(v, bool) or isinstance(v, (int, float)):
            out[key] = v
        else:
            out[key] = str(v)[:_MAX_META_VALUE_LEN]
    return out


def _parse_client_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


@router.post("", response_model=EventAckResponse, summary="행동 이벤트 기록 (fire-and-forget)")
async def create_event(body: EventIn, db: Session = Depends(get_db)):
    # ★ 계측은 절대 사용자 흐름을 막지 않는다 - 어떤 예외든 여기서 삼키고 200을 돌려준다.
    try:
        if body.event_type not in _ALLOWED_EVENT_TYPES:
            return EventAckResponse(accepted=0)
        row = Event(
            device_hash=_hash_device(body.device_id),
            session_id=(body.session_id or "unknown")[:64],
            event_type=body.event_type,
            screen=body.screen if body.screen in _ALLOWED_SCREENS else None,
            target=_sanitize_target(body.target),
            client_ts=_parse_client_ts(body.ts),
            meta=_sanitize_meta(body.meta),
        )
        db.add(row)
        db.commit()
        return EventAckResponse(accepted=1)
    except Exception as e:  # noqa: BLE001 - 계측 실패가 사용자 화면에 나가면 안 된다
        log.warning("[events] 기록 실패(무시하고 계속): %s", e)
        return EventAckResponse(accepted=0)


@router.get(
    "/summary",
    response_model=EventSummaryResponse,
    summary="집계 - 화면별 체류시간/이탈률/클릭수/근거링크 클릭률 (8/5 사용성 테스트용)",
)
async def summary(db: Session = Depends(get_db)):
    """세션 단위로 재구성해 집계한다. 표본이 적은 사용성 테스트 규모(하루치, 참가자
    수십 명 이하)를 가정하고 DB 에서 전부 읽어 파이썬으로 계산한다 - SQL 윈도우
    함수보다 느리지만, 이 규모에서는 차이가 없고 계산 과정이 훨씬 읽기 쉽다.
    """
    rows = db.query(Event).order_by(Event.session_id, Event.created_at).all()

    sessions: dict[str, list[Event]] = {}
    for r in rows:
        sessions.setdefault(r.session_id, []).append(r)

    reached: dict[str, int] = {s: 0 for s in _ALLOWED_SCREENS}
    exited_last: dict[str, int] = {s: 0 for s in _ALLOWED_SCREENS}
    dwell: dict[str, list[float]] = {s: [] for s in _ALLOWED_SCREENS}
    first_click_latency: dict[str, list[float]] = {s: [] for s in _ALLOWED_SCREENS}
    click_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    evidence_click_sessions = 0

    for evs in sessions.values():
        enters = [e for e in evs if e.event_type == "screen_enter" and e.screen]
        if not enters:
            continue

        for s in {e.screen for e in enters}:
            reached[s] += 1
        exited_last[enters[-1].screen] += 1

        for e in enters:
            # 이 화면 진입 시각 이후, 같은 화면의 leave 중 가장 빠른 것 = 체류시간
            leave = next(
                (x for x in evs if x.event_type == "screen_leave" and x.screen == e.screen and x.created_at >= e.created_at),
                None,
            )
            if leave:
                gap = (leave.created_at - e.created_at).total_seconds()
                if 0 <= gap <= _MAX_PLAUSIBLE_GAP_SEC:
                    dwell[e.screen].append(gap)

            # 이 화면 진입 시각 이후, 같은 화면의 첫 클릭 = 진입~첫클릭 시간
            first_click = next(
                (x for x in evs if x.event_type == "click" and x.screen == e.screen and x.created_at >= e.created_at),
                None,
            )
            if first_click:
                gap = (first_click.created_at - e.created_at).total_seconds()
                if 0 <= gap <= _MAX_PLAUSIBLE_GAP_SEC:
                    first_click_latency[e.screen].append(gap)

        if any(e.event_type == "evidence_link_click" for e in evs):
            evidence_click_sessions += 1

        for e in evs:
            if e.event_type == "click" and e.target:
                click_counts[e.target] = click_counts.get(e.target, 0) + 1
            if e.event_type == "error" and e.target:
                error_counts[e.target] = error_counts.get(e.target, 0) + 1

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    total_sessions = sum(1 for evs in sessions.values() if any(e.event_type == "screen_enter" for e in evs))
    s3_reached = reached.get("S3", 0)

    return EventSummaryResponse(
        total_sessions=total_sessions,
        screen_reached_sessions=reached,
        screen_avg_dwell_sec={s: _avg(v) for s, v in dwell.items()},
        screen_dwell_sample_count={s: len(v) for s, v in dwell.items()},
        screen_drop_off_rate={
            s: round(exited_last[s] / reached[s], 3) if reached[s] else 0.0 for s in _ALLOWED_SCREENS
        },
        screen_avg_time_to_first_click_sec={s: _avg(v) for s, v in first_click_latency.items()},
        click_counts=click_counts,
        evidence_link_click_sessions=evidence_click_sessions,
        evidence_link_click_rate=round(evidence_click_sessions / s3_reached, 3) if s3_reached else 0.0,
        error_counts=error_counts,
    )
