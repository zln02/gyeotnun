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
