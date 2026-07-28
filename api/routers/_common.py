"""라우터 공통 유틸: mock 판별 / 키 없음 → 501 변환."""
from __future__ import annotations

from fastapi import HTTPException, Query

from config import MissingKeyError, settings

MockFlag = Query(
    0,
    alias="mock",
    description="1 이면 mocks/fixtures.py 고정 응답을 반환한다 (API 키 없이 전 플로우 시연 가능).",
)


def use_mock(mock: int) -> bool:
    """?mock=1 이거나, 데모 폴백 설정이 켜져 있으면 mock 을 쓴다."""
    return bool(mock) or settings.DEMO_FALLBACK_TO_MOCK


def not_implemented(err: Exception) -> HTTPException:
    """키 없음/미구현을 501 + 사람이 읽는 안내로 변환한다."""
    if isinstance(err, MissingKeyError):
        detail = {
            "error": "missing_api_key",
            "key": err.key_name,
            "message": str(err),
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요.",
        }
    else:
        detail = {
            "error": "not_implemented",
            "message": str(err) or "아직 구현되지 않은 기능입니다.",
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요.",
        }
    return HTTPException(status_code=501, detail=detail)
