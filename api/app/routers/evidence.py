"""
곁눈(Gyeotnun) - 출처 교차대조 결과
담당: 김유리

GET /api/checks/{check_id}/evidence

공식 출처에서 찾지 못한 경우에도 found=False 레코드를 반환한다.
"찾지 못했다"는 사실 자체가 사용자에게 중요한 확인 신호이기 때문.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Check, Evidence
from ..schemas import EvidenceListOut, EvidenceOut
from ..services import search

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checks", tags=["evidence"])

NOTE_NOT_FOUND = (
    "정부24와 정책브리핑에서 같은 이름으로 찾아보았는데, 나오지 않았습니다. "
    "공식 안내에 없는 내용은 한 번 더 확인해 보시면 좋겠습니다."
)
NOTE_FOUND = "공식 안내에서 관련 내용을 찾았습니다. 직접 눌러서 확인해 보시겠어요?"


@router.get("/{check_id}/evidence", response_model=EvidenceListOut, summary="출처 교차대조 결과")
def get_evidence(
    check_id: int,
    refresh: bool = False,
    db: Session = Depends(get_db),
) -> EvidenceListOut:
    """
    검사 건에 대한 교차대조 결과를 반환한다.

    이미 저장된 결과가 있으면 그대로 반환하고,
    없거나 refresh=true 이면 다시 검색한다.
    """
    check = db.get(Check, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="검사를 찾을 수 없습니다.")

    existing = db.query(Evidence).filter(Evidence.check_id == check_id).all()

    if existing and not refresh:
        items = [EvidenceOut.model_validate(e) for e in existing]
        query_used = existing[0].query_used or ""
    else:
        if refresh:
            for e in existing:
                db.delete(e)
            db.flush()

        query_used = search.extract_query(check.ocr_text_masked)
        results = search.cross_check(query_used)

        rows = [Evidence(check_id=check_id, **r) for r in results]
        db.add_all(rows)
        check.status = "questioning"
        db.commit()
        for r in rows:
            db.refresh(r)
        items = [EvidenceOut.model_validate(r) for r in rows]

    official_found = any(i.is_official and i.found for i in items)

    return EvidenceListOut(
        check_id=check_id,
        query_used=query_used,
        official_found=official_found,
        items=items,
        note=NOTE_FOUND if official_found else NOTE_NOT_FOUND,
    )
