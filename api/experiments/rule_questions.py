"""
규칙 기반 확인 질문 생성기 (실험, 2026-08-04)

배경: 비용 실측 결과 확인 질문 생성이 건당 원가의 79.8%(22.56원)를 차지한다
(docs/evaluation/cost_analysis.md). 이걸 규칙으로 대체할 수 있는지 보는 실험이다.

★ services/ 를 건드리지 않는다. 이 모듈은 프로덕션 경로에서 import 되지 않는다.
  services/prompt_chain.py 는 그대로 두고, 여기서 나온 결과를 같은 기준으로
  채점해 비교만 한다.

설계
  1) 마스킹 정규식(services/masking.py)을 재사용해 신호를 뽑는다.
     ★ collect_evidence() 에 들어오는 텍스트는 이미 마스킹된 상태라
       "010-****-****", "***-***-******" 같은 형태다. 원본형과 마스킹형을
       둘 다 잡아야 한다(실측으로 확인한 사항).
  2) 신호별 질문 템플릿을 둔다.
  3) 신호가 여러 개면 우선순위대로 최대 2개만 낸다.

★ 모든 템플릿은 아래를 지켜야 한다(prompt_chain 과 같은 제약):
   - FORBIDDEN_PATTERNS(가짜·사기·진짜입니다 등) 미포함 → 판정하지 않는다
   - 2문장 이내
   - 사용자가 지금 할 수 있는 행동을 제시한다
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------- 신호 정규식
# 마스킹 전/후를 모두 잡는다. 마스킹 결과는 서비스에서 실측한 형태를 그대로 반영했다.
PAT = {
    # 계좌: 123-456-789012 또는 ***-***-******
    "account": re.compile(r"(?<![\d*-])([\d*]{2,6})-([\d*]{2,6})-([\d*]{4,8})(?![\d*-])"),
    # 계좌 문맥어 + 숫자/별표 덩어리
    "account_ctx": re.compile(r"(계좌|입금|송금)\s*[:：]?\s*[\d*]{6,}"),
    # 전화: 010-1234-5678 또는 010-****-****
    "phone": re.compile(r"(?<![\d*])(01[016789])[-\s]?([\d*]{3,4})[-\s]?([\d*]{4})(?![\d*])"),
    # 단축 URL (실제 서비스에서 흔한 것들)
    "short_url": re.compile(r"\b(bit\.ly|han\.gl|buly\.kr|url\.kr|tinyurl|me2\.do|goo\.gl|vo\.la)\b", re.I),
    # 공식 도메인이 아닌 링크 (go.kr/or.kr 이 아닌 도메인)
    "nonofficial_url": re.compile(r"\b(?:https?://|hxxps?://|www\.)?([a-z0-9][a-z0-9\-]*\.(?:com|net|kr|co\.kr|org|info|xyz|top))\b", re.I),
    "official_domain": re.compile(r"\b[a-z0-9\-]+\.(?:go\.kr|or\.kr)\b", re.I),
}

KEYWORDS = {
    "urgency": ["오늘까지", "마감", "긴급", "서둘러", "선착순", "즉시", "지금 바로", "안 하면", "취소됩니다", "기한"],
    "condition_omitted": ["전원", "누구나", "무조건", "모두에게", "전부", "전 국민", "대상자로 선정"],
    "prepay": ["인증비", "수수료", "선입금", "입금 후", "먼저 입금", "보증금", "예치금"],
    "personal_info": ["주민번호", "주민등록번호", "본인인증", "계좌번호", "카드번호", "비밀번호", "이름과 전화번호"],
    "agency_claim": ["정부", "복지부", "보건복지부", "국민연금", "건강보험", "정부24", "복지로", "주민센터",
                     "한국사회보장정보원", "질병관리청", "국세청", "공단"],
    "money_claim": ["지원금", "환급금", "당첨", "지급", "만원", "포인트", "혜택"],
}


@dataclass
class RuleSignal:
    key: str
    label: str
    evidence: str = ""          # 실제로 걸린 부분(디버깅·검증용)
    priority: int = 99


@dataclass
class RuleQuestion:
    question: str
    why: str
    signal_key: str
    options: List[dict] = field(default_factory=list)


# ---------------------------------------------------------------- 신호 추출
def detect_rule_signals(text: str) -> List[RuleSignal]:
    """텍스트에서 규칙으로 잡히는 신호를 우선순위와 함께 뽑는다.

    우선순위 근거: 시니어 피해 규모가 큰 순서로 뒀다. 돈이 실제로 빠져나가는
    경로(선입금 요구 > 계좌 > 개인정보)를 가장 앞에 두고, 판단을 서두르게 만드는
    압박(마감)과 확인을 어렵게 만드는 장치(단축URL·비공식도메인)를 그다음에 뒀다.
    """
    t = text or ""
    out: List[RuleSignal] = []

    def has(group: str) -> str:
        for w in KEYWORDS[group]:
            if w in t:
                return w
        return ""

    w = has("prepay")
    if w:
        out.append(RuleSignal("prepay", "돈을 먼저 보내라는 요구", w, 1))

    if PAT["account"].search(t) or PAT["account_ctx"].search(t):
        m = PAT["account"].search(t) or PAT["account_ctx"].search(t)
        out.append(RuleSignal("account", "계좌번호가 적혀 있음", m.group(0), 2))

    w = has("personal_info")
    if w:
        out.append(RuleSignal("personal_info", "개인정보를 요구함", w, 3))

    if PAT["short_url"].search(t):
        out.append(RuleSignal("short_url", "단축 주소가 있음", PAT["short_url"].search(t).group(0), 4))

    # 비공식 도메인: go.kr/or.kr 이 아닌 링크가 있는데 기관을 사칭하는 경우
    nonoff = PAT["nonofficial_url"].search(t)
    if nonoff and not PAT["official_domain"].search(t):
        out.append(RuleSignal("nonofficial_url", "공식 주소가 아닌 링크", nonoff.group(1), 5))

    w = has("urgency")
    if w:
        out.append(RuleSignal("urgency", "서두르게 만드는 표현", w, 6))

    w = has("condition_omitted")
    if w:
        out.append(RuleSignal("condition_omitted", "조건 없이 모두에게 준다는 표현", w, 7))

    if PAT["phone"].search(t):
        out.append(RuleSignal("phone", "연락처가 적혀 있음", PAT["phone"].search(t).group(0), 8))

    agency = has("agency_claim")
    money = has("money_claim")
    if agency and money:
        out.append(RuleSignal("agency_money", f"기관 이름과 금액이 함께 있음", f"{agency}/{money}", 9))

    out.sort(key=lambda s: s.priority)
    return out


# ---------------------------------------------------------------- 질문 템플릿
# ★ 전부 2문장 이내, 금지어 없음, 마지막에 사용자가 지금 할 수 있는 행동을 둔다.
TEMPLATES = {
    "prepay": [
        ("돈을 먼저 보내야 준다고 적혀 있습니다. 공식 기관이 지원금을 주면서 먼저 돈을 받는 경우가 있는지 확인해 보시겠어요?",
         "지원금을 준다면서 먼저 돈을 요구하는 것은 공식 절차에 없는 방식입니다."),
        ("받기 전에 내야 하는 돈이 있다고 합니다. 해당 기관 대표번호로 전화해 같은 안내를 하는지 물어봐 주시겠어요?",
         "기관에 직접 확인하면 안내 내용이 실제인지 바로 알 수 있습니다."),
    ],
    "account": [
        ("글 안에 계좌번호가 적혀 있습니다. 이 계좌가 기관 공식 누리집에도 같이 안내되어 있는지 확인해 보시겠어요?",
         "공식 기관은 계좌를 문자보다 누리집에 먼저 안내합니다."),
        ("입금할 계좌가 안내되어 있습니다. 돈을 보내기 전에 가족이나 주민센터에 한 번 물어봐 주시겠어요?",
         "송금은 되돌리기 어려우므로 보내기 전 확인이 가장 중요합니다."),
    ],
    "personal_info": [
        ("주민번호나 계좌번호 같은 정보를 요구하고 있습니다. 이 정보를 문자로 받는 것이 정상 절차인지 기관에 물어봐 주시겠어요?",
         "공식 기관은 문자나 링크로 주민번호를 받지 않습니다."),
        ("본인 확인을 위해 개인정보를 보내라고 합니다. 기관 대표번호로 직접 전화해 같은 요청을 했는지 확인해 보시겠어요?",
         "요청한 곳이 실제 기관인지는 대표번호로만 확인할 수 있습니다."),
    ],
    "short_url": [
        ("주소가 짧게 줄여진 형태입니다. 눌러보기 전에 기관 공식 누리집 주소와 같은지 비교해 보시겠어요?",
         "줄인 주소는 실제 연결되는 곳을 감출 수 있습니다."),
        ("링크가 어디로 연결되는지 주소만 봐서는 알기 어렵습니다. 검색창에 기관 이름을 직접 쳐서 들어가 보시겠어요?",
         "주소를 직접 입력하면 안전하게 같은 내용을 찾을 수 있습니다."),
    ],
    "nonofficial_url": [
        ("링크 주소가 정부 기관 주소(go.kr)와 다릅니다. 기관 이름을 검색창에 직접 쳐서 나오는 주소와 비교해 보시겠어요?",
         "정부·공공기관 누리집 주소는 go.kr 또는 or.kr 로 끝납니다."),
        ("안내된 주소가 공식 기관 주소 형태가 아닙니다. 정부24나 복지로에서 같은 안내를 찾을 수 있는지 확인해 보시겠어요?",
         "같은 내용이 공식 누리집에 없다면 한 번 더 확인이 필요합니다."),
    ],
    "urgency": [
        ("'{evidence}'처럼 서두르게 하는 표현이 있습니다. 실제 신청 기한이 언제까지인지 기관에 직접 확인해 보시겠어요?",
         "서두르게 만드는 표현은 확인할 시간을 줄이려는 경우가 많습니다."),
        ("시간이 얼마 없다고 적혀 있습니다. 하루 정도 두고 확인해도 되는 내용인지 살펴봐 주시겠어요?",
         "공식 제도는 대개 신청 기간이 넉넉하고 누리집에 기한이 적혀 있습니다."),
    ],
    "condition_omitted": [
        ("'{evidence}'라고 적혀 있습니다. 공식 안내에도 조건 없이 모두에게 준다고 되어 있는지 확인해 보시겠어요?",
         "지원금은 보통 나이·소득 같은 조건이 붙습니다."),
        ("대상에 제한이 없다고 되어 있습니다. 신청 자격이 무엇인지 기관 누리집에서 찾아봐 주시겠어요?",
         "조건이 적혀 있지 않다면 원문을 확인해 볼 필요가 있습니다."),
    ],
    "phone": [
        ("글에 적힌 번호로 연락하라고 되어 있습니다. 이 번호가 기관 대표번호와 같은지 확인해 보시겠어요?",
         "기관 대표번호는 누리집 첫 화면에서 확인할 수 있습니다."),
    ],
    "agency_money": [
        ("기관 이름과 지급 금액이 함께 적혀 있습니다. 그 기관 누리집에서 같은 안내를 찾을 수 있는지 확인해 보시겠어요?",
         "기관 이름은 누구나 적을 수 있어서, 원문이 있는지가 더 확실한 단서입니다."),
        ("어느 기관에서 보낸 것인지 적혀 있습니다. 그 기관 대표번호로 전화해 같은 안내를 했는지 물어봐 주시겠어요?",
         "발신 이름만으로는 보낸 곳을 확인할 수 없습니다."),
    ],
}

# 신호가 하나도 안 잡혔을 때(정상 안내문 등) 쓰는 기본 질문.
# ★ 의심을 유도하지 않는 중립 문장이어야 한다 - 정상 10건에서 불필요한 의심
#   질문이 나가면 안 된다는 절대 조건 때문이다.
#   ★ 순서 주의: 실행 가능한 행동을 담은 것을 앞에 둔다. "어디에서 받으셨는지
#     기억나시나요"는 회상 질문일 뿐 사용자가 확인할 대상이 없어서, 지표 4)
#     '확인 가능성' 기준으로도 실제 도움 면에서도 뒤진다(스모크 테스트로 확인).
NEUTRAL = [
    ("글에 적힌 기관 이름을 찾으셨나요? 그 기관 누리집에서 같은 안내를 볼 수 있는지 확인해 보시겠어요?",
     "같은 내용이 공식 누리집에 있으면 안심하고 진행하실 수 있습니다."),
    ("이 안내를 어디에서 받으셨는지 기억나시나요? 보낸 곳의 공식 대표번호로 같은 내용인지 물어봐 주시겠어요?",
     "보낸 곳에 직접 확인하는 것이 가장 확실합니다."),
]

FOLLOWUP_OPTIONS = [
    {"id": "checked", "label": "확인해 봤어요"},
    {"id": "not_yet", "label": "아직 못 해봤어요"},
    {"id": "hard", "label": "어떻게 하는지 모르겠어요"},
]


def generate_questions(text: str, max_q: int = 2) -> List[RuleQuestion]:
    """규칙만으로 확인 질문을 만든다. 신호 우선순위대로 최대 max_q 개."""
    signals = detect_rule_signals(text)
    out: List[RuleQuestion] = []

    for sig in signals:
        tpl = TEMPLATES.get(sig.key)
        if not tpl:
            continue
        q, why = tpl[len(out) % len(tpl)]
        out.append(RuleQuestion(
            question=q.format(evidence=sig.evidence),
            why=why, signal_key=sig.key, options=list(FOLLOWUP_OPTIONS),
        ))
        if len(out) >= max_q:
            break

    if not out:
        for q, why in NEUTRAL[:max_q]:
            out.append(RuleQuestion(question=q, why=why, signal_key="neutral",
                                    options=list(FOLLOWUP_OPTIONS)))
    return out
