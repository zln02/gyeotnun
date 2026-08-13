"""
공식 문서 검색 - 임베딩 실패 시 BM25 폴백 테스트
실행: cd api && python -m pytest tests/test_search_fallback.py -q

★ 왜 이 테스트가 있는가: 발표 당일 최대 리스크는 외부 API(Upstage) 의존이라고
  사용자가 명시했다. 실제 API 를 죽일 수는 없으니, embeddings.match_embedding_docs()
  가 실패(EmbeddingUnavailableError)하는 상황을 모의(mock)해서 search.py 가
  정말로 BM25 로 넘어가는지, 그리고 그 사실이 로그에 남는지를 코드로 검증한다.
"""
from __future__ import annotations

import logging
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import corpus_index, search  # noqa: E402
from services.embeddings import EmbeddingUnavailableError  # noqa: E402

TEXT = "농어가목돈마련저축 저축장려금 지급 안내입니다."


def test_embedding_success_path_reports_embedding_mode():
    """임베딩이 정상 동작하면 mode='embedding' 이어야 한다."""
    fake_doc = corpus_index.OFFICIAL_DOCS[0] if corpus_index.OFFICIAL_DOCS else None
    if fake_doc is None:
        pytest.skip("OFFICIAL_DOCS 가 로컬에 없다(별도 전달 코퍼스 없이 도는 환경) - 스킵")

    with patch(
        "services.embeddings.match_embedding_docs",
        return_value=[(0.9, fake_doc)],
    ):
        docs, mode, top_score = search.match_official_docs_safe(TEXT)

    assert mode == "embedding"
    assert docs == [fake_doc]
    assert top_score == 0.9


def test_embedding_failure_falls_back_to_bm25(caplog):
    """임베딩이 EmbeddingUnavailableError 를 던지면(키 없음/타임아웃/API 오류 등
    전부 이 예외 하나로 온다) BM25 로 자동 폴백해야 하고, 그 사실이 로그에 남아야 한다."""
    with patch(
        "services.embeddings.match_embedding_docs",
        side_effect=EmbeddingUnavailableError("모의 실패: 타임아웃"),
    ):
        with caplog.at_level(logging.WARNING, logger="gyeotnun.search"):
            docs, mode, top_score = search.match_official_docs_safe(TEXT)

    assert mode == "bm25_fallback"
    assert top_score is None
    # BM25 로 실제로 검색이 수행됐는지도 확인한다 - 이 문구는 BM25 로도 매칭되는
    # 실제 케이스다(docs/evaluation/eval_30_report.md 에서 실측 확인된 문구).
    assert len(docs) >= 1

    assert any("폴백" in rec.message for rec in caplog.records), \
        "폴백 발생 사실이 로그에 남아야 한다(운영 중 장애 여부를 나중에 추적할 수 있어야 함)"


def test_embedding_infrastructure_failure_triggers_fallback():
    """임베딩 계층이 '실제로' 죽었을 때(호출 함수가 예외를 던질 때) BM25 로 넘어가는지
    확인한다 - EmbeddingUnavailableError 를 직접 던지는 위 테스트와 달리, 여기서는
    embeddings.py 의 예외 변환 로직을 실제로 통과시킨다.

    ★ 2026-08-04 로컬 임베딩 전환에 맞춰 고쳤다. 전에는 httpx.post 를 모의해
      네트워크 타임아웃을 흉내 냈는데, 로컬 제공자는 httpx 를 아예 쓰지 않아서
      그 방식으로는 아무것도 검증하지 못한다(모의가 무시되고 임베딩이 그냥 성공).
      제공자와 무관하게 '임베딩 호출 자체가 터지는' 상황을 모의하도록 바꿨다.
    """
    from services import embeddings

    if not embeddings._INDEX.ready:
        pytest.skip("이 테스트 환경에 임베딩 인덱스가 없다 - 스킵")

    def _boom(*args, **kwargs):
        raise TimeoutError("모의 인프라 장애(타임아웃)")

    # embed_texts 는 제공자(upstage/local) 어느 쪽이든 반드시 거쳐 가는 지점이다.
    with patch("services.embeddings.embed_texts", side_effect=_boom):
        docs, mode, top_score = search.match_official_docs_safe(TEXT)

    assert mode == "bm25_fallback"


def test_collect_evidence_falls_back_and_still_returns_a_valid_result():
    """collect_evidence() 전체가 임베딩 실패 상황에서도 죽지 않고 정상적인
    SearchResult 를 돌려주는지 확인한다(엔드투엔드 안전망)."""
    with patch(
        "services.embeddings.match_embedding_docs",
        side_effect=EmbeddingUnavailableError("모의 실패"),
    ):
        result = search.collect_evidence(TEXT)

    assert result.verdict_hint in ("needs_check", "partially_matched", "no_source_found")
    assert isinstance(result.references, list)


def test_weak_embedding_similarity_below_confidence_threshold_yields_no_source_found():
    """근거(레퍼런스)는 찾았지만 유사도가 CONFIDENT_MATCH_THRESHOLD 미만이면
    needs_check 로 단정하지 않고 no_source_found 로 유보해야 한다(2026-08 변경).
    다른 확증(위험신호·사기사례매칭)이 전혀 없는 경우로 모의한다.

    ★ 2026-08-12 픽스처 수정 - 예전에는 OFFICIAL_DOCS[0] 을 그대로 썼는데,
      그게 하필 warning_case("정당관계자 사칭 노쇼 사기 주의")였다. 경보문이
      근거로 붙으면 official_alert_matched(attention)가 붙게 되면서
      "다른 확증이 전혀 없다"는 이 테스트의 전제가 깨졌다.
      단정을 완화한 게 아니라, 전제에 맞는 문서(제도 안내문)를 고르도록 고쳤다.
      경보문이 붙는 경우는 아래 test_alert_doc_match_raises_attention 이 따로 본다."""
    fake_doc = next(
        (d for d in corpus_index.OFFICIAL_DOCS if not search._is_alert_doc(d)), None,
    )
    if fake_doc is None:
        pytest.skip("OFFICIAL_DOCS 가 로컬에 없다 - 스킵")

    weak_score = search.CONFIDENT_MATCH_THRESHOLD - 0.05
    assert weak_score >= 0  # 이 테스트 자체의 전제 조건

    with patch(
        "services.embeddings.match_embedding_docs",
        return_value=[(weak_score, fake_doc)],
    ), patch("services.corpus_index.match_evidence", return_value=[]), \
       patch("services.corpus_index.match_scam_cases", return_value=[]), \
       patch("services.search.detect_signals", return_value=[]):
        result = search.collect_evidence("이 문구는 위험신호가 전혀 없는 임의의 텍스트입니다")

    assert result.references, "근거(레퍼런스)는 그대로 보여줘야 한다 - '근거는 찾되'"
    assert result.verdict_hint == "no_source_found", (
        f"약한 유사도({weak_score})는 확인됨으로 단정하면 안 된다, 실제={result.verdict_hint}"
    )


def test_alert_doc_match_raises_attention():
    """근거로 붙은 공식 문서가 '사기 경보문'(warning_case)이면 attention 신호를
    붙이고 확인됨으로 단정하지 않아야 한다 (2026-08-12, S22).

    ★ 배경: KISA 사칭 문자에 "KISA 보안공지를 사칭한 스미싱 문자 주의"라는 바로
      그 경보문을 0.7023 으로 찾아 놓고, 경보문이 OFFICIAL_DOCS 에 있다는 이유로
      official_source_found(info)만 붙어 화면에 초록 "공식 자료를 찾았어요"가
      나갔다. 찾은 건 맞는데 뜻이 정반대로 전달됐다.
      docs/evaluation/IDF척도이동_A안_2026-08-12.md
    """
    alert_doc = next(
        (d for d in corpus_index.OFFICIAL_DOCS if search._is_alert_doc(d)), None,
    )
    if alert_doc is None:
        pytest.skip("OFFICIAL_DOCS 에 경보문이 없다 - 스킵")

    # 확신선을 넘는 점수를 줘도(= 전에는 needs_check 로 갔던 조건) 단정하지 않아야 한다.
    strong = search.CONFIDENT_MATCH_THRESHOLD + 0.02
    with patch(
        "services.embeddings.match_embedding_docs",
        return_value=[(strong, alert_doc)],
    ), patch("services.corpus_index.match_evidence", return_value=[]), \
       patch("services.corpus_index.match_scam_cases", return_value=[]), \
       patch("services.search.detect_signals", return_value=[]):
        result = search.collect_evidence("임의의 텍스트")

    keys = [s["key"] for s in result.signals]
    assert "official_alert_matched" in keys, f"경보문 신호가 없다: {keys}"
    assert any(s["key"] == "official_alert_matched" and s["severity"] == "attention"
               for s in result.signals), "경보문 신호는 attention 이어야 한다"
    assert result.verdict_hint != "needs_check", (
        f"경보문을 찾았는데 확인됨으로 단정하면 안 된다, 실제={result.verdict_hint}"
    )
    # ★ label 에 "찾았습니다"가 들어가면 초록 화면 문구와 같아져 오해를 재생산한다.
    label = next(s["label"] for s in result.signals if s["key"] == "official_alert_matched")
    assert "찾았" not in label, f"label 에 '찾았' 표현이 있다: {label}"
    assert "사기" not in label and "가짜" not in label, f"금지어가 있다: {label}"


def test_alert_allowlist_covers_only_reviewed_press_releases():
    """press_release 는 '사람이 검수해 올린 8건'만 경보문으로 본다 (2026-08-13).

    ★ 이 테스트가 지키는 것: 누군가 편하다고 ALERT_DOC_DATA_TYPES 에
      "press_release" 를 넣어 버리면 C 16건(업무협약·시상식·단속실적·성과통계)이
      함께 경보문이 된다. 그 순간 "사람이 확인한 것만 들어간다"가 깨진다.
      아래 두 단정이 그 변경을 즉시 빨간불로 만든다.
      분류 근거: docs/evaluation/press_release_24건_분류초안_2026-08-13.md
    """
    docs = {d.id: d for d in corpus_index.OFFICIAL_DOCS}
    if not docs:
        pytest.skip("OFFICIAL_DOCS 가 로컬에 없다 - 스킵")

    listed = [docs[i] for i in search.ALERT_DOC_IDS if i in docs]
    assert len(listed) == len(search.ALERT_DOC_IDS), (
        "허용목록의 문서 id 중 코퍼스에 없는 것이 있다 - 코퍼스가 바뀌었으면 "
        "재분류가 필요하다: " + str(search.ALERT_DOC_IDS - set(docs))
    )
    assert all(search._is_alert_doc(d) for d in listed), "허용목록 문서가 경보문으로 안 잡힌다"

    others = [d for d in corpus_index.OFFICIAL_DOCS
              if getattr(d, "data_type", "") == "press_release"
              and d.id not in search.ALERT_DOC_IDS]
    assert others, "press_release 가 전부 허용목록이면 이 테스트는 아무것도 지키지 못한다"
    assert not any(search._is_alert_doc(d) for d in others), (
        f"허용목록에 없는 press_release {len(others)}건이 경보문으로 잡힌다 - "
        "ALERT_DOC_DATA_TYPES 에 press_release 가 들어갔는지 확인할 것"
    )


def _reset_fallback_observer():
    search._recent_search_fallbacks.clear()
    search._search_fallback_alerted = False


def test_search_fallback_rate_warns_when_repeated(caplog):
    """폴백이 '반복되고 있다'는 사실이 로그와 EX-006 으로 남는지 (2026-08-13).

    ★ 개별 발생(EX-003)은 이미 남고 있었다. 없던 것은 비율이다.
      8/9 에 외부 LLM 폴백률이 8시간 동안 100% 였는데 아무도 몰랐던 것과 같은
      구조라, 질문 생성 쪽 GN-003 과 같은 형식으로 맞춘 것을 검증한다.
    """
    _reset_fallback_observer()
    codes = []
    with patch(
        "services.embeddings.match_embedding_docs",
        side_effect=EmbeddingUnavailableError("모의 실패"),
    ), patch("services.incident_log.log_incident",
             side_effect=lambda code, **kw: codes.append(code)):
        with caplog.at_level(logging.WARNING, logger="gyeotnun.search"):
            for _ in range(search._SEARCH_FALLBACK_MIN_SAMPLES):
                search.match_official_docs_safe(TEXT)

    assert any("[search_fallback_rate]" in r.message for r in caplog.records), \
        "폴백률이 임계를 넘었는데 상태 경고가 없다"
    assert codes.count("EX-006") == 1, (
        f"EX-006 은 임계를 넘는 동안 한 번만 남아야 한다(플래핑 방지), 실제={codes}"
    )
    _reset_fallback_observer()


def test_search_fallback_rate_is_silent_when_healthy(caplog):
    """임베딩이 정상일 때는 아무 경고도 남기지 않는다 - 관측이 소음이 되면 안 본다."""
    _reset_fallback_observer()
    fake_doc = corpus_index.OFFICIAL_DOCS[0] if corpus_index.OFFICIAL_DOCS else None
    if fake_doc is None:
        pytest.skip("OFFICIAL_DOCS 가 로컬에 없다 - 스킵")

    with patch("services.embeddings.match_embedding_docs", return_value=[(0.9, fake_doc)]):
        with caplog.at_level(logging.WARNING, logger="gyeotnun.search"):
            for _ in range(search._SEARCH_FALLBACK_WINDOW):
                search.match_official_docs_safe(TEXT)

    assert not any("[search_fallback_rate]" in r.message for r in caplog.records)
    _reset_fallback_observer()


def test_alert_signal_can_be_disabled():
    """되돌릴 스위치가 실제로 동작하는지 - ALERT_DOC_AS_ATTENTION=False 면 이전 동작."""
    alert_doc = next(
        (d for d in corpus_index.OFFICIAL_DOCS if search._is_alert_doc(d)), None,
    )
    if alert_doc is None:
        pytest.skip("OFFICIAL_DOCS 에 경보문이 없다 - 스킵")

    strong = search.CONFIDENT_MATCH_THRESHOLD + 0.02
    with patch("services.search.ALERT_DOC_AS_ATTENTION", False), patch(
        "services.embeddings.match_embedding_docs",
        return_value=[(strong, alert_doc)],
    ), patch("services.corpus_index.match_evidence", return_value=[]), \
       patch("services.corpus_index.match_scam_cases", return_value=[]), \
       patch("services.search.detect_signals", return_value=[]):
        result = search.collect_evidence("임의의 텍스트")

    assert "official_alert_matched" not in [s["key"] for s in result.signals]
    assert result.verdict_hint == "needs_check", "스위치를 끄면 이전 동작이어야 한다"
