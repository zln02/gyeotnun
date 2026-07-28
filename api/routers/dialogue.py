"""
S3 - 질문 카드 (★ 서비스의 핵심 화면)
POST /api/v1/checks/{check_id}/dialogue
담당: 김태희 (프롬프트) / 박진영 (계약)

응답의 question 은 반드시 prompt_chain.validate_question() 을 통과한다.
mock 응답도 예외 없이 같은 검증을 통과시킨다 — 시연에서 나가는 문장도
서비스 원칙을 지켜야 하기 때문이다.
"""
from __future__ import annotations

from fastapi import APIRouter

from mocks import fixtures
from models.schemas import DialogueRequest, DialogueResponse
from routers._common import MockFlag, not_implemented, use_mock
from routers.checks import _MEMORY_STORE
from services import prompt_chain, search

router = APIRouter(prefix="/checks", tags=["dialogue"])


@router.post("/{check_id}/dialogue", response_model=DialogueResponse, summary="확인 질문 받기")
async def next_question(check_id: str, body: DialogueRequest, mock: int = MockFlag):
    """다음 확인 질문 1개를 반환한다. 절대 진위를 판정하지 않는다."""
    if use_mock(mock):
        data = dict(fixtures.dialogue_for(body.turn))
        # ★ mock 이라도 후처리 검증을 통과시킨다 (원칙 위반 문장이 시연에 나가지 않도록)
        checked = prompt_chain.validate_question(
            data["question"],
            allowed_refs=fixtures.allowed_refs(),
            evidence_refs=data.get("evidence_refs"),
        )
        data["question"] = checked.question
        data["evidence_refs"] = checked.evidence_refs
        return DialogueResponse(**data)

    stored = _MEMORY_STORE.get(check_id)
    if not stored:
        raise not_implemented(RuntimeError(f"check_id={check_id} 를 찾을 수 없습니다."))
    try:
        evidence = search.collect_evidence(stored["masked_text"], domain=stored.get("domain"))
        vq = prompt_chain.generate_question(
            extracted_text=stored["masked_text"],
            signals=evidence.signals,
            references=evidence.references,
            history=stored.get("history", []),
        )
    except Exception as e:  # noqa: BLE001
        raise not_implemented(e) from e

    return DialogueResponse(
        turn=body.turn,
        question=vq.question,
        why="",
        evidence_refs=vq.evidence_refs,
        options=[],
        is_final=body.turn >= 3,
    )
