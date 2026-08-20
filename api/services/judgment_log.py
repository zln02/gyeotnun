"""판단 행동 로그 — 세션 1개당 1행 (2026-08-20 신설).

■ 무엇을 재는가
  "무엇을 확인하고 무엇을 근거로 결정했나"를 세션 단위로 남긴다.
  events 표(화면 진입·클릭 낱개)와 목적이 다르다 - 저쪽은 **화면을 어떻게 썼나**,
  이쪽은 **판단을 어떻게 했나**다. session_id 를 같은 값으로 주면 두 표가 조인된다.

■ ★★ 개인정보: 자유 텍스트는 한 글자도 담지 않는다 ★★
  - user_ref 는 sha256(device_id). 원문은 받지도 저장하지도 않는다.
  - 나머지는 bool·정수·실수이거나 **허용 목록에 있는 짧은 코드값**뿐이다.
    허용 목록에 없으면 조용히 버린다(None). 잘라 넣지 않는다 - 자르면 자유 텍스트의
    앞부분이 그대로 남는다. events 의 target 은 길이만 잘랐지만, 여기 컬럼들은
    값의 종류가 미리 정해져 있으므로 더 강하게 막을 수 있다.
  - tests/test_judgment_log.py 가 이 원칙 두 가지(컬럼에 자유 텍스트 없음,
    허용 목록 밖 값은 버림)를 자동으로 지킨다.

■ ★ 절대 사용자 흐름을 막지 않는다
  routers/events.py 와 같은 규칙이다. 여기서 나는 모든 예외를 삼키고, 서버는
  incident_log 로 스스로 인지한다. 계측 실패가 확인 화면을 막으면 본말전도다.

■ ★ NULL 은 '아니오'가 아니라 '측정하지 않음'이다
  checked_* 와 question_opened 는 클라이언트가 보고할 때만 값이 들어간다.
  보고가 없으면 NULL 로 남는다. 집계할 때 NULL 을 0으로 세면 "아무도 출처를
  확인하지 않았다"는 거짓 결론이 나온다 - summary 계산은 NULL 을 표본에서 뺀다.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import logging
from typing import Optional

from models.db import JudgmentLog, SessionLocal
from services.incident_log import log_incident

log = logging.getLogger("gyeotnun.judgment_log")

# ── 허용 목록 (여기 없는 값은 버린다)
#
# ★ input_type: 지시서는 photo/link/voice 였는데 실제 입력 경로는 image/link/text 다.
#   - photo  ← 서비스의 image (사진 업로드)
#   - link   ← link
#   - text   ← 붙여넣기. **지시서에 없었지만 실제로 가장 많이 쓰이는 경로**라 넣었다.
#              빼면 대부분의 세션이 input_type=NULL 로 남는다.
#   - voice  ← ★ 지금 서비스에 음성 입력 경로가 없다. 값만 미리 열어 둔다.
#              (평가셋 CSV 의 '입력채널=음성' 은 평가용 라벨이지 API 경로가 아니다.)
ALLOWED_INPUT_TYPES = {"photo", "link", "text", "voice"}
_INPUT_TYPE_ALIASES = {"image": "photo", "photo": "photo", "link": "link",
                       "text": "text", "voice": "voice"}

# ★ session_type: 훈련 전후 비교용. 서비스에는 아직 이 구분이 없고 **클라이언트가
#   보내야만** 값이 생긴다. 서버가 임의로 baseline 을 채우지 않는다 - 안 보낸 것을
#   baseline 으로 세면 훈련 효과가 있는 것처럼 보이는 방향으로 데이터가 오염된다.
ALLOWED_SESSION_TYPES = {"baseline", "training", "posttest"}

# ★ decision: 지시서는 신청/공유/보류/안함이었다. 기존 Decision 리터럴과의 대조:
#     신청 = apply        (있음)
#     보류 = hold         (있음)
#     안함 = not_apply    (있음)
#     공유 = share        (★ 지금 화면에 '공유' 버튼이 없다 - 값만 열어 둔다)
#     ask_family (가족에게 물어보기) 는 기존에 있는 값이라 함께 받는다.
#       ★ ask_family 를 '공유'로 접지 않는다. 가족에게 묻는 것과 남에게 퍼뜨리는 것은
#         정반대 행동이고, 하나로 세면 전파 위험 지표가 통째로 뒤집힌다.
ALLOWED_DECISIONS = {"apply", "share", "hold", "not_apply", "ask_family"}

ALLOWED_CARD_RESULTS = {"correct", "wrong", "skipped"}

_MAX_ID_LEN = 64
_MAX_CARD_ID_LEN = 40
_MAX_TAG_LEN = 32


def hash_device(device_id: Optional[str]) -> Optional[str]:
    """device_id → sha256. check_store.hash_device 와 같은 방식(같은 값이 나온다).

    ★ 별도 해시 체계를 만들지 않는다. 다르게 만들면 checks·events·judgment_logs 가
      같은 사람을 서로 다른 사람으로 세게 된다.
    """
    if not device_id:
        return None
    return hashlib.sha256(device_id.encode()).hexdigest()


def session_key(session_id: Optional[str], check_id: Optional[str] = None) -> Optional[str]:
    """세션 키를 정한다.

    ★ 클라이언트가 session_id 를 보내면 그것을 쓴다(events 와 조인된다).
      아직 안 보내는 화면이 있으므로, 없으면 "chk:<check_id>" 로 대체한다.
      대체 키를 쓰면 events 와 조인은 안 되지만 판단 기록 자체는 남는다.
      ★ 대체 키가 있어서 프론트 변경 없이도 오늘부터 기록이 쌓인다.
    """
    if session_id:
        return str(session_id)[:_MAX_ID_LEN]
    if check_id:
        return f"chk:{check_id}"[:_MAX_ID_LEN]
    return None


def _pick(value: Optional[str], allowed: set[str], *, aliases: dict | None = None) -> Optional[str]:
    """허용 목록에 있으면 통과, 없으면 None. ★ 자르지 않고 버린다."""
    if value is None:
        return None
    v = str(value).strip()
    if aliases:
        v = aliases.get(v, v)
    return v if v in allowed else None


def _as_bool(value) -> Optional[bool]:
    """★ None 은 None 으로 남긴다. 측정하지 않은 것을 False 로 바꾸지 않는다."""
    return None if value is None else bool(value)


def _count_checks(*flags: Optional[bool]) -> Optional[int]:
    """확인 항목 개수. ★ 하나도 보고되지 않았으면 0이 아니라 None 이다."""
    if all(f is None for f in flags):
        return None
    return sum(1 for f in flags if f is True)


class _session:
    """세션 획득까지 감싸는 컨텍스트 매니저.

    ★ 왜 필요한가: 전에는 `db = SessionLocal()` 이 try 밖에 있었다. 커넥션 풀이
      마르거나 엔진이 깨지면 **세션을 만드는 그 줄에서** 예외가 나고, 그게 그대로
      라우터로 올라가 확인 화면이 500 이 된다 - "계측은 절대 흐름을 막지 않는다"는
      이 파일의 약속이 정확히 그 자리에서 깨진다.
      tests/test_judgment_log.py::test_recording_failure_never_raises 가 잡았다.
    ★ 예외를 삼키고 None 을 넘긴다. 호출부는 db 가 None 이면 아무것도 하지 않는다.
    """

    def __init__(self, where: str, device_id: Optional[str] = None):
        self.where, self.device_id, self.db = where, device_id, None

    def __enter__(self):
        try:
            self.db = SessionLocal()
        except Exception as e:  # noqa: BLE001
            _swallow(self.where, e, self.device_id)
            self.db = None
        return self.db

    def __exit__(self, exc_type, exc, tb):
        if exc is not None and self.db is not None:
            try:
                self.db.rollback()
            except Exception:  # noqa: BLE001 - 롤백 실패까지 위로 올리지 않는다
                pass
        if exc is not None:
            _swallow(self.where, exc, self.device_id)
        if self.db is not None:
            try:
                self.db.close()
            except Exception:  # noqa: BLE001
                pass
        return True          # ★ 어떤 예외든 여기서 멈춘다


def _swallow(where: str, e: Exception, device_id: Optional[str] = None) -> None:
    log.warning("[judgment_log] %s 실패(무시하고 계속): %s", where, type(e).__name__)
    log_incident("ST-003", device_id=device_id, detail=f"judgment_log.{where}: {type(e).__name__}")


# ─────────────────────────────────────────────────────────── 기록 지점 1. 세션 시작
def start(session_id: Optional[str], *, check_id: str, device_id: Optional[str],
          input_type: Optional[str], session_type: Optional[str] = None) -> None:
    """확인 1건이 만들어질 때(POST /checks) 세션 행을 연다.

    ★ 이미 있는 세션이면 **덮어쓰지 않는다.** 같은 session_id 로 두 번째 자극을
      시작하면 첫 판단이 사라지기 때문이다. 대신 경고를 남긴다 - 클라이언트가
      자극마다 새 session_id 를 발급해야 한다는 신호다.
    """
    key = session_key(session_id, check_id)
    if not key:
        return
    with _session("start", device_id) as db:
        if db is None:
            return
        row = db.get(JudgmentLog, key)
        if row is not None:
            if row.decision is not None:
                log.warning("[judgment_log] 세션 %s 는 이미 판단이 끝났다 - 새 자극이면 "
                            "새 session_id 가 필요하다(이번 건은 기록되지 않는다)", key)
            return
        db.add(JudgmentLog(
            session_id=key,
            user_ref=hash_device(device_id),
            session_type=_pick(session_type, ALLOWED_SESSION_TYPES),
            input_type=_pick(input_type, ALLOWED_INPUT_TYPES, aliases=_INPUT_TYPE_ALIASES),
            questions_shown=0,
        ))
        db.commit()


# ────────────────────────────────────────────────────── 기록 지점 2. 질문을 보여줌
def question_shown(session_id: Optional[str], *, check_id: str,
                   answered: bool = False, opened: Optional[bool] = None) -> None:
    """확인 질문 1개를 내보낼 때(POST /checks/{id}/dialogue) 센다.

    ★ questions_shown 은 서버가 확실히 아는 값이다(응답을 내보냈으니까).
    ★ question_opened 는 다르다. "화면에 떴다"와 "사람이 열어서 읽었다"는 다르다.
      - 클라이언트가 opened 를 명시하면 그 값을 쓴다(가장 정확하다).
      - 없으면 **답을 했는지(answered)** 로 대체한다. 질문에 답한 것은 열었다는
        증거가 되지만, 열고 답하지 않은 경우는 못 잡는다.
      ★ 한 번 True 가 된 뒤에는 False 로 내리지 않는다(다음 턴에 답을 안 했다고
        해서 앞 턴에 연 사실이 사라지지 않는다).
    """
    key = session_key(session_id, check_id)
    if not key:
        return
    with _session("question_shown") as db:
        if db is None:
            return
        row = db.get(JudgmentLog, key)
        if row is None:
            return                                  # start 가 안 열린 세션 - 만들지 않는다
        row.questions_shown = int(row.questions_shown or 0) + 1
        flag = _as_bool(opened) if opened is not None else (True if answered else None)
        if flag is True or (flag is False and row.question_opened is not True):
            row.question_opened = flag
        db.commit()


# ────────────────────────────────────────────────────────── 기록 지점 3. 판단 확정
def decided(session_id: Optional[str], *, check_id: str, decision: str,
            misjudge_tag: Optional[str] = None,
            checked_source=None, checked_author=None,
            checked_date=None, checked_condition=None) -> None:
    """사용자가 행동을 고를 때(POST /checks/{id}/verdict) 마무리한다.

    time_to_decision 은 **세션 행이 열린 시각 ~ 지금**(서버 기준 초)이다.
    ★ 사용자가 화면을 본 시간이 아니다. 탭을 열어 두고 자리를 비우면 그대로 커진다
      (events.summary 가 _MAX_PLAUSIBLE_GAP_SEC 로 거르는 것과 같은 한계다).
      집계할 때 이상치를 빼는 것은 읽는 쪽 몫으로 남긴다 - 여기서 잘라 버리면
      원자료가 사라져 나중에 기준을 바꿀 수 없다.
    """
    key = session_key(session_id, check_id)
    if not key:
        return
    with _session("decided") as db:
        if db is None:
            return
        row = db.get(JudgmentLog, key)
        if row is None:
            return
        row.decision = _pick(decision, ALLOWED_DECISIONS)
        row.misjudge_tag = (str(misjudge_tag)[:_MAX_TAG_LEN] if misjudge_tag else None)
        cs, ca, cd, cc = (_as_bool(checked_source), _as_bool(checked_author),
                          _as_bool(checked_date), _as_bool(checked_condition))
        row.checked_source, row.checked_author = cs, ca
        row.checked_date, row.checked_condition = cd, cc
        row.check_count = _count_checks(cs, ca, cd, cc)
        started = row.created_at or _dt.datetime.utcnow()
        row.time_to_decision = round((_dt.datetime.utcnow() - started).total_seconds(), 1)
        db.commit()


# ──────────────────────────────────────────────────────── 기록 지점 4. 훈련 결과
def card_answered(session_id: Optional[str], *, card_id: Optional[str], result: str,
                  device_id: Optional[str] = None,
                  session_type: Optional[str] = None) -> bool:
    """훈련 카드를 풀었을 때(POST /training/result).

    ★ 훈련 세션은 확인(check) 없이 시작될 수 있으므로, 세션 행이 없으면 여기서 연다.
      이 경로에서는 check_id 대체 키를 쓸 수 없어 **session_id 가 반드시 필요하다.**
    """
    key = session_key(session_id)
    if not key:
        return False
    ok = False
    with _session("card_answered", device_id) as db:
        if db is None:
            return False
        row = db.get(JudgmentLog, key)
        if row is None:
            row = JudgmentLog(session_id=key, user_ref=hash_device(device_id),
                              session_type=_pick(session_type, ALLOWED_SESSION_TYPES),
                              questions_shown=0)
            db.add(row)
        row.card_id = (str(card_id)[:_MAX_CARD_ID_LEN] if card_id else None)
        row.card_result = _pick(result, ALLOWED_CARD_RESULTS)
        db.commit()
        ok = True
    return ok


# ───────────────────────────────────────────────────────────────────── 집계
def summarize(rows: list) -> dict:
    """세션 목록 → 요약. ★ NULL 은 표본에서 뺀다(0으로 세지 않는다).

    각 비율에 **표본 수를 함께 돌려준다.** 비율만 주면 "3명 중 1명"과
    "300명 중 100명"이 똑같이 0.333 으로 보인다.
    """
    def _rate(flagged: list) -> tuple[float, int]:
        vals = [bool(v) for v in flagged if v is not None]
        if not vals:
            return 0.0, 0
        return round(sum(vals) / len(vals), 3), len(vals)

    def _avg(vals: list) -> tuple[float, int]:
        xs = [float(v) for v in vals if v is not None]
        if not xs:
            return 0.0, 0
        return round(sum(xs) / len(xs), 1), len(xs)

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r.session_type or "unknown"] = by_type.get(r.session_type or "unknown", 0) + 1
    decisions: dict[str, int] = {}
    for r in rows:
        if r.decision:
            decisions[r.decision] = decisions.get(r.decision, 0) + 1
    misjudge: dict[str, int] = {}
    for r in rows:
        if r.misjudge_tag:
            misjudge[r.misjudge_tag] = misjudge.get(r.misjudge_tag, 0) + 1

    opened_rate, opened_n = _rate([r.question_opened for r in rows])
    ttd, ttd_n = _avg([r.time_to_decision for r in rows])
    cnt, cnt_n = _avg([r.check_count for r in rows])
    card_ok, card_n = _rate([r.card_result == "correct" for r in rows if r.card_result])

    checked = {}
    for name in ("checked_source", "checked_author", "checked_date", "checked_condition"):
        rate, n = _rate([getattr(r, name) for r in rows])
        checked[name] = rate
        checked[f"{name}_sample"] = n

    return {
        "total_sessions": len(rows),
        "sessions_by_type": by_type,
        "question_opened_rate": opened_rate,
        "question_opened_sample": opened_n,
        "avg_questions_shown": round(
            sum(int(r.questions_shown or 0) for r in rows) / len(rows), 1) if rows else 0.0,
        "checked_rates": checked,
        "avg_check_count": cnt,
        "avg_check_count_sample": cnt_n,
        "decisions": decisions,
        "avg_time_to_decision_sec": ttd,
        "time_to_decision_sample": ttd_n,
        "misjudge_tags": misjudge,
        "card_correct_rate": card_ok,
        "card_sample": card_n,
    }
