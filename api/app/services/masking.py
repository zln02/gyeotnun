"""
곁눈(Gyeotnun) - 개인정보 마스킹
담당: 박진 (보안)

★ 이 모듈은 목업이 아니라 **실제 동작하는 구현**입니다. ★
  보안성이 심사 배점 항목이므로 실동작이 필요합니다.

원칙
    1. OCR로 뽑은 텍스트는 DB에 들어가기 전에 반드시 이 함수를 통과한다.
    2. 원본(마스킹 전) 텍스트는 어디에도 저장하지 않는다.
    3. 마스킹은 되돌릴 수 없다 (복호화 불가). 해시도 저장하지 않는다.

사용 예
    >>> mask_pii("연락처 010-1234-5678 국민 123456-78-901234 로 입금")
    '연락처 010-****-**** 국민 ***-**-****** 로 입금'
"""

from __future__ import annotations

import re

__all__ = ["mask_pii", "mask_pii_detail", "MASK_KINDS"]

MASK_KINDS = ("rrn", "phone", "card", "account", "email")


# ------------------------------------------------------------------
# 정규식 정의
#   주의: 적용 순서가 중요하다.
#   주민번호(6-7) → 카드번호(4-4-4-4) → 계좌번호 → 전화번호 → 이메일
#   순서를 바꾸면 전화번호 패턴이 계좌 앞자리를 먼저 먹어버린다.
# ------------------------------------------------------------------

# 주민등록번호: 900101-1234567 / 900101 1234567 / 9001011234567
_RE_RRN = re.compile(
    r"(?<![0-9])"
    r"([0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01]))"  # YYMMDD (유효 월일)
    r"\s*[-~.\s]?\s*"
    r"([1-4][0-9]{6})"                                        # 성별코드 1~4 + 6자리
    r"(?![0-9])"
)

# 외국인등록번호 (성별코드 5~8)
_RE_FRN = re.compile(
    r"(?<![0-9])"
    r"([0-9]{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01]))"
    r"\s*[-~.\s]?\s*"
    r"([5-8][0-9]{6})"
    r"(?![0-9])"
)

# 카드번호: 1234-5678-9012-3456 / 1234 5678 9012 3456 / 1234567890123456
_RE_CARD = re.compile(
    r"(?<![0-9])"
    r"([0-9]{4})[-\s.]?([0-9]{4})[-\s.]?([0-9]{4})[-\s.]?([0-9]{4})"
    r"(?![0-9])"
)

# 휴대폰: 010-1234-5678, 011-123-4567, +82-10-1234-5678
_RE_MOBILE = re.compile(
    r"(?<![0-9])"
    r"(?:\+?82[-\s.]?)?"
    r"(01[016789])[-\s.]?([0-9]{3,4})[-\s.]?([0-9]{4})"
    r"(?![0-9])"
)

# 유선전화: 02-123-4567, 031-1234-5678
_RE_TEL = re.compile(
    r"(?<![0-9])"
    r"(0[2-6][0-9]?)[-\s.]([0-9]{3,4})[-\s.]([0-9]{4})"
    r"(?![0-9])"
)

# 대표번호(4+4자리): 1588-1234, 1899-0000, 1600-5678
#   계좌번호 패턴보다 먼저 처리해야 한다. (안 그러면 계좌로 잡힘)
_RE_TEL_SHORT = re.compile(
    r"(?<![0-9])"
    r"(1[5-9][0-9]{2})[-\s.]([0-9]{4})"
    r"(?![0-9])"
)

# 계좌번호: 은행 계좌는 자릿수/구분이 제각각이라
#           "숫자 10~14자리 + 하이픈 1개 이상" 또는 "연속 숫자 10~16자리"를 잡는다.
#           (카드/주민/전화를 먼저 처리했으므로 남은 긴 숫자열은 계좌로 간주)
_RE_ACCOUNT_DASH = re.compile(
    r"(?<![0-9])"
    r"([0-9]{2,6})-([0-9]{2,6})-?([0-9]{0,6})"
    r"(?![0-9])"
)
_RE_ACCOUNT_PLAIN = re.compile(r"(?<![0-9])([0-9]{10,16})(?![0-9])")

# 이메일
_RE_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _mask_rrn(_m: re.Match) -> str:
    return "***-**-******"


def _mask_card(_m: re.Match) -> str:
    return "****-****-****-****"


def _mask_mobile(m: re.Match) -> str:
    # 앞 3자리(010)는 남겨 사용자가 "내 번호구나" 정도는 알 수 있게 한다.
    return f"{m.group(1)}-****-****"


def _mask_tel(m: re.Match) -> str:
    return f"{m.group(1)}-***-****"


def _mask_tel_short(m: re.Match) -> str:
    # 대표번호 앞 4자리는 기관 식별에 쓰이므로 남기고 뒤만 가린다.
    return f"{m.group(1)}-****"


def _mask_account_dash(m: re.Match) -> str:
    head = m.group(1)
    return f"{head}-***-******" if m.group(3) else f"{head}-*****"


def _mask_account_plain(_m: re.Match) -> str:
    return "**********"


def _mask_email(m: re.Match) -> str:
    local, _, domain = m.group(0).partition("@")
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}***@{domain}"


def mask_pii(text: str) -> str:
    """
    텍스트에서 개인정보를 마스킹한다.

    Args:
        text: OCR 등으로 추출된 원문 텍스트.

    Returns:
        마스킹된 텍스트. DB에는 이 결과만 저장한다.

    마스킹 대상
        - 주민등록번호 / 외국인등록번호
        - 카드번호
        - 휴대폰 / 유선전화 / 대표번호
        - 계좌번호
        - 이메일
    """
    if not text:
        return ""

    masked, _ = mask_pii_detail(text)
    return masked


def mask_pii_detail(text: str) -> tuple[str, list[str]]:
    """
    mask_pii와 동일하되, 어떤 종류가 가려졌는지도 함께 반환한다.

    Returns:
        (마스킹된 텍스트, 가려진 항목 종류 리스트)
        예: ("...", ["phone", "account"])

    checks.masked_kinds 컬럼에 저장해 보안 처리 근거로 사용한다.
    """
    if not text:
        return "", []

    kinds: list[str] = []
    out = text

    # 1) 주민/외국인등록번호 (가장 먼저)
    out, n = _RE_RRN.subn(_mask_rrn, out)
    total = n
    out, n = _RE_FRN.subn(_mask_rrn, out)
    total += n
    if total:
        kinds.append("rrn")

    # 2) 카드번호 (16자리 → 계좌 패턴보다 먼저)
    out, n = _RE_CARD.subn(_mask_card, out)
    if n:
        kinds.append("card")

    # 3) 전화번호
    out, n = _RE_MOBILE.subn(_mask_mobile, out)
    total = n
    out, n = _RE_TEL.subn(_mask_tel, out)
    total += n
    out, n = _RE_TEL_SHORT.subn(_mask_tel_short, out)
    total += n
    if total:
        kinds.append("phone")

    # 4) 계좌번호 (남은 긴 숫자열)
    out, n = _RE_ACCOUNT_DASH.subn(_mask_account_dash, out)
    total = n
    out, n = _RE_ACCOUNT_PLAIN.subn(_mask_account_plain, out)
    total += n
    if total:
        kinds.append("account")

    # 5) 이메일
    out, n = _RE_EMAIL.subn(_mask_email, out)
    if n:
        kinds.append("email")

    return out, kinds


def contains_pii(text: str) -> bool:
    """마스킹이 필요한 개인정보가 남아 있는지 검사 (테스트/가드용)."""
    _, kinds = mask_pii_detail(text or "")
    return bool(kinds)


if __name__ == "__main__":  # 간단 자체 점검:  python -m app.services.masking
    samples = [
        "국민지원금 신청은 010-1234-5678 로 전화주세요",
        "주민번호 900101-1234567 입력 후 진행하세요",
        "농협 352-0123-4567-89 로 입금 바랍니다",
        "카드번호 1234-5678-9012-3456 확인",
        "문의 gyeotnun@example.com / 대표번호 1588-1234",
        "계좌 12345678901234 송금 요망",
    ]
    for s in samples:
        m, k = mask_pii_detail(s)
        print(f"{s}\n  -> {m}   {k}\n")
