"""
온보딩 진단 (첫 실행 3문항)
POST /api/v1/onboarding/diagnosis
담당: 장지석 (태깅) / 조희진 (화면)

★ 결과 화면 카피 원칙: '당신은 ~에 약합니다' (X) → '앞으로 여기를 같이 봐요' (O)
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter

from mocks import fixtures
from models.schemas import DiagnosisRequest, DiagnosisResponse
from routers._common import MockFlag, use_mock
from services import rag, tagger

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

# 진단 문항의 선택지 → 오판유형 매핑 (3문항, 각 선택지가 유형 1개를 가리킨다)
CHOICE_TO_TYPE = {
    "q1_a": "title_dependent",
    "q1_b": "number_condition",
    "q2_a": "authority_impersonation",
    "q2_b": "overgeneralization",
    "q3_a": "number_condition",
    "q3_b": "title_dependent",
}


@router.post("/diagnosis", response_model=DiagnosisResponse, summary="첫 실행 진단")
async def diagnosis(body: DiagnosisRequest, mock: int = MockFlag):
    if use_mock(mock):
        return DiagnosisResponse(**fixtures.ONBOARDING_DIAGNOSIS)

    scores = {t: 0.0 for t in tagger.ERROR_TYPES}
    for a in body.answers:
        etype = CHOICE_TO_TYPE.get(a.choice_id)
        if etype:
            scores[etype] += 1.0
    total = sum(scores.values()) or 1.0
    scores = {k: round(v / total, 2) for k, v in scores.items()}
    dominant = max(scores, key=lambda t: scores[t]) if any(scores.values()) else "number_condition"

    # device_id 는 해시로만 다룬다 (원문 저장 금지)
    user_id = "usr_" + hashlib.sha256(body.device_id.encode()).hexdigest()[:10]
    card = rag.pick_today_card(dominant) or {}
    return DiagnosisResponse(
        user_id=user_id,
        dominant_error_type=dominant,
        score=scores,
        starter_card_id=card.get("card_id", "card_default"),
        message="앞으로 이 부분을 같이 살펴봐요. 첫 연습 카드를 준비해 두었습니다.",
    )
