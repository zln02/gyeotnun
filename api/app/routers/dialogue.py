"""
곁눈(Gyeotnun) - 질문형 가이드
담당: 김태희

POST /api/checks/{check_id}/dialogue

★ 이 엔드포인트는 절대 판정문을 반환하지 않는다. ★
  prompt_chain.SYSTEM_PROMPT_V0 + contains_verdict_phrase 가드 참조.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Check, Evidence
from ..schemas import DialogueIn, DialogueOut, EvidenceOut
from ..services import prompt_chain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/checks", tags=["dialogue"])


@router.post("/{check_id}/dialogue", response_model=DialogueOut, summary="다음 질문 생성 (판정 없음)")
def next_dialogue(
    check_id: int,
    payload: DialogueIn,
    db: Session = Depends(get_db),
) -> DialogueOut:
    """
    다음 단계의 질문을 생성한다.

    흐름
        1. 사용자 답변이 있으면 dialogue_log 에 append
        2. 저장된 evidence 를 링크로만 LLM에 전달
        3. prompt_chain.generate_questions() 호출
        4. 생성된 질문을 dialogue_log 에 append 후 반환

    API 키가 없으면 목업 질문이 반환된다 (mocked=true).
    """
    check = db.get(Check, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="검사를 찾을 수 없습니다.")

    log: list[dict] = list(check.dialogue_log or [])

    # 1) 사용자 답변 기록
    if payload.user_message:
        log.append({"role": "user", "content": payload.user_message, "step": payload.step})

    # 2) 근거 로드 (링크·제목·게시일만)
    rows = db.query(Evidence).filter(Evidence.check_id == check_id).order_by(Evidence.rank).all()
    evidence_dicts = [
        {
            "source": r.source,
            "source_label": r.source_label,
            "found": r.found,
            "title": r.title,
            "url": r.url,
            "publisher": r.publisher,
            "published_at": r.published_at,
            "is_official": r.is_official,
            "rank": r.rank,
        }
        for r in rows
    ]

    # 3) 질문 생성
    result = prompt_chain.generate_questions(
        masked_text=check.ocr_text_masked,
        evidence=evidence_dicts,
        dialogue_log=log,
        step=payload.step,
    )

    # 4) 생성된 질문 기록
    for q in result.get("questions", []):
        log.append({"role": "assistant", "content": q, "step": payload.step, "stage": result.get("stage", "")})

    check.dialogue_log = log
    check.status = "questioning" if not result.get("is_final") else "judged"
    db.commit()

    return DialogueOut(
        check_id=check_id,
        step=payload.step,
        stage=result.get("stage", ""),
        questions=result.get("questions", []),
        hint=result.get("hint", ""),
        evidence_links=[EvidenceOut(**e) for e in evidence_dicts],
        is_final=bool(result.get("is_final")),
        mocked=bool(result.get("mocked")),
    )
