"""
곁눈(Gyeotnun) - 이미지/링크에서 텍스트 추출
담당: 박진 (인식)

입력 3종
  - image : 카카오톡 캡처, 유튜브 썸네일 사진 → Google Vision OCR
  - link  : 유튜브/블로그 URL → 제목·본문(자막) 추출
  - text  : 붙여넣은 텍스트 → 그대로 사용

★ 원본 이미지는 메모리에서만 다루고 디스크에 쓰지 않는다.
  추출 직후 masking.mask_text() 를 통과시킨 결과만 상위로 넘긴다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import MissingKeyError, settings

# 주제 영역 추정용 키워드 (간이 규칙 기반. 추후 분류 모델로 교체 - TODO 박진)
# NOTE: '계좌', '입금' 같은 단어는 개인정보 문맥에서도 흔히 나와 도메인 오판을 유발한다.
#       (실측: "지원금 ... 계좌 123-456-789012" 가 policy 가 아닌 finance 로 분류됨)
#       → 주제 판별 키워드에서 제외하고, masking.py 의 신호로만 다룬다.
DOMAIN_KEYWORDS = {
    "policy": ["지원금", "연금", "기초연금", "정부", "신청", "지급", "복지", "보조금", "혜택", "재난지원"],
    "health": ["암", "혈압", "당뇨", "치매", "효능", "복용", "건강", "면역", "관절", "부작용"],
    "finance": ["투자", "수익률", "원금", "코인", "주식", "대출", "보험", "적금", "펀드"],
    "news": ["속보", "단독", "충격", "긴급", "발표"],
}
# 동점일 때의 우선순위. 시니어 피해가 큰 순서(정책 사칭 > 건강 > 금융)로 둔다.
DOMAIN_PRIORITY = ["policy", "health", "finance", "news"]


@dataclass
class ExtractResult:
    text: str
    detected_domain: Optional[str] = None
    status: str = "extracted"


def detect_domain(text: str) -> Optional[str]:
    """텍스트에서 주제 영역을 추정한다. 어느 쪽 검색 코퍼스를 볼지 결정하는 데 쓴다."""
    if not text:
        return None
    scores = {d: sum(1 for k in kws if k in text) for d, kws in DOMAIN_KEYWORDS.items()}
    # 동점이면 DOMAIN_PRIORITY 순서로 결정한다 (dict 순서에 의존하지 않도록)
    best = max(DOMAIN_PRIORITY, key=lambda d: (scores[d], -DOMAIN_PRIORITY.index(d)))
    return best if scores[best] > 0 else "unknown"


def extract_from_text(text: str) -> ExtractResult:
    """텍스트 입력은 외부 API 없이 즉시 처리 가능하다(키 없이도 동작)."""
    text = (text or "").strip()
    return ExtractResult(
        text=text,
        detected_domain=detect_domain(text),
        status="extracted" if text else "needs_input",
    )


def extract_from_image(image_bytes: bytes) -> ExtractResult:
    """TODO(박진): Google Vision DOCUMENT_TEXT_DETECTION 호출.

    구현 스케치::

        payload = {"requests": [{
            "image": {"content": base64.b64encode(image_bytes).decode()},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["ko"]},
        }]}
        r = httpx.post(
            f"https://vision.googleapis.com/v1/images:annotate?key={settings.GOOGLE_VISION_API_KEY}",
            json=payload, timeout=15,
        )
        text = r.json()["responses"][0]["fullTextAnnotation"]["text"]

    주의: 반환 직후 masking.mask_text() 를 반드시 통과시킬 것.
    """
    if not settings.has_vision:
        raise MissingKeyError("GOOGLE_VISION_API_KEY", owner="박진")
    raise NotImplementedError("extract_from_image 미구현. ?mock=1 을 사용하세요.")


def extract_from_link(url: str) -> ExtractResult:
    """TODO(박진): 링크에서 제목/본문 추출.

    - youtube.com / youtu.be → oEmbed 로 제목, 가능하면 자막 API
    - 그 외 → HTML <title> + 본문 텍스트 (readability 계열)
    - robots.txt 를 존중하고, 요청에 타임아웃을 반드시 건다.
    """
    if not url:
        return ExtractResult(text="", status="needs_input")
    raise NotImplementedError("extract_from_link 미구현. ?mock=1 을 사용하세요.")
