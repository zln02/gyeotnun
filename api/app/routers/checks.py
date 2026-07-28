"""
곁눈(Gyeotnun) - 검사 생성/조회
담당: 박진

POST /api/checks              캡처 이미지 또는 텍스트 업로드
GET  /api/checks/{check_id}   검사 조회

★ 보안 ★
    업로드된 이미지는 이 함수 안에서만 존재하고, 저장하지 않는다.
    OCR → 마스킹 → 마스킹된 텍스트만 DB 저장 → 이미지 바이트는 폐기.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Check, User
from ..schemas import CheckCreateOut, CheckCreateText, CheckOut
from ..services import masking, ocr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checks", tags=["checks"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


def _get_or_create_user(db: Session, device_id: str | None) -> User | None:
    if not device_id:
        return None
    user = db.query(User).filter(User.device_id == device_id).first()
    if user is None:
        user = User(device_id=device_id)
        db.add(user)
        db.flush()
    return user


@router.post("", response_model=CheckCreateOut, summary="캡처 이미지 업로드 → 검사 생성")
async def create_check(
    file: UploadFile = File(..., description="카톡 캡처 이미지"),
    device_id: str | None = Form(None),
    db: Session = Depends(get_db),
) -> CheckCreateOut:
    """
    이미지를 받아 텍스트를 추출하고, 개인정보를 마스킹해 검사를 생성한다.

    ※ 원본 이미지는 저장하지 않는다.
      image_bytes 는 이 함수 스코프를 벗어나지 않는다.
    """
    image_bytes = await file.read()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="이미지가 너무 큽니다 (최대 10MB).")

    # 1) 텍스트 추출 (담당: 박진)
    result = ocr.extract_text(image_bytes)

    # 2) [보안] 즉시 마스킹. 원문은 변수 밖으로 내보내지 않는다.
    masked_text, masked_kinds = masking.mask_pii_detail(result.get("text", ""))

    # 3) 원본 바이트 폐기
    del image_bytes

    user = _get_or_create_user(db, device_id)

    check = Check(
        user_id=user.id if user else None,
        source_type="image",
        ocr_text_masked=masked_text,
        masked_kinds=masked_kinds,
        status="searching",
        dialogue_log=[],
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    logger.info("검사 생성 id=%s masked_kinds=%s", check.id, masked_kinds)

    return CheckCreateOut(
        check_id=check.id,
        status=check.status,
        ocr_text_masked=check.ocr_text_masked,
        masked_kinds=masked_kinds,
        next=f"/api/checks/{check.id}/evidence",
    )


@router.post("/text", response_model=CheckCreateOut, summary="텍스트/URL로 검사 생성 (개발·데모용)")
def create_check_text(
    payload: CheckCreateText,
    db: Session = Depends(get_db),
) -> CheckCreateOut:
    """이미지 없이 텍스트나 URL로 검사를 만든다. 프론트 개발 편의용."""
    raw = payload.content
    if payload.source_type == "url":
        raw = ocr.extract_from_url(payload.content).get("text", payload.content)

    masked_text, masked_kinds = masking.mask_pii_detail(raw)
    user = _get_or_create_user(db, payload.device_id)

    check = Check(
        user_id=user.id if user else None,
        source_type=payload.source_type,
        source_url=payload.content if payload.source_type == "url" else None,
        ocr_text_masked=masked_text,
        masked_kinds=masked_kinds,
        status="searching",
        dialogue_log=[],
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    return CheckCreateOut(
        check_id=check.id,
        status=check.status,
        ocr_text_masked=check.ocr_text_masked,
        masked_kinds=masked_kinds,
        next=f"/api/checks/{check.id}/evidence",
    )


@router.get("/{check_id}", response_model=CheckOut, summary="검사 조회")
def get_check(check_id: int, db: Session = Depends(get_db)) -> Check:
    """검사 상태와 마스킹된 텍스트를 조회한다. 원본 이미지는 응답에 없다."""
    check = db.get(Check, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="검사를 찾을 수 없습니다.")
    return check
