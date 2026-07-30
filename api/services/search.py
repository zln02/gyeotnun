"""
곁눈(Gyeotnun) - 공공데이터 대조 + 실시간 검색
담당: 김유리 (검색)

역할
  추출된 텍스트에서 '확인 포인트'를 뽑고, 실제로 존재하는 출처를 모아 온다.
  ★ 여기서 모은 references 의 URL 집합이 곧 prompt_chain 의 화이트리스트가 된다.
    즉 이 모듈이 근거의 진실성을 책임진다. 링크를 임의 생성하면 안 된다.

3단 검색 (근거 우선순위 순)
  1) corpus_index (근거_검증표/재라벨링표 CSV) - 데이터팀이 검수한 근거,
     키 없이 동작, 가장 신뢰도 높음
  2) 로컬 공공데이터 코퍼스(public_data/*.json, 577건 목표) - 아직 미수집 상태
  3) 네이버 검색 API - 최신 이슈 보강 (NAVER_CLIENT_ID/SECRET 필요, 미구현)

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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from config import MissingKeyError, settings
from services import corpus_index

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


def collect_evidence(text: str, domain: str | None = None) -> SearchResult:
    """근거 수집 파이프라인.

    우선순위: corpus_index(근거_검증표/사기사례) → public_data(577건, 아직 비어 있음)
    둘 다 못 찾으면 '못 찾았다'는 사실 자체를 신호로 남긴다 (판정하지 않는다).
    """
    signals = detect_signals(text)

    matched_evidence = corpus_index.match_evidence(text)
    matched_scam = corpus_index.match_scam_cases(text)
    legacy_refs = search_corpus(text, domain=domain)

    # ---- 신호: 공식 공고(=근거_검증표) 존재 여부 + 발행 기관 명시 여부 (한 신호에 함께 담는다.
    #      근거_검증표는 확인완료 행만 남겨서 기관명이 항상 채워져 있으므로 따로 쪼갤 이유가 없다)
    for doc in matched_evidence:
        signals.append({
            "key": "official_source_found",
            "label": f"공식 통계·자료와 대조했습니다: {doc.publisher} - {doc.title}",
            "severity": "info",
        })

    # ---- 신호: 유사 사기 사례 일치 (강한 경고 신호)
    for case in matched_scam:
        signals.append({"key": "similar_scam_case", "label": case.signal_label(), "severity": "attention"})

    refs = _dedup_refs(
        [d.to_reference() for d in matched_evidence]
        + [c.to_reference() for c in matched_scam]
        + legacy_refs
    )

    # ★★ 3단계 판정 - 모듈 docstring의 기준을 그대로 코드로 옮긴 것이다.
    #   official_source_found/source_missing(둘 다 severity="info")은 판정에 영향을
    #   주지 않는다 - "출처를 찾았다"는 사실 자체와 "위험하다"는 신호는 다른 질문이다.
    #   attention 신호(사기 패턴 일치, 조건 생략, 서두름)가 있을 때만 '의심'으로 올린다.
    risky = any(s["severity"] == "attention" for s in signals)

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
    else:
        hint = "needs_check"

    return SearchResult(verdict_hint=hint, signals=signals, references=refs)
