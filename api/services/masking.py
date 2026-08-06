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
# 한국 휴대폰/일반전화:
# - 기존 휴대폰·지역번호와 070
# - 숫자만, 일반 공백, 하이픈, 점, 앞자리 괄호, 하이픈 주변 공백
# - 슬래시와 그룹 사이 줄바꿈은 제외
PHONE_PREFIX_PATTERN = r"(?:01[016789]|070|0[2-6][0-5]?)"
PHONE_RE = re.compile(
    r"(?<![0-9A-Za-z_])"
    r"(?:\((?P<paren_prefix>" + PHONE_PREFIX_PATTERN + r")\)|"
    r"(?P<plain_prefix>" + PHONE_PREFIX_PATTERN + r"))"
    r"[ \t]*[-.]?[ \t]*(\d{3,4})"
    r"[ \t]*[-.]?[ \t]*(\d{4})"
    r"(?![0-9A-Za-z_])"
)
PHONE_POSITIVE_CONTEXT_RE = re.compile(
    r"연\s*락(?:\s*처)?|전\s*화(?:\s*번\s*호)?|문의|휴대\s*전화|"
    r"보낸\s*사람\s*번호|상담\s*받을\s*번호",
    re.IGNORECASE,
)
PHONE_NEGATIVE_CONTEXT_RE = re.compile(
    r"버전|모델(?:\s*번호)?|제품|빌드|문서|페이지|우편\s*번호|코드",
    re.IGNORECASE,
)
PHONE_CONTEXT_WINDOW = 20

# 주민등록번호:
# 표준 하이픈, 구분자 없음, 일반 공백, 하이픈 주변 공백, 점, 슬래시,
# 그룹 사이 한 번의 줄바꿈을 지원한다.
RRN_RE = re.compile(
    r"(?<![0-9A-Za-z_-])"
    r"(\d{6})[ \t]*[-./\r\n]?[ \t]*([1-4]\d{6})"
    r"(?![0-9A-Za-z_])"
)

# 카드번호:
# 15자리(4-6-5), 16자리(4-4-4-4), 19자리(4-4-4-4-3), 구분자 없는
# 15·16·19자리를 지원한다. 구분자는 일반 공백 또는 하이픈만 허용하며
# 한 번호 안에서는 같은 구분자만 사용한다. 점·슬래시·줄바꿈은 제외한다.
CARD_RE = re.compile(
    r"(?<![0-9A-Za-z_-])(?:"
    r"\d{4}(?P<sep19>[ -])\d{4}(?P=sep19)\d{4}(?P=sep19)\d{4}(?P=sep19)\d{3}"
    r"|\d{4}(?P<sep16>[ -])\d{4}(?P=sep16)\d{4}(?P=sep16)\d{4}"
    r"|\d{4}(?P<sep15>[ -])\d{6}(?P=sep15)\d{5}"
    r"|\d{19}|\d{16}|\d{15}"
    r")(?![0-9A-Za-z_-])"
)
CARD_POSITIVE_CONTEXT_RE = re.compile(
    r"카\s*드(?:\s*번\s*호)?|결제(?:\s*카드|\s*수단)?|CARD(?:\s*NO\.?)?",
    re.IGNORECASE,
)
CARD_NEGATIVE_CONTEXT_RE = re.compile(
    r"계좌(?:\s*번호)?|입금|송금|예금주|은행|account|"
    r"택배|제품(?:\s*키)?|문서(?:\s*번호)?|체크섬|쿠폰|빌드|표\s*번호",
    re.IGNORECASE,
)
CARD_CONTEXT_WINDOW = 24

# 계좌 후보는 처리 순서상 주민번호·카드·전화번호를 제거한 뒤 검사한다.
# 연속형 10~16자리 또는 2~4개 숫자 그룹을 수집하고, 실제 마스킹은 아래의
# 단순 문맥 존재 검사에서 결정한다.
ACCOUNT_RE = re.compile(
    r"(?<![0-9A-Za-z])(?:"
    r"\d{10,16}"
    r"|"
    r"\d{2,6}(?:[ \t./\-\r\n]+\d{2,8}){1,3}"
    r")(?![0-9A-Za-z])"
)

# 기존 상수 이름과 두 캡처 그룹 계약은 외부 호환성을 위해 보존한다.
ACCOUNT_CONTEXT_RE = re.compile(
    r"(계좌|입금|송금|account)\s*[:：]?\s*(\d{10,16})(?!\d)",
    re.IGNORECASE,
)
ACCOUNT_KEYWORD_RE = re.compile(
    r"계좌(?:\s*번호)?|입금|송금|예금주|은행|account",
    re.IGNORECASE,
)
ACCOUNT_MIN_DIGITS = 10
ACCOUNT_MAX_DIGITS = 16
ACCOUNT_CONTEXT_WINDOW = 24
RRN_LIKE_ACCOUNT_RE = re.compile(r"^\d{6}\s*-\s*[1-4]\d{6}$")


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


def _has_context(
    pattern: re.Pattern,
    source: str,
    start: int,
    end: int,
    window: int,
) -> bool:
    """후보 주변에 문맥어가 존재하는지만 확인한다. 거리는 계산하지 않는다."""
    left = max(0, start - window)
    right = min(len(source), end + window)
    return bool(pattern.search(source[left:right]))


def _luhn_valid(digits: str) -> bool:
    """카드 후보의 체크섬을 보조 신호로 검사한다."""
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _mask_card_candidates(text: str, found: dict) -> str:
    source = text

    def replace(match: re.Match) -> str:
        raw = match.group(0)
        digits = "".join(char for char in raw if char.isdigit())
        has_positive = _has_context(
            CARD_POSITIVE_CONTEXT_RE,
            source,
            match.start(),
            match.end(),
            CARD_CONTEXT_WINDOW,
        )
        has_negative = _has_context(
            CARD_NEGATIVE_CONTEXT_RE,
            source,
            match.start(),
            match.end(),
            CARD_CONTEXT_WINDOW,
        )

        # 거리를 쓰지 않는 정책: 카드 문맥이 있으면 개인정보 보호를 우선하고,
        # 카드 문맥 없이 부정 문맥만 있으면 일반 식별자로 남긴다.
        if has_positive:
            _add(found, "card", "****-****-****-****")
            return "****-****-****-****"
        if has_negative:
            return raw

        # 문맥이 없으면 표준 그룹 모양 또는 Luhn 통과를 보조 근거로 쓴다.
        if " " in raw or "-" in raw or _luhn_valid(digits):
            _add(found, "card", "****-****-****-****")
            return "****-****-****-****"
        return raw

    return CARD_RE.sub(replace, source)


def _mask_phone_candidates(text: str, found: dict) -> str:
    source = text

    def replace(match: re.Match) -> str:
        has_positive = _has_context(
            PHONE_POSITIVE_CONTEXT_RE,
            source,
            match.start(),
            match.end(),
            PHONE_CONTEXT_WINDOW,
        )
        has_negative = _has_context(
            PHONE_NEGATIVE_CONTEXT_RE,
            source,
            match.start(),
            match.end(),
            PHONE_CONTEXT_WINDOW,
        )

        # 거리를 쓰지 않는 정책: 전화 문맥이 있으면 마스킹하고, 전화 문맥 없이
        # 부정 문맥만 있으면 일반 번호로 남긴다.
        if not has_positive and has_negative:
            return match.group(0)

        prefix = match.group("paren_prefix") or match.group("plain_prefix")
        _add(found, "phone", f"{prefix}-****-****")
        return f"{prefix}-****-****"

    return PHONE_RE.sub(replace, source)


def _mask_account_candidates(text: str, found: dict) -> str:
    source = text

    def replace(match: re.Match) -> str:
        raw = match.group(0)
        digit_count = sum(char.isdigit() for char in raw)
        if not (ACCOUNT_MIN_DIGITS <= digit_count <= ACCOUNT_MAX_DIGITS):
            return raw
        if RRN_LIKE_ACCOUNT_RE.fullmatch(raw):
            return raw
        if not _has_context(
            ACCOUNT_KEYWORD_RE,
            source,
            match.start(),
            match.end(),
            ACCOUNT_CONTEXT_WINDOW,
        ):
            return raw

        _add(found, "account", "***-***-******")
        return "***-***-******"

    return ACCOUNT_RE.sub(replace, source)


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
    out = _mask_card_candidates(out, found)

    # 3) 전화번호 (계좌보다 먼저: 010-1234-5678 이 계좌 패턴에 먹히지 않도록)
    out = _mask_phone_candidates(out, found)

    # 4) 계좌번호
    out = _mask_account_candidates(out, found)

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
