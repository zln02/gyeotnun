"""판단 행동 집계 (2026-08-20 신설)
GET /api/v1/judgments/summary   세션 단위 판단 행동 요약 (★ 운영자 전용)

events/summary 가 "화면을 어떻게 썼나"라면 이쪽은 "판단을 어떻게 했나"다.
- 질문을 열었는가 (성급 판단의 역지표)
- 무엇을 확인했는가 (출처·보낸 곳·날짜·조건)
- 무엇을 골랐는가, 얼마나 걸렸는가
- baseline / training / posttest 로 나눠 보면 훈련 전후 비교가 된다

★ 운영자 전용이다. 개별 행에는 자유 텍스트가 없지만, 그래도 집계만 내보낸다 -
  세션 단위 원자료를 API 로 열어 둘 이유가 없다(events/summary 와 같은 판단).
★ 표본이 적을 때 비율만 보면 오해가 크므로 **모든 비율에 표본 수를 함께** 준다.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from models.db import JudgmentLog, get_db
from models.schemas import JudgmentSummaryResponse
from routers._common import AdminTokenHeader, require_operator
from services import judgment_log

router = APIRouter(prefix="/judgments", tags=["judgments"])


@router.get("/summary", response_model=JudgmentSummaryResponse,
            summary="집계 - 세션 단위 판단 행동 (훈련 전후 비교용)")
async def summary(
    db: Session = Depends(get_db),
    session_type: Optional[str] = Query(
        None, description="baseline|training|posttest 로 좁혀 본다. 없으면 전체"),
    x_admin_token: str | None = AdminTokenHeader,
):
    """표본이 수십~수백 세션 규모라고 보고 전부 읽어 파이썬으로 계산한다
    (events/summary 와 같은 방식·같은 이유 - 이 규모에서는 SQL 집계보다 읽기 쉽다)."""
    require_operator(x_admin_token)
    q = db.query(JudgmentLog)
    if session_type in judgment_log.ALLOWED_SESSION_TYPES:
        q = q.filter(JudgmentLog.session_type == session_type)
    rows = q.order_by(JudgmentLog.created_at).all()
    return JudgmentSummaryResponse(**judgment_log.summarize(rows))
