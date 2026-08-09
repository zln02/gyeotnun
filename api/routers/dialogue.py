"""
S3 - 질문 카드 (★ 서비스의 핵심 화면)
POST /api/v1/checks/{check_id}/dialogue
담당: 김태희 (프롬프트) / 박진영 (계약)

응답의 question 은 반드시 prompt_chain.validate_question() 을 통과한다.
mock 응답도 예외 없이 같은 검증을 통과시킨다 — 시연에서 나가는 문장도
서비스 원칙을 지켜야 하기 때문이다.
"""
from __future__ import annotations

import logging
from collections import deque

from fastapi import APIRouter

from config import MissingKeyError
from mocks import fixtures
from models.schemas import DialogueRequest, DialogueResponse
from routers._common import MockFlag, not_implemented, use_mock
from routers.checks import require_owner
from services import prompt_chain, search
from services.incident_log import log_incident

router = APIRouter(prefix="/checks", tags=["dialogue"])
log = logging.getLogger("gyeotnun.dialogue")

# ══════════════════════════════════════════════ 폴백률 상시 관측 (2026-08-09)
# ★ 왜 넣는가: 크레딧이 바닥나 **8시간 동안 폴백률 100%** 였는데 아무도 몰랐다.
#   사용자 화면에는 오류가 안 뜨고 질문만 고정 문구가 되는 '조용한 품질 저하'라서다.
#   개별 실패(GN-001)는 이미 기록되지만, "계속 이러고 있다"를 말해 주는 건 없었다.
#
# ★ 최소 구현이다. 최근 N건의 폴백 여부만 메모리에 들고, 비율이 임계를 넘으면
#   경고를 한 번 남긴다. 서비스 동작은 전혀 바꾸지 않는다(관측만).
#   - 프로세스 메모리라 재시작하면 초기화된다. 워커도 1개 전제다
#     (docker-compose.yml 이 --workers 1 로 고정. _MEMORY_STORE 와 같은 제약).
#   - 매 요청 경고하면 로그가 시끄러워지므로, 임계를 넘는 동안에는 한 번만 남기고
#     정상으로 돌아오면 다시 무장한다(플래핑 방지).
_FALLBACK_WINDOW = 20          # 최근 몇 건을 볼 것인가
_FALLBACK_MIN_SAMPLES = 5      # 이만큼 쌓이기 전에는 비율을 말하지 않는다
_FALLBACK_ALERT_RATE = 0.5     # 이 비율을 넘으면 경고
_recent_fallbacks: deque = deque(maxlen=_FALLBACK_WINDOW)
_fallback_alerted = False


def _observe_fallback(is_fallback: bool) -> None:
    """질문 생성 1건의 폴백 여부를 기록하고, 비율이 임계를 넘으면 경고한다."""
    global _fallback_alerted
    _recent_fallbacks.append(bool(is_fallback))
    if len(_recent_fallbacks) < _FALLBACK_MIN_SAMPLES:
        return
    rate = sum(_recent_fallbacks) / len(_recent_fallbacks)
    if rate > _FALLBACK_ALERT_RATE:
        if not _fallback_alerted:
            _fallback_alerted = True
            log.warning("[fallback_rate] 최근 %d건 중 %d건이 기본 질문으로 대체됨 (%.0f%%) "
                        "- 외부 LLM 상태를 점검할 것",
                        len(_recent_fallbacks), sum(_recent_fallbacks), rate * 100)
            log_incident("GN-003", screen="S3",
                         detail=f"최근 {len(_recent_fallbacks)}건 중 폴백 {sum(_recent_fallbacks)}건 "
                                f"({rate * 100:.0f}%)")
    elif _fallback_alerted:
        _fallback_alerted = False   # 정상 복귀 - 다음 악화 때 다시 경고할 수 있게 무장
        log.info("[fallback_rate] 폴백률이 임계 아래로 돌아왔다 (%.0f%%)", rate * 100)


@router.post("/{check_id}/dialogue", response_model=DialogueResponse, summary="확인 질문 받기")
async def next_question(check_id: str, body: DialogueRequest, mock: int = MockFlag):
    """다음 확인 질문 1개를 반환한다. 절대 진위를 판정하지 않는다."""
    if use_mock(mock):
        data = dict(fixtures.dialogue_for(body.turn))
        # ★ mock 이라도 후처리 검증을 통과시킨다 (원칙 위반 문장이 시연에 나가지 않도록)
        checked = prompt_chain.validate_question(
            data["question"],
            allowed_refs=fixtures.allowed_refs(),
            evidence_refs=data.get("evidence_refs"),
        )
        data["question"] = checked.question
        data["evidence_refs"] = checked.evidence_refs
        return DialogueResponse(**data)

    stored = require_owner(check_id, body.device_id)   # ★ IDOR 방지: 소유자만 통과

    history = stored.setdefault("history", [])
    if body.user_reply:
        history.append(f"사용자 답변: {body.user_reply}")

    try:
        evidence = search.collect_evidence(stored["masked_text"], domain=stored.get("domain"))
        vq = prompt_chain.generate_question(
            extracted_text=stored["masked_text"],
            signals=evidence.signals,
            references=evidence.references,
            history=history,
        )
    except Exception as e:  # noqa: BLE001
        # ★ 키 자체가 없어 시도조차 못 한 경우만 외부연동(EX-002)이다. generate_question()
        #   은 호출이 "됐지만" 반복 실패한 경우엔 예외를 던지지 않고 GN-001 로 자체
        #   폴백하므로(services/prompt_chain.py), 여기까지 올라오는 다른 예외는 대부분
        #   collect_evidence() 쪽 예상 밖 버그(SR-001)다.
        code = "EX-002" if isinstance(e, MissingKeyError) else "SR-001"
        raise not_implemented(e, code, screen="S3", device_id=stored.get("device_id")) from e

    _observe_fallback(getattr(vq, "fallback", False))   # 관측만 - 응답은 바꾸지 않는다
    history.append(f"질문{body.turn}: {vq.question}")

    return DialogueResponse(
        turn=body.turn,
        question=vq.question,
        why=vq.why,
        evidence_refs=vq.evidence_refs,
        options=vq.options,
        # 마지막 턴 판단은 계약(3턴)을 따르되, 모델이 먼저 끝내자고 하면 존중한다.
        is_final=body.turn >= 3 or vq.is_final,
    )
