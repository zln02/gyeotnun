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


def test_embedding_timeout_specifically_triggers_fallback():
    """타임아웃(httpx.TimeoutException 계열)도 EmbeddingUnavailableError 로 변환돼
    같은 폴백 경로를 타는지 확인한다 - embeddings.py 의 실제 예외 변환 로직을 통해서
    (has_embeddings/인덱스 준비 여부는 이 테스트 환경에 실제로 설정된 값을 그대로
    쓴다 - 그 두 속성은 읽기 전용 프로퍼티라 모의할 필요도 없다)."""
    import httpx
    from config import settings
    from services import embeddings

    if not settings.has_embeddings or not embeddings._INDEX.ready:
        pytest.skip("이 테스트 환경에 UPSTAGE_API_KEY/임베딩 인덱스가 없다 - 스킵")

    def _raise_timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("모의 타임아웃")

    with patch("httpx.post", side_effect=_raise_timeout):
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
    다른 확증(위험신호·사기사례매칭)이 전혀 없는 경우로 모의한다."""
    fake_doc = corpus_index.OFFICIAL_DOCS[0] if corpus_index.OFFICIAL_DOCS else None
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
