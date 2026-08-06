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

    # ⚠️ 보안(IDOR): 아래 TODO 를 구현할 때 device_id 로 그 사용자의 기록을 조회하게
    #    되는데, 지금처럼 요청 파라미터 device_id 를 그대로 신뢰하면 남의 device_id 를
    #    넣어 타인의 주간 리포트를 보는 IDOR 가 된다. checks 의 require_owner 처럼
    #    소유권(또는 그 이상의 인증)을 반드시 먼저 건 뒤 집계할 것. 현재는 스텁이라
    #    전부 0 을 돌려주므로 유출이 없다 - 구현 전까지 이 경고를 지우지 말 것.
    # TODO(박진영): taggings / training_cards 집계 쿼리로 교체 (위 보안 경고 먼저 처리)
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
