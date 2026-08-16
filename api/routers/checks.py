"""
S1/S2 - 업로드 & 근거 수집
POST /api/v1/checks
GET  /api/v1/checks/{check_id}/evidence
담당: 박진영(계약) / 박진(OCR·마스킹) / 김유리(검색)
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool

from config import settings
from mocks import fixtures
from models.schemas import CheckCreateResponse, EvidenceResponse
from routers._common import MockFlag, not_implemented, use_mock
from services import masking, ocr, search

router = APIRouter(prefix="/checks", tags=["checks"])

# 메모리 임시 저장소 (해커톤용). TODO(박진영): DB 세션으로 교체.
_MEMORY_STORE: dict[str, dict] = {}

# ★ 소유자로 인정하지 않는 값. create_check 의 device_id 기본값이 "anonymous" 라,
#   이를 소유자로 허용하면 "anonymous" 를 보내는 누구나 서로의 기록을 읽는 구멍이 된다.
#   정상 프론트는 항상 실제 UUID(deviceId())를 보내므로 이 거부는 정상 흐름을 깨지 않는다.
_NON_OWNER_IDS = {"", "anonymous"}


def require_owner(check_id: str, device_id: Optional[str]) -> dict:
    """이 check_id 기록의 소유자만 통과시킨다 (IDOR 방지).

    저장 시 함께 넣어 둔 device_id 와 요청자의 device_id 를 대조한다.
    ★ '없는 id / 남의 id / device_id 미제공 / 익명 소유자·요청자' 를 **모두 같은
      404 로** 거부한다. 구분하면 check_id 존재 여부가 새어나가기 때문이다.
    ★ 한계: device_id 는 프론트가 보내는 값이라 위조 가능하다. 이 최소 수정은
      "아무 id 나 넣으면 남의 기록이 나오는" 접근 통제 부재만 막는다. 서명 토큰·
      세션 발급 같은 근본 인증은 별도 과제다(docs/security 참조).
    """
    stored = _MEMORY_STORE.get(check_id)
    owner = stored.get("device_id") if stored else None
    if (
        not device_id
        or device_id in _NON_OWNER_IDS      # 요청자가 익명값을 내밀면 거부
        or stored is None
        or owner in _NON_OWNER_IDS          # 익명으로 만들어진 기록은 아무도 못 읽음
        or owner != device_id
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "code": "ST-001",
                "message": "요청하신 확인 내역을 찾을 수 없습니다.",
            },
        )
    return stored


@router.post("", response_model=CheckCreateResponse, summary="의심 정보 업로드")
async def create_check(
    mock: int = MockFlag,
    device_id: str = Form("anonymous", description="비회원 식별자"),
    image: Optional[UploadFile] = File(None, description="카카오톡 캡처 등 이미지"),
    link: Optional[str] = Form(None, description="유튜브/블로그 URL"),
    text: Optional[str] = Form(None, description="붙여넣은 텍스트"),
):
    """이미지·링크·텍스트 중 하나를 받아 텍스트를 추출하고 개인정보를 가린다.

    ★ 원본 이미지는 이 함수 안에서만 존재하고, 응답 후 파기된다. 저장하지 않는다.
    """
    if use_mock(mock):
        return CheckCreateResponse(**fixtures.CHECK_CREATE)

    check_id = f"chk_{uuid.uuid4().hex[:10]}"
    try:
        if text:
            extracted = ocr.extract_from_text(text)
        elif link:
            # ★ 링크 본문 가져오기는 네트워크 대기다 - 루프 밖으로.
            extracted = await run_in_threadpool(ocr.extract_from_link, link)
        elif image:
            raw = await image.read()
            if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
                masking.discard_original(raw)
                # ★ 파일이 너무 큰 건 서버 오류가 아니다. 501 대신 200으로 안내하고
                #   텍스트 직접 입력 경로를 제시한다.
                return CheckCreateResponse(
                    check_id=check_id, extracted_text="", masked=False, masked_items=[],
                    detected_domain=None, status="failed", error_code="IN-001",
                    message=(
                        f"사진 용량이 너무 큽니다 ({len(raw) / 1024 / 1024:.1f}MB). "
                        f"{settings.MAX_UPLOAD_MB}MB 이하 사진으로 다시 올려 주시거나, "
                        "'글로 붙여넣기'로 내용을 직접 입력해 주세요."
                    ),
                )
            try:
                # ★ OCR 은 요청당 2.2초짜리 CPU 작업이다 - 루프 밖으로.
                extracted = await run_in_threadpool(ocr.extract_from_image, raw)
            finally:
                masking.discard_original(raw)   # ★ 원본 즉시 파기
        else:
            return CheckCreateResponse(
                check_id=check_id, extracted_text="", masked=False,
                masked_items=[], detected_domain=None, status="needs_input",
            )
    except (NotImplementedError, Exception) as e:  # noqa: BLE001
        # ★ 오류 코드 체계(2026-08): 어느 입력 경로에서 실패했는지로 코드를 나눈다.
        #   link → 아직 미구현(IN-002), image → AI 인식 서비스 자체가 실패(EX-001),
        #   그 외(text 경로는 원래 예외를 던지지 않는다)는 미분류 안전망(SYS-000).
        code = "IN-002" if link else ("EX-001" if image else "SYS-000")
        raise not_implemented(e, code, screen="S1", device_id=device_id) from e

    if extracted.status == "failed":
        # ★ 인식 실패(흐림/텍스트 없음/캡처 아님)도 서버 오류가 아니다.
        #   ocr.extract_from_image() 가 예외 대신 이 상태로 알려 준 정상 결과다.
        return CheckCreateResponse(
            check_id=check_id, extracted_text="", masked=False, masked_items=[],
            detected_domain=None, status="failed", error_code="RC-001",
            message=(
                "사진에서 글자를 읽지 못했습니다. 밝은 곳에서 화면 전체가 나오게 "
                "다시 찍어 주시거나, '글로 붙여넣기'로 내용을 직접 입력해 주세요."
            ),
        )

    try:
        masked = masking.mask_text(extracted.text)    # ★ DB 저장 전 비식별화
    except Exception as e:  # noqa: BLE001 - 이 지점은 기존에 보호되지 않던 곳이라 새로 감쌌다
        raise not_implemented(e, "MK-001", screen="S1", device_id=device_id) from e
    _MEMORY_STORE[check_id] = {
        "masked_text": masked.text,
        "domain": extracted.detected_domain,
        "device_id": device_id,
    }
    return CheckCreateResponse(
        check_id=check_id,
        extracted_text=masked.text,
        masked=masked.masked,
        masked_items=masked.masked_items,
        detected_domain=extracted.detected_domain,
        status=extracted.status,
    )


@router.get("/{check_id}/evidence", response_model=EvidenceResponse, summary="근거 수집 결과")
async def get_evidence(
    check_id: str,
    mock: int = MockFlag,
    device_id: Optional[str] = Query(None, description="이 확인 건을 만든 기기 식별자 (소유권 확인용)"),
):
    """공공데이터 대조 + 실시간 검색 결과.

    ★ verdict_hint 는 needs_check / partially_matched / no_source_found 뿐이다.
      true/false 를 반환하지 않는 것이 곁눈의 원칙이다.
    """
    if use_mock(mock):
        # 데모(mock)는 고정 픽스처만 반환하고 실제 저장 데이터를 건드리지 않으므로
        # 소유권 검사 대상이 아니다(남의 기록이 새어나갈 경로가 없다).
        data = dict(fixtures.EVIDENCE)
        data["check_id"] = check_id
        return EvidenceResponse(**data)

    stored = require_owner(check_id, device_id)   # ★ IDOR 방지: 소유자만 통과
    try:
        # ★ 2026-08-16 (#33 2단계) — 이벤트 루프 밖에서 돈다.
        #   임베딩 추론(CPU)과 url_expand 의 외부 HEAD(최대 3초)가 여기 들어 있다.
        #   전에는 async def 안에서 동기로 불러 그 동안 다른 사용자가 전부 멈췄다.
        result = await run_in_threadpool(
            search.collect_evidence, stored["masked_text"], domain=stored.get("domain"))
    except Exception as e:  # noqa: BLE001
        raise not_implemented(e, "SR-001", screen="S2", device_id=stored.get("device_id")) from e
    return EvidenceResponse(
        check_id=check_id,
        verdict_hint=result.verdict_hint,
        signals=result.signals,
        references=result.references,
    )
