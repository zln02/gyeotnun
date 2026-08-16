"""생성된 질문이 **입력 사실을 잘못 전제하는지** 검사한다 (2026-08-16, 라이브 실사용 발견).

■ 왜 필요한가 — 실물 사례
  입력  "[국민건강보험공단] 건강보험료 환급금 128,000원이 미수령 상태입니다 …"
  질문  "…어느 기관에서 발표했는지 글 안에서 한번 찾아봐 주시겠어요?
         **기관 이름이 보이지 않는다면** 그것만으로도 한 번 더 확인해 볼 신호입니다."

  입력에 기관 이름이 **버젓이 있다.** 어르신이 이 질문을 읽고 이름을 찾으면
  "있으니 괜찮다"로 읽는다. 사칭 문자에서 **안심시키는 방향으로 작동한다.**
  이건 문구가 어색한 문제가 아니라 서비스 목적을 정면으로 거스르는 문제다.

■ ★ 두 방향을 다 본다
    (가) 입력에 **없는** 것을 있다고 전제   "글에 적힌 담당자 이름을 …"  (없는데)
    (나) 입력에 **있는** 것을 없다고 전제   "기관 이름이 없다면 …"       (있는데)
  (나)가 이번에 발견된 방향이다. (가)만 막으면 이번 사례는 그대로 통과한다.

■ ★ 설계 원칙 — 어휘를 실패 사례에서 뽑지 않는다
  검사 대상 카테고리는 "질문이 참조할 수 있고, 입력에서 **확실히** 검출할 수 있는
  것"으로만 정했다. 평가셋에서 실패한 문장을 보고 고른 것이 아니다.
  재현율보다 **정밀도**를 택했다 - 이 검사가 오탐을 내면 멀쩡한 질문이 재생성되고,
  재생성이 반복되면 폴백(고정 질문)으로 떨어져 품질이 오히려 나빠진다.

■ ★ 아직 파이프라인에 연결하지 않았다
  지금은 측정 도구다. 채택(재생성 신호로 쓸지)은 실측 후 사람이 정한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# ──────────────────────────────────────────── 입력에서 사실을 검출한다
_RE_BRACKET_SENDER = re.compile(r"\[[^\]]{2,20}\]")
_RE_ORG_WORD = re.compile(
    r"[가-힣]{2,}(?:공단|공사|재단|센터|협회|위원회|진흥원|연구원|은행|카드|보험|"
    r"교통부|복지부|노동부|기획재정부|행정안전부|국세청|경찰청|검찰청|소방청|"
    r"관세청|병무청|질병관리청|금융감독원|금융위원회|우체국|정부24)"
)
_RE_URLISH = re.compile(r"(?:https?://\S+|[a-zA-Z0-9-]+\.(?:kr|com|net|org|co|io|me|xyz|top|site|link))")
_RE_MONEY = re.compile(r"\d[\d,]*\s*(?:원|만원|억원|억)")
_RE_DEADLINE = re.compile(r"(오늘까지|내일까지|모레까지|이내에|까지 신청|마감|기한|"
                          r"\d{1,2}월\s*\d{1,2}일|\d{1,2}/\d{1,2})")
_RE_PHONE = re.compile(r"(?:\d{2,4}-\*{3,4}-\*{4}|\d{2,4}-\d{3,4}-\d{4}|\d{4}-\d{4}|"
                       r"☎|전화\s*\d)")
_RE_ACCOUNT = re.compile(r"(?:\*{3}-\*{3}-\*{6}|계좌번호\s*[\d*]|\d{3}-\d{2,6}-\d{5,6})")


def _has_org(text: str) -> bool:
    """발신 기관 이름이 글에 적혀 있는가.

    ★ 접미사 한 글자(부·처·청·원)만으로 판정하지 않는다. '지원'·'병원'·'확인' 같은
      보통 낱말이 전부 걸려 거의 항상 '있다'가 되고, 그러면 (나) 검사가 오탐 덩어리가 된다.
      대괄호 발신 표기 또는 2자 이상 + 기관 접미사만 인정한다.
    """
    return bool(_RE_BRACKET_SENDER.search(text) or _RE_ORG_WORD.search(text))


@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    present: Callable[[str], bool]
    # 질문이 이 사실을 가리킬 때 쓰는 말
    words: tuple[str, ...]


FACTS: tuple[Fact, ...] = (
    Fact("기관이름", "발신 기관 이름", _has_org,
         ("기관 이름", "기관명", "기관이름", "어느 기관", "발표한 기관", "보낸 기관",
          "보낸 곳", "발신", "어디에서 보냈")),
    Fact("주소", "인터넷 주소", lambda t: bool(_RE_URLISH.search(t)),
         ("주소", "링크", "사이트", "인터넷 주소")),
    Fact("금액", "금액", lambda t: bool(_RE_MONEY.search(t)),
         ("금액", "액수", "얼마")),
    Fact("기한", "기한·날짜", lambda t: bool(_RE_DEADLINE.search(t)),
         ("기한", "마감", "날짜", "언제까지")),
    Fact("전화번호", "전화번호", lambda t: bool(_RE_PHONE.search(t)),
         ("전화번호", "연락처", "전화 번호")),
    Fact("계좌번호", "계좌번호", lambda t: bool(_RE_ACCOUNT.search(t)),
         ("계좌번호", "계좌")),
)

# ──────────────────────────────────────────── 질문에서 전제를 찾는다
# (나) "…이 없다면 / 보이지 않는다면 / 적혀 있지 않으면 / 찾을 수 없다면"
_ABSENCE_TAIL = (r"(?:이|가|은|는)?\s*(?:글\s*안에서\s*)?"
                 r"(?:보이지\s*않|적혀\s*있지\s*않|나와\s*있지\s*않|쓰여\s*있지\s*않|"
                 r"찾을\s*수\s*없|확인되지\s*않|안\s*보이|안\s*적혀|없)\S{0,4}"
                 r"(?:다면|으면|면|을\s*때|경우)")
# (가) "글에 적힌 … / 문자에 나온 … / 안내문에 있는 …"
_PRESENCE_HEAD = r"(?:글|문자|안내문|메시지|내용|여기)\s*(?:에|의|안에)\s*(?:적힌|나온|있는|쓰인|기재된|나와\s*있는)\s*"

# ★ 의문사·확인 요청은 전제가 아니다 (2026-08-16 실측 후 교정).
#   "글에 적힌 내용을 **어느** 기관에서 발표했는지 찾아봐 주시겠어요?" 는 기관 이름이
#   적혀 있다고 전제하지 않는다 - 있는지 **묻는** 문장이다. 그런데 초판 패턴은 이걸
#   (가)로 잡았다(B08·S38). 전제와 질문을 가르지 못하면 이 검사는 멀쩡한 질문을
#   재생성시키고, 재생성이 반복되면 폴백으로 떨어져 품질이 오히려 나빠진다.
#   ★ 이건 평가셋 실패를 보고 맞춘 것이 아니라 '전제(presupposition)' 정의에서 나온다.
_INTERROGATIVE = re.compile(r"(?:어느|어떤|무슨|누가|어디|있나요|있는지|있는가|"
                            r"적혀\s*있나요|찾아봐|찾아보|살펴봐|살펴보)")


@dataclass
class Finding:
    direction: str      # "가" | "나"
    fact: str
    quote: str
    detail: str = ""


@dataclass
class QuestionCheck:
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def _window(text: str, idx: int, before: int = 24, after: int = 24) -> str:
    return text[max(0, idx - before): idx + after].strip()


def check_question(question: str, source_text: str, why: str = "") -> QuestionCheck:
    """질문(+why)이 입력 사실을 잘못 전제하는지 본다.

    ★ 판정하지 않는다 - 어긋난 지점을 짚어 줄 뿐이다. 무엇을 할지는 호출자가 정한다.
    """
    out = QuestionCheck()
    blob = f"{question} {why}".strip()
    for fact in FACTS:
        present = fact.present(source_text)
        for w in fact.words:
            # (나) 있는데 없다고 전제
            m = re.search(re.escape(w) + _ABSENCE_TAIL, blob)
            if m and present:
                out.findings.append(Finding(
                    "나", fact.key, _window(blob, m.start()),
                    f"입력에 {fact.label}이(가) 있는데 질문이 '없다면'을 전제한다"))
                break
        for w in fact.words:
            # (가) 없는데 있다고 전제
            m = re.search(_PRESENCE_HEAD + r"[^.!?]{0,10}" + re.escape(w), blob)
            if m and not present:
                # ★ 같은 절 안에 의문사가 있으면 전제가 아니라 질문이다 - 넘긴다.
                clause = blob[m.start(): m.end() + 24]
                if _INTERROGATIVE.search(clause):
                    continue
                out.findings.append(Finding(
                    "가", fact.key, _window(blob, m.start()),
                    f"입력에 {fact.label}이(가) 없는데 질문이 '적혀 있는' 것으로 전제한다"))
                break
    return out
