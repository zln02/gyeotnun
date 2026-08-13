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


# ── 화면 신호로 내보내기 (2026-08-13, 안B: tier 를 올리지 않는다)
def test_risk_action_signal_is_emitted_with_detail_and_quote():
    """유형(detail)과 근거 구절(quote)이 함께 나가야 한다.

    ★ quote 가 핵심이다. 유형 라벨이 만에 하나 어긋나도 사용자는 실제 문장을 본다.
      "받으신 것을 그대로 보여주고 눈으로 비교하게 한다"는 프론트 원칙 그대로다.
    """
    text = "고객님 안내입니다. KB Pay 앱 설치 후 이용해주세요."
    result = search.collect_evidence(text)
    sig = next((s for s in result.signals if s["key"] == "risk_action_requested"), None)
    assert sig is not None, f"위험행동 신호가 없다: {[s['key'] for s in result.signals]}"
    assert sig["detail"] == "앱설치"
    assert sig["quote"] == "KB Pay 앱 설치 후 이용해주세요."
    # ★ 금지어 - 이 화면은 판정이 아니라 안내다.
    assert "사기" not in sig["label"] and "가짜" not in sig["label"]
    assert "찾았" not in sig["label"]


def test_risk_action_raises_tier_is_on_and_paired_with_action_frame():
    """안A 적용 상태 - severity=attention 으로 나간다 (2026-08-13 3단계).

    ★★ 이 스위치를 켜는 데에는 전제가 있다 ★★
      위험행동만으로 올라간 글은 화면에서 **행동 프레임(tier 'act', 주황)** 으로
      나가야 한다. 사기사례 유사 화면("확인이 필요한 문자예요", 빨강)을 재사용하면
      그건 의심 프레임이고 "정상을 의심으로 표시하지 않는다"는 절대 조건과 충돌한다.
      R10(쿠팡 광고 + 본인인증)·R11(카드사 당첨 + 앱설치)이 그런 글이다.

      화면 쪽 짝은 web/src/verdict.js 의 tier 'act' 분기다. 그쪽이 사라지면
      이 스위치는 정상 문자에 빨간 경고를 띄우게 된다 - 함께 움직여야 한다.
      전수 대조 도구: tools/render_verdict.mjs
    """
    assert search.RISK_ACTION_RAISES_TIER is True
    result = search.collect_evidence("고객님 KB Pay 앱 설치 후 이용해주세요.")
    sig = next(s for s in result.signals if s["key"] == "risk_action_requested")
    assert sig["severity"] == "attention"


def test_risk_action_signal_can_be_disabled():
    """되돌릴 스위치가 실제로 동작하는지."""
    from unittest.mock import patch
    with patch("services.search.RISK_ACTION_SIGNAL", False):
        result = search.collect_evidence("고객님 KB Pay 앱 설치 후 이용해주세요.")
    assert "risk_action_requested" not in [s["key"] for s in result.signals]


def test_quote_is_omitted_when_keyword_survives_masking_removal():
    """근거 어휘가 인용문에서 사라지면 인용하지 않는다 - 지어내지 않는다."""
    assert search.risk_action_quote("아무 관계 없는 문장입니다.", "앱 설치") == ""
    assert search.risk_action_quote("앱 설치 후 이용", "") == ""


def test_quote_comes_from_already_masked_text():
    """collect_evidence 입력은 masked_text 라 인용에 원본 숫자가 실릴 수 없다.

    ★ 여기서는 그 전제가 유지되는지를 마스킹된 문자열로 직접 확인한다.
    """
    from services.masking import mask_text
    raw = "계좌 123-456-789012 로 입금해 주세요. 문의 010-1234-5678"
    masked = mask_text(raw).text
    result = search.collect_evidence(masked)
    sig = next((s for s in result.signals if s["key"] == "risk_action_requested"), None)
    assert sig is not None
    import re as _re
    assert not _re.search(r"\d{2,3}-\d{3,4}-\d{4}|\d{3,}-\d{2,}-\d{4,}", sig["quote"] or ""), \
        f"인용에 숫자가 살아 있다: {sig['quote']}"
