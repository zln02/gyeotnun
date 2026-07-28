"""
주간 리포트 (가족 공유용)
GET /api/v1/reports/weekly
담당: 박진영 (API·DB)

★ 리포트에는 '몇 번 속았는지'를 쓰지 않는다. '몇 번 확인했는지'를 쓴다.
"""
from __future__ import annotations

import datetime as _dt

from fastapi import APIRouter, Query

from mocks import fixtures
from models.schemas import WeeklyReportResponse
from routers._common import MockFlag, use_mock
from services import rag

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly", response_model=WeeklyReportResponse, summary="주간 리포트")
async def weekly(mock: int = MockFlag, device_id: str = Query("anonymous")):
    if use_mock(mock):
        return WeeklyReportResponse(**fixtures.WEEKLY_REPORT)

    # TODO(박진영): taggings / training_cards 집계 쿼리로 교체
    now = _dt.date.today()
    iso = now.isocalendar()
    return WeeklyReportResponse(
        week=f"{iso[0]}-W{iso[1]:02d}",
        checks_count=0,
        training_completed=0,
        error_type_trend={t: 0 for t in ("title_dependent", "authority_impersonation",
                                         "number_condition", "overgeneralization")},
        streak_days=0,
        message=rag.build_weekly_message(0, 0, 0),
    )
