"""문자 속 주소가 최종적으로 어디로 가는지 펼친다 (2026-08-15).

설계·근거: docs/evaluation/URL펼치기_설계_2026-08-15.md
실측 근거: docs/reports/2026-08-15_URL안전_조사.md

■ 무엇을 하는가 / 하지 않는가
  하는 것    : 단축·추적 주소를 펼쳐 **최종 도메인**을 사실로 알려 준다.
  하지 않는 것: 안전/위험 판정, 차단, 사칭 탐지. tier 를 올리지 않는다.

  실측: 확대 112건의 단축·추적 URL 6건이 **전부 정상 문자**였고, 사칭 2건은
  단축을 쓰지 않았다. 이 기능으로 잡히는 사칭은 0건이다. 사칭 검출률이
  오르는 것처럼 말하면 안 된다. **사용자에게 재료를 하나 더 주는 기능이다.**

■ ★ 요청 흐름 안에 두는 것으로 확정 (2026-08-16, #33)
  한때 "느린 대상 하나가 동시 접속자 전원을 최대 3초 잡는다"는 이유로 흐름에서 뺄지
  검토했다. **빼지 않는다.** 근거 두 가지다.
    1) #33 2단계에서 collect_evidence 가 이벤트 루프 밖(스레드풀)으로 나갔다.
       이 HEAD 도 함께 나갔으므로, 느려도 **자기 요청만** 기다린다.
       (그 전 실측: 주소 있는 본문은 동시 5명 간격이 0.19초 → 0.34초로 벌어졌다.
        지금은 그 전파 경로가 없다.)
    2) TIMEOUT_SEC = 3.0 상한이 이미 있다. 무한정 잡히지 않는다.
  ★ 다시 검토해야 하는 조건: 스레드풀이 이 대기로 포화되는 게 실측될 때.
    그때는 '뺀다'가 아니라 '전용 풀로 격리한다'가 먼저다.

■ ★ 절대 규칙
  1) HEAD 만 보낸다. 본문을 받지 않는다 - 악성 페이지 내용을 서버로 끌어오지 않는다.
  2) HEAD 를 거부(403/405/501)해도 **GET 으로 승격하지 않는다.**
     실측에서 광주시는 403, KT 는 405 를 주는데 필요한 Location 은 1홉에서 이미
     나왔다. 최종 200 을 받을 필요가 없다.
  3) 리다이렉트를 자동 추종하지 않는다. **홉마다 우리가 직접 검증한다.**
  4) 사설·링크로컬 IP 로 가면 그 홉에서 중단한다(SSRF 방지).
  5) 실패하면 **아무 말도 하지 않는다**(EX-007, user_message 빈 문자열).
     "확인하지 못했습니다"는 어르신이 "수상하다"로 읽는다.

■ ★ DNS 리바인딩 대응 - 이 파일에서 가장 중요한 부분
  순진한 구현은 TOCTOU 로 깨진다.
      1) 호스트명 해석 -> 1.2.3.4 (공인 IP, 통과)
      2) 검증 통과 후 호스트명으로 다시 접속 -> 이번엔 DNS 가 127.0.0.1 을 준다
  검증한 IP 와 접속한 IP 가 다르다. 그래서 **해석한 그 IP 로 직접 소켓을 연다.**
  Host 헤더와 TLS SNI 는 원래 호스트명을 유지한다(안 그러면 인증서 검증이 깨지고
  가상호스트가 응답하지 않는다).
  ★ requests/httpx 의 기본 동작은 이걸 제공하지 않는다. 그래서 표준 라이브러리로
    직접 짰다. 라이브러리에 맡기면 위 보장이 조용히 깨진다.
"""
from __future__ import annotations

import http.client
import ipaddress
import logging
import re
import socket
import ssl
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

log = logging.getLogger("gyeotnun.url_expand")

# ── 설계값 (docs/evaluation/URL펼치기_설계_2026-08-15.md §2-1)
TIMEOUT_SEC = 3.0          # 임베딩 타임아웃과 같은 값
MAX_HOPS = 3               # 실측에서 6건 전부 1회로 끝났다. 여유 있는 상한
ALLOWED_PORTS = (80, 443)
_UA = "gyeotnun/1.0 (+https://gyeotnun.duckdns.org)"

# ★ 되돌리기 스위치. False 면 신호를 아예 내보내지 않는다(2026-08-15 이전 동작).
URL_EXPAND_ENABLED = True

# 공공기관 도메인 접미사. ★ 등록 자격이 정부·공공기관으로 제한돼 있어서
#   "공공기관 주소다"가 판정이 아니라 등록 제도에서 나오는 사실이 된다.
#   누구나 살 수 있는 .com 과 다르다 - 사칭 S03(gov24-refund-event.com),
#   S08(nhis-refund24.com)이 전부 .com 인 것이 실측으로 확인됐다.
PUBLIC_SUFFIXES = (".go.kr", ".or.kr")

_BLOCKED_NETS = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8", "10.0.0.0/8", "127.0.0.0/8",
        "169.254.0.0/16",          # ★ 클라우드 메타데이터
        "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
        "192.0.0.0/24", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10",
    )
]

# 본문에서 http(s) 주소만 뽑는다. 스킴 없는 문자열은 대상이 아니다
# (마스킹된 계좌·전화번호가 주소로 오인되는 것을 막는다).
_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]{}]+")
_TRAILING = ".,;:!?)]}’”"


@dataclass
class ExpandResult:
    start_url: str
    final_url: Optional[str]        # 펼치기 성공 시 최종 URL, 실패면 None
    final_host: Optional[str]
    hops: int
    failure: Optional[str] = None   # 실패 사유(내부 로그용, 화면에 안 나간다)
    blocked_private: bool = False   # ★ 사설 IP 차단으로 멈췄나 (내부망 탐색 시도 흔적)

    @property
    def redirected(self) -> bool:
        """시작과 최종이 실제로 다른가. 같으면 보여 줄 게 없다."""
        if not self.final_host:
            return False
        return _host_of(self.start_url) != self.final_host

    @property
    def is_public_domain(self) -> bool:
        h = self.final_host or ""
        return any(h == s.lstrip(".") or h.endswith(s) for s in PUBLIC_SUFFIXES)


def _host_of(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h


def _is_blocked_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return True   # 해석 불가는 막는다
    if isinstance(a, ipaddress.IPv6Address) and a.ipv4_mapped:
        # ★ ::ffff:127.0.0.1 형태. 이걸 빠뜨리는 구현이 흔하다.
        return _is_blocked_ip(str(a.ipv4_mapped))
    if a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_reserved:
        return True
    return any(a in n for n in _BLOCKED_NETS)


def extract_urls(text: str) -> list[str]:
    """본문에서 http(s) 주소를 뽑는다. 중복은 순서를 지키며 한 번만."""
    out: list[str] = []
    for m in _URL_RE.findall(text or ""):
        u = m.rstrip(_TRAILING)
        if u and u not in out:
            out.append(u)
    return out


def _head_once(url: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """한 홉만 HEAD 로 두드린다. 반환 (status, location, 차단사유).

    ★ 해석한 IP 로 직접 접속하고 Host/SNI 는 원래 호스트명을 유지한다.
    """
    p = urlsplit(url)
    if p.scheme not in ("http", "https"):
        return None, None, f"scheme:{p.scheme}"
    if p.username or p.password:
        return None, None, "credentials_in_url"
    host = p.hostname
    if not host:
        return None, None, "no_host"
    port = p.port or (443 if p.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        return None, None, f"port:{port}"

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return None, None, f"dns:{e.errno}"
    ips = sorted({i[4][0] for i in infos})
    if not ips:
        return None, None, "dns:empty"
    # ★ 하나라도 걸리면 중단한다. 일부만 검사하면 라운드로빈으로 우회된다.
    if any(_is_blocked_ip(ip) for ip in ips):
        return None, None, "private_ip"

    ip = ips[0]
    sock = None
    try:
        sock = socket.create_connection((ip, port), timeout=TIMEOUT_SEC)
        if p.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)   # ★ SNI = 원래 호스트명
            conn = http.client.HTTPSConnection(host, port, timeout=TIMEOUT_SEC)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SEC)
        conn.sock = sock
        path = p.path or "/"
        if p.query:
            path += "?" + p.query
        # 쿠키·리퍼러는 보내지 않는다.
        conn.request("HEAD", path, headers={"Host": host, "User-Agent": _UA, "Accept": "*/*"})
        r = conn.getresponse()
        status, loc = r.status, r.getheader("Location")
        conn.close()
        return status, loc, None
    except Exception as e:  # noqa: BLE001 - 어떤 네트워크 오류든 조용히 실패한다
        try:
            if sock is not None:
                sock.close()
        except Exception:  # noqa: BLE001
            pass
        return None, None, f"{type(e).__name__}"


def expand(url: str) -> ExpandResult:
    """주소를 최대 MAX_HOPS 번 펼친다. 실패하면 failure 를 채운다."""
    cur = url
    for hop in range(1, MAX_HOPS + 1):
        status, loc, blocked = _head_once(cur)
        if blocked:
            return ExpandResult(url, None, None, hop, failure=blocked,
                                blocked_private=(blocked == "private_ip"))
        if status in (301, 302, 303, 307, 308) and loc:
            cur = urljoin(cur, loc)
            continue
        # ★ 200 이든 403 이든 405 든 여기서 끝이다. 리다이렉트가 아니면 최종이다.
        #   GET 으로 승격하지 않는다 - 본문을 받는 행위이기 때문이다.
        return ExpandResult(url, cur, _host_of(cur), hop)
    return ExpandResult(url, None, None, MAX_HOPS, failure="max_hops")


def expand_first_url(text: str) -> Optional[ExpandResult]:
    """본문의 첫 주소 하나만 펼친다. 주소가 없으면 None.

    ★ 하나만 보는 이유: 화면에 한 줄만 나가고(두 줄이면 어르신에게 과하다),
      요청 1건당 외부 접속을 최소로 유지하기 위해서다.
    """
    urls = extract_urls(text)
    if not urls:
        return None
    return expand(urls[0])


def build_signal(result: ExpandResult) -> Optional[dict]:
    """펼치기 결과를 화면 신호로 만든다. 보여 줄 게 없으면 None.

    ★★ severity 는 반드시 "info" 다. tier 를 올리지 않는다. ★★
      verdict.js 의 ATTENTION_KEYS 는 허용 목록이라 이 키가 거기 없는 한
      attention 으로 잘못 내보내도 tier 는 움직이지 않지만(2026-08-15 실측),
      의도를 코드에도 남긴다.

    ★ 침묵 규칙 (설계 §1-②)
      - 펼쳐지지 않았으면(시작 == 최종) 아무 말도 하지 않는다. 보여 줄 사실이 없다.
      - .go.kr/.or.kr 이 아니라고 해서 아무 말도 하지 않는다.
        실측에서 kt.com·coupang.com·play.google.com 이 전부 정상 문자였다.
        "공공기관 주소가 아닙니다"는 그 셋을 의심으로 만든다.
    """
    if not URL_EXPAND_ENABLED or not result.redirected:
        return None
    return {
        "key": "url_expanded",
        "label": f"받으신 주소는 최종적으로 {result.final_host} 로 연결됩니다.",
        "severity": "info",
        "detail": result.final_host,
        "public_domain": result.is_public_domain,
    }
