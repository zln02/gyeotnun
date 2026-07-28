"""
곁눈(Gyeotnun) - 훈련카드
담당: 장지석

GET  /api/training/today
POST /api/training/{card_id}/complete
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TrainingCard, User
from ..schemas import TrainingCardOut, TrainingCompleteIn, TrainingCompleteOut
from ..services import training as training_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/training", tags=["training"])


@router.get("/today", response_model=TrainingCardOut, summary="오늘의 훈련 카드")
def get_today(
    device_id: str | None = None,
    error_type: str | None = None,
    db: Session = Depends(get_db),
) -> TrainingCardOut:
    """
    오늘의 훈련카드를 반환한다.

    error_type 을 지정하지 않으면 사용자의 최근 태깅 유형을 사용한다.
    아직 태깅 이력이 없으면 기본 유형으로 시작한다.
    """
    user = db.query(User).filter(User.device_id == device_id).first() if device_id else None

    if error_type is None and user is not None:
        latest = (
            db.query(TrainingCard)
            .filter(TrainingCard.user_id == user.id)
            .order_by(TrainingCard.created_at.desc())
            .first()
        )
        if latest:
            error_type = latest.error_type

    card = training_service.get_today_card(user.id if user else None, error_type)
    return TrainingCardOut(**card)


@router.post("/{card_id}/complete", response_model=TrainingCompleteOut, summary="훈련 완료 처리")
def complete_training(
    card_id: int,
    payload: TrainingCompleteIn,
    db: Session = Depends(get_db),
) -> TrainingCompleteOut:
    """훈련카드를 완료 처리하고 연속 훈련 일수를 반환한다."""
    card = db.get(TrainingCard, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="훈련카드를 찾을 수 없습니다.")

    card.completed = True
    card.completed_at = datetime.now(timezone.utc)
    card.user_answer = payload.user_answer
    card.is_correct = payload.is_correct
    db.commit()

    streak = training_service.compute_streak(card.user_id)

    return TrainingCompleteOut(
        card_id=card_id,
        completed=True,
        streak_days=streak,
        message="오늘도 한 번 더 확인해 보셨습니다. 잘하셨습니다.",
    )
