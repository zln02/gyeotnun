"""
곁눈(Gyeotnun) - 판정 억제 질문 생성 체인  ★ 서비스 정체성 모듈
담당: 김태희 (프롬프트)

이 서비스는 "이건 가짜입니다"라고 말하지 않는다.
기존 팩트체크 서비스가 실패한 지점이 바로 그것이다.
  - AI가 판정해 주면 사용자는 판단을 AI에 위임한다 (의존).
  - 틀린 판정 한 번이면 서비스 신뢰가 무너진다 (리스크).
  - 무엇보다, 어르신을 '속은 사람'으로 만든다 (자존감 훼손).

곁눈은 대신 **스스로 확인할 질문 한 개**를 돌려준다.
확인 과정을 거친 사람은 다음번에 스스로 걸러낼 수 있게 된다.

2단 안전장치
  1) SYSTEM_PROMPT : 모델에게 판정 금지 규칙을 건다 (사전 억제)
  2) validate_question() : 생성된 문장을 코드로 재검사한다 (사후 차단)
     → 프롬프트는 뚫릴 수 있으므로, 후처리 검증이 최종 방어선이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from config import MissingKeyError, settings

# ============================================================ 1) 시스템 프롬프트
SYSTEM_PROMPT = """당신은 '곁눈'의 확인 도우미입니다. 시니어 사용자가 받은 정보를 스스로 확인하도록 돕습니다.

[가장 중요한 규칙 - 판정 금지]
- 정보의 진위를 판정하지 마십시오. 참인지 거짓인지 결론 내리지 않습니다.
- "가짜입니다", "사기입니다", "진짜입니다", "허위입니다", "확실합니다" 같은 표현을 절대 쓰지 마십시오.
- 대신 사용자가 스스로 확인할 수 있는 질문을 한 번에 하나씩 던지십시오.

[근거 사용 규칙]
- 근거는 제공된 검색 결과에 실제로 존재하는 링크만 사용하십시오.
- 링크나 기관명, 날짜를 지어내지 마십시오. 기억에 의존해 URL을 쓰지 마십시오.
- 제공된 검색 결과에서 출처를 찾지 못했다면, 없는 출처를 만들지 말고
  "공식 자료에서 찾지 못했다"는 사실을 그대로 알리십시오.
  찾지 못했다는 것 자체가 사용자에게 중요한 확인 신호입니다.

[말투 규칙]
- 사용자의 기존 판단이나 믿음을 비난하지 마십시오. "속으셨네요", "잘못 아셨네요" 같은 말은 금지입니다.
- 한 번에 한 가지만 묻고, 두 문장을 넘기지 마십시오.
- 초등학생도 이해할 쉬운 말을 쓰십시오. 전문용어, 영어 약자, 한자어를 피하십시오.
- 어르신을 존중하는 존댓말을 쓰되, 지나치게 격식적이지 않게 하십시오.

[출력 형식]
JSON 하나만 출력하십시오.
{"question": "...", "why": "...", "evidence_refs": ["https://..."], "options": [{"id":"...","label":"..."}], "is_final": false}
- question: 사용자가 스스로 확인할 질문 (두 문장 이내)
- why: 이 질문을 하는 이유 한 줄
- evidence_refs: 제공된 검색 결과에 실제로 있던 URL만
- options: 타이핑 없이 고를 수 있는 보기 2~3개
"""

# ============================================================ 2) few-shot 예시
FEW_SHOT_EXAMPLES = [
    {
        "input": {
            "extracted_text": "★긴급★ 65세 이상 어르신 전원 매달 40만원 지급 확정! 신청 안 하면 못 받습니다.",
            "signals": [
                "글에 적힌 금액과 공식 자료의 금액 기준이 다름",
                "'전원'이라고 적혀 있으나 공식 자료에는 소득 조건이 있음",
                "발표 기관이 적혀 있지 않음",
            ],
            "references": [
                {"title": "기초연금 제도 안내", "url": "https://basicpension.mohw.go.kr/", "publisher": "보건복지부"}
            ],
        },
        # ↓ 이 출력이 '좋은 답'의 기준이다. 판정어 없음 / 2문장 / 실제 링크만 / 비난 없음
        "output": {
            "question": "이 글에 적힌 '매달 40만원'은 어디에서 발표한 내용일까요? 글 안에서 기관 이름을 한번 찾아봐 주세요.",
            "why": "숫자가 크게 적혀 있을수록, 그 숫자를 누가 말했는지부터 확인하면 판단이 쉬워집니다.",
            "evidence_refs": ["https://basicpension.mohw.go.kr/"],
            "options": [
                {"id": "found", "label": "기관 이름이 적혀 있어요"},
                {"id": "not_found", "label": "찾지 못하겠어요"},
                {"id": "unsure", "label": "잘 모르겠어요"},
            ],
            "is_final": False,
        },
    }
]

# ============================================================ 3) 후처리 검증
# 판정으로 읽히는 표현 목록. 새로운 사례가 나오면 여기에 추가하고 테스트도 함께 추가할 것.
FORBIDDEN_PATTERNS: List[str] = [
    "가짜",
    "사기",
    "진짜입니다",
    "진짜예요",
    "사실입니다",
    "확실합니다",
    "확실해요",
    "허위",
    "거짓",
    "조작된",
    "속으신",
    "속으셨",
    "낚시글",
    "믿으시면 안",
    "믿지 마세요",
    "틀렸습니다",
    "잘못 아셨",
]

MAX_SENTENCES = 2
_SENTENCE_SPLIT_RE = re.compile(r"[.!?。？！]+")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


class ValidationError(Exception):
    """생성 문장이 곁눈의 원칙을 어겼을 때. 호출부는 이 예외를 재생성 신호로 쓴다.

    attributes:
        reason: forbidden_word | too_long | empty
        detail: 어떤 표현/몇 문장이었는지
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"[{reason}] {detail}")


@dataclass
class ValidatedQuestion:
    """검증을 통과한 질문. dropped_refs 는 '지어낸 링크'로 판단해 제거된 URL."""

    question: str
    evidence_refs: List[str] = field(default_factory=list)
    dropped_refs: List[str] = field(default_factory=list)
    sentence_count: int = 0


def count_sentences(text: str) -> int:
    """마침표/물음표 기준 문장 수. 종결부호가 없으면 1문장으로 본다."""
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text or "") if p.strip()]
    return len(parts) if parts else 0


def validate_question(
    text: str,
    allowed_refs: Sequence[str] | None = None,
    evidence_refs: Iterable[str] | None = None,
) -> ValidatedQuestion:
    """★ 곁눈의 최종 방어선. LLM 출력이 원칙을 지켰는지 코드로 재검사한다.

    검사 항목
      1) 금지어: 판정으로 읽히는 표현이 하나라도 있으면 ValidationError(reason="forbidden_word")
         → 호출부는 이를 '재생성 신호'로 받아 다시 생성한다.
      2) 링크: evidence_refs 중 allowed_refs(=실제 검색 결과)에 없는 URL은 **제거**한다.
         본문(text) 안에 박힌 URL도 같은 기준으로 검사해, 허용되지 않으면 문장에서 지운다.
         → 예외를 던지지 않고 제거하는 이유: 링크만 빼면 질문 자체는 여전히 유효하기 때문.
      3) 길이: 2문장 초과면 ValidationError(reason="too_long")

    Args:
        text: LLM이 생성한 질문 문장
        allowed_refs: 실제 검색/코퍼스에서 확보한 URL 화이트리스트
        evidence_refs: LLM이 함께 내놓은 근거 URL 목록(선택)

    Returns:
        ValidatedQuestion (정제된 문장 + 살아남은 링크 + 제거된 링크)

    Raises:
        ValidationError: 금지어 포함 / 문장 수 초과 / 빈 문자열
    """
    if not text or not text.strip():
        raise ValidationError("empty", "질문이 비어 있습니다.")

    cleaned = text.strip()

    # ---- 1) 금지어 검사 (공백 제거본에서도 검사해 '가 짜' 우회를 일부 차단)
    flat = re.sub(r"\s+", "", cleaned)
    for word in FORBIDDEN_PATTERNS:
        if word in cleaned or re.sub(r"\s+", "", word) in flat:
            raise ValidationError(
                "forbidden_word",
                f"판정으로 읽히는 표현이 포함됨: '{word}'. 질문형으로 재생성이 필요합니다.",
            )

    # ---- 2) 링크 화이트리스트 검증
    allow = set(allowed_refs or [])
    kept: List[str] = []
    dropped: List[str] = []

    for url in list(evidence_refs or []):
        (kept if url in allow else dropped).append(url)

    for url in _URL_RE.findall(cleaned):
        if url not in allow:
            dropped.append(url)
            cleaned = cleaned.replace(url, "").strip()
        elif url not in kept:
            kept.append(url)

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()

    # ---- 3) 길이 검증 (링크 제거 후 기준)
    n = count_sentences(cleaned)
    if n > MAX_SENTENCES:
        raise ValidationError(
            "too_long", f"{n}문장입니다. 한 번에 한 가지만, {MAX_SENTENCES}문장 이내로 재생성이 필요합니다."
        )
    if n == 0:
        raise ValidationError("empty", "링크를 제거하고 나니 남는 문장이 없습니다.")

    return ValidatedQuestion(
        question=cleaned,
        evidence_refs=kept,
        dropped_refs=sorted(set(dropped)),
        sentence_count=n,
    )


# ============================================================ 4) 실제 생성 (TODO)
def build_messages(extracted_text: str, signals: list, references: list, history: list) -> list:
    """Claude Messages API 로 보낼 user 메시지를 조립한다.

    references 는 반드시 '검색으로 실제 확보한 것'만 넣는다.
    여기에 없는 링크를 모델이 쓰면 validate_question 이 잘라낸다.
    """
    ref_lines = "\n".join(
        f"- {r.get('title', '')} | {r.get('publisher', '')} | {r.get('url', '')}" for r in references
    ) or "- (검색 결과 없음: 출처를 찾지 못했다는 사실을 그대로 알릴 것)"
    sig_lines = "\n".join(f"- {s.get('label', s)}" for s in signals) or "- (특이 신호 없음)"
    hist_lines = "\n".join(f"- {h}" for h in history) or "- (첫 질문)"

    user = (
        f"[사용자가 받은 글]\n{extracted_text}\n\n"
        f"[확인이 필요한 지점]\n{sig_lines}\n\n"
        f"[사용할 수 있는 실제 출처 - 이 목록 밖의 링크는 절대 쓰지 말 것]\n{ref_lines}\n\n"
        f"[지금까지의 대화]\n{hist_lines}\n\n"
        "위 내용을 바탕으로 다음 확인 질문 하나를 JSON으로 출력하십시오."
    )
    return [{"role": "user", "content": user}]


def generate_question(
    extracted_text: str,
    signals: list,
    references: list,
    history: list | None = None,
    max_retry: int = 2,
) -> ValidatedQuestion:
    """TODO(김태희): Claude API 호출 → validate_question → 실패 시 재생성 루프.

    구현 스케치::

        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        allowed = [r["url"] for r in references]
        for attempt in range(max_retry + 1):
            resp = client.messages.create(
                model="claude-sonnet-4-5",
                system=SYSTEM_PROMPT,
                messages=build_messages(...),
                max_tokens=500,
            )
            data = json.loads(resp.content[0].text)
            try:
                return validate_question(data["question"], allowed, data.get("evidence_refs"))
            except ValidationError as e:
                if e.reason == "forbidden_word" and attempt < max_retry:
                    continue          # 판정어가 섞였다 → 재생성
                raise

    키가 없으면 여기서 MissingKeyError → 라우터가 501 + 안내 메시지로 변환한다.
    """
    if not settings.has_llm:
        raise MissingKeyError("ANTHROPIC_API_KEY", owner="김태희")
    raise NotImplementedError(
        "generate_question 은 아직 구현 전입니다. 현재는 ?mock=1 로 고정 질문을 사용하세요."
    )
