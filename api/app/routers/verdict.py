"""
곁눈(Gyeotnun) - 사용자 판단 제출 → 오판유형 태깅
담당: 장지석

POST /api/checks/{check_id}/verdict

여기서 제출되는 verdict 는 **사용자의 판단**이다. AI의 판정이 아니다.
AI는 이 판단에 대해 맞다/틀리다를 말하지 않고,
어떤 확인 지점이 약했는지만 태깅해 다음 훈련으로 연결한다.
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Check, Tagging, TrainingCard
from ..schemas import VerdictIn, VerdictOut
from ..services import tagger, training

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checks", tags=["verdict"])


@router.post("/{check_id}/verdict", response_model=VerdictOut, summary="사용자 판단 제출 → 오판유형 태깅")
def submit_verdict(
    check_id: int,
    payload: VerdictIn,
    db: Session = Depends(get_db),
) -> VerdictOut:
    """
    사용자의 판단을 저장하고, 대화 로그를 분석해 오판유형을 태깅한다.
    태깅 결과에 맞는 훈련카드를 함께 발급한다.
    """
    check = db.get(Check, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="검사를 찾을 수 없습니다.")

    check.user_verdict = payload.verdict
    check.user_verdict_reason = payload.reason
    check.status = "judged"

    # 오판유형 분류 (담당: 장지석)
    error_type, confidence = tagger.tag_with_confidence(check.dialogue_log or [])
    label = tagger.label_of(error_type)

    existing = db.query(Tagging).filter(Tagging.check_id == check_id).first()
    if existing:
        existing.error_type = error_type
        existing.error_type_label = label
        existing.confidence = confidence
        tagging = existing
    else:
        tagging = Tagging(
            check_id=check_id,
            user_id=check.user_id,
            error_type=error_type,
            error_type_label=label,
            confidence=confidence,
        )
        db.add(tagging)

    # 훈련카드 발급
    card_data = training.get_today_card(check.user_id, error_type)
    card = TrainingCard(
        user_id=check.user_id,
        error_type=error_type,
        issued_for=date.today(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)

    logger.info("판단 제출 check=%s verdict=%s error_type=%s", check_id, payload.verdict, error_type)

    return VerdictOut(
        check_id=check_id,
        user_verdict=payload.verdict,
        error_type=error_type,
        error_type_label=label,
        confidence=confidence,
        feedback=tagger.build_feedback(error_type, payload.verdict),
        training_card_id=card.id,
    )
