"""라우터 공통 유틸: mock 판별 / 키 없음 → 501 변환 / 운영자 게이트."""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, Query

from config import MissingKeyError, settings
from services.incident_log import log_incident

MockFlag = Query(
    0,
    alias="mock",
    description="1 이면 mocks/fixtures.py 고정 응답을 반환한다 (API 키 없이 전 플로우 시연 가능).",
)

# 운영자 전용 엔드포인트(집계류)에서 쓰는 공유 헤더. 값은 config.settings.ADMIN_TOKEN.
AdminTokenHeader = Header(None, alias="X-Admin-Token", description="운영자 전용 집계 접근 토큰")


def use_mock(mock: int) -> bool:
    """?mock=1 이거나, 데모 폴백 설정이 켜져 있으면 mock 을 쓴다."""
    return bool(mock) or settings.DEMO_FALLBACK_TO_MOCK


def require_operator(x_admin_token: Optional[str]) -> None:
    """운영자 전용 게이트. settings.ADMIN_TOKEN 이 비어 있으면(기본) 항상 닫는다(404).

    ★ 인증 없이 전 세션/전 오류 집계를 노출하던 엔드포인트(events/summary,
      errors/summary)를 막는다. 서명 토큰·세션 발급 체계가 아니라 단순 공유 비밀
      (환경변수) 대조다. 실패 시 존재 사실을 흘리지 않도록 404 로 응답한다.
    ★ 두 집계 엔드포인트가 같은 게이트를 써야 문서에 '운영자 전용'이라 쓸 수 있다
      (한쪽만 막으면 다른 쪽으로 그대로 새어나간다).
    """
    expected = settings.ADMIN_TOKEN
    if not expected or x_admin_token != expected:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "code": "ST-001", "message": "요청하신 자료를 찾을 수 없습니다."},
        )


def not_implemented(
    err: Exception,
    code: str = "SYS-000",
    *,
    screen: Optional[str] = None,
    device_id: Optional[str] = None,
) -> HTTPException:
    """키 없음/미구현/예외를 501 + 사람이 읽는 안내 + 오류 코드로 변환한다.

    ★ 2026-08 오류 코드 체계 도입: 기존 메시지·상태코드(501)는 그대로 두고
      "code" 필드만 추가한다(docs/error_codes.md·services/error_codes.py 가 단일
      소스). 호출부(각 라우터)가 상황에 맞는 code 를 넘긴다 - 안 넘기면 SYS-000
      (미분류 안전망)으로 처리된다.
    """
    if isinstance(err, MissingKeyError):
        detail = {
            "error": "missing_api_key",
            "code": code,
            "key": err.key_name,
            "message": str(err),
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요.",
        }
    else:
        detail = {
            "error": "not_implemented",
            "code": code,
            "message": str(err) or "아직 구현되지 않은 기능입니다.",
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요.",
        }
    log_incident(code, screen=screen, device_id=device_id, detail=str(err)[:120])
    return HTTPException(status_code=501, detail=detail)
