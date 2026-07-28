"""
S5 - 오늘의 5분 훈련
GET /api/v1/training/today
담당: 장지석 (RAG)
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from mocks import fixtures
from models.schemas import TrainingCardResponse
from routers._common import MockFlag, not_implemented, use_mock
from services import rag

router = APIRouter(prefix="/training", tags=["training"])


@router.get("/today", response_model=TrainingCardResponse, summary="오늘의 훈련 카드")
async def today_card(
    mock: int = MockFlag,
    error_type: Optional[str] = Query(None, description="사용자의 취약 유형(있으면 우선 매칭)"),
):
    """5분 안에 끝나는 훈련 카드 1장. 취약 유형이 있으면 그 유형을 우선한다."""
    if use_mock(mock):
        return TrainingCardResponse(**fixtures.TRAINING_TODAY)

    card = rag.pick_today_card(error_type)
    if not card:
        raise not_implemented(RuntimeError("훈련 카드가 없습니다. corpus/training_cards 를 채워 주세요."))
    return TrainingCardResponse(**card)
