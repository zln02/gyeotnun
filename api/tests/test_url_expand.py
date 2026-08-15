"""URL 펼치기 - 안전 규칙과 침묵 규칙 검증 (2026-08-15).

실행: cd api && python -m pytest tests/test_url_expand.py -q

■ 이 파일이 지키는 것
  이 기능은 **우리 서버가 바깥으로 요청을 보내는 유일한 경로**다(질문 생성 LLM
  호출 외에). 그래서 테스트가 지켜야 할 것은 "잘 펼치는가"보다
  **"위험한 곳으로 안 가는가"** 와 **"쓸데없는 말을 안 하는가"** 다.

  네트워크를 실제로 타지 않는다 - _head_once 를 모의해서 규칙만 검증한다.
  실제 펼치기는 2026-08-15 에 6건으로 1회 실측했고 결과는
  docs/reports/2026-08-15_URL안전_조사.md §3-3 에 있다.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import url_expand as ue  # noqa: E402


# ──────────────────────────────────────────── 주소 추출
def test_extract_urls_only_takes_http_schemes():
    """스킴 없는 문자열은 주소로 보지 않는다 - 마스킹된 계좌·전화번호 오인 방지."""
    t = "연락처 010-****-**** 계좌 ***-***-****** 안내 https://example.go.kr/a 확인"
    assert ue.extract_urls(t) == ["https://example.go.kr/a"]


def test_extract_urls_strips_trailing_punctuation():
    assert ue.extract_urls("자세히는 https://example.go.kr/a 를 보세요.") == ["https://example.go.kr/a"]
    assert ue.extract_urls("(https://example.go.kr/a)") == ["https://example.go.kr/a"]


def test_extract_urls_dedupes_keeping_order():
    t = "https://a.go.kr 과 https://b.go.kr 그리고 https://a.go.kr"
    assert ue.extract_urls(t) == ["https://a.go.kr", "https://b.go.kr"]


# ──────────────────────────────────────────── SSRF 차단
@pytest.mark.parametrize("ip", [
    "127.0.0.1",            # 루프백
    "10.0.0.5",             # 사설
    "192.168.1.1",          # 사설
    "172.16.0.1",           # 사설
    "169.254.169.254",      # ★ 클라우드 메타데이터
    "100.64.0.1",           # CGNAT
    "0.0.0.0",
    "::1",                  # IPv6 루프백
    "fe80::1",              # 링크로컬
    "fc00::1",              # 유니크 로컬
    "::ffff:127.0.0.1",     # ★ IPv4 매핑 - 빠뜨리기 쉬운 우회로
])
def test_blocked_ip_ranges(ip):
    assert ue._is_blocked_ip(ip) is True, f"{ip} 를 막지 못했다"


@pytest.mark.parametrize("ip", ["8.8.8.8", "117.52.137.139", "2001:4860:4860::8888"])
def test_public_ips_are_allowed(ip):
    assert ue._is_blocked_ip(ip) is False


def test_private_ip_stops_the_hop():
    """사설 IP 로 해석되면 접속하지 않고 그 홉에서 멈춘다."""
    with patch("services.url_expand.socket.getaddrinfo",
               return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]), \
         patch("services.url_expand.socket.create_connection") as conn:
        r = ue.expand("https://evil.example/a")
    assert r.final_url is None
    assert r.blocked_private is True
    assert r.failure == "private_ip"
    conn.assert_not_called()   # ★ 소켓을 아예 열지 않았다


def test_all_resolved_ips_are_checked_not_just_the_first():
    """★ 하나라도 사설이면 막는다 - 일부만 검사하면 라운드로빈으로 우회된다."""
    with patch("services.url_expand.socket.getaddrinfo", return_value=[
        (2, 1, 6, "", ("8.8.8.8", 443)),        # 공인
        (2, 1, 6, "", ("127.0.0.1", 443)),      # 사설이 섞여 있다
    ]), patch("services.url_expand.socket.create_connection") as conn:
        r = ue.expand("https://rebind.example/a")
    assert r.failure == "private_ip"
    conn.assert_not_called()


@pytest.mark.parametrize("url,reason", [
    ("file:///etc/passwd", "scheme:file"),
    ("gopher://x/1", "scheme:gopher"),
    ("https://user:pw@example.go.kr/", "credentials_in_url"),
    ("https://example.go.kr:8080/", "port:8080"),
    ("https://example.go.kr:22/", "port:22"),
])
def test_rejected_before_any_network_call(url, reason):
    """스킴·인증정보·포트는 DNS 조회 전에 걸러낸다."""
    with patch("services.url_expand.socket.getaddrinfo") as gai:
        status, loc, blocked = ue._head_once(url)
    assert blocked == reason
    gai.assert_not_called()


# ──────────────────────────────────────────── 펼치기 동작
def test_redirect_chain_is_followed_hop_by_hop():
    seq = [(308, "https://youth.gwangju.go.kr/www/50", None), (403, None, None)]
    with patch("services.url_expand._head_once", side_effect=seq) as h:
        r = ue.expand("https://m.site.naver.com/2dNkw")
    assert r.final_host == "youth.gwangju.go.kr"
    assert r.hops == 2
    assert h.call_count == 2


def test_head_rejection_is_a_success_not_a_failure():
    """★ 403/405 여도 실패가 아니다 - 필요한 Location 은 1홉에서 이미 나왔다.

    실측: 광주시 서버는 HEAD 를 403, KT 는 405 로 막는다(2026-08-15).
    그래서 GET 으로 승격할 이유가 없다.
    """
    with patch("services.url_expand._head_once",
               side_effect=[(301, "https://kt.com/q7qd", None), (405, None, None)]):
        r = ue.expand("https://su.kt.co.kr/Al4dv64")
    assert r.final_host == "kt.com"
    assert r.failure is None


def test_hop_limit_is_enforced():
    with patch("services.url_expand._head_once",
               return_value=(302, "https://loop.example/next", None)) as h:
        r = ue.expand("https://loop.example/start")
    assert r.final_url is None
    assert r.failure == "max_hops"
    assert h.call_count == ue.MAX_HOPS


# ──────────────────────────────────────────── 침묵 규칙 (설계 §1-②)
def test_no_signal_when_not_redirected():
    """펼쳐지지 않았으면(시작 == 최종) 보여 줄 사실이 없다."""
    with patch("services.url_expand._head_once", return_value=(200, None, None)):
        r = ue.expand("https://gov24-refund-event.com/")
    assert r.redirected is False
    assert ue.build_signal(r) is None


def test_no_signal_when_expansion_failed():
    """실패하면 침묵한다 - '확인하지 못했습니다'는 어르신이 '수상하다'로 읽는다."""
    with patch("services.url_expand._head_once", return_value=(None, None, "TimeoutError")):
        r = ue.expand("https://slow.example/a")
    assert ue.build_signal(r) is None


def test_public_domain_note_only_for_go_kr_and_or_kr():
    with patch("services.url_expand._head_once",
               side_effect=[(308, "https://youth.gwangju.go.kr/x", None), (200, None, None)]):
        sig = ue.build_signal(ue.expand("https://m.site.naver.com/2dNkw"))
    assert sig["public_domain"] is True
    assert sig["detail"] == "youth.gwangju.go.kr"


@pytest.mark.parametrize("dest", [
    "https://kt.com/q7qd",                      # 정상 (KT)
    "https://cls-coujob.coupang.com/",          # 정상 (쿠팡)
    "https://play.google.com/store/apps/x",     # 정상 (KB Pay 앱 설치)
])
def test_non_public_domains_get_no_note(dest):
    """★ 이 셋은 전부 정상 문자다. '공공 주소가 아닙니다'를 띄우면 정상을 의심으로 만든다."""
    with patch("services.url_expand._head_once", side_effect=[(301, dest, None), (200, None, None)]):
        sig = ue.build_signal(ue.expand("https://short.example/a"))
    assert sig is not None, "펼친 사실 자체는 알려 준다"
    assert sig["public_domain"] is False, "그러나 공공기관 여부는 말하지 않는다"


# ──────────────────────────────────────────── tier 보호
def test_signal_severity_is_always_info():
    """★★ tier 를 올리지 않는다. 이 단정이 깨지면 정상 문자 6건이 경고로 간다. ★★"""
    with patch("services.url_expand._head_once",
               side_effect=[(301, "https://kt.com/x", None), (200, None, None)]):
        sig = ue.build_signal(ue.expand("https://su.kt.co.kr/a"))
    assert sig["severity"] == "info"
    assert sig["key"] == "url_expanded"


def test_key_is_not_in_frontend_attention_allowlist():
    """프론트 허용 목록(verdict.js ATTENTION_KEYS)에 이 키가 없어야 한다.

    ★ 서버 severity 가 실수로 attention 이 돼도 이 목록에 없으면 tier 가 안 움직인다.
      허용 목록이 두 번째 방어선이다(2026-08-15 실측으로 확인).

    ★★ 이 테스트는 api 컨테이너에서 **스킵된다**(web/ 이 마운트되지 않는다).
      스킵은 초록불처럼 보이므로 여기 명시해 둔다. 실질 방어는 두 겹이다:
        1) 위 test_signal_severity_is_always_info — 컨테이너에서 항상 돈다
        2) tools/render_verdict.mjs 전수 대조 — 배포 전 사람이 돌린다
           (2026-08-15 실측: attention 으로 잘못 넣어도 142건 tier 변화 0)
    """
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "web/src/verdict.js"
    if not p.exists():
        # api 컨테이너에는 web/ 이 마운트되지 않는다. 호스트에서 돌릴 때만 검사한다.
        pytest.skip("web/src/verdict.js 가 이 환경에 없다 - 스킵")
    block = p.read_text(encoding="utf-8").split("const ATTENTION_KEYS = [", 1)[1].split("]", 1)[0]
    assert "url_expanded" not in block, "url_expanded 가 ATTENTION_KEYS 에 들어가면 안 된다"


# ──────────────────────────────────────────── 스위치
def test_switch_off_yields_no_signal():
    with patch("services.url_expand._head_once",
               side_effect=[(301, "https://kt.com/x", None), (200, None, None)]):
        r = ue.expand("https://su.kt.co.kr/a")
    with patch("services.url_expand.URL_EXPAND_ENABLED", False):
        assert ue.build_signal(r) is None
