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

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from config import MissingKeyError, settings

log = logging.getLogger("gyeotnun.prompt_chain")

# ============================================================ 0) 모델 설정
MODEL = "claude-sonnet-5"
# 재생성 포함 총 생성 시도 횟수. 전부 실패하면 FALLBACK_QUESTION 으로 내려간다.
MAX_ATTEMPTS = 3
# 질문 한 개를 만드는 짧은 작업이라 낮은 effort 로 충분하다. 시니어가 기다리는 화면이므로 지연이 곧 비용이다.
EFFORT = "low"
# thinking + 응답 JSON 이 함께 들어가는 상한. 넉넉히 두어 중간에 잘리지 않게 한다.
MAX_TOKENS = 4096

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

# ★★ 문장을 나누기 전에 '문장 끝이 아닌 점'을 보호한다 (2026-08-17) ★★
#
#   왜: _SENTENCE_SPLIT_RE 는 마침표를 무조건 문장 끝으로 본다. 그래서
#       "받으신 주소 nhis-refund24.com과 공식 주소 nhis.or.kr을 비교해 보셨나요?"
#   이 **1문장**이 **4문장**으로 세어졌다. 상한이 2라 재생성 3회가 전부 막히고
#   폴백으로 떨어졌다. 2026-08-16 라이브에서 실제로 그렇게 나갔다.
#
#   ★ 하필 도메인 2개를 나란히 놓는 질문 - 사칭 문자에 줄 수 있는 가장 좋은 질문 -
#     이 구조적으로 통과 불가였다(점 3개 → 4문장).
#
#   ★ 목적은 그대로다: **긴 질문을 시니어에게 주지 않는다.** 진짜 3·4문장은 계속 막는다.
#     여기서 하는 일은 "문장 끝이 아닌 점을 문장 끝으로 세지 않는" 것뿐이다.
#
#   ★ 정규식을 복잡하게 만들지 않는다. 보호할 것만 목록으로 두고
#     플레이스홀더로 치환 → 기존 분리기로 분리 → 복원한다.
#     (experiments/score_questions.py 가 2026-08-05 에 같은 문제를 발견하고 그쪽에서만
#      우회하고 있었다. "프로덕션에도 같은 문제가 있다"고 적어 둔 그 메모를 이제 지운다.)
_PROTECT_RES = (
    re.compile(r"https?://\S+"),                                  # URL
    re.compile(r"(?:[A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}"),   # 도메인
    re.compile(r"\d+(?:\.\d+)+"),                                 # 소수점·버전 숫자
    re.compile(r"[*]{2,}(?:[-.][*]{2,})*"),                        # 마스킹 (***-***-******)
    re.compile(r"(?:[A-Za-z]\.){2,}"),                             # 약어 (U.S.A.)
)
_PLACEHOLDER = "\uf8ff"   # 사용자 정의 영역. 본문에 나올 일이 없고 분리자도 아니다.


def _split_sentences(text: str) -> list[str]:
    """문장으로 나눈다. 문장 끝이 아닌 점은 보호했다가 되돌린다."""
    kept: list[str] = []

    def _stash(m: re.Match) -> str:
        kept.append(m.group(0))
        return f"{_PLACEHOLDER}{len(kept) - 1}{_PLACEHOLDER}"

    t = text or ""
    for rx in _PROTECT_RES:
        t = rx.sub(_stash, t)

    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(t) if p.strip()]

    # ★ 복원. 세기만 쓰더라도 되돌려 둔다 - 나중에 조각을 쓰는 곳이 생겨도 안전하다.
    def _restore(p: str) -> str:
        for i, original in enumerate(kept):
            p = p.replace(f"{_PLACEHOLDER}{i}{_PLACEHOLDER}", original)
        return p

    return [_restore(p) for p in parts]
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
    """검증을 통과한 질문. dropped_refs 는 '지어낸 링크'로 판단해 제거된 URL.

    why / options / is_final 은 generate_question 이 LLM 응답에서 채운다.
    validate_question 만 단독으로 쓸 때는 기본값(빈 값)으로 남는다.
    fallback 은 3회 재생성이 모두 실패해 기본 질문으로 내려갔음을 뜻한다.
    """

    question: str
    evidence_refs: List[str] = field(default_factory=list)
    dropped_refs: List[str] = field(default_factory=list)
    sentence_count: int = 0
    why: str = ""
    options: List[dict] = field(default_factory=list)
    is_final: bool = False
    fallback: bool = False


def count_sentences(text: str) -> int:
    """마침표/물음표 기준 문장 수. 종결부호가 없으면 1문장으로 본다.

    ★ URL·도메인·소수점·마스킹·약어 안의 점은 문장 끝으로 세지 않는다
      (_split_sentences 주석 참고).
    """
    return len(_split_sentences(text))


def find_forbidden(text: str) -> str | None:
    """판정으로 읽히는 표현이 있으면 그 단어를, 없으면 None 을 돌려준다.

    공백 제거본에서도 검사해 '가 짜' 같은 우회를 일부 차단한다.
    질문 본문뿐 아니라 why·보기 문구에도 같은 기준을 적용하기 위해 분리했다.
    """
    if not text:
        return None
    flat = re.sub(r"\s+", "", text)
    for word in FORBIDDEN_PATTERNS:
        if word in text or re.sub(r"\s+", "", word) in flat:
            return word
    return None


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
    word = find_forbidden(cleaned)
    if word:
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


# ============================================================ 4) 실제 생성
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


# 응답 스키마. structured outputs 로 강제해 "JSON 파싱 실패" 재시도를 없앤다.
# (파싱 실패에 재시도를 쓰면 정작 판정어 재생성에 쓸 횟수가 줄어든다.)
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "사용자가 스스로 확인할 질문 (두 문장 이내)"},
        "why": {"type": "string", "description": "이 질문을 하는 이유 한 줄"},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "제공된 출처 목록에 실제로 있던 URL만",
        },
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "label": {"type": "string"}},
                "required": ["id", "label"],
                "additionalProperties": False,
            },
            "description": "타이핑 없이 고를 수 있는 보기 2~3개",
        },
        "is_final": {"type": "boolean"},
    },
    "required": ["question", "why", "evidence_refs", "options", "is_final"],
    "additionalProperties": False,
}

# 3회 재생성이 모두 실패했을 때 내려갈 안전한 질문.
# 어떤 글에도 쓸 수 있고, 판정어가 없으며, 2문장이다. (테스트로 고정한다)
#
# ★★ 폴백은 **입력을 모른다는 것이 전제다.** 그러니 입력 사실을 단정하면 안 된다. ★★
#   2026-08-16 라이브에서 실제로 사고가 났다. 예전 문장은 이랬다:
#       "…어느 기관에서 발표했는지 글 안에서 한번 찾아봐 주시겠어요?
#        **기관 이름이 보이지 않는다면** 그것만으로도 한 번 더 확인해 볼 신호입니다."
#   그런데 받은 글은 "[국민건강보험공단] 건강보험료 환급금…" 이었다. 기관 이름이
#   버젓이 적혀 있는 사칭 문자다. 어르신이 이름을 찾으면 **"있으니 괜찮다"로 읽는다.**
#   확인을 도와야 할 질문이 정확히 반대로 작동했다.
#   ★ 실측: 기관명이 있는 입력에서 폴백이 나면 이 오류는 **100%** 발생했다(2/2).
#     모델이 생성한 질문에서는 0/50 이었다 - 폴백 문장만의 문제였다.
#
#   ★ 보기(FALLBACK_OPTIONS)도 같은 기준으로 바꿨다. 예전 첫 보기는
#     "기관 이름이 적혀 있어요" 였는데, 고르는 순간 그 전제가 한 번 더 굳는다.
#     지금은 **입력 사실을 묻지 않고 다음 행동만** 고르게 한다.
#
#   ★★ 새 문장을 고칠 때 지킬 것: 입력을 안 보고도 참이어야 한다.
#     services/question_check.py 가 이 기준을 기계로 검사한다.
FALLBACK_QUESTION = (
    "이 내용을 어디서 확인할 수 있는지 함께 찾아볼까요? "
    "보내신 곳의 공식 창구에서 같은 안내가 있는지 보면 판단이 쉬워집니다."
)
FALLBACK_WHY = "어디서 나온 말인지부터 확인하면 나머지 판단이 훨씬 쉬워집니다."
FALLBACK_OPTIONS = [
    {"id": "will_check", "label": "확인해 볼게요"},
    {"id": "how", "label": "어떻게 확인하나요?"},
    {"id": "unsure", "label": "잘 모르겠어요"},
]

# ---------------------------------------------------------------- 가드레일 집계
# 기획서의 '가드레일 차단율' 근거가 되는 수치. 프로세스 수명 동안 누적된다.
_STATS: dict[str, int] = {
    "calls": 0,             # generate_question 호출 수
    "attempts": 0,          # 실제 Claude 호출 수 (재생성 포함)
    "regenerated": 0,       # 검증 실패로 다시 생성한 횟수
    "forbidden_word": 0,    # 사유별 내역
    "too_long": 0,
    "bad_ref": 0,
    "empty": 0,
    "api_error": 0,
    "fallback": 0,          # 3회 모두 실패해 기본 질문으로 내려간 횟수
}


def guardrail_stats() -> dict:
    """가드레일 집계 스냅샷. block_rate = 재생성 / 전체 생성 시도."""
    s = dict(_STATS)
    s["block_rate"] = round(s["regenerated"] / s["attempts"], 4) if s["attempts"] else 0.0
    return s


def reset_guardrail_stats() -> None:
    """테스트용 초기화."""
    for k in _STATS:
        _STATS[k] = 0


def _record(reason: str, attempt: int, detail: str = "") -> None:
    """재생성 1건을 집계하고 로그로 남긴다. 이 로그가 차단율의 원장이다."""
    _STATS["regenerated"] += 1
    if reason in _STATS:
        _STATS[reason] += 1
    log.warning(
        "[guardrail] blocked attempt=%d/%d reason=%s detail=%s",
        attempt, MAX_ATTEMPTS, reason, detail,
    )


# ---------------------------------------------------------------- Claude 호출
def _few_shot_text() -> str:
    """few-shot 예시를 시스템 프롬프트 뒤에 붙일 텍스트로 만든다.

    프롬프트 캐시는 접두사 일치라서, 매 요청 고정인 few-shot 을 system 블록에
    함께 넣어야 캐시 구간이 최대가 된다. (요청마다 달라지는 내용은 messages 로)
    """
    parts = ["[좋은 답의 기준 - 아래 예시와 같은 형태로 답하십시오]"]
    for ex in FEW_SHOT_EXAMPLES:
        parts.append("입력:\n" + json.dumps(ex["input"], ensure_ascii=False, indent=2))
        parts.append("출력:\n" + json.dumps(ex["output"], ensure_ascii=False, indent=2))
    return "\n\n".join(parts)


def _system_blocks() -> list:
    """캐시 가능한 고정 시스템 블록. 바이트가 매 요청 같아야 캐시가 걸린다."""
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT + "\n\n" + _few_shot_text(),
            # ★ 프롬프트 캐싱: 이 블록까지가 캐시 접두사가 된다.
            #   Sonnet 5 의 최소 캐시 길이는 1024토큰이라 few-shot 을 함께 넣어야 걸린다.
            "cache_control": {"type": "ephemeral"},
        }
    ]


_client = None


def _get_client():
    """Anthropic 클라이언트 싱글턴. 커넥션 재사용 목적."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


_async_client = None


def _get_async_client():
    """비동기 Anthropic 클라이언트 싱글턴 (2026-08-16, #33 2단계).

    ★ 동기 클라이언트와 별개 객체지만 같은 키·같은 모델·같은 인자를 쓴다.
      동기 클라이언트를 async 라우터에서 부르면 그 5초 동안 이벤트 루프가 통째로
      멈춘다(실측: 동시 3명이 5.8 / 10.2 / 14.8초 계단).
    """
    global _async_client
    if _async_client is None:
        import anthropic

        _async_client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _async_client


def _call_kwargs(messages: list) -> dict:
    """호출 인자를 한곳에서 만든다. ★ 동기·비동기가 다른 인자를 쓰면 안 된다."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": _system_blocks(),
        "messages": messages,
        # 짧은 생성이라 낮은 effort 로 충분하다. thinking 은 Sonnet 5 기본값(adaptive)을 쓴다.
        "output_config": {"effort": EFFORT,
                          "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
    }


def _finish_call(resp) -> tuple[dict, str]:
    """응답 처리도 한곳에서. ★ 동기·비동기가 갈라지면 한쪽만 고쳐진다."""
    usage = resp.usage
    log.info(
        "[llm] model=%s in=%s cache_write=%s cache_read=%s out=%s",
        resp.model, usage.input_tokens,
        getattr(usage, "cache_creation_input_tokens", 0),
        getattr(usage, "cache_read_input_tokens", 0),
        usage.output_tokens,
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("모델이 응답을 거절했습니다(refusal).")

    raw = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(raw), raw


def _call_claude(messages: list) -> tuple[dict, str]:
    """Claude 를 한 번 호출해 (파싱된 payload, 원문 JSON) 을 돌려준다."""
    return _finish_call(_get_client().messages.create(**_call_kwargs(messages)))


async def _acall_claude(messages: list) -> tuple[dict, str]:
    """_call_claude 의 비동기판. 하는 일이 같아야 한다 - 인자·후처리를 공유한다."""
    return _finish_call(await _get_async_client().messages.create(**_call_kwargs(messages)))


def _screen_payload(payload: dict, allowed: Sequence[str]) -> ValidatedQuestion:
    """LLM 응답 전체를 곁눈의 원칙으로 검사한다.

    ★ question 뿐 아니라 why 와 보기 문구도 같은 금지어 기준을 적용한다.
      why 에 "가짜라서 그렇습니다" 가 새어 나가면 화면에서는 결국 판정이 된다.
    """
    vq = validate_question(
        payload.get("question", ""),
        allowed_refs=allowed,
        evidence_refs=payload.get("evidence_refs"),
    )

    why = (payload.get("why") or "").strip()
    word = find_forbidden(why)
    if word:
        raise ValidationError("forbidden_word", f"why 에 판정 표현 '{word}' 이(가) 있습니다.")

    options: List[dict] = []
    for opt in payload.get("options") or []:
        label = (opt.get("label") or "").strip()
        word = find_forbidden(label)
        if word:
            raise ValidationError("forbidden_word", f"보기 문구에 판정 표현 '{word}' 이(가) 있습니다.")
        if opt.get("id") and label:
            options.append({"id": opt["id"], "label": label})

    vq.why = why
    vq.options = options
    vq.is_final = bool(payload.get("is_final"))
    return vq


def _fallback_question(allowed: Sequence[str]) -> ValidatedQuestion:
    """3회 모두 실패했을 때의 안전한 기본 질문. 이 경로도 검증을 통과시킨다."""
    _STATS["fallback"] += 1
    log.error(
        "[guardrail] fallback used - %d회 생성이 모두 검증을 통과하지 못했습니다. stats=%s",
        MAX_ATTEMPTS, guardrail_stats(),
    )
    # ★ 오류 코드 체계(2026-08): 이 폴백(기본 질문으로 대체)은 그대로 두고, 서버가
    #   빈도를 인지하도록 GN-001 만 남긴다. 사용자에게 보이는 질문 화면은 바뀌지 않는다.
    from services.incident_log import log_incident
    log_incident("GN-001", detail=f"재생성 {MAX_ATTEMPTS}회 모두 검증 실패")
    vq = validate_question(FALLBACK_QUESTION, allowed_refs=allowed, evidence_refs=list(allowed)[:1])
    vq.why = FALLBACK_WHY
    vq.options = list(FALLBACK_OPTIONS)
    vq.fallback = True
    return vq


def _question_driver(
    extracted_text: str,
    signals: list,
    references: list,
    history: list | None = None,
    max_attempts: int = MAX_ATTEMPTS,
):
    """★★ 가드레일(재생성·검증) 로직 **한 벌**. 실제 API 호출만 바깥에 맡긴다. ★★

    왜 이렇게 나눴나 (2026-08-16, #33 2단계)
      비동기 호출을 넣으려면 이 재시도 루프가 필요한데, 동기용·비동기용으로 사본을
      두 벌 두면 **한쪽만 고쳐지는 날이 온다.** 그 순간 원칙을 어긴 질문이 화면에
      나간다 - 이 파일이 막으려는 바로 그 일이다. 그래서 루프는 여기 하나만 두고,
      "Claude 를 어떻게 부르는가"만 호출자가 정한다.

    프로토콜
        drv = _question_driver(...)
        messages = next(drv)                       # 보낼 messages
        while True:
            try:
                messages = drv.send(("ok", payload, raw))   # 호출 성공
                # 호출이 실패했으면  drv.send(("error", exc, None))
            except StopIteration as stop:
                return stop.value                  # ValidatedQuestion

    흐름 자체는 예전 generate_question 과 같다
      1) Claude 호출 (system 은 프롬프트 캐시, 응답은 structured outputs 로 강제)
      2) validate_question + why/보기 금지어 검사
      3) 실패하면 무엇이 틀렸는지 알려 주고 재생성 (최대 max_attempts 회)
      4) 전부 실패하면 FALLBACK_QUESTION 으로 내려가고 그 사실을 로그로 남긴다
    """
    if not settings.has_llm:
        raise MissingKeyError("ANTHROPIC_API_KEY", owner="김태희")

    _STATS["calls"] += 1
    allowed = [r.get("url") for r in references if r.get("url")]
    messages = build_messages(extracted_text, signals, references, history or [])

    for attempt in range(1, max_attempts + 1):
        _STATS["attempts"] += 1
        last = attempt == max_attempts

        kind, first, second = yield messages
        if kind == "error":
            _STATS["api_error"] += 1
            log.warning("[llm] attempt=%d/%d 호출 실패: %s", attempt, max_attempts, first)
            if last:
                return _fallback_question(allowed)
            continue
        payload, raw = first, second

        try:
            vq = _screen_payload(payload, allowed)
        except ValidationError as e:
            _record(e.reason, attempt, e.detail)
            if last:
                return _fallback_question(allowed)
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    f"방금 답은 곁눈의 원칙을 어겼습니다: {e.detail}\n"
                    "같은 내용을 원칙에 맞게 다시 JSON 으로만 출력하십시오."
                )},
            ]
            continue

        # 허용 목록 밖 링크가 섞였다 = 지어낸 출처다. 링크는 이미 제거됐지만 한 번 더 생성해 본다.
        if vq.dropped_refs and not last:
            _record("bad_ref", attempt, f"허용되지 않은 링크 {vq.dropped_refs}")
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": (
                    f"{vq.dropped_refs} 은(는) 제공된 출처 목록에 없는 링크입니다. "
                    "목록에 있는 URL만 쓰거나, 없다면 evidence_refs 를 빈 배열로 두고 다시 출력하십시오."
                )},
            ]
            continue

        if vq.dropped_refs:
            # 마지막 시도였다면 링크만 제거된 상태로 내보낸다 (질문 자체는 여전히 유효하다).
            _STATS["bad_ref"] += 1
            log.warning("[guardrail] 마지막 시도에서 링크 제거됨: %s", vq.dropped_refs)

        log.info("[guardrail] ok attempt=%d/%d stats=%s", attempt, max_attempts, guardrail_stats())
        return vq

    return _fallback_question(allowed)  # 도달하지 않지만 방어적으로 둔다


def generate_question(
    extracted_text: str,
    signals: list,
    references: list,
    history: list | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> ValidatedQuestion:
    """확인 질문 1개를 만든다 (동기). 가드레일은 _question_driver 가 전부 처리한다.

    이 함수가 하는 일은 **호출 방식뿐**이다 - 동기 클라이언트로 부르고 결과를
    드라이버에 넘긴다. 검증·재생성·폴백 판단은 여기 없다.

    키가 없으면 MissingKeyError → 라우터가 501 + 안내 메시지로 변환한다.
    """
    drv = _question_driver(extracted_text, signals, references, history, max_attempts)
    try:
        messages = next(drv)
        while True:
            try:
                payload, raw = _call_claude(messages)
                outcome = ("ok", payload, raw)
            except Exception as e:  # noqa: BLE001 - API/파싱 오류는 모두 재시도 대상
                outcome = ("error", e, None)
            messages = drv.send(outcome)
    except StopIteration as stop:
        return stop.value


async def agenerate_question(
    extracted_text: str,
    signals: list,
    references: list,
    history: list | None = None,
    max_attempts: int = MAX_ATTEMPTS,
) -> ValidatedQuestion:
    """generate_question 의 비동기판 (2026-08-16, #33 2단계).

    ★ 같은 드라이버를 돌린다. 다른 것은 `await _acall_claude` 한 줄뿐이다.
      가드레일이 동기판과 다를 수 없는 구조다 - 그게 이 설계의 목적이다.
    """
    drv = _question_driver(extracted_text, signals, references, history, max_attempts)
    try:
        messages = next(drv)
        while True:
            try:
                payload, raw = await _acall_claude(messages)
                outcome = ("ok", payload, raw)
            except Exception as e:  # noqa: BLE001 - 동기판과 같은 취급
                outcome = ("error", e, None)
            messages = drv.send(outcome)
    except StopIteration as stop:
        return stop.value
