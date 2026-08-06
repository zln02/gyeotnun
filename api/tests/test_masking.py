"""개인정보 마스킹의 기존 계약과 확장된 판정 규칙을 검증한다."""
from __future__ import annotations

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import masking  # noqa: E402


def test_mask_phone_and_account():
    result = masking.mask_text(
        "연락처 010-0000-0001 계좌 000-000-000001 로 보내주세요."
    )

    assert "010-0000-0001" not in result.text
    assert "000-000-000001" not in result.text
    assert "010-****-****" in result.text
    assert "***-***-******" in result.text
    assert {"phone", "account"} <= {
        item["type"] for item in result.masked_items
    }


def test_mask_rrn_and_card():
    result = masking.mask_text(
        "주민번호 900101-1000001 카드 4242-4242-4242-4242"
    )

    assert "900101-1000001" not in result.text
    assert "4242-4242-4242-4242" not in result.text
    assert {"rrn", "card"} <= {item["type"] for item in result.masked_items}


def test_mask_phone_without_hyphen():
    result = masking.mask_text("전화 01000000001 입니다.")
    assert "01000000001" not in result.text


def test_mask_noop_when_clean():
    text = "오늘 날씨가 좋습니다."
    result = masking.mask_text(text)

    assert not result.masked
    assert result.text == text


@pytest.mark.parametrize(
    "raw",
    ("070-0000-0001", "(010) 0000-0001", "010 - 0000 - 0001"),
)
def test_phone_supported_variants(raw):
    assert "****-****" in masking.mask_text(f"연락처 {raw}").text


@pytest.mark.parametrize("raw", ("010/0000/0001", "010-0000\n-0001"))
def test_phone_unsupported_variants_stay_unmasked(raw):
    assert raw in masking.mask_text(f"연락처 {raw}").text


def test_phone_positive_context_wins_over_negative_context():
    negative = masking.mask_text("제품 버전 010.123.4567")
    both = masking.mask_text("제품 설명서 연락처 010-0000-0001")

    assert "010.123.4567" in negative.text
    assert "010-****-****" in both.text


@pytest.mark.parametrize(
    "raw",
    (
        "3782-822463-10005",
        "4242 4242 4242 4242",
        "4000-0000-0000-0000-006",
    ),
)
def test_card_supported_lengths_and_separators(raw):
    assert "****-****-****-****" in masking.mask_text(f"카드번호 {raw}").text


def test_card_luhn_and_context_policy():
    product_number = "5100 0051 0000 5101"

    assert product_number in masking.mask_text(f"제품 번호 {product_number}").text
    assert "****-****-****-****" in masking.mask_text(
        "결제 카드 4242424242424242"
    ).text


def test_account_requires_context_for_expanded_shapes():
    assert "***-***-******" in masking.mask_text(
        "은행 계좌는 000.000.000001입니다."
    ).text
    assert "000000000001" in masking.mask_text("생년월일 000000000001").text


def test_no_distance_algorithm_is_present():
    source = inspect.getsource(masking)

    assert "nearest_distance" not in source
    assert "positive_distance" not in source
    assert "negative_distance" not in source


def test_public_api_contract_and_original_discard_helpers():
    result = masking.mask_text("연락처 010-0000-0001")

    assert isinstance(result.text, str)
    assert isinstance(result.masked, bool)
    assert isinstance(result.masked_items, list)
    assert set(result.masked_items[0]) == {"type", "original_hint", "count"}

    image = b"synthetic-image"
    returned, items = masking.mask_image_faces(image)
    assert returned == image
    assert isinstance(items, list)
    assert masking.discard_original(image) is None
