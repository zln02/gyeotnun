"""
확인 질문 품질 채점기 (실험, 2026-08-04)

★ LLM 생성과 규칙 생성을 **완전히 같은 기준**으로 채점하기 위한 모듈이다.
  어느 쪽에도 유리하게 만들지 않는다 - 채점 함수는 질문 문자열과 원문만 받고,
  누가 만들었는지 모른다.

지표 4가지 (지시받은 정의 그대로)
  1) 판정 여부   : 금지어가 있으면 실패        → services/prompt_chain.FORBIDDEN_PATTERNS 재사용
  2) 문장 수     : 2문장 이내면 통과            → services/prompt_chain.count_sentences 재사용
  3) 신호 대응   : 원문의 위험 신호를 실제로 짚는가
  4) 확인 가능성 : 사용자가 실행할 수 있는 행동을 제시하는가

  ★ 1·2 는 이미 프로덕션에 있는 검증 로직을 그대로 쓴다(새로 만들면 기준이 달라진다).
  ★ 3·4 는 기존에 지표가 없어 이번에 정의했다. 정의 근거는 각 함수 주석 참고.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, "/app")

from services.prompt_chain import count_sentences, find_forbidden  # noqa: E402
from services.search import SIGNAL_RULES, detect_signals  # noqa: E402

# ---- 지표 3) 신호 대응: 원문에 이 신호가 있으면, 질문이 아래 단어 중 하나를
#      담고 있어야 "그 신호를 짚었다"고 본다. 신호 정의(SIGNAL_RULES)의 안내
#      문구에서 핵심어를 그대로 가져와 자의성을 줄였다.
SIGNAL_EXPECT = {
    "condition_omitted": ["조건", "대상", "자격", "모두", "전원", "누구나", "제한"],
    "urgency_pressure": ["기한", "마감", "서두", "오늘", "시간", "언제까지", "급"],
    "contact_in_image": ["계좌", "입금", "송금", "연락처", "번호", "돈"],
}

# ---- 지표 4) 확인 가능성: "무엇을 할지"가 있어야 한다.
#      행동 동사 + 확인 대상이 함께 있어야 실행 가능한 것으로 본다.
ACTION_VERBS = ["확인", "찾아", "물어", "살펴", "비교", "전화", "방문", "검색", "여쭤", "알아"]
ACTION_TARGETS = ["누리집", "홈페이지", "대표번호", "기관", "주민센터", "가족", "공식", "원문",
                  "검색창", "정부24", "복지로", "번호", "주소", "안내"]


@dataclass
class QuestionScore:
    question: str
    no_verdict: bool          # 1) 판정 안 함
    forbidden_word: str = ""
    within_2_sentences: bool = True
    sentence_count: int = 0
    signal_addressed: bool = False    # 3) 신호 대응
    signal_expected: List[str] = field(default_factory=list)   # 원문에 있던 신호
    actionable: bool = False          # 4) 확인 가능성

    @property
    def passed_all(self) -> bool:
        """신호가 없는 경우(정상 안내문 등)에는 3) 을 요구하지 않는다 -
        짚을 신호가 없는데 억지로 짚으라고 하면 정상 문구에 의심을 유도하게 된다."""
        need_signal = bool(self.signal_expected)
        return (self.no_verdict and self.within_2_sentences and self.actionable
                and (self.signal_addressed if need_signal else True))


def score_question(question: str, source_text: str) -> QuestionScore:
    q = question or ""

    # 1) 판정 여부
    bad = find_forbidden(q)

    # 2) 문장 수
    n = count_sentences(q)

    # 3) 신호 대응
    sigs = [s["key"] for s in detect_signals(source_text)]
    expected = [k for k in sigs if k in SIGNAL_EXPECT]
    addressed = False
    for k in expected:
        if any(w in q for w in SIGNAL_EXPECT[k]):
            addressed = True
            break

    # 4) 확인 가능성
    has_verb = any(v in q for v in ACTION_VERBS)
    has_target = any(t in q for t in ACTION_TARGETS)

    return QuestionScore(
        question=q, no_verdict=(bad is None), forbidden_word=bad or "",
        within_2_sentences=(n <= 2), sentence_count=n,
        signal_addressed=addressed, signal_expected=expected,
        actionable=(has_verb and has_target),
    )


def summarize(scores: List[QuestionScore]) -> dict:
    n = len(scores)
    if n == 0:
        return {}
    need_sig = [s for s in scores if s.signal_expected]
    return {
        "n": n,
        "판정안함": round(sum(s.no_verdict for s in scores) / n, 3),
        "2문장이내": round(sum(s.within_2_sentences for s in scores) / n, 3),
        "신호대응": round(sum(s.signal_addressed for s in need_sig) / len(need_sig), 3) if need_sig else None,
        "신호대응_분모": len(need_sig),
        "확인가능": round(sum(s.actionable for s in scores) / n, 3),
        "전부통과": round(sum(s.passed_all for s in scores) / n, 3),
        "평균문장수": round(sum(s.sentence_count for s in scores) / n, 2),
    }
