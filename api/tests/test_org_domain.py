"""기관 도메인 대조 - 발동 조건과 침묵 규칙 검증 (2026-08-16).

실행: cd api && python -m pytest tests/test_org_domain.py -q

■ 이 파일이 지키는 것
  이 기능은 화면에 **다른 기관 이름과 주소 두 개**를 띄운다. 잘못 뜨면 정상 문자가
  곧바로 의심을 받는다. 그래서 테스트의 무게중심은 "잘 잡는가"가 아니라
  **"쓸데없이 뜨지 않는가"** 에 있다 - 침묵 테스트가 발동 테스트보다 많다.

  네트워크를 타지 않는다. 표(corpus/기관_공식도메인_2026-08-15.csv)는 실제 파일을
  읽는다 - 표가 깨지면 여기서 먼저 터지는 게 맞다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import org_domain as od  # noqa: E402
from services.url_expand import ExpandResult  # noqa: E402


# ──────────────────────────────────────────── 표
def test_table_loads_and_active_rows_are_a_strict_subset():
    """발동 대상은 표 전체보다 **좁다**. 침묵 판정용 집합은 표 전체다."""
    assert len(od.ORGS) > 0, "표가 안 읽혔다"
    assert len(od.ORGS) < len(od.KNOWN_DOMAINS), "발동 대상이 표 전체와 같으면 안 된다"


def test_pending_review_rows_never_fire():
    """★ `브라우저검수대기` 행(복지로 등)은 발동하지 않는다.

    제목으로 기관을 확인하지 못한 행이다. 검수 후 검수상태를 `1차검수` 로 바꾸면
    코드를 고치지 않아도 켜진다.
    """
    assert not any(o.domain == "bokjiro.go.kr" for o in od.ORGS)
    assert od.build_signal("복지로 안내입니다 bokjiro-event.com", None) is None


# ──────────────────────────────────────────── 등록가능 도메인
@pytest.mark.parametrize("host,expected", [
    ("www.nhis.or.kr", "nhis.or.kr"),        # ★ apex 가 안 뜨는 곳이 있어 www 를 흡수해야 한다
    ("nhis.or.kr", "nhis.or.kr"),
    ("youth.gwangju.go.kr", "gwangju.go.kr"),
    ("www.gov.kr", "gov.kr"),                # ★ gov.kr 은 2라벨이다 (.go.kr 이 아니다)
    ("gov.kr", "gov.kr"),
    ("ex.co.kr", "ex.co.kr"),                # ★ 공공기관인데 .co.kr
    ("www.kepco.co.kr", "kepco.co.kr"),
    ("gov24-refund-event.com", "gov24-refund-event.com"),
    ("a.b.gov24-refund-event.com", "gov24-refund-event.com"),
])
def test_registrable_domain(host, expected):
    assert od.registrable_domain(host) == expected


# ──────────────────────────────────────────── 주소 추출
def test_extract_domains_finds_schemeless_addresses():
    """★★ 노리는 두 건의 원문에는 http:// 가 없다. 스킴을 요구하면 기능이 죽는다. ★★"""
    assert od.extract_domains("정부24 미수령 환급금 확인 gov24-refund-event.com") == [
        "gov24-refund-event.com"]
    assert od.extract_domains("건강보험료 환급 신청 nhis-refund24.com") == ["nhis-refund24.com"]


def test_extract_domains_finds_host_inside_full_url():
    assert od.extract_domains("안내 ☞ https://m.site.naver.com/2dNkw") == ["m.site.naver.com"]


@pytest.mark.parametrize("text", [
    "할인율 3.5% 적용",
    "오전 9.30 부터",
    "계좌 ***-***-****** 로 보내세요",
    "문의 1372 번",
    "버전 1.2.3 배포",
])
def test_extract_domains_ignores_numbers_and_masked_values(text):
    """숫자와 마스킹된 값이 주소로 잡히면 안 된다 - 그 순간 오탐이 쏟아진다."""
    assert od.extract_domains(text) == []


def test_unknown_tld_is_ignored_and_that_is_the_safe_direction():
    """모르는 TLD 는 버린다 = 침묵한다. 사칭을 놓치는 쪽이지 정상을 의심하는 쪽이 아니다."""
    assert od.extract_domains("정부24 안내 gov24-refund.zzzz") == []


# ──────────────────────────────────────────── 발동 (노린 두 건)
@pytest.mark.parametrize("text,org,official,received", [
    ("정부24 미수령 환급금 확인 gov24-refund-event.com",
     "정부24", "gov.kr", "gov24-refund-event.com"),
    ("건강보험료 환급 신청 nhis-refund24.com",
     "국민건강보험공단", "nhis.or.kr", "nhis-refund24.com"),
])
def test_fires_on_the_two_measured_cases(text, org, official, received):
    sig = od.build_signal(text, None)
    assert sig is not None
    assert sig["detail"] == org
    assert sig["official_domain"] == official
    assert sig["received_domain"] == received


def test_label_has_no_verdict_words():
    """★ '가짜'·'사칭'·'위험'·'안전' 을 쓰지 않는다(validate_question 금지어와 같은 기준)."""
    sig = od.build_signal("정부24 미수령 환급금 확인 gov24-refund-event.com", None)
    for banned in ("가짜", "사칭", "사기", "위험", "안전", "찾았"):
        assert banned not in sig["label"], f"판정 문구 '{banned}' 가 들어갔다"


# ──────────────────────────────────────────── 침묵
def test_silent_when_org_mentioned_but_no_address():
    """★★ 이 테스트가 정상 3건(N01·N02 복지로, N11 국민연금공단)을 지킨다. ★★

    확대평가셋에서 표의 기관명이 언급된 건은 22건인데 주소가 함께 있는 건은 2건뿐이다.
    '주소가 있어야 발동' 조건을 빼면 나머지 20건이 전부 후보가 된다.
    """
    assert od.build_signal(
        "기초연금 신청은 주소지 주민센터나 국민연금공단 지사에서 하실 수 있습니다.", None) is None


def test_silent_when_no_org_is_mentioned():
    assert od.build_signal("오늘 저녁에 봐요 example.com", None) is None


def test_silent_when_domain_matches():
    """일치하면 침묵한다. ★ '맞습니다'·'안전합니다' 를 쓰지 않기 때문에 보여 줄 게 없다."""
    assert od.build_signal("국민건강보험공단 안내 https://www.nhis.or.kr/menu", None) is None


def test_silent_when_address_belongs_to_another_org_in_the_table():
    """★ 침묵 (b). 국세청 문자에 홈택스 링크는 정상이다 - 한 기관 = 한 도메인이 아니다.

    이 규칙이 없으면 표가 커질수록 오탐이 늘어난다.
    """
    assert od.build_signal("국세청 연말정산 안내 https://www.hometax.go.kr/ab", None) is None


def test_silent_for_any_go_kr_address_even_if_not_in_the_table():
    """★ 침묵 (c). 표에 없는 공공기관 주소(129.go.kr 등)를 오탐하지 않는다.

    .go.kr 은 등록 자격이 제한돼 있다(url_expand.PUBLIC_SUFFIXES 와 같은 근거).
    """
    assert od.build_signal("보건복지부 안내 https://129.go.kr/", None) is None


def test_local_government_stays_silent_because_it_is_not_in_the_table():
    """★ 지자체는 표에 없다(수백 곳이라 유지가 안 된다). R01 은 침묵 대상으로 남는 게 맞다."""
    assert od.build_signal(
        "[전남광주 통합특별시청 청년정책과] 신청 ☞ https://m.site.naver.com/2dNkw", None) is None


def test_switch_off_yields_no_signal():
    text = "정부24 미수령 환급금 확인 gov24-refund-event.com"
    assert od.build_signal(text, None) is not None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(od, "ORG_DOMAIN_ENABLED", False)
        assert od.build_signal(text, None) is None


# ──────────────────────────────────────────── 펼친 주소와 함께
def test_expanded_official_destination_silences_a_shortened_link():
    """★ 진짜 기관이 단축주소를 쓴 경우. 펼친 곳이 공식이면 침묵한다.

    본문 주소(naver.me)만 봤다면 오탐이 났을 자리다.
    """
    exp = ExpandResult("https://naver.me/x", "https://www.nps.or.kr/a", "www.nps.or.kr", 2)
    assert od.build_signal("국민연금공단 안내 https://naver.me/x", exp) is None


def test_expansion_failure_still_compares_the_raw_address():
    """★ 죽은 사칭 도메인은 펼치기가 실패한다. 그때도 본문 주소로 대조한다.

    펼친 것만 봤다면 S03·S08 이 조용히 빠졌을 것이다.
    """
    exp = ExpandResult("http://gov24-refund-event.com", None, None, 1, failure="dns:-2")
    sig = od.build_signal("정부24 미수령 환급금 확인 gov24-refund-event.com", exp)
    assert sig is not None
    assert sig["received_domain"] == "gov24-refund-event.com"


def test_shows_the_final_host_when_redirected():
    exp = ExpandResult("https://short.example/a", "https://gov24-refund.com/x",
                       "gov24-refund.com", 2)
    sig = od.build_signal("정부24 안내 https://short.example/a", exp)
    assert sig is not None
    assert sig["received_domain"] == "gov24-refund.com"


# ──────────────────────────────────────────── tier 보호
def test_signal_severity_is_always_info():
    """★★ tier 를 올리지 않는다. 이 단정이 깨지면 S03·S08 이 화면 단계를 움직인다. ★★"""
    sig = od.build_signal("정부24 미수령 환급금 확인 gov24-refund-event.com", None)
    assert sig["severity"] == "info"
    assert sig["key"] == "org_domain_mismatch"


def test_key_is_not_in_frontend_attention_allowlist():
    """프론트 허용 목록(verdict.js ATTENTION_KEYS)에 이 키가 없어야 한다.

    ★★ 이 테스트는 api 컨테이너에서 **스킵된다**(web/ 이 마운트되지 않는다).
      스킵은 초록불처럼 보이므로 여기 명시해 둔다. 실질 방어는 두 겹이다:
        1) 위 test_signal_severity_is_always_info - 컨테이너에서 항상 돈다
        2) tools/render_verdict.mjs 전수 대조 - 배포 전 사람이 돌린다
    """
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "web/src/verdict.js"
    if not p.exists():
        pytest.skip("web/src/verdict.js 가 이 환경에 없다 - 스킵")
    block = p.read_text(encoding="utf-8").split("const ATTENTION_KEYS = [", 1)[1].split("]", 1)[0]
    assert "org_domain_mismatch" not in block


def test_schema_declares_the_new_fields():
    """★★ 8/15 에 public_domain 이 응답에서 조용히 사라진 그 버그 유형이다. ★★

    Pydantic response_model 은 선언되지 않은 필드를 말없이 버린다. 단위 테스트는
    통과하고 화면에서만 값이 빈다. 그래서 스키마를 여기서 직접 단정한다.
    """
    from models.schemas import Signal
    sig = od.build_signal("정부24 미수령 환급금 확인 gov24-refund-event.com", None)
    out = Signal(**sig).model_dump()
    assert out["official_domain"] == "gov.kr"
    assert out["received_domain"] == "gov24-refund-event.com"
    assert out["detail"] == "정부24"
