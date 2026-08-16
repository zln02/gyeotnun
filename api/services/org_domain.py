"""문자가 말하는 기관의 공식 주소와, 실제로 받은 주소를 나란히 놓는다 (2026-08-16).

표: corpus/기관_공식도메인_2026-08-15.csv (사람이 검수한다)
조사·측정 근거: docs/evaluation/기관도메인_매핑_조사_2026-08-15.md

■ 무엇을 하는가 / 하지 않는가
  하는 것    : "○○의 공식 주소는 △△입니다. 받으신 주소는 ◇◇입니다" 두 줄의 사실.
  하지 않는 것: 사칭 판정, 차단, 경고. **tier 를 올리지 않는다.**

  ★ 실측(2026-08-15): 확대 112건에서 걸리는 것은 2건(S03·S08)뿐이고 둘 다 사칭이다.
    사칭 37건 중 2건 = 5.4%. **이 규칙은 '사칭 탐지'가 아니라 유형 하나를 메우는
    것이다.** 검출률이 오르는 것처럼 말하면 안 된다.

■ ★ 발동 조건 (셋 다 만족할 때만)
  ① 본문에 표의 기관명(또는 별칭)이 있다
  ② 본문에 주소가 있다        ← ★ 이 조건이 정상 문자를 막는다
  ③ 등록가능 도메인이 표의 값과 다르고, 아래 침묵 규칙에 하나도 걸리지 않는다

  ★★ ②에서 url_expand.extract_urls 를 그대로 쓰면 안 된다 ★★
    그건 http(s):// 로 시작하는 것만 뽑는다(마스킹된 계좌·전화번호 오인 방지).
    그런데 노리는 두 건의 실제 원문에는 스킴이 없다:
        S03  "정부24 미수령 환급금 확인 gov24-refund-event.com"
        S08  "건강보험료 환급 신청 nhis-refund24.com"
    재사용했으면 **목표 2건이 전부 조용히 침묵했을 것이다.** 그래서 여기서는
    스킴 없는 도메인도 뽑되, 마지막 라벨이 _KNOWN_TLDS 에 있을 때만 인정한다
    (그래야 "3.5%"·"오전 9.30" 같은 숫자가 주소로 잡히지 않는다).

  ②가 왜 결정적인가: 표의 기관명이 언급된 확대평가셋 건은 22건인데 URL 이 함께
  있는 건은 2건뿐이다. **정상 3건(N01·N02 복지로, N11 국민연금공단)이 표의 기관을
  언급하지만 URL 이 없어 발동하지 않는다.** 이 조건을 빼면 그 3건이 곧바로 위험해진다.

■ ★ 침묵 규칙 - 하나라도 걸리면 아무 말도 하지 않는다
  (a) 받은 주소가 그 기관의 공식 도메인과 같다
  (b) 받은 주소가 **표 전체 35행 중 아무 기관의 공식 도메인**과 같다
      → 국세청(nts.go.kr) 문자에 홈택스(hometax.go.kr) 링크가 붙는 것은 정상이다.
        한 기관 = 한 도메인이 아니다. 이 규칙이 없으면 그게 전부 오탐이 된다.
      ★ 여기서는 `브라우저검수대기` 4행도 센다. **침묵 쪽은 넓게, 발동 쪽은
        좁게** 가 이 파일의 원칙이다. 검수가 덜 된 행이 침묵을 늘리는 것은
        안전한 방향이고, 발동을 늘리는 것은 위험한 방향이다.
  (c) 받은 주소가 .go.kr / .or.kr 이다 (url_expand.PUBLIC_SUFFIXES 와 같은 근거:
      등록 자격이 제한돼 있다). 표에 없는 공공기관 주소를 오탐하지 않기 위해서다.
      ★ 대가: .or.kr 유사 도메인을 쓰는 사칭은 이 규칙으로 못 잡는다. 알고 고른
        쪽이다 - 정상 문자를 의심으로 표시하지 않는 것이 먼저다.

■ ★ 펼친 주소와 원래 주소를 **둘 다** 후보로 본다
  하나라도 침묵 규칙에 걸리면 침묵한다. 이유가 양쪽에 하나씩 있다.
    - 펼친 것만 보면: 펼치기가 실패한 사칭(죽은 도메인)을 놓친다.
    - 원래 것만 보면: 단축주소를 쓴 진짜 기관 문자가 오탐이 된다.
  겹쳐 놓고 **침묵 쪽으로 판정**한다.
"""
from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from services import url_expand

log = logging.getLogger("gyeotnun.org_domain")

TABLE_PATH = Path(__file__).resolve().parents[2] / "corpus" / "기관_공식도메인_2026-08-15.csv"

# ★ 되돌리기 스위치. False 면 신호를 아예 내보내지 않는다(2026-08-16 이전 동작).
ORG_DOMAIN_ENABLED = True

# ★ 발동 자격. 이 접두사로 시작하는 검수상태만 대조에 쓴다.
#   `브라우저검수대기` 4행(복지로·과기정통부·방통위·대법원)은 제목으로 기관을 확인하지
#   못했다. 검수 후 검수상태를 `1차검수` 로 바꾸면 자동으로 켜진다 - 코드를 안 고친다.
_ACTIVE_PREFIX = "1차검수"

# 마지막 3라벨로 잘라야 하는 2단계 접미사. ★ 전체 Public Suffix List 가 아니다.
#   표에 실제로 쓰이는 .kr 계열만 손으로 적었다. 목록에 없으면 마지막 2라벨을
#   쓰는데, 그 경우 도메인이 더 넓게 잡혀 **비교가 더 잘 같아진다 = 더 침묵한다.**
#   빠뜨렸을 때 안전한 쪽으로 틀리도록 고른 기본값이다.
_TWO_LABEL_SUFFIXES = (
    "go.kr", "or.kr", "co.kr", "ne.kr", "re.kr", "pe.kr", "ac.kr",
    "es.kr", "ms.kr", "hs.kr", "sc.kr", "kg.kr", "mil.kr",
    "co.uk", "co.jp", "com.cn",
)

# 스킴 없는 도메인을 뽑기 위한 패턴 + 인정할 마지막 라벨.
#   ★ 목록에 없는 TLD 는 주소로 보지 않는다 = 침묵한다. 빠뜨렸을 때 안전한 쪽이다.
#     (사칭을 놓치는 쪽으로 틀리지, 정상 문자를 의심하는 쪽으로 틀리지 않는다.)
#     새 TLD 를 쓰는 사칭이 실측되면 여기에 더한다 - 근거 없이 미리 늘리지 않는다.
_DOMAIN_RE = re.compile(
    r"(?<![\w.-])"
    r"(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}"
    r"(?![\w-])"
)
_KNOWN_TLDS = frozenset((
    "kr", "com", "net", "org", "co", "io", "me", "cc", "info", "biz",
    "xyz", "top", "site", "online", "shop", "store", "link", "click",
    "live", "app", "page", "vip", "asia", "jp", "cn", "ru", "vn", "us", "uk",
))


@dataclass(frozen=True)
class Org:
    name: str
    aliases: tuple[str, ...]
    domain: str


def registrable_domain(host: str) -> str:
    """비교 단위를 맞춘다. www.nhis.or.kr 과 nhis.or.kr 은 같은 곳이다.

    ★ 정확한 호스트명으로 비교하면 안 된다 - 실측에서 nhis.or.kr·
      counterscam112.go.kr 은 apex 가 해석조차 안 되고 www 만 뜬다.
    """
    h = (host or "").lower().strip().rstrip(".")
    if not h:
        return ""
    parts = h.split(".")
    want = 3 if any(h.endswith("." + s) for s in _TWO_LABEL_SUFFIXES) else 2
    if len(parts) <= want:
        return h
    return ".".join(parts[-want:])


def _load_table() -> tuple[tuple[Org, ...], frozenset[str]]:
    """(발동 대상 기관들, 표 전체의 공식 도메인 집합) 을 돌려준다.

    ★ 두 번째 값이 침묵 규칙 (b) 다. 발동 대상보다 **넓다** - 검수가 덜 된 행도
      "여긴 진짜 기관 주소다"라는 근거로는 충분하기 때문이다.
    """
    if not TABLE_PATH.exists():
        log.warning("[org_domain] 매핑표가 없다(%s). 이 기능은 침묵한다.", TABLE_PATH.name)
        return (), frozenset()
    orgs: list[Org] = []
    known: set[str] = set()
    with TABLE_PATH.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            domain = (row.get("공식도메인") or "").strip().lower()
            if not domain:
                continue
            known.add(registrable_domain(domain))
            if not (row.get("검수상태") or "").strip().startswith(_ACTIVE_PREFIX):
                continue
            name = (row.get("기관명") or "").strip()
            if not name:
                continue
            aliases = tuple(
                a.strip() for a in (row.get("별칭") or "").split("|") if a.strip()
            )
            orgs.append(Org(name=name, aliases=aliases, domain=domain))
    return tuple(orgs), frozenset(known)


ORGS, KNOWN_DOMAINS = _load_table()
log.info(
    "[org_domain] 매핑표 적재 - 발동 대상 %s곳 / 알려진 공식 도메인 %s개 (출처: %s)",
    len(ORGS), len(KNOWN_DOMAINS), TABLE_PATH.name,
)


def find_org(text: str) -> Optional[tuple[Org, str]]:
    """본문에 언급된 기관을 찾는다. 반환 (기관, 실제로 걸린 이름).

    ★ 가장 긴 이름이 이긴다. "국민건강보험공단" 이 있는 글에서 별칭 "건강보험"
      때문에 엉뚱한 행이 잡히는 것을 막는다.
    """
    t = text or ""
    best: Optional[tuple[Org, str]] = None
    for org in ORGS:
        for cand in (org.name, *org.aliases):
            if cand and cand in t:
                if best is None or len(cand) > len(best[1]):
                    best = (org, cand)
    return best


def extract_domains(text: str) -> list[str]:
    """본문에서 도메인처럼 생긴 것을 뽑는다. 스킴(http://)이 없어도 뽑는다.

    ★ 마지막 라벨이 _KNOWN_TLDS 에 있을 때만 인정한다. 모르는 TLD 는 그냥
      **버린다 = 침묵한다.** 목록을 빠뜨렸을 때 안전한 쪽으로 틀리는 기본값이다
      (사칭을 놓치는 쪽이지, 정상을 의심하는 쪽이 아니다).
    ★ 한글 사이의 마침표는 잡히지 않는다 - 패턴이 ASCII 라벨만 본다.
    """
    out: list[str] = []
    # ① 스킴이 붙어 있으면 TLD 를 따지지 않는다. http(s):// 가 있으면 그건 주소다.
    #    ★ 이게 없으면 bit.ly 처럼 목록에 없는 TLD 를 쓴 단축주소가 통째로 빠진다.
    for u in url_expand.extract_urls(text):
        host = (urlsplit(u).hostname or "").lower()
        if host and host not in out:
            out.append(host)
    # ② 스킴이 없으면 마지막 라벨이 아는 TLD 일 때만 주소로 본다.
    for m in _DOMAIN_RE.finditer(text or ""):
        host = m.group(0).lower().rstrip(".")
        if host.split(".")[-1] not in _KNOWN_TLDS:
            continue
        if host not in out:
            out.append(host)
    return out


def _is_public_suffix(host: str) -> bool:
    h = (host or "").lower()
    return any(h == s.lstrip(".") or h.endswith(s) for s in url_expand.PUBLIC_SUFFIXES)


def build_signal(
    text: str,
    expanded: Optional[url_expand.ExpandResult] = None,
) -> Optional[dict]:
    """대조 결과를 화면 신호로 만든다. 보여 줄 게 없으면 None(= 침묵).

    ★★ severity 는 반드시 "info" 다. tier 를 올리지 않는다. ★★
      verdict.js 의 ATTENTION_KEYS 는 허용목록이라 이 키가 거기 없는 한 화면
      tier 는 움직이지 않지만(2026-08-15 실측), 의도를 코드에도 남긴다.
    """
    if not ORG_DOMAIN_ENABLED or not ORGS:
        return None

    hit = find_org(text)          # ① 기관명
    if hit is None:
        return None
    org, _matched = hit

    raw_hosts = extract_domains(text)   # ② 주소 (스킴 없어도 본다)
    final_host = expanded.final_host if expanded is not None else None
    if not raw_hosts and not final_host:
        return None

    # ③ 후보 주소들. 펼친 결과가 있으면 함께 본다(성공했을 때만 - 실패는 None 이다).
    candidates: list[str] = list(raw_hosts)
    if final_host and final_host not in candidates:
        candidates.append(final_host)

    official = registrable_domain(org.domain)
    for host in candidates:
        reg = registrable_domain(host)
        if not reg:
            return None                      # 이상한 주소 - 말하지 않는다
        if reg == official:                  # 침묵 (a)
            return None
        if reg in KNOWN_DOMAINS:             # 침묵 (b) - 표 안의 다른 기관 주소
            return None
        if _is_public_suffix(host):          # 침묵 (c) - .go.kr / .or.kr
            return None

    # 보여 줄 주소: 펼쳐졌으면 최종, 아니면 본문의 첫 주소. 사용자가 실제로 닿는 곳이다.
    shown = (final_host if (expanded is not None and expanded.redirected and final_host)
             else (raw_hosts[0] if raw_hosts else final_host))
    return {
        "key": "org_domain_mismatch",
        # ★ "가짜입니다"·"사칭입니다"·"위험합니다" 를 쓰지 않는다. 판정이 아니다.
        #   두 주소를 나란히 놓는 것 자체가 사실이고, 비교는 사용자가 한다.
        "label": f"{org.name}의 공식 주소는 {org.domain}입니다. 받으신 주소는 {shown}입니다.",
        "severity": "info",
        "detail": org.name,
        "official_domain": org.domain,
        "received_domain": shown,
    }
