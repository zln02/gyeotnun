"""
S4 - 판단 기록 & 오판유형 태깅
POST /api/v1/checks/{check_id}/verdict
담당: 장지석 (태깅)

★ 최종 결정은 언제나 사용자가 한다. AI는 결정을 대신하지 않고 기록하고 격려한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from mocks import fixtures
from models.schemas import VerdictRequest, VerdictResponse
from routers._common import MockFlag, not_implemented, use_mock
from routers.checks import require_owner
from services import search, tagger

router = APIRouter(prefix="/checks", tags=["verdict"])


@router.post("/{check_id}/verdict", response_model=VerdictResponse, summary="사용자 판단 기록")
async def record_verdict(check_id: str, body: VerdictRequest, mock: int = MockFlag):
    """사용자가 고른 행동(decision)을 기록하고 오판유형을 태깅한다.

    ★ tag_error_type_llm() 은 실패해도 예외를 던지지 않고 규칙 기반으로 내려가므로
      이 엔드포인트는 사실상 항상 200을 돌려준다. try/except 는 정말 예상 못 한
      버그(예: _MEMORY_STORE 형태가 바뀌는 등)에 대한 방어선이다.
    """
    if use_mock(mock):
        data = dict(fixtures.VERDICT)
        data["check_id"] = check_id
        return VerdictResponse(**data)

    # ★ IDOR 방지: 소유자만 통과. try 밖에서 검사한다 - 여기서 나는 404(HTTPException)를
    #   아래 except 가 501 로 삼키면 안 되기 때문이다.
    stored = require_owner(check_id, body.device_id)
    try:
        text = stored.get("masked_text", "")
        signals = search.detect_signals(text)                     # 키 불필요 (규칙 기반)
        error_type, confidence = tagger.tag_error_type_llm(text, signals, decision=body.decision)
    except Exception as e:  # noqa: BLE001 - tag_error_type_llm() 은 실패해도 예외를 던지지
        # 않으므로(자체적으로 규칙 기반 GN-002 로 대체) 여기 도달하는 예외는 정말 예상 밖의
        # 버그다. 특정 영역으로 분류할 근거가 없어 미분류 안전망(SYS-000)을 쓴다.
        raise not_implemented(e, "SYS-000", screen="S4", device_id=stored.get("device_id")) from e

    return VerdictResponse(
        check_id=check_id,
        tagged_error_type=error_type,
        confidence=confidence,
        message=tagger.build_message(error_type, body.decision),
    )
