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

from config import MissingKeyError
from mocks import fixtures
from models.schemas import DialogueRequest, DialogueResponse
from routers._common import MockFlag, not_implemented, use_mock
from routers.checks import require_owner
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

    stored = require_owner(check_id, body.device_id)   # ★ IDOR 방지: 소유자만 통과

    history = stored.setdefault("history", [])
    if body.user_reply:
        history.append(f"사용자 답변: {body.user_reply}")

    try:
        evidence = search.collect_evidence(stored["masked_text"], domain=stored.get("domain"))
        vq = prompt_chain.generate_question(
            extracted_text=stored["masked_text"],
            signals=evidence.signals,
            references=evidence.references,
            history=history,
        )
    except Exception as e:  # noqa: BLE001
        # ★ 키 자체가 없어 시도조차 못 한 경우만 외부연동(EX-002)이다. generate_question()
        #   은 호출이 "됐지만" 반복 실패한 경우엔 예외를 던지지 않고 GN-001 로 자체
        #   폴백하므로(services/prompt_chain.py), 여기까지 올라오는 다른 예외는 대부분
        #   collect_evidence() 쪽 예상 밖 버그(SR-001)다.
        code = "EX-002" if isinstance(e, MissingKeyError) else "SR-001"
        raise not_implemented(e, code, screen="S3", device_id=stored.get("device_id")) from e

    history.append(f"질문{body.turn}: {vq.question}")

    return DialogueResponse(
        turn=body.turn,
        question=vq.question,
        why=vq.why,
        evidence_refs=vq.evidence_refs,
        options=vq.options,
        # 마지막 턴 판단은 계약(3턴)을 따르되, 모델이 먼저 끝내자고 하면 존중한다.
        is_final=body.turn >= 3 or vq.is_final,
    )
