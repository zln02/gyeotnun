"""
곁눈(Gyeotnun) - 비식별화(마스킹) 모듈
담당: 박진 (인식·마스킹)

★ 왜 만드는가 (보안성 배점 대응)
  시니어가 올리는 카카오톡 캡처에는 본인·지인의 전화번호, 계좌번호, 얼굴이
  그대로 들어 있는 경우가 매우 많다. 곁눈은 그 이미지를 '판단 재료'로만 쓰고
  개인정보는 **서버에 도달한 직후, DB 저장 전에** 지운다.

파이프라인 상 위치
  업로드 → OCR(ocr.py) → **mask_text() ← 여기** → DB 저장(masked_text) → 원본 이미지 파기

구현 상태
  - 텍스트 마스킹(전화/계좌/주민번호/카드): 실제 동작 (아래 정규식)
  - 얼굴 마스킹: TODO 스텁 (Vision face detection + 블러 예정)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# --------------------------------------------------------------- 정규식 정의
# 한국 휴대폰/일반전화: 010-1234-5678, 01012345678, 010 1234 5678, 02-123-4567
PHONE_RE = re.compile(
    r"(?<![\d-])(01[016789]|0[2-6][0-5]?)[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?![\d-])"
)

# 주민등록번호: 900101-1234567 (전화보다 먼저 처리해야 오탐이 없다)
RRN_RE = re.compile(r"(?<!\d)(\d{6})[-\s]?([1-4]\d{6})(?!\d)")

# 카드번호: 1234-5678-9012-3456
CARD_RE = re.compile(r"(?<!\d)(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})(?!\d)")

# 계좌번호: 은행마다 자릿수가 달라 '2~3개 하이픈 그룹 + 총 10~14자리' 로 잡는다.
# 예) 123-456-789012, 110-123-456789, 1002-345-678901
ACCOUNT_RE = re.compile(r"(?<![\d-])(\d{2,6})-(\d{2,6})-(\d{4,8})(?![\d-])")

# '계좌', '입금' 등 문맥어가 붙은 연속 숫자(하이픈 없는 계좌) 보조 규칙
ACCOUNT_CONTEXT_RE = re.compile(r"(계좌|입금|송금|account)\s*[:：]?\s*(\d{10,16})(?!\d)")


@dataclass
class MaskResult:
    """마스킹 결과. masked_items 는 API 응답에 그대로 실린다."""

    text: str
    masked_items: List[dict] = field(default_factory=list)

    @property
    def masked(self) -> bool:
        return bool(self.masked_items)


def _add(items: dict, kind: str, hint: str) -> None:
    if kind in items:
        items[kind]["count"] += 1
    else:
        items[kind] = {"type": kind, "original_hint": hint, "count": 1}


def mask_text(text: str) -> MaskResult:
    """텍스트에서 개인식별정보를 치환한다.

    ★ 원본 문자열은 반환하지 않는다. 호출부는 반환된 text 만 저장해야 한다.

    >>> mask_text("연락처 010-1234-5678 계좌 123-456-789012").text
    '연락처 010-****-**** 계좌 ***-***-******'
    """
    if not text:
        return MaskResult(text="", masked_items=[])

    found: dict = {}
    out = text

    # 1) 주민등록번호 (가장 민감 → 최우선)
    def _rrn(m: re.Match) -> str:
        _add(found, "rrn", "******-*******")
        return "******-*******"

    out = RRN_RE.sub(_rrn, out)

    # 2) 카드번호
    def _card(m: re.Match) -> str:
        _add(found, "card", "****-****-****-****")
        return "****-****-****-****"

    out = CARD_RE.sub(_card, out)

    # 3) 전화번호 (계좌보다 먼저: 010-1234-5678 이 계좌 패턴에 먹히지 않도록)
    def _phone(m: re.Match) -> str:
        _add(found, "phone", f"{m.group(1)}-****-****")
        return f"{m.group(1)}-****-****"

    out = PHONE_RE.sub(_phone, out)

    # 4) 계좌번호 (하이픈 형)
    def _acct(m: re.Match) -> str:
        _add(found, "account", "***-***-******")
        return "***-***-******"

    out = ACCOUNT_RE.sub(_acct, out)

    # 5) 계좌번호 (문맥어 + 연속 숫자형)
    def _acct_ctx(m: re.Match) -> str:
        _add(found, "account", "***-***-******")
        return f"{m.group(1)} ***-***-******"

    out = ACCOUNT_CONTEXT_RE.sub(_acct_ctx, out)

    return MaskResult(text=out, masked_items=list(found.values()))


def mask_image_faces(image_bytes: bytes) -> Tuple[bytes, List[dict]]:
    """TODO(박진): 이미지 속 얼굴 비식별화.

    계획
      1) Google Vision faceDetection 으로 bounding box 획득
      2) Pillow/OpenCV 로 해당 영역 가우시안 블러 (모자이크보다 복원 난이도 높음)
      3) 블러된 바이트만 다음 단계로 넘기고, **원본 바이트는 즉시 메모리에서 해제**
    현재는 스켈레톤이므로 원본을 그대로 돌려주되, 호출부가 이미지를 저장하지 않도록
    설계되어 있어 (models/db.py 주석 참고) 실제 유출 경로는 없다.
    """
    # NOTE: 구현 전까지는 '얼굴 마스킹 미적용' 을 명시적으로 알린다.
    return image_bytes, [{"type": "face", "original_hint": "미구현(TODO)", "count": 0}]


def discard_original(image_bytes: bytes | None) -> None:
    """원본 이미지 파기 훅.

    곁눈은 원본 이미지를 디스크에 쓰지 않는다(메모리에서만 처리).
    S3/로컬 저장을 추가하는 순간 이 원칙이 깨지므로, 저장이 필요해지면
    반드시 팀 논의 후 이 함수에 삭제 로직을 함께 넣을 것.
    """
    del image_bytes  # 참조 해제 (GC 대상화)
