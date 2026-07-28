"""
곁눈(Gyeotnun) - 이미지 인식(Claude Vision) 테스트
실행: cd api && python -m pytest tests/test_ocr_vision.py -q -s

fixtures/kakao_sample.jpg 는 실제 카톡 캡처가 아니라 합성 이미지다(개인정보 없음,
숫자는 전부 테스트용 더미 값). 말풍선/발신자명/시간표시/상태바가 섞인 실제 캡처의
구조를 재현해, "본문만 뽑고 나머지는 버리는지"를 검증하기 위해 만들었다.

오프라인 테스트(키 불필요)와 라이브 테스트(ANTHROPIC_API_KEY 필요, 없으면 skip)로
나뉜다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MissingKeyError, settings          # noqa: E402
from services import ocr                              # noqa: E402
from services.masking import mask_text                # noqa: E402

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "kakao_sample.jpg"
BLANK_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "blank_sample.jpg"


# ==================================================== 1) 오프라인 (키 불필요)
def test_detect_media_type_jpeg():
    assert ocr._detect_media_type(b"\xff\xd8\xff\xe0rest") == "image/jpeg"


def test_detect_media_type_png():
    assert ocr._detect_media_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"


def test_detect_media_type_gif():
    assert ocr._detect_media_type(b"GIF89a" + b"rest") == "image/gif"


def test_detect_media_type_webp():
    data = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"rest"
    assert ocr._detect_media_type(data) == "image/webp"


def test_detect_media_type_unknown_returns_none():
    assert ocr._detect_media_type(b"this is not an image at all") is None


def test_missing_key_raises_missing_key_error(monkeypatch):
    """★ 키가 없으면 미인식이 아니라 501로 변환될 예외를 던진다 (설정 문제이므로)."""
    monkeypatch.setattr(ocr.settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(MissingKeyError):
        ocr.extract_from_image(b"\xff\xd8\xff\xe0dummy")


def test_unsupported_format_returns_failed_not_exception(monkeypatch):
    """★ 형식 미지원은 서버 오류가 아니라 '인식 실패' 결과다. 예외를 던지지 않는다."""
    monkeypatch.setattr(ocr.settings, "ANTHROPIC_API_KEY", "test-key-not-real")
    result = ocr.extract_from_image(b"this is not an image at all")
    assert result.status == "failed"
    assert result.text == ""


def test_vision_system_prompt_tells_model_to_drop_chrome():
    """★ 카톡 캡처 특성(말풍선/발신자명/시간표시)을 고려하라는 지시가 실수로
    빠지지 않도록 시스템 프롬프트에 핵심 문구를 고정한다."""
    for must in ["발신자", "시:분", "상태바", "옮기지 않는다"]:
        assert must in ocr.VISION_SYSTEM_PROMPT


def test_fixture_images_exist():
    assert FIXTURE_PATH.exists(), "tests/fixtures/kakao_sample.jpg 가 없습니다."
    assert BLANK_FIXTURE_PATH.exists(), "tests/fixtures/blank_sample.jpg 가 없습니다."


# ==================================================== 2) 라이브 (키 있을 때만)
requires_key = pytest.mark.skipif(
    not settings.has_llm, reason="ANTHROPIC_API_KEY 가 없습니다. 라이브 Vision 테스트를 건너뜁니다."
)


@requires_key
def test_live_extract_from_kakao_screenshot(capsys):
    """★ 업로드 → 추출 → 마스킹까지 실제로 관통시킨다.

    합성 캡처에는 전화번호·계좌·주민번호·카드번호가 섞여 있다(모두 테스트용
    더미 값). masking.mask_text() 를 거친 뒤에는 원본 숫자가 하나도 남지 않아야
    한다.
    """
    image_bytes = FIXTURE_PATH.read_bytes()

    extracted = ocr.extract_from_image(image_bytes)
    assert extracted.status == "extracted"
    assert extracted.text

    # ---- 본문은 뽑혔는가
    for must in ["정부지원금", "40만원", "지급"]:
        assert must in extracted.text

    # ---- ★ 카톡 캡처 특성: 발신자명/시간표시/상태바는 버려졌는가
    for must_not in ["오후 2:15", "오후 2:16", "9:41", "LTE 100%", "메시지를 입력하세요"]:
        assert must_not not in extracted.text, f"UI 요소가 본문에 섞였습니다: {must_not!r}"

    # ---- 마스킹까지 이어붙인다
    masked = mask_text(extracted.text)
    assert masked.masked is True
    types = {i["type"] for i in masked.masked_items}
    assert {"phone", "account", "rrn", "card"} <= types
    for raw in ("010-1234-5678", "123-456-789012", "900101-1234567", "1234-5678-9012-3456"):
        assert raw not in masked.text, f"원본 개인정보가 마스킹 후에도 남아 있습니다: {raw}"

    with capsys.disabled():
        print("\n--- OCR 추출 결과 ---")
        print(extracted.text)
        print("--- 마스킹 후 ---")
        print(masked.text)


@requires_key
def test_live_blank_image_is_reported_as_failed():
    """텍스트가 없는 이미지는 예외 없이 status='failed' 로 알려 줘야 한다."""
    result = ocr.extract_from_image(BLANK_FIXTURE_PATH.read_bytes())
    assert result.status == "failed"
    assert result.text == ""
