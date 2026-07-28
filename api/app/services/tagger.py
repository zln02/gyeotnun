"""
곁눈(Gyeotnun) - 오판유형 분류
담당: 장지석

사용자가 판단을 내린 뒤, 그 대화 로그를 보고
**어떤 지점에서 판단이 흔들렸는지**를 4종 유형으로 분류한다.

이 태깅 결과가 다음 날 훈련카드(training.py)의 입력이 된다.
즉, "틀렸다"를 알려주기 위한 것이 아니라 **무엇을 연습할지 고르기 위한** 분류다.

TODO (장지석)
    [ ] 규칙 기반 1차 분류 (키워드/패턴)
    [ ] Claude 기반 2차 분류 (규칙으로 애매할 때만 호출 - 비용 절감)
    [ ] confidence 산출 로직
    [ ] 라벨링 기준은 corpus/README.md 와 반드시 일치시킬 것
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "ERROR_TYPES",
    "ERROR_TYPE_LABELS",
    "ERROR_TYPE_DESCRIPTIONS",
    "TITLE_DEPENDENT",
    "AUTHORITY_SPOOF",
    "NUMBER_CONDITION",
    "OVERGENERALIZATION",
    "tag_error_type",
    "tag_with_confidence",
    "label_of",
]


# ============================================================
# 오판유형 4종 (models.ERROR_TYPES 와 값이 일치해야 함)
# ============================================================
TITLE_DEPENDENT = "TITLE_DEPENDENT"          # 제목의존형
AUTHORITY_SPOOF = "AUTHORITY_SPOOF"          # 권위자사칭수용형
NUMBER_CONDITION = "NUMBER_CONDITION"        # 숫자조건혼동형
OVERGENERALIZATION = "OVERGENERALIZATION"    # 과잉일반화형

ERROR_TYPES = (
    TITLE_DEPENDENT,
    AUTHORITY_SPOOF,
    NUMBER_CONDITION,
    OVERGENERALIZATION,
)

ERROR_TYPE_LABELS: dict[str, str] = {
    TITLE_DEPENDENT: "제목의존형",
    AUTHORITY_SPOOF: "권위자사칭수용형",
    NUMBER_CONDITION: "숫자조건혼동형",
    OVERGENERALIZATION: "과잉일반화형",
}

ERROR_TYPE_DESCRIPTIONS: dict[str, str] = {
    TITLE_DEPENDENT: (
        "제목이나 첫 문장만 보고 판단하는 유형. "
        "본문에 있는 단서(날짜, 조건, 출처)를 끝까지 읽지 않습니다."
    ),
    AUTHORITY_SPOOF: (
        "기관 이름·공무원·의사 등 권위가 붙으면 그대로 받아들이는 유형. "
        "이름이 실제 기관과 같은지 확인하는 단계를 건너뜁니다."
    ),
    NUMBER_CONDITION: (
        "금액·나이·기간 같은 숫자 조건을 혼동하는 유형. "
        "'만 65세 이상'과 '65세부터' 같은 차이를 놓칩니다."
    ),
    OVERGENERALIZATION: (
        "한 사례를 전체로 넓혀 받아들이는 유형. "
        "'누가 받았다더라'를 '모두 받는다'로 이해합니다."
    ),
}

# 시니어에게 보여줄 훈련 방향 한 줄 (프론트 Report 화면용)
ERROR_TYPE_COACHING: dict[str, str] = {
    TITLE_DEPENDENT: "끝까지 읽는 연습을 함께 해보시면 좋겠습니다.",
    AUTHORITY_SPOOF: "기관 이름을 한 글자씩 확인하는 연습을 해보시면 좋겠습니다.",
    NUMBER_CONDITION: "숫자와 조건을 소리 내어 읽어보는 연습이 도움이 됩니다.",
    OVERGENERALIZATION: "'모두'인지 '일부'인지 구분해 보는 연습을 해보시면 좋겠습니다.",
}


def label_of(error_type: str) -> str:
    """코드 → 한글 라벨."""
    return ERROR_TYPE_LABELS.get(error_type, "")


def tag_error_type(dialogue_log: list[dict[str, Any]]) -> str:
    """
    대화 로그를 보고 오판유형 1종을 반환한다.

    Args:
        dialogue_log: [{"role": "assistant"|"user", "content": "...", "stage": "source"}, ...]

    Returns:
        ERROR_TYPES 중 하나 (문자열 코드).

    TODO(장지석): 아래 규칙 기반 분류를 실제로 구현.
        - 사용자가 'source'/'timing' 단계 질문에 "안 봤다/모르겠다"로 답 → TITLE_DEPENDENT
        - 'publisher' 단계에서 기관명을 확인 없이 신뢰 → AUTHORITY_SPOOF
        - 'basis' 단계에서 금액/나이 조건을 잘못 읽음 → NUMBER_CONDITION
        - "주변에서 다 받았다더라" 류 답변 → OVERGENERALIZATION
    """
    result, _ = tag_with_confidence(dialogue_log)
    return result


def tag_with_confidence(dialogue_log: list[dict[str, Any]]) -> tuple[str, int]:
    """
    오판유형과 신뢰도(0~100)를 함께 반환한다.

    Returns:
        (error_type, confidence)
    """
    if not dialogue_log:
        logger.info("dialogue_log 비어 있음 → 기본 유형 반환")
        return TITLE_DEPENDENT, 40

    # TODO(장지석): 실제 분류 로직으로 교체
    #   user_texts = [t["content"] for t in dialogue_log if t.get("role") == "user"]
    #   ... 규칙 매칭 ...
    #   애매하면 _classify_with_llm(dialogue_log) 호출

    # 목업: 데모 시나리오(효도지원금)에 맞춰 권위자사칭수용형 반환
    return AUTHORITY_SPOOF, 78


def build_feedback(error_type: str, user_verdict: str) -> str:
    """
    사용자에게 보여줄 피드백 문구를 만든다.

    ※ "틀렸습니다"라고 말하지 않는다. 확인한 행동 자체를 격려한다.
    """
    coaching = ERROR_TYPE_COACHING.get(error_type, "")
    if user_verdict == "suspect":
        head = "한 번 더 확인해 보신 것, 아주 잘하셨습니다."
    elif user_verdict == "unsure":
        head = "바로 판단하지 않고 멈추신 것도 좋은 선택입니다."
    else:
        head = "직접 살펴보고 판단하신 점이 좋았습니다."
    return f"{head} {coaching}".strip()


def _classify_with_llm(dialogue_log: list[dict[str, Any]]) -> tuple[str, int]:
    """
    TODO(장지석): 규칙으로 애매할 때만 Claude 호출.

    프롬프트 주의사항
        - 사용자를 비난하는 표현을 생성하지 않도록 시스템 프롬프트에 명시할 것.
        - 반드시 ERROR_TYPES 4종 중 하나만 반환하도록 강제할 것.
    """
    raise NotImplementedError
