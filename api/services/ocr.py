"""
곁눈(Gyeotnun) - 이미지/링크에서 텍스트 추출
담당: 박진 (인식)

입력 3종
  - image : 카카오톡 캡처, 유튜브 썸네일 사진 → Claude Vision (멀티모달)으로 직접 추출
  - link  : 유튜브/블로그 URL → 제목·본문(자막) 추출
  - text  : 붙여넣은 텍스트 → 그대로 사용

★ 원본 이미지는 메모리에서만 다루고 디스크에 쓰지 않는다.
  추출 직후 masking.mask_text() 를 통과시킨 결과만 상위로 넘긴다.
  Vision 호출 자체도 base64 인코딩한 바이트를 요청 본문에 실어 보낼 뿐,
  어디에도 파일로 쓰지 않는다.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from config import MissingKeyError, settings

log = logging.getLogger("gyeotnun.ocr")

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
    status: str = "extracted"   # extracted | needs_input | failed


# ============================================================ Claude Vision OCR
VISION_MODEL = "claude-sonnet-5"
VISION_MAX_TOKENS = 2048
# 짧고 기계적인(창작이 아닌) 전사 작업이라 낮은 effort 로 충분하다.
VISION_EFFORT = "low"

VISION_SYSTEM_PROMPT = """당신은 곁눈의 이미지 읽기 도우미입니다. 카카오톡 등 메신저 대화 캡처 화면에서
사용자가 받은 메시지의 '본문 내용'만 정확히 옮겨 적습니다. 내용을 판단하거나 요약하지 않습니다.

[캡처 화면에는 여러 요소가 섞여 있습니다 - 반드시 구분하십시오]
- 말풍선 안의 실제 메시지 본문 → 그대로 옮긴다 (가장 중요, 절대 요약하거나 지어내지 않는다)
- 말풍선 위의 작은 글씨(발신자 이름) → 옮기지 않는다
- 말풍선 옆의 작은 글씨(오전/오후 시:분, 읽음 표시) → 옮기지 않는다
- 화면 맨 위 상태바(시간, 배터리, 통신사) → 옮기지 않는다
- 앱 상단바의 대화상대 이름, 뒤로가기·검색·더보기 아이콘, 하단 입력창 placeholder → 옮기지 않는다
- 말풍선이 여러 개면 화면에 보이는 순서(위 → 아래)대로 줄바꿈해 이어 붙인다.

[출력 형식]
JSON 하나만 출력하십시오.
{"readable": true 또는 false, "extracted_text": "...", "reason": "..."}
- readable: 메시지 본문을 읽어 옮길 수 있으면 true.
  화면이 너무 흐리거나, 글자가 없거나, 메신저 캡처가 아니면 false.
- extracted_text: 말풍선 본문만 이어 붙인 텍스트. readable 이 false 면 빈 문자열.
- reason: readable 이 false 일 때만 이유를 한 줄로 적는다 (예: "글자가 흐려서 읽기 어렵습니다").
  readable 이 true 면 빈 문자열로 둔다.
"""

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "readable": {"type": "boolean"},
        "extracted_text": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["readable", "extracted_text", "reason"],
    "additionalProperties": False,
}

# 매직 바이트로 판별한다. UploadFile.content_type 은 클라이언트가 보낸 값이라
# 신뢰할 수 없다(확장자만 바꿔도 브라우저가 잘못된 값을 보낼 수 있다).
_MEDIA_TYPE_SNIFFERS = [
    (lambda b: b[:3] == b"\xff\xd8\xff", "image/jpeg"),
    (lambda b: b[:8] == b"\x89PNG\r\n\x1a\n", "image/png"),
    (lambda b: b[:6] in (b"GIF87a", b"GIF89a"), "image/gif"),
    (lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP", "image/webp"),
]


def _detect_media_type(image_bytes: bytes) -> Optional[str]:
    for check, media_type in _MEDIA_TYPE_SNIFFERS:
        if check(image_bytes):
            return media_type
    return None


_client = None


def _get_client():
    """Anthropic 클라이언트 싱글턴. prompt_chain.py 와 같은 키(ANTHROPIC_API_KEY)를 쓴다."""
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


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


# ============================================================ 로컬 OCR (PaddleOCR)
# ★ 튜닝 실험 결론(docs/evaluation/paddleocr_tuning.md): baseline 이 최선.
#   구성 = 모바일 검출기 + 문서 전처리 off + mkldnn on + 말풍선 필터.
#   전처리 4종(deskew/clahe/denoise/upscale)·box_thresh 0.4 는 넣지 않는다(기각·짧은 이력).
LOCAL_OCR_DET = "PP-OCRv5_mobile_det"
LOCAL_OCR_REC = "korean_PP-OCRv5_mobile_rec"

_paddle_ocr = None

# ★ PaddleOCR 한국어 인식 모델은 한글↔영문/숫자 경계에서 공백을 떨어뜨리는 경향이 있다
#   (예: "환급 신청nhis-refund24.com"). 검증에서 사칭 S08 이 이 공백 하나로 사칭 신호가
#   억제돼 9/10 로 떨어졌다. 경계에 공백을 되살리면 10/10 로 회복되고 정상 오판 0·정확도
#   불변(0.951→0.950). 일반 규칙이라 특정 이미지에 맞춘 튜닝이 아니다.
_HANGUL_LATIN = re.compile(r"([가-힣])([A-Za-z0-9])")
_LATIN_HANGUL = re.compile(r"([A-Za-z0-9])([가-힣])")


def _restore_boundary_spaces(text: str) -> str:
    return _LATIN_HANGUL.sub(r"\1 \2", _HANGUL_LATIN.sub(r"\1 \2", text))


def _get_paddle():
    """PaddleOCR 싱글턴(임베딩의 로컬 모델 싱글턴과 같은 구조). 최초 1회 로드."""
    global _paddle_ocr
    if _paddle_ocr is None:
        from paddleocr import PaddleOCR

        _paddle_ocr = PaddleOCR(
            lang="korean",
            text_detection_model_name=LOCAL_OCR_DET,
            text_recognition_model_name=LOCAL_OCR_REC,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=True,
            cpu_threads=4,
        )
    return _paddle_ocr


def _extract_local(image_bytes: bytes) -> ExtractResult:
    """PaddleOCR 로 메신저 캡처 본문을 뽑는다.

    ★ 원본 이미지는 메모리에서만 다루고 디스크에 쓰지 않는다(Vision 경로와 동일 원칙).
      bytes → ndarray 로 디코드해 predict 하고, 말풍선 필터는 in-memory PIL 로 건다.
    ★ 반환 형식(ExtractResult: text/detected_domain/status)은 Vision 과 완전히 동일하다
      - 응답 계약이 바뀌지 않으므로 프론트 변경이 필요 없다.
    실패 의미: 형식 미지원/본문 없음 → status="failed"(정상 결과). 모델 로드·추론 자체가
      실패하면 예외를 던져 501 로 변환(서비스가 시도조차 못한 경우).
    """
    import cv2
    import numpy as np
    from PIL import Image

    from services import local_ocr

    if _detect_media_type(image_bytes) is None:
        log.warning("[ocr:local] 지원하지 않는 이미지 형식")
        return ExtractResult(text="", status="failed")
    arr = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        return ExtractResult(text="", status="failed")

    try:
        res = _get_paddle().predict(input=arr)
    except Exception as e:  # noqa: BLE001 - 로드/추론 실패는 서비스가 시도조차 못한 경우
        raise RuntimeError(f"로컬 OCR(PaddleOCR) 추론 실패: {e}") from e

    if not res:
        return ExtractResult(text="", status="failed")
    r = res[0]
    texts = r.get("rec_texts", []) or []
    scores = r.get("rec_scores", []) or []
    polys = None
    for key in ("rec_polys", "dt_polys", "rec_boxes"):
        v = r.get(key)
        if v is not None and len(v):
            polys = v
            break
    boxes = []
    for i, t in enumerate(texts):
        p = polys[i] if polys is not None and i < len(polys) else [[0, 0]] * 4
        conf = float(scores[i]) if i < len(scores) else 1.0
        boxes.append(([[float(pt[0]), float(pt[1])] for pt in p], t, conf))

    pil = Image.fromarray(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
    try:
        kept = local_ocr._keep_bubble_boxes(pil, boxes)   # 말풍선 필터(위치·배경밝기)
    except Exception:  # noqa: BLE001 - 필터 실패 시 정규식 후처리로 폴백
        kept = texts
    text = local_ocr._strip_ui_noise("\n".join(kept))     # 상태바·시각 등 UI 잡음 제거
    text = _restore_boundary_spaces(text)                 # 한글↔영문 경계 공백 보정(S08)
    if not text:
        return ExtractResult(text="", status="failed")
    log.info("[ocr:local] 인식 성공: %d자", len(text))
    return ExtractResult(text=text, detected_domain=detect_domain(text), status="extracted")


def extract_from_image(image_bytes: bytes) -> ExtractResult:
    """카카오톡 등 메신저 캡처에서 본문 텍스트만 뽑는다.

    ★ OCR_PROVIDER=local(기본) → PaddleOCR(오프라인, 이미지 외부 미전송).
      OCR_PROVIDER=vision → 아래 Claude Vision 경로(코드·키 그대로 보존).
    아래 docstring·코드는 Vision 경로 설명이다.

    별도 OCR 서비스(Google Vision 등)를 쓰지 않는다. ANTHROPIC_API_KEY 하나로
    처리한다(질문 생성과 같은 키). 원본 바이트는 base64 로 인코딩해 요청 본문에
    실을 뿐 어디에도 파일로 저장하지 않고, 호출이 끝나면 호출부(routers/checks.py)가
    즉시 파기한다.

    반환값 status:
      "extracted" - 정상 인식. text 는 반드시 이후 masking.mask_text() 를 거쳐야 한다.
      "failed"    - 이미지 형식이 지원되지 않거나, 모델이 "읽을 수 없다"고 판단했거나,
                    응답을 JSON 으로 파싱할 수 없는 경우. 서버 오류가 아니라 정상적인
                    결과이므로 예외를 던지지 않는다. 호출부가 "다시 찍어 주세요" 안내로
                    바꾼다.
    키 자체가 없거나(설정 문제) API 호출이 실패하면(네트워크/인증 등, 재시도해도
    의미 없는 상태) 예외를 던져 501 로 변환되게 한다 - 이건 인식 실패가 아니라
    서비스가 시도조차 못 한 경우이기 때문이다.
    """
    if settings.OCR_PROVIDER == "local":
        return _extract_local(image_bytes)

    if not settings.has_llm:
        raise MissingKeyError("ANTHROPIC_API_KEY", owner="박진")

    media_type = _detect_media_type(image_bytes)
    if media_type is None:
        log.warning("[ocr] 지원하지 않는 이미지 형식 (jpeg/png/gif/webp 아님)")
        return ExtractResult(text="", status="failed")

    b64 = base64.b64encode(image_bytes).decode()
    resp = _get_client().messages.create(
        model=VISION_MODEL,
        max_tokens=VISION_MAX_TOKENS,
        system=VISION_SYSTEM_PROMPT,
        output_config={"effort": VISION_EFFORT, "format": {"type": "json_schema", "schema": VISION_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": "이 메신저 캡처에서 말풍선 본문만 옮겨 적어 주세요."},
            ],
        }],
    )

    if resp.stop_reason == "refusal":
        log.warning("[ocr] 모델이 이미지 처리를 거절했습니다(refusal)")
        return ExtractResult(text="", status="failed")

    raw = "".join(b.text for b in resp.content if b.type == "text")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("[ocr] 응답 JSON 파싱 실패: %s", raw[:200])
        return ExtractResult(text="", status="failed")

    text = (payload.get("extracted_text") or "").strip()
    if not payload.get("readable") or not text:
        log.info("[ocr] 인식 실패: %s", payload.get("reason") or "본문을 찾지 못함")
        return ExtractResult(text="", status="failed")

    log.info("[ocr] 인식 성공: %d자", len(text))
    return ExtractResult(text=text, detected_domain=detect_domain(text), status="extracted")


def extract_from_link(url: str) -> ExtractResult:
    """TODO(박진): 링크에서 제목/본문 추출.

    - youtube.com / youtu.be → oEmbed 로 제목, 가능하면 자막 API
    - 그 외 → HTML <title> + 본문 텍스트 (readability 계열)
    - robots.txt 를 존중하고, 요청에 타임아웃을 반드시 건다.
    """
    if not url:
        return ExtractResult(text="", status="needs_input")
    raise NotImplementedError("extract_from_link 미구현. ?mock=1 을 사용하세요.")
