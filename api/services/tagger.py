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

import json
import logging
from typing import Iterable, Tuple

from config import settings

log = logging.getLogger("gyeotnun.tagger")

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


# ============================================================ LLM 기반 태깅 (v2)
# 위 tag_error_type() 은 결정적 규칙 기반이라 그대로 남겨 둔다(테스트 고정, 키 불필요,
# 아래 LLM 버전의 최종 안전망이기도 하다). 실제 서비스 경로(mock=0)는 아래
# tag_error_type_llm() 을 쓴다. corpus_index 의 사례_재라벨링표(실제 피싱 사례에
# 사람이 직접 붙인 오판유형 라벨)를 few-shot 근거로 삼아 Claude 로 분류한다.
#
# ★ 왜 실패해도 예외를 던지지 않는가
#   S4(판단 기록)는 사용자가 방금 결정을 내린 직후의 화면이다. 여기서 끊기면
#   "내 선택이 기록됐는지" 조차 알 수 없게 된다. 그래서 키가 없거나 호출이
#   실패하면 조용히 규칙 기반(tag_error_type)으로 내려간다 - 품질은 낮아져도
#   화면은 항상 끝까지 돈다. (prompt_chain 의 FALLBACK_QUESTION 과 같은 이유)
TAG_MODEL = "claude-sonnet-5"
TAG_EFFORT = "low"
TAG_MAX_TOKENS = 512

# 사례_20-46건_재라벨링표.csv 의 한글 오판유형 라벨 → 이 API 의 4종 영문 상수.
KOREAN_LABEL_TO_ERROR_TYPE = {
    "제목의존형": "title_dependent",
    "권위자사칭 수용형": "authority_impersonation",
    "숫자·조건 혼동형": "number_condition",
    "과잉일반화형": "overgeneralization",
}

TAG_SYSTEM_PROMPT = """당신은 곁눈의 오판유형 분류기입니다. 사용자가 확인을 마친 글이
아래 4가지 오판유형 중 무엇에 가장 가깝게 만들어졌는지 하나만 고릅니다.

[4가지 오판유형]
- title_dependent (제목 의존형): 본문을 확인하지 않고 제목·첫 문장만 보고 판단하기 쉬운 글
- authority_impersonation (권위 사칭형): 기관·전문가 이름이 붙으면 검증 없이 믿기 쉬운 글
- number_condition (숫자·조건 누락형): 금액/기간/자격 조건이 빠져 있거나 헷갈리는 글
- overgeneralization (과잉 일반화형): '누구나·전원·무조건' 처럼 일부를 전체로 넓혀 말하는 글

[규칙]
- 넷 중 정확히 하나만 고르십시오.
- 이 글의 진위(가짜/사기 여부)를 판정하지 마십시오. 오판유형 분류는 판정이 아니라
  "다음에 어떤 훈련이 도움이 될지" 를 정하기 위한 메타 정보입니다.
- confidence 는 그 라벨이 맞다고 보는 확신도(0~1)입니다.
"""

TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "error_type": {"type": "string", "enum": list(ERROR_TYPES)},
        "confidence": {"type": "number"},
    },
    "required": ["error_type", "confidence"],
    "additionalProperties": False,
}

_client = None


def _get_client():
    """Anthropic 클라이언트 싱글턴. prompt_chain.py 와 같은 키를 쓴다."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def _few_shot_examples(per_type: int = 2) -> str:
    """재라벨링표의 실제 사례를 오판유형별로 몇 건씩 뽑아 few-shot 예시로 만든다.

    ★ 예시 문장은 지어내지 않는다. corpus_index 가 CSV 에서 그대로 읽어 온
      사례내용/신뢰단서만 쓴다.
    """
    from services import corpus_index

    buckets: dict[str, list] = {t: [] for t in ERROR_TYPES}
    for case in corpus_index.SCAM_CASES:
        if case.origin != "relabeled":   # 평가세트에는 오판유형 라벨이 없다
            continue
        for kr_label in case.error_types:
            etype = KOREAN_LABEL_TO_ERROR_TYPE.get(kr_label)
            if etype and len(buckets[etype]) < per_type:
                buckets[etype].append(case)

    lines = ["[실제 사례 예시 - 사람이 직접 라벨링한 데이터]"]
    for etype, cases in buckets.items():
        for case in cases:
            lines.append(f"- 사례: {case.text}")
            if case.risk_clues:
                lines.append(f"  신뢰단서: {', '.join(case.risk_clues)}")
            lines.append(f"  → {etype}")
    return "\n".join(lines)


def tag_error_type_llm(
    text: str,
    signals: Iterable[dict] | None = None,
    decision: str = "hold",
) -> Tuple[str, float]:
    """Claude 로 오판유형을 분류한다. (error_type, confidence) 반환.

    실패(키 없음/네트워크 오류/거절/파싱 실패)해도 예외를 던지지 않고
    tag_error_type() 규칙 기반으로 내려간다. 이유는 모듈 상단 주석 참고.
    """
    signals = list(signals or [])

    if not settings.has_llm:
        log.info("[tag] ANTHROPIC_API_KEY 없음 - 규칙 기반으로 대체")
        return tag_error_type(signals, text=text, decision=decision)

    sig_lines = "\n".join(f"- {s.get('label', s)}" for s in signals) or "- (특이 신호 없음)"
    user = (
        f"[사용자가 확인한 글]\n{text}\n\n"
        f"[확인 과정에서 감지된 신호]\n{sig_lines}\n\n"
        f"[사용자가 고른 행동] {decision}\n\n"
        "위 글이 4가지 오판유형 중 어디에 가장 가까운지 하나만 골라 JSON으로 출력하십시오."
    )

    try:
        resp = _get_client().messages.create(
            model=TAG_MODEL,
            max_tokens=TAG_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": TAG_SYSTEM_PROMPT + "\n\n" + _few_shot_examples(),
                "cache_control": {"type": "ephemeral"},   # 판단 1건마다 반복 호출되므로 캐싱 이득이 크다
            }],
            output_config={"effort": TAG_EFFORT, "format": {"type": "json_schema", "schema": TAG_SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("모델이 분류를 거절했습니다(refusal).")

        raw = "".join(b.text for b in resp.content if b.type == "text")
        payload = json.loads(raw)
        etype = payload["error_type"]
        if etype not in ERROR_TYPES:
            raise ValueError(f"알 수 없는 오판유형: {etype}")
        confidence = max(0.0, min(1.0, float(payload["confidence"])))
        log.info("[tag] LLM 분류 성공: %s (%.2f)", etype, confidence)
        return etype, confidence
    except Exception as e:  # noqa: BLE001 - 어떤 이유로든 실패하면 규칙 기반으로 내려간다
        log.warning("[tag] LLM 분류 실패, 규칙 기반으로 대체: %s", e)
        return tag_error_type(signals, text=text, decision=decision)


def build_message(error_type: str, decision: str = "hold") -> str:
    """비난하지 않는 마무리 문장을 만든다."""
    praise = {
        "apply": "직접 확인해 보신 점이 좋았습니다.",
        "not_apply": "한 번 더 확인하고 결정하신 점이 좋았습니다.",
        "hold": "바로 결정하지 않고 미뤄 두신 것도 좋은 선택입니다.",
        "ask_family": "가족에게 물어보기로 하신 것은 아주 좋은 방법입니다.",
    }.get(decision, "확인해 보신 점이 좋았습니다.")
    return f"{praise} {MESSAGES.get(error_type, '')}".strip()
