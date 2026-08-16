"""질문의 잘못된 전제 검사 (2026-08-16, 라이브 실사용 발견).

실행: cd api && python -m pytest tests/test_question_check.py -q

■ 이 파일이 지키는 것
  이 검사기는 **오탐이 나면 손해가 큰** 도구다. 재생성 신호로 쓰이면 멀쩡한 질문을
  다시 만들게 하고, 재생성이 반복되면 폴백(고정 질문)으로 떨어져 품질이 오히려
  나빠진다. 그래서 "잡는가" 만큼 **"안 잡아야 할 것을 안 잡는가"** 를 단정한다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.question_check import check_question  # noqa: E402

# ★ 2026-08-16 라이브 실사용에서 실제로 나온 한 쌍. 이 파일의 존재 이유다.
LIVE_TEXT = ("[국민건강보험공단] 건강보험료 환급금 128,000원이 미수령 상태입니다. "
             "오늘까지 신청하지 않으면 소멸됩니다. 아래 주소에서 계좌번호 ***-***-****** "
             "입력 후 본인확인 바랍니다. 문의 010-****-**** https://nhis-refund2026.com")
LIVE_Q = ("이 글에 적힌 내용을 어느 기관에서 발표했는지 글 안에서 한번 찾아봐 주시겠어요? "
          "기관 이름이 보이지 않는다면 그것만으로도 한 번 더 확인해 볼 신호입니다.")


# ──────────────────────────────────────────── (나) 있는데 없다고 전제
def test_live_case_is_caught_as_direction_na():
    """★★ 실물 사례. 입력에 [국민건강보험공단] 이 있는데 '보이지 않는다면' 을 전제했다.

    어르신이 이름을 찾으면 "있으니 괜찮다"로 읽는다 - 사칭 문자에서
    **안심시키는 방향으로** 작동한다. 이걸 못 잡으면 이 검사기는 의미가 없다.
    """
    r = check_question(LIVE_Q, LIVE_TEXT)
    assert not r.ok
    assert [f.direction for f in r.findings] == ["나"]
    assert r.findings[0].fact == "기관이름"


def test_same_question_is_fine_when_the_org_name_is_really_absent():
    """★★ 문구가 아니라 **어긋남**을 본다. ★★

    같은 질문이라도 입력에 기관 이름이 정말 없으면 옳은 질문이다.
    여기가 깨지면 이 검사기는 특정 표현을 금지하는 도구가 되어 버린다.
    """
    assert check_question(LIVE_Q, "환급금이 있으니 오늘까지 신청하세요").ok


@pytest.mark.parametrize("q,text,fact", [
    ("받으신 주소가 보이지 않는다면 한 번 더 확인해 보세요.",
     "안내입니다 https://example.com", "주소"),
    ("금액이 적혀 있지 않다면 공식 안내와 비교해 보세요.",
     "환급금 128,000원 안내", "금액"),
])
def test_other_facts_are_caught_too(q, text, fact):
    r = check_question(q, text)
    assert [f.fact for f in r.findings] == [fact]


# ──────────────────────────────────────────── (가) 없는데 있다고 전제
def test_direction_ga_is_caught():
    r = check_question("글에 적힌 전화번호로 먼저 연락하지 마시고 대표번호로 확인해 보세요.",
                       "상담을 위해 가족 연락처를 알려 주세요.")
    assert [f.direction for f in r.findings] == ["가"]
    assert r.findings[0].fact == "전화번호"


def test_interrogative_is_not_a_presupposition():
    """★ '어느 기관에서 발표했는지 찾아봐 주시겠어요' 는 **묻는** 문장이다.

    기관 이름이 적혀 있다고 전제하지 않는다. 초판은 이걸 (가)로 잡았고(B08·S38),
    그대로 뒀으면 멀쩡한 질문 2건이 재생성 대상이 됐다.
    ★ 전제(presupposition)의 정의에서 나온 구분이지, 평가셋 실패를 보고 맞춘 것이 아니다.
    """
    assert check_question(
        "이 글에 적힌 내용을 어느 기관에서 발표했는지 찾아봐 주시겠어요?",
        "환급금이 있으니 신청하세요").ok


# ──────────────────────────────────────────── 오탐 방지 (여기가 더 중요하다)
@pytest.mark.parametrize("q,text", [
    # 기관 '대표번호로 확인' 은 입력에 번호가 있다는 전제가 아니다
    ("기관 대표번호로 직접 전화해 확인해 보시겠어요?", "[국민건강보험공단] 환급금 안내"),
    # 실제로 있는 것을 가리키는 것은 전제 오류가 아니다
    ("이 글에 적힌 금액이 공식 안내와 같은지 확인해 보시겠어요?", "환급금 128,000원 안내입니다"),
    ("글에 적힌 계좌번호로 바로 보내지 말고 확인해 보세요.", "계좌번호 ***-***-****** 입력"),
    # 아무 사실도 가리키지 않는 일반 질문
    ("이 내용을 가족과 한번 이야기해 보시겠어요?", "[국민건강보험공단] 환급금 안내"),
])
def test_no_false_positive(q, text):
    r = check_question(q, text)
    assert r.ok, f"오탐: {[f.detail for f in r.findings]}"


def test_common_nouns_do_not_count_as_org_name():
    """★ '지원'·'병원'·'확인' 같은 낱말이 기관 이름으로 잡히면 (나) 검사가 무너진다.

    접미사 한 글자로 판정하지 않는다는 설계를 여기서 못 박는다.
    """
    from services.question_check import _has_org
    assert _has_org("[국민건강보험공단] 안내") is True
    assert _has_org("국민연금공단 지사에서 신청") is True
    assert _has_org("지원금을 병원에서 확인하세요") is False


def test_check_does_not_judge_only_points():
    """검사기는 판정하지 않는다 - 어긋난 지점과 근거만 돌려준다."""
    r = check_question(LIVE_Q, LIVE_TEXT)
    f = r.findings[0]
    assert f.quote and f.detail
    for banned in ("가짜", "사기", "위험", "안전"):
        assert banned not in f.detail
