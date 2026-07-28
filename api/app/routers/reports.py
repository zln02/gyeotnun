"""
곁눈(Gyeotnun) - 주간 리포트
담당: 장지석

GET /api/reports/weekly

가족에게 공유할 수 있는 한 주 요약.
"몇 번 틀렸다"가 아니라 "몇 번 확인했다"를 강조한다.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Check, Tagging, TrainingCard, User
from ..schemas import ErrorTypeCount, WeeklyReportOut
from ..services import tagger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/weekly", response_model=WeeklyReportOut, summary="주간 리포트")
def weekly_report(
    device_id: str | None = None,
    db: Session = Depends(get_db),
) -> WeeklyReportOut:
    """
    이번 주(월~일) 활동을 집계한다.

    TODO(장지석)
        [ ] weekly_reports 테이블에 스냅샷 저장 (배치 or 최초 조회 시)
        [ ] 이전 주 대비 증감 표시
        [ ] 가족 공유용 요약 문구를 Claude로 다듬기 (선택)
    """
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    user = db.query(User).filter(User.device_id == device_id).first() if device_id else None
    user_id = user.id if user else None

    checks_q = db.query(Check).filter(Check.created_at >= week_start)
    tag_q = db.query(Tagging).filter(Tagging.created_at >= week_start)
    card_q = db.query(TrainingCard).filter(
        TrainingCard.issued_for >= week_start,
        TrainingCard.completed.is_(True),
    )
    if user_id is not None:
        checks_q = checks_q.filter(Check.user_id == user_id)
        tag_q = tag_q.filter(Tagging.user_id == user_id)
        card_q = card_q.filter(TrainingCard.user_id == user_id)

    checks_count = checks_q.count()
    trainings_completed = card_q.count()

    counts: dict[str, int] = {code: 0 for code in tagger.ERROR_TYPES}
    for t in tag_q.all():
        if t.error_type in counts:
            counts[t.error_type] += 1

    correct = sum(1 for c in card_q.all() if c.is_correct)
    accuracy = int(correct / trainings_completed * 100) if trainings_completed else 0

    top_type = max(counts, key=lambda k: counts[k]) if any(counts.values()) else None

    items = [
        ErrorTypeCount(error_type=code, label=tagger.label_of(code), count=n)  # type: ignore[arg-type]
        for code, n in counts.items()
    ]

    if checks_count == 0:
        summary = "이번 주에는 아직 확인하신 소식이 없습니다."
    elif top_type:
        summary = (
            f"이번 주에 {checks_count}번 확인해 보셨습니다. "
            f"{tagger.ERROR_TYPE_COACHING.get(top_type, '')}"
        )
    else:
        summary = f"이번 주에 {checks_count}번 확인해 보셨습니다. 잘하고 계십니다."

    return WeeklyReportOut(
        week_start=week_start,
        week_end=week_end,
        checks_count=checks_count,
        trainings_completed=trainings_completed,
        accuracy_rate=accuracy,
        error_type_counts=items,
        top_error_type=top_type,  # type: ignore[arg-type]
        top_error_type_label=tagger.label_of(top_type) if top_type else "",
        summary=summary,
    )
