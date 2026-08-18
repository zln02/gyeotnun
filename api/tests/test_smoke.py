"""
곁눈(Gyeotnun) 스모크 테스트
실행: cd api && python -m pytest tests/ -q

가장 중요한 것은 test_validate_question_* 이다.
곁눈이 '판정하지 않는다'는 약속을 코드로 강제하는 테스트이므로,
프롬프트를 고칠 때마다 여기가 통과하는지 반드시 확인한다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mocks import fixtures                                  # noqa: E402
from services.masking import mask_text                      # noqa: E402
from services.prompt_chain import (                         # noqa: E402
    FORBIDDEN_PATTERNS,
    SYSTEM_PROMPT,
    ValidationError,
    count_sentences,
    validate_question,
)
from services.tagger import ERROR_TYPES, tag_error_type     # noqa: E402

ALLOWED = ["https://basicpension.mohw.go.kr/", "https://www.bokjiro.go.kr/"]


# ==================================================== 1) 판정 억제 (핵심)
def test_valid_question_passes():
    """정상 질문은 그대로 통과하고, 허용된 링크는 살아남는다."""
    r = validate_question(
        "이 글에 적힌 금액은 어디에서 발표한 내용일까요? 글 안에서 기관 이름을 찾아봐 주세요.",
        ALLOWED,
        evidence_refs=["https://basicpension.mohw.go.kr/"],
    )
    assert r.sentence_count == 2
    assert r.evidence_refs == ["https://basicpension.mohw.go.kr/"]
    assert r.dropped_refs == []


@pytest.mark.parametrize(
    "bad",
    [
        "이 글은 가짜입니다.",
        "이건 사기입니다. 절대 믿지 마세요.",
        "이 내용은 진짜입니다.",
        "제가 확인해 보니 확실합니다.",
        "허위 정보입니다.",
        "거짓 정보이니 주의하세요.",
        "속으신 것 같습니다.",
        "잘못 아셨네요.",
    ],
)
def test_forbidden_words_are_blocked(bad):
    """★ 판정어가 하나라도 있으면 반드시 막힌다. (재생성 신호)"""
    with pytest.raises(ValidationError) as e:
        validate_question(bad, ALLOWED)
    assert e.value.reason == "forbidden_word"


def test_forbidden_word_with_spacing_workaround():
    """'가 짜'처럼 공백으로 우회해도 걸린다."""
    with pytest.raises(ValidationError):
        validate_question("이 글은 가 짜 입니다.", ALLOWED)


def test_too_long_is_blocked():
    """2문장을 넘기면 실패한다. 시니어는 한 번에 한 가지만 본다."""
    with pytest.raises(ValidationError) as e:
        validate_question("첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.", ALLOWED)
    assert e.value.reason == "too_long"


def test_empty_is_blocked():
    with pytest.raises(ValidationError):
        validate_question("   ", ALLOWED)


def test_hallucinated_link_in_refs_is_dropped():
    """★ 지어낸 링크는 조용히 제거된다 (예외가 아니라 제거)."""
    r = validate_question(
        "이 내용을 공식 안내에서 함께 찾아볼까요?",
        ALLOWED,
        evidence_refs=["https://basicpension.mohw.go.kr/", "https://fake-gov-site.example.com/notice"],
    )
    assert r.evidence_refs == ["https://basicpension.mohw.go.kr/"]
    assert "https://fake-gov-site.example.com/notice" in r.dropped_refs


def test_hallucinated_link_inside_text_is_removed():
    """본문에 박힌 미허용 URL도 문장에서 지운다."""
    r = validate_question(
        "여기에서 확인해 보세요 https://fake.example.com/a 그리고 알려 주세요.",
        ALLOWED,
    )
    assert "fake.example.com" not in r.question
    assert "https://fake.example.com/a" in r.dropped_refs


def test_system_prompt_contains_core_rules():
    """시스템 프롬프트에서 핵심 규칙이 실수로 빠지지 않도록 고정한다."""
    for must in ["진위를 판정하지", "가짜입니다", "지어내지 마십시오", "찾지 못했다", "두 문장"]:
        assert must in SYSTEM_PROMPT


def test_all_mock_questions_pass_validation():
    """★ 시연에 나가는 mock 문장도 예외 없이 원칙을 지킨다."""
    allowed = fixtures.allowed_refs()
    for turn, data in fixtures.DIALOGUE_TURNS.items():
        r = validate_question(data["question"], allowed, data["evidence_refs"])
        assert r.dropped_refs == [], f"turn {turn}: 허용되지 않은 링크가 있습니다"
        assert r.sentence_count <= 2


def test_count_sentences():
    assert count_sentences("한 문장입니다") == 1
    assert count_sentences("하나. 둘?") == 2
    assert count_sentences("") == 0


def test_forbidden_list_not_empty():
    assert len(FORBIDDEN_PATTERNS) >= 10


# ==================================================== 2) 마스킹 (보안)
def test_mask_phone_and_account():
    """★ 요구 케이스: 010-1234-5678 / 계좌 123-456-789012"""
    r = mask_text("연락처 010-1234-5678 계좌 123-456-789012 로 보내주세요")
    assert "010-1234-5678" not in r.text
    assert "123-456-789012" not in r.text
    assert "010-****-****" in r.text
    assert "***-***-******" in r.text
    assert r.masked is True
    types = {i["type"] for i in r.masked_items}
    assert {"phone", "account"} <= types


def test_mask_rrn_and_card():
    r = mask_text("주민번호 900101-1234567 카드 1234-5678-9012-3456")
    assert "900101-1234567" not in r.text
    assert "1234-5678-9012-3456" not in r.text
    assert {"rrn", "card"} <= {i["type"] for i in r.masked_items}


def test_mask_phone_without_hyphen():
    r = mask_text("전화 01012345678 입니다")
    assert "01012345678" not in r.text


def test_mask_noop_when_clean():
    r = mask_text("오늘 날씨가 좋습니다")
    assert r.masked is False
    assert r.text == "오늘 날씨가 좋습니다"


def test_mock_extracted_text_has_no_raw_pii():
    """mock 응답에도 원본 개인정보가 남아 있으면 안 된다."""
    assert "010-1234-5678" not in fixtures.CHECK_CREATE["extracted_text"]
    assert "123-456-789012" not in fixtures.CHECK_CREATE["extracted_text"]


# ==================================================== 3) 태깅
def test_tag_error_type_number_condition():
    signals = [{"key": "number_mismatch"}, {"key": "condition_omitted"}]
    etype, conf = tag_error_type(signals, text="전원 매달 40만원 지급", decision="hold")
    assert etype in ERROR_TYPES
    assert etype == "number_condition"
    assert 0.0 <= conf <= 1.0


def test_tag_error_type_default():
    etype, conf = tag_error_type([], text="", decision="hold")
    assert etype in ERROR_TYPES


# ==================================================== 4) 스키마 계약
def test_evidence_hint_is_never_boolean():
    """★ verdict_hint 에 true/false 가 들어가면 서비스 정체성이 깨진다."""
    assert fixtures.EVIDENCE["verdict_hint"] in ("needs_check", "partially_matched", "no_source_found")


def test_all_mock_refs_have_url():
    for ref in fixtures.EVIDENCE["references"]:
        assert ref["url"].startswith("http")
        assert ref["publisher"]


# ══════════════════════════════════════════ 문장 세기 보호 (2026-08-17)
#
# ★★ 왜 이 묶음이 있나 — 라이브 사고 ★★
#   count_sentences 가 도메인 안의 점을 문장 끝으로 세어, 사람이 보면 1문장인
#   "받으신 주소 a.com과 공식 주소 b.or.kr을 비교해 보셨나요?" 를 4문장으로 셌다.
#   상한이 2라 재생성 3회가 전부 막히고 폴백으로 떨어졌다. 하필 **도메인 2개를
#   나란히 놓는 질문**(사칭 문자에 가장 좋은 질문)이 구조적으로 통과 불가였다.
#
# ★★ 그래서 "통과시키는가"보다 **"막아야 할 것을 여전히 막는가"** 를 먼저 단정한다.
#   보호가 지나쳐 긴 질문이 통과하면 이 가드레일의 목적 자체가 사라진다.
import pytest as _pytest  # noqa: E402

from services.prompt_chain import MAX_SENTENCES, _split_sentences  # noqa: E402


@_pytest.mark.parametrize("text,expected", [
    # ★ 반드시 계속 막혀야 하는 것 (상한 2 초과)
    ("첫째 문장입니다. 둘째 문장입니다. 셋째 문장입니다.", 3),
    ("기관을 확인하세요. 금액을 확인하세요. 주소를 확인하세요. 그리고 전화도 해보세요.", 4),
    # ★ 도메인이 들어 있어도 진짜 3문장이면 막힌다 - 보호가 지나치지 않았다는 증거
    ("문자에 적힌 주소는 nhis-refund24.com입니다. 공식 주소는 nhis.or.kr입니다. 비교해 보시겠어요?", 3),
])
def test_real_multi_sentence_is_still_blocked(text, expected):
    assert count_sentences(text) == expected
    assert count_sentences(text) > MAX_SENTENCES, "막아야 할 긴 질문이 통과한다"


@_pytest.mark.parametrize("text,expected", [
    # ★ 라이브에서 실제로 죽었던 문장들 - 사람이 세면 1문장이다
    ("받으신 주소 nhis-refund24.com과 공식 주소 nhis.or.kr을 비교해 보셨나요?", 1),
    ("문자 속 주소 nhis-refund2026.com과 공식 주소 nhis.or.kr을 한번 비교해 보시겠어요?", 1),
    # 도메인 1개 + 진짜 2문장
    ("정부24 공식 주소는 gov.kr 입니다. 받으신 주소와 비교해 보시겠어요?", 2),
    # 마스킹 패턴
    ("글에 적힌 계좌번호 ***-***-****** 를 보내기 전에 확인해 보시겠어요?", 1),
    # 소수점
    ("할인율 3.5% 가 공식 안내와 같은지 확인해 보시겠어요?", 1),
    # 약어
    ("이 안내가 U.S.A. 기관에서 온 것인지 확인해 보시겠어요?", 1),
    # URL
    ("https://www.bokjiro.go.kr/ssis-tbu/twataa 에서 같은 안내를 찾아보시겠어요?", 1),
])
def test_dots_that_are_not_sentence_ends_are_protected(text, expected):
    assert count_sentences(text) == expected
    assert count_sentences(text) <= MAX_SENTENCES


def test_protected_parts_are_restored():
    """★ 보호는 세기 위한 임시 조치다. 조각을 돌려줄 때는 원문이어야 한다."""
    parts = _split_sentences("정부24 공식 주소는 gov.kr 입니다. 받으신 주소와 비교해 보시겠어요?")
    assert parts == ["정부24 공식 주소는 gov.kr 입니다", "받으신 주소와 비교해 보시겠어요"]
    assert "" not in " ".join(parts), "플레이스홀더가 새어 나갔다"


def test_two_domain_comparison_question_can_pass_validation():
    """★★ 이 테스트가 사고의 본체다.

    사칭 문자에 줄 수 있는 가장 좋은 질문 - 두 주소를 나란히 놓고 비교하게 하는 질문 -
    이 세기 오류 때문에 **절대 통과할 수 없었다.** 이제 통과해야 한다.
    """
    from services.prompt_chain import validate_question
    q = "받으신 주소 nhis-refund24.com과 공식 주소 nhis.or.kr을 비교해 보셨나요?"
    r = validate_question(q, allowed_refs=[])
    assert r.sentence_count == 1
