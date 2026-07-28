"""
S1/S2 - 업로드 & 근거 수집
POST /api/v1/checks
GET  /api/v1/checks/{check_id}/evidence
담당: 박진영(계약) / 박진(OCR·마스킹) / 김유리(검색)
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile

from config import settings
from mocks import fixtures
from models.schemas import CheckCreateResponse, EvidenceResponse
from routers._common import MockFlag, not_implemented, use_mock
from services import masking, ocr, search

router = APIRouter(prefix="/checks", tags=["checks"])

# 메모리 임시 저장소 (해커톤용). TODO(박진영): DB 세션으로 교체.
_MEMORY_STORE: dict[str, dict] = {}


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
            extracted = ocr.extract_from_link(link)
        elif image:
            raw = await image.read()
            if len(raw) > settings.MAX_UPLOAD_MB * 1024 * 1024:
                raise ValueError(f"이미지가 너무 큽니다. {settings.MAX_UPLOAD_MB}MB 이하로 올려 주세요.")
            try:
                extracted = ocr.extract_from_image(raw)
            finally:
                masking.discard_original(raw)   # ★ 원본 즉시 파기
        else:
            return CheckCreateResponse(
                check_id=check_id, extracted_text="", masked=False,
                masked_items=[], detected_domain=None, status="needs_input",
            )
    except (NotImplementedError, Exception) as e:  # noqa: BLE001
        raise not_implemented(e) from e

    masked = masking.mask_text(extracted.text)    # ★ DB 저장 전 비식별화
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
async def get_evidence(check_id: str, mock: int = MockFlag):
    """공공데이터 대조 + 실시간 검색 결과.

    ★ verdict_hint 는 needs_check / partially_matched / no_source_found 뿐이다.
      true/false 를 반환하지 않는 것이 곁눈의 원칙이다.
    """
    if use_mock(mock):
        data = dict(fixtures.EVIDENCE)
        data["check_id"] = check_id
        return EvidenceResponse(**data)

    stored = _MEMORY_STORE.get(check_id)
    if not stored:
        raise not_implemented(RuntimeError(f"check_id={check_id} 를 찾을 수 없습니다. 먼저 POST /checks 를 호출하세요."))
    try:
        result = search.collect_evidence(stored["masked_text"], domain=stored.get("domain"))
    except Exception as e:  # noqa: BLE001
        raise not_implemented(e) from e
    return EvidenceResponse(
        check_id=check_id,
        verdict_hint=result.verdict_hint,
        signals=result.signals,
        references=result.references,
    )
