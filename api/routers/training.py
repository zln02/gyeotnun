"""
S5 - 오늘의 5분 훈련
GET  /api/v1/training/today    오늘의 카드 1장
POST /api/v1/training/result   ★ 2026-08-20 신설 - 푼 결과를 남긴다
담당: 장지석 (RAG)

★ 왜 result 를 새로 만들었나
  전에는 카드를 **주기만** 하고 결과를 받는 곳이 없었다. 그래서 "훈련을 했는가"도
  "맞혔는가"도 서버가 알 수 없었고, weekly_reports.training_completed 는 늘 0이었다.
  판단 행동 로그(judgment_logs)의 card_id·card_result 를 채우려면 이 자리가 필요하다.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from mocks import fixtures
from models.schemas import TrainingCardResponse, TrainingResultAck, TrainingResultIn
from routers._common import MockFlag, not_implemented, use_mock
from services import judgment_log, rag

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
        raise not_implemented(
            RuntimeError("훈련 카드가 없습니다. corpus/training_cards 를 채워 주세요."),
            "ST-002", screen="S5",
        )
    return TrainingCardResponse(**card)


@router.post("/result", response_model=TrainingResultAck, summary="훈련 카드 결과 기록")
async def record_result(body: TrainingResultIn):
    """푼 결과를 판단 행동 로그에 남긴다.

    ★ events 와 같은 fire-and-forget 계약이다 - 기록에 실패해도 200(accepted=0)을
      돌려주고 서버만 인지한다(services/judgment_log 안에서 ST-003 으로 남는다).
      훈련을 다 풀고 나서 "기록 실패" 화면을 보는 일은 없어야 한다.
    ★ 자유 텍스트를 받지 않는다. 카드 id 와 정오답뿐이다.
    """
    ok = judgment_log.card_answered(
        body.session_id, card_id=body.card_id, result=body.result,
        device_id=body.device_id, session_type=body.session_type,
    )
    return TrainingResultAck(accepted=1 if ok else 0)
