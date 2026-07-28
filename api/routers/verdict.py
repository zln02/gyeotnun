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
from routers._common import MockFlag, use_mock
from routers.checks import _MEMORY_STORE
from services import search, tagger

router = APIRouter(prefix="/checks", tags=["verdict"])


@router.post("/{check_id}/verdict", response_model=VerdictResponse, summary="사용자 판단 기록")
async def record_verdict(check_id: str, body: VerdictRequest, mock: int = MockFlag):
    """사용자가 고른 행동(decision)을 기록하고 오판유형을 태깅한다."""
    if use_mock(mock):
        data = dict(fixtures.VERDICT)
        data["check_id"] = check_id
        return VerdictResponse(**data)

    stored = _MEMORY_STORE.get(check_id, {})
    text = stored.get("masked_text", "")
    signals = search.detect_signals(text)                     # 키 불필요 (규칙 기반)
    error_type, confidence = tagger.tag_error_type(signals, text=text, decision=body.decision)
    return VerdictResponse(
        check_id=check_id,
        tagged_error_type=error_type,
        confidence=confidence,
        message=tagger.build_message(error_type, body.decision),
    )
