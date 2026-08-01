"""
곁눈(Gyeotnun) - 공공데이터 대조 + 실시간 검색
담당: 김유리 (검색)

역할
  추출된 텍스트에서 '확인 포인트'를 뽑고, 실제로 존재하는 출처를 모아 온다.
  ★ 여기서 모은 references 의 URL 집합이 곧 prompt_chain 의 화이트리스트가 된다.
    즉 이 모듈이 근거의 진실성을 책임진다. 링크를 임의 생성하면 안 된다.

검색 우선순위
  1) corpus_index.OFFICIAL_DOCS - 공공데이터 1,017건, BM25 검색 (2026-07-30 확장)
  2) corpus_index.EVIDENCE - 근거_검증표.csv 11건, 수작업 검증 통계
  3) 로컬 공공데이터 레거시 코퍼스(public_data/*.json) - 사실상 미사용(빈 폴더)
  4) 네이버 검색 API - 최신 이슈 보강 (NAVER_CLIENT_ID/SECRET 필요, 미구현)
  (별도) corpus_index.SCAM_CASES - 사기 사례 대조. 위 공식 문서 검색과는 완전히
  분리된 신호(similar_scam_case)로, 같은 인덱스/신호에 절대 섞지 않는다.

★★ 3단계 확인 결과 판정 기준 (collect_evidence 참고, 신호 조합으로 판단한다) ★★
  확인됨(needs_check)        : 공식 출처에서 동일 내용을 찾았고, 사기 패턴 일치나
                                문장 자체의 위험 신호가 없다.
  의심(partially_matched)    : 알려진 사기 패턴과 일치하거나(similar_scam_case),
                                문장 자체에 위험 신호(조건 생략·서두름)가 있다.
  확인 불가(no_source_found) : 공식 출처를 전혀 찾지 못했다 - 기본값. 애매하면
                                '의심'이나 '확인됨'으로 단정하지 않고 여기로 유보한다.

★ 절대 하지 않는 것
  - 참/거짓 판정 반환. 이 모듈은 verdict_hint 로 '확인 필요 정도'만 돌려준다.
  - URL·기관명 생성. references 는 corpus_index/CSV 에 실제로 있던 값만 담는다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from config import MissingKeyError, settings
from services import corpus_index

log = logging.getLogger("gyeotnun.search")

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus" / "public_data"

# 문장 자체에서 뽑는 '요구 행동의 위험도' 신호 - 출처 매칭 결과와는 무관하게 문장만 본다.
SIGNAL_RULES = [
    ("condition_omitted", ["전원", "누구나", "무조건", "모두에게", "전부"],
     "'모두에게'라는 표현이 있습니다. 공식 자료에 조건이 붙어 있는지 확인이 필요합니다."),
    ("urgency_pressure", ["긴급", "마감", "오늘까지", "서둘러", "신청 안 하면", "선착순"],
     "서두르게 만드는 표현이 있습니다. 시간을 두고 확인해도 되는 내용인지 살펴보세요."),
    ("contact_in_image", ["계좌", "입금", "송금", "연락처"],
     "개인 연락처나 계좌 정보가 들어 있습니다."),
]

# ★ 발행기관 명시 여부: 예전엔 보건복지부·질병관리청 등 특정 기관명 8개를 정확히
#   써야만 "명시됨"으로 인정했다. 실제 문장은 '복지로에서 확인하세요'처럼 서술형이
#   많아 이 좁은 목록에 잘 안 걸렸고, 그 결과 정상적인 공식 안내조차 '미명시'로
#   오판되어 needs_check(확인됨)에 아예 도달하지 못했다(docs/evaluation/eval_30_report.md
#   §6-1). 특정 기관명을 나열하는 대신 한국 공공기관 이름에 흔한 접미사로 넓게 잡고,
#   아래 collect_evidence() 에서 이 신호를 severity="info"(참고용)로만 쓴다 - 판정은
#   실제로 공식 출처를 찾았는지(코퍼스 매칭)로 하는 게 키워드 나열보다 신뢰도가 높다.
_ORG_SUFFIX_RE = re.compile(r"(부|처|청|원|공단|공사|재단|센터|협회|위원회|복지로|정부24|건강보험|국민연금)")


@dataclass
class SearchResult:
    verdict_hint: str = "no_source_found"   # needs_check | partially_matched | no_source_found
    signals: List[dict] = field(default_factory=list)
    references: List[dict] = field(default_factory=list)


def detect_signals(text: str) -> List[dict]:
    """텍스트 자체에서 '요구 행동의 위험도' + '발행기관 명시 여부' 신호를 뽑는다.

    ★ source_missing 은 severity="info" 다 - 이것만으로 확인불가/의심을 정하지
      않는다. 실제 판정은 collect_evidence() 가 공식 출처 매칭 여부까지 함께 본다.
    """
    text = text or ""
    out: List[dict] = []
    for key, keywords, label in SIGNAL_RULES:
        if any(k in text for k in keywords):
            severity = "info" if key == "contact_in_image" else "attention"
            out.append({"key": key, "label": label, "severity": severity})
    if not _ORG_SUFFIX_RE.search(text):
        out.append({
            "key": "source_missing",
            "label": "이 글 자체에는 어느 기관이 발표했는지가 적혀 있지 않습니다.",
            "severity": "info",
        })
    return out


def search_corpus(query: str, domain: str | None = None, limit: int = 5) -> List[dict]:
    """레거시: 공공데이터 577건 코퍼스(corpus/public_data/*.json)에서 찾는다 (키 불필요).

    아직 원문이 수집되지 않아 현재는 항상 빈 리스트를 돌려준다(폴더가 비어 있음).
    수집이 끝나면 collect_evidence() 에서 corpus_index 결과에 보조로 합쳐진다.
    TODO(김유리): 임베딩 기반 유사도 검색으로 교체 (장지석 RAG 인덱스와 공유).
    """
    if not CORPUS_DIR.exists():
        return []
    tokens = [t for t in (query or "").replace("\n", " ").split() if len(t) >= 2]
    hits: List[dict] = []
    for path in sorted(CORPUS_DIR.glob("*.json")):
        try:
            docs = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(docs, dict):
            docs = [docs]
        for doc in docs:
            blob = f"{doc.get('title', '')} {doc.get('body', '')}"
            score = sum(1 for t in tokens if t in blob)
            if domain and doc.get("domain") == domain:
                score += 1
            if score > 0:
                hits.append((score, doc))
    hits.sort(key=lambda x: -x[0])
    return [
        {
            "title": d.get("title", ""),
            "url": d.get("url", ""),
            "publisher": d.get("publisher", ""),
            "published_at": d.get("published_at"),
            "source_type": "public_data",
        }
        for _, d in hits[:limit]
        if d.get("url")            # ★ URL 없는 문서는 근거로 쓰지 않는다
    ]


def search_web(query: str, display: int = 5) -> List[dict]:
    """TODO(김유리): 네이버 검색 API(news/webkr) 호출.

    구현 스케치::

        headers = {
            "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        }
        r = httpx.get("https://openapi.naver.com/v1/search/news.json",
                      params={"query": query, "display": display, "sort": "sim"},
                      headers=headers, timeout=10)
        → title 의 <b> 태그 제거, originallink 를 url 로 사용

    ★ 응답에 실제로 들어 있던 링크만 references 에 담는다. 가공/추측 금지.
    """
    if not settings.has_search:
        raise MissingKeyError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET", owner="김유리")
    raise NotImplementedError("search_web 미구현. ?mock=1 을 사용하세요.")


def _dedup_refs(refs: List[dict]) -> List[dict]:
    """URL 기준으로 중복을 없앤다. 먼저 들어온 순서(우선순위)를 지킨다."""
    seen: set[str] = set()
    out: List[dict] = []
    for r in refs:
        u = r.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


# ==================================================== 하이브리드 검색 (BM25 + 임베딩)
# ★ 실험/벤치마크용이다. collect_evidence() 는 아직 이 함수들을 쓰지 않는다 - BM25/
#   임베딩/하이브리드 중 어느 것을 실제로 쓸지는 3방식 벤치마크 결과를 보고 사용자가
#   결정한다(docs/evaluation/hybrid_search_report.md). 그 전까지 프로덕션 경로는
#   기존 BM25 단독(corpus_index.match_official_docs)이다.

def _reciprocal_rank_fusion(
    rankings: List[List[str]],
    weights: List[float] | None = None,
    k: int = 60,
) -> dict:
    """순위 기반 결합(RRF). 점수를 직접 더하지 않는 이유:

    BM25 점수(코퍼스 크기에 따라 0~30점대까지 요동)와 코사인 유사도(항상 0~1)는
    척도가 완전히 달라서, 그대로 더하면 절대값이 큰 BM25 가 결과를 사실상 지배해
    버린다(정규화를 해도 분포 형태가 다르면 여전히 왜곡된다). RRF 는 "몇 점인지"가
    아니라 "몇 등인지"만 보므로 척도가 다른 신호를 안전하게 섞을 수 있다 - 정보
    검색에서 표준적으로 쓰이는 결합 방식이다(Cormack et al., 2009).

        score(d) = Σ_r  weight_r / (k + rank_r(d))   (그 방법의 결과에 없으면 0)

    k=60 은 RRF 원 논문의 기본값을 그대로 썼다 - 상위 몇 등 차이의 영향을 과하게
    키우지 않으면서도 순위 정보를 반영하는 값으로 이미 널리 검증돼 있어, 우리
    데이터로 다시 튜닝할 특별한 이유를 찾지 못했다(바꾸게 되면 이 주석에 실측
    근거를 추가할 것).
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    scores: dict = {}
    for ranking, w in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return scores


# ★ 결합 가중치(BM25:임베딩)의 근거는 docs/evaluation/hybrid_search_report.md
#   §가중치 튜닝 참고 - 30건 평가세트로 실측해서 정했다. 아래는 그 실측 결과값이다.
HYBRID_WEIGHT_BM25 = 1.0
HYBRID_WEIGHT_EMBEDDING = 1.0


def match_official_docs_hybrid(
    text: str,
    limit: int = 2,
    weight_bm25: float = HYBRID_WEIGHT_BM25,
    weight_embedding: float = HYBRID_WEIGHT_EMBEDDING,
    k: int = 60,
):
    """BM25 순위 + 임베딩 순위를 RRF 로 결합한 공식 문서 검색 (실험/벤치마크용).

    한쪽이 후보를 못 찾아도(예: 임베딩 인덱스 파일이 아직 없음) 나머지 하나만으로
    계속 동작한다 - 하이브리드가 반쪽만 살아 있어도 서비스가 죽지 않는다.
    """
    from services import embeddings  # 순환 임포트 방지 - embeddings.py 가 corpus_index 를 쓴다

    bm25_docs = corpus_index.match_official_docs(text, limit=max(limit, 10))
    bm25_ranking = [d.id for d in bm25_docs]

    embedding_hits = embeddings.match_embedding_docs(text, limit=max(limit, 10))
    embedding_ranking = [d.id for _, d in embedding_hits]

    if not bm25_ranking and not embedding_ranking:
        return []

    fused = _reciprocal_rank_fusion(
        [bm25_ranking, embedding_ranking],
        weights=[weight_bm25, weight_embedding],
        k=k,
    )
    ranked_ids = sorted(fused, key=lambda rid: -fused[rid])[:limit]
    return [
        corpus_index._OFFICIAL_DOCS_BY_ID[rid]
        for rid in ranked_ids
        if rid in corpus_index._OFFICIAL_DOCS_BY_ID
    ]


# ★ 2026-08 채택 결정: 임베딩 단독(Upstage) - 30건 벤치마크에서 BM25 대비 뚜렷한
#   우위(정상 근거매칭 7/10→10/10, Recall@3 30%→65%)를 실측으로 확인했다
#   (docs/evaluation/hybrid_search_report.md). 하이브리드(RRF)는 미채택이지만
#   코드는 지우지 않고 남겨 뒀다(match_official_docs_hybrid, 위) - 나중에 다시
#   검토하거나 폴백 전략을 바꿀 때 재활용한다.
#
# ★ 발표 당일 최대 리스크는 외부 API(Upstage) 의존이다(사용자 명시) - 그래서
#   임베딩을 기본으로 쓰되, 실패하면 로컬 BM25 로 즉시 폴백한다. BM25 는 "공짜
#   보험" - 어떤 이유로든 임베딩이 안 되면 서비스가 멈추는 대신 조용히 BM25 로
#   내려간다.
def match_official_docs_safe(text: str, limit: int = 2) -> tuple:
    """공식 문서 검색 - 임베딩을 우선 쓰고, 실패하면 즉시 BM25 로 폴백한다.

    반환값: (문서 리스트, 실제 쓰인 방식("embedding"|"bm25_fallback"),
    임베딩 최상위 유사도 - BM25 폴백이면 None, 척도가 달라 비교 불가하다).
    """
    from services import embeddings

    try:
        hits = embeddings.match_embedding_docs(text, limit=limit)
        docs = [d for _, d in hits]
        top_score = hits[0][0] if hits else None
        log.info("[official_search] 임베딩 검색 성공 (%d건)", len(docs))
        return docs, "embedding", top_score
    except embeddings.EmbeddingUnavailableError as e:
        log.warning("[official_search] 임베딩 검색 실패 - BM25 로 폴백: %s", e)
        docs = corpus_index.match_official_docs(text, limit=limit)
        log.info("[official_search] BM25 폴백 완료 (%d건)", len(docs))
        return docs, "bm25_fallback", None


# ★ 임계값(0.52)의 근거: 30건 평가세트 실측(docs/evaluation/hybrid_search_report.md
#   §0-1과 같은 실측 세션). '정상' 10건 중 최저 유사도는 0.5378(N02)이었고,
#   '경계'(모호한 사례, 확인불가가 기대판단) 10건 중 최고 유사도는 0.5058(B01)
#   이었다 - 0.5058과 0.5378 사이가 비어 있어 0.52 를 그 사이에 놓았다. 이 값
#   아래면 "근거는 찾았지만(레퍼런스로는 보여주되) 확인됨으로 단정할 만큼
#   확신하지는 않는다"로 취급해 확인불가로 유보한다 - 검색 성공 여부(참고자료
#   유무)와 판정 확신도(needs_check로 볼지)를 분리한 것이다.
CONFIDENT_MATCH_THRESHOLD = 0.52


def collect_evidence(text: str, domain: str | None = None) -> SearchResult:
    """근거 수집 파이프라인.

    우선순위: 공식 문서(임베딩 우선, 실패 시 BM25 폴백 - match_official_docs_safe)
    → corpus_index 근거_검증표(EVIDENCE, 11건 수작업 검증 통계) → public_data 레거시
    (577건, 아직 비어 있음). 셋 다 못 찾으면 '못 찾았다'는 사실 자체를 신호로 남긴다
    (판정하지 않는다).

    ★ 사기 사례(SCAM_CASES) 매칭은 공식 문서 매칭과 완전히 별개의 신호(similar_scam_case)
      다 - "공식 자료를 찾았다"와 "사기 사례와 비슷하다"를 절대 같은 신호로 섞지 않는다.
    """
    signals = detect_signals(text)

    # ---- 공식 문서를 먼저 검색한다 (임베딩 우선, 실패 시 BM25 폴백)
    matched_official, official_mode, official_top_score = match_official_docs_safe(text)
    matched_evidence = corpus_index.match_evidence(text)
    matched_scam = corpus_index.match_scam_cases(text)
    legacy_refs = search_corpus(text, domain=domain)

    # ---- 신호: 공식 문서/통계 매칭. matched_official 과 matched_evidence 는 인덱스는
    #      다르지만 사용자 입장에서는 둘 다 "공식 자료를 찾았다"는 같은 의미라
    #      같은 신호 키(official_source_found)를 쓴다 - 어느 코퍼스에서 왔는지는
    #      내부 구현일 뿐, 사용자에게 중요한 건 '공식 자료인지 여부'다.
    for doc in matched_official:
        signals.append({
            "key": "official_source_found",
            "label": f"공식 자료와 대조했습니다: {doc.source_agency} - {doc.title}",
            "severity": "info",
        })
    for doc in matched_evidence:
        signals.append({
            "key": "official_source_found",
            "label": f"공식 통계·자료와 대조했습니다: {doc.publisher} - {doc.title}",
            "severity": "info",
        })

    # ---- 신호: 유사 사기 사례 일치 (강한 경고 신호) - 위 official_source_found 와
    #      명확히 다른 키를 쓴다. 같은 텍스트가 공식 문서와도, 사기 사례와도 동시에
    #      매칭될 수 있다(예: 실제 제도명을 사칭한 문자) - 그때도 두 신호를 각각 보여준다.
    for case in matched_scam:
        signals.append({"key": "similar_scam_case", "label": case.signal_label(), "severity": "attention"})

    refs = _dedup_refs(
        [d.to_reference() for d in matched_official]
        + [d.to_reference() for d in matched_evidence]
        + [c.to_reference() for c in matched_scam]
        + legacy_refs
    )

    # ★★ 3단계 판정 - 모듈 docstring의 기준을 그대로 코드로 옮긴 것이다.
    #   official_source_found/source_missing(둘 다 severity="info")은 판정에 영향을
    #   주지 않는다 - "출처를 찾았다"는 사실 자체와 "위험하다"는 신호는 다른 질문이다.
    #   attention 신호(사기 패턴 일치, 조건 생략, 서두름)가 있을 때만 '의심'으로 올린다.
    risky = any(s["severity"] == "attention" for s in signals)

    # ★ 경계 케이스 개선(2026-08): "근거를 찾았는가"와 "그 근거를 확인됨으로 볼
    #   만큼 확신하는가"를 분리한다. matched_evidence(수작업 검증 통계)·
    #   matched_scam(사기사례 매칭, 자체 임계값 5.0 통과)·BM25 폴백(자체 임계값
    #   12.0 통과)은 이미 각자의 검증을 거쳤으니 그대로 확신 있는 근거로 본다.
    #   임베딩 경로만 추가로 CONFIDENT_MATCH_THRESHOLD 를 넘는지 본다 - 넘지
    #   못하면(예: 0.45~0.52 사이의 약한 유사도) references 에는 그대로 보여주되
    #   (근거는 찾되) needs_check 로 단정하지는 않는다.
    if official_mode == "embedding":
        official_confident = official_top_score is not None and official_top_score >= CONFIDENT_MATCH_THRESHOLD
    else:  # bm25_fallback 이거나 애초에 매칭이 없었던 경우
        official_confident = bool(matched_official)
    has_confident_source = official_confident or bool(matched_evidence) or bool(matched_scam)

    if not refs:
        # ★ 확인 불가가 기본값이다. 출처를 못 찾았을 때 '가짜'라고 단정하지 않고
        #   '못 찾았다'는 사실만 남긴다 - 애매할 때 의심/확인됨으로 넘기지 않는다.
        hint = "no_source_found"
        signals.append({
            "key": "no_official_source",
            "label": "공식 자료에서 같은 내용을 찾지 못했습니다. 찾지 못했다는 것 자체가 확인 신호입니다.",
            "severity": "attention",
        })
    elif risky:
        hint = "partially_matched"
    elif not has_confident_source:
        # ★ 근거는 있다(refs 는 비어 있지 않다 - 화면에 참고자료로 계속 보여준다)
        #   그런데 그 근거가 임베딩의 약한 유사도뿐이라 확신하기엔 부족하다.
        #   확인됨으로 단정하지 않고 확인불가로 유보한다.
        hint = "no_source_found"
    else:
        hint = "needs_check"

    return SearchResult(verdict_hint=hint, signals=signals, references=refs)
