"""
곁눈(Gyeotnun) - 오판유형 태깅
담당: 장지석 (태깅)

곁눈이 남기는 데이터는 '이 사람이 속았다'가 아니라
'이 사람은 어떤 종류의 정보에 약한가' 이다. 그 유형이 훈련 카드로 연결된다.

4가지 오판유형
  title_dependent          제목 의존형   : 본문을 확인하지 않고 제목만 보고 판단
  authority_impersonation  권위 사칭형   : 기관·전문가 이름이 붙으면 검증 없이 수용
  number_condition         숫자·조건 누락형: 금액/기간/자격 조건을 놓침
  overgeneralization       과잉 일반화형 : 일부 사례를 전체로 확대 해석

★ 이 태그는 사용자에게 '약점'이 아니라 '다음에 볼 곳'으로 보여준다. (UX 카피 주의)
"""
from __future__ import annotations

from typing import Iterable, Tuple

ERROR_TYPES = (
    "title_dependent",
    "authority_impersonation",
    "number_condition",
    "overgeneralization",
)

# 신호 → 오판유형 가중치 (규칙 기반 v1. 라벨 200건 모이면 분류기로 교체 - TODO 장지석)
SIGNAL_WEIGHTS = {
    "number_mismatch": {"number_condition": 0.5},
    "condition_omitted": {"number_condition": 0.4, "overgeneralization": 0.3},
    "source_missing": {"authority_impersonation": 0.35},
    "authority_claimed": {"authority_impersonation": 0.5},
    "urgency_pressure": {"title_dependent": 0.3},
    "headline_only": {"title_dependent": 0.5},
    "single_case_generalized": {"overgeneralization": 0.5},
    "no_official_source": {"authority_impersonation": 0.2, "title_dependent": 0.2},
}

TEXT_HINTS = {
    "title_dependent": ["속보", "단독", "충격", "긴급", "이것만"],
    "authority_impersonation": ["박사", "교수", "전문의", "정부", "공단", "청와대", "기관"],
    "number_condition": ["만원", "%", "퍼센트", "지급", "지원금", "기간", "이내"],
    "overgeneralization": ["누구나", "모두", "전원", "무조건", "항상", "절대"],
}

# 유형별 마무리 문장. 절대 비난하지 않는다.
MESSAGES = {
    "title_dependent": "제목이 강한 글일수록 본문을 한 줄만 더 읽어 보면 판단이 쉬워집니다.",
    "authority_impersonation": "기관 이름이 보이면 그 기관 공식 페이지에서 같은 내용을 찾아보는 습관이 도움이 됩니다.",
    "number_condition": "금액과 조건이 함께 적혀 있는지 확인하는 것만으로도 많이 걸러집니다.",
    "overgeneralization": "'모두·누구나' 같은 말이 보이면 예외가 없는지 한 번 더 살펴보시면 좋습니다.",
}


def tag_error_type(
    signals: Iterable[dict] | None = None,
    text: str = "",
    decision: str = "hold",
) -> Tuple[str, float]:
    """신호 + 텍스트 힌트로 오판유형을 고른다. (error_type, confidence) 반환.

    키가 필요 없는 규칙 기반이라 mock 없이도 항상 동작한다.
    """
    scores = {t: 0.0 for t in ERROR_TYPES}

    for s in signals or []:
        key = s.get("key") if isinstance(s, dict) else str(s)
        for etype, w in SIGNAL_WEIGHTS.get(key, {}).items():
            scores[etype] += w

    for etype, hints in TEXT_HINTS.items():
        scores[etype] += 0.1 * sum(1 for h in hints if h in (text or ""))

    # 'apply(따라해본다)' 를 골랐다면 확인이 덜 된 상태일 수 있어 가중치를 약간 올린다.
    if decision == "apply":
        for etype in scores:
            scores[etype] *= 1.1

    best = max(scores, key=lambda t: scores[t])
    total = sum(scores.values())
    confidence = round(min(scores[best] / total, 0.95), 2) if total > 0 else 0.3
    if total == 0:
        best = "number_condition"       # 기본값: 가장 흔한 유형
    return best, confidence


def build_message(error_type: str, decision: str = "hold") -> str:
    """비난하지 않는 마무리 문장을 만든다."""
    praise = {
        "apply": "직접 확인해 보신 점이 좋았습니다.",
        "not_apply": "한 번 더 확인하고 결정하신 점이 좋았습니다.",
        "hold": "바로 결정하지 않고 미뤄 두신 것도 좋은 선택입니다.",
        "ask_family": "가족에게 물어보기로 하신 것은 아주 좋은 방법입니다.",
    }.get(decision, "확인해 보신 점이 좋았습니다.")
    return f"{praise} {MESSAGES.get(error_type, '')}".strip()
