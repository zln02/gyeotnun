"""
곁눈(Gyeotnun) - 이미지 텍스트 추출 (OCR / Vision)
담당: 박진

★ 보안 원칙 ★
    - 이 함수에 들어온 image_bytes 는 **메모리에서만** 다룬다.
    - 디스크/DB/S3 어디에도 원본 이미지를 저장하지 않는다.
    - 함수 반환 후 호출자는 반드시 masking.mask_pii() 를 거쳐 저장한다.

TODO (박진)
    [ ] OCR_PROVIDER=tesseract : pytesseract + 한국어 학습데이터(kor)
        - Dockerfile에 tesseract-ocr-kor 이미 설치되어 있음
        - 카톡 캡처는 대비가 낮아 이진화/확대 전처리 필요
    [ ] OCR_PROVIDER=clova     : 네이버 클로바 OCR (정확도 최상, 유료)
    [ ] OCR_PROVIDER=claude_vision : Claude 이미지 입력으로 텍스트+발신자 추출
    [ ] 카톡 UI 요소(시간, 읽음표시, 프로필명) 제거 후처리
    [ ] 이미지가 아닌 경우(PDF, 스크린샷 아님) 예외 처리
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

__all__ = ["extract_text"]


# 목업: 실제 데모 시나리오와 동일한 "효도지원금 사칭" 텍스트.
# 전화번호·계좌번호가 들어 있어 masking.py 동작을 바로 확인할 수 있다.
_MOCK_TEXT = (
    "[효도지원금 안내]\n"
    "2026년 어르신 효도지원금 신청이 오늘 마감됩니다.\n"
    "만 65세 이상 어르신께 1인당 80만원을 지급해 드립니다.\n"
    "신청서 접수: 대한복지지원센터 010-1234-5678\n"
    "접수비 3만원을 아래 계좌로 먼저 입금해 주세요.\n"
    "국민은행 123456-78-901234 (예금주: 복지지원센터)\n"
    "오늘 안에 신청하지 않으시면 올해는 받으실 수 없습니다.\n"
    "주변 어르신들께도 꼭 알려주세요!"
)


def extract_text(image_bytes: bytes) -> dict[str, Any]:
    """
    이미지에서 텍스트를 추출한다.

    Args:
        image_bytes: 업로드된 이미지 원본 바이트. **저장하지 말 것.**

    Returns:
        {
          "text": str,            # 추출된 원문 (아직 마스킹 전!)
          "confidence": int,      # 0~100 추출 신뢰도
          "provider": str,        # mock | tesseract | clova | claude_vision
          "lines": list[str],     # 줄 단위 분리 결과 (UI 하이라이트용)
          "warnings": list[str],  # 예: ["글자가 흐려 일부를 읽지 못했습니다"]
        }

    주의:
        반환된 "text"는 마스킹 전 원문이다.
        호출자(routers/checks.py)는 반드시 masking.mask_pii_detail() 을 통과시킨 뒤
        그 결과만 DB에 저장해야 한다.
    """
    provider = settings.OCR_PROVIDER

    if provider == "tesseract":
        # TODO(박진): pytesseract 구현
        #   from PIL import Image; import pytesseract, io
        #   img = Image.open(io.BytesIO(image_bytes))
        #   img = _preprocess(img)   # 그레이스케일 → 이진화 → 2배 확대
        #   text = pytesseract.image_to_string(img, lang="kor+eng")
        logger.warning("OCR_PROVIDER=tesseract 미구현 → 목업 반환")
    elif provider == "clova":
        # TODO(박진): 클로바 OCR REST 호출 (settings.CLOVA_OCR_URL / SECRET)
        logger.warning("OCR_PROVIDER=clova 미구현 → 목업 반환")
    elif provider == "claude_vision":
        # TODO(박진): anthropic 이미지 블록으로 텍스트 + 발신자명 동시 추출
        logger.warning("OCR_PROVIDER=claude_vision 미구현 → 목업 반환")

    return _mock_result()


def _mock_result() -> dict[str, Any]:
    """목업 결과. 프론트가 바로 개발을 시작할 수 있도록 제공."""
    return {
        "text": _MOCK_TEXT,
        "confidence": 92,
        "provider": "mock",
        "lines": _MOCK_TEXT.split("\n"),
        "warnings": [],
    }


def extract_from_url(url: str) -> dict[str, Any]:
    """
    URL 입력에서 본문 텍스트를 가져온다. (이미지 대신 링크를 받은 경우)

    TODO(박진): httpx로 fetch → 태그 제거 → 본문 추출.
                단축 URL은 리다이렉트 최종 목적지를 함께 반환할 것.
    """
    return {
        "text": f"(링크 본문 추출 미구현) {url}",
        "confidence": 0,
        "provider": "mock",
        "lines": [],
        "warnings": ["링크 본문 추출은 아직 구현되지 않았습니다."],
    }
