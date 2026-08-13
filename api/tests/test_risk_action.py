"""위험행동 유형 탐지 테스트 (2026-08-13)
실행: cd api && python -m pytest tests/test_risk_action.py -q

■ 왜 이 테스트가 있는가
  detect_risk_action() 은 오랫동안 urgency_pressure 강등 여부를 가르는 **이진 게이트**
  였다. "무언가 요구가 있다"만 맞으면 됐고 유형이 틀려도 아무 데도 드러나지 않았다.
  화면이 유형을 말하기 시작하면 **유형 오류가 곧 거짓말이 된다** - 그 순간부터
  이 함수의 정확도는 표시 정직성 원칙(verdict.js 머리말)에 직접 걸린다.

  실측·근거: docs/evaluation/위험행동_신호_설계측정_2026-08-13.md
    유형일치 88.0% → 92.0% · 정상 과검출 1건 → 0건 · tier 변경 0건

  ★ 아래 단정은 전부 **유형 정의**에서 나온다. 평가셋 실패를 보고 맞춘 것이 아니다.
    케이스 id 를 적어 둔 것은 추적을 위해서지, 그 케이스를 통과시키려고 쓴 게 아니다.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import search  # noqa: E402


# ── (가) 최장 매칭 우선 : dict 순서에 기대지 않는다
def test_longer_keyword_wins_over_dict_order():
    """'통장 사본'(5자)이 '보내 주'(4자)를 이긴다.

    '통장 사본을 보내라'는 개인정보 요구이지 자금 이체가 아니다 - 유형 정의다.
    (전에는 계좌이체가 dict 첫 키라 먼저 걸렸다. B25·H40)
    """
    label, kw = search.detect_risk_action_detail("통장 사본을 보내 주세요.")
    assert label == "개인정보요구", f"실제={label}"
    assert kw == "통장 사본", f"근거 어휘가 틀렸다: {kw}"


def test_dict_order_is_not_relied_on():
    """키 순서를 바꿔도 결과가 같아야 한다 - 순서 의존이 정말 없는지 본다."""
    original = search.RISK_ACTION_KEYWORDS
    reversed_order = dict(reversed(list(original.items())))
    try:
        search.RISK_ACTION_KEYWORDS = reversed_order
        assert search.detect_risk_action("통장 사본을 보내 주세요.") == "개인정보요구"
    finally:
        search.RISK_ACTION_KEYWORDS = original


# ── (나) 문맥 조건 : 유형 이름이 '앱 설치'다. 장비 설치는 앱 설치가 아니다
def test_hardware_install_is_not_app_install():
    """정상 제도 안내문의 '장비를 설치'가 앱설치로 잡히면 안 된다.

    ★ 이게 무해하지 않은 이유: 화면에 "앱을 설치하라는 내용이 있어요" 가 나가는데
      그 글에는 그런 내용이 없다. 검출하지 않은 것을 적는 셈이다. (N17)
    """
    assert search.detect_risk_action(
        "댁에 응급안전안심 장비를 설치해 화재·응급상황을 자동으로 알려 드리는 서비스입니다."
    ) is None


def test_app_install_with_software_context_is_detected():
    """소프트웨어 문맥이 있으면 정상적으로 잡는다 - 조건을 걸었다고 못 잡으면 안 된다."""
    label, kw = search.detect_risk_action_detail("KB Pay 앱 설치 후 이용해주세요.")
    assert label == "앱설치"
    assert kw == "앱 설치"


def test_generic_send_verb_needs_money_context():
    """'보내 주'만으로 계좌이체가 되면 안 된다. 금전 문맥이 함께 있어야 한다."""
    assert search.detect_risk_action("사진을 보내 주세요.") != "계좌이체"
    assert search.detect_risk_action("자부담금을 안내 계좌로 입금해 주세요.") == "계좌이체"


def test_self_evident_money_words_stand_alone():
    """'입금·송금·이체'는 그 자체가 금전 어휘라 문맥 조건 없이 인정한다."""
    for t in ("지금 바로 송금이 필요해", "기존 대출금을 지정 계좌로 이체하세요"):
        assert search.detect_risk_action(t) == "계좌이체", t


# ── 근거 어휘 반환 : 화면 인용의 원천이다
def test_detail_returns_matched_keyword_for_quoting():
    """유형과 함께 근거가 된 어휘를 돌려줘야 화면에 원문 구절을 인용할 수 있다."""
    label, kw = search.detect_risk_action_detail("본인인증 후 조회하실 수 있습니다.")
    assert label == "인증번호"
    assert kw and kw in "본인인증 후 조회하실 수 있습니다."


def test_no_risk_action_returns_none_and_empty_keyword():
    assert search.detect_risk_action_detail("오늘 날씨가 좋네요.") == (None, "")
