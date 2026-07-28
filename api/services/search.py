"""
곁눈(Gyeotnun) - 공공데이터 대조 + 실시간 검색
담당: 김유리 (검색)

역할
  추출된 텍스트에서 '확인 포인트'를 뽑고, 실제로 존재하는 출처를 모아 온다.
  ★ 여기서 모은 references 의 URL 집합이 곧 prompt_chain 의 화이트리스트가 된다.
    즉 이 모듈이 근거의 진실성을 책임진다. 링크를 임의 생성하면 안 된다.

2단 검색
  1) 로컬 코퍼스(공공데이터 577건) 대조 - 키 없이 동작, 빠르고 안정적
  2) 네이버 검색 API - 최신 이슈 보강 (NAVER_CLIENT_ID/SECRET 필요)

★ 절대 하지 않는 것
  - 참/거짓 판정 반환. 이 모듈은 verdict_hint 로 '확인 필요 정도'만 돌려준다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from config import MissingKeyError, settings

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus" / "public_data"

# 확인 포인트 탐지 규칙 (간이 버전. 코퍼스 확보 후 정교화 - TODO 김유리)
SIGNAL_RULES = [
    ("condition_omitted", ["전원", "누구나", "무조건", "모두에게", "전부"],
     "'모두에게'라는 표현이 있습니다. 공식 자료에 조건이 붙어 있는지 확인이 필요합니다."),
    ("urgency_pressure", ["긴급", "마감", "오늘까지", "서둘러", "신청 안 하면", "선착순"],
     "서두르게 만드는 표현이 있습니다. 시간을 두고 확인해도 되는 내용인지 살펴보세요."),
    ("source_missing", [], "이 글에는 어느 기관이 발표했는지가 적혀 있지 않습니다."),
    ("contact_in_image", ["계좌", "입금", "송금", "연락처"],
     "개인 연락처나 계좌 정보가 들어 있습니다."),
]

_PUBLISHER_HINTS = ["보건복지부", "질병관리청", "금융감독원", "국민연금", "정책브리핑", "복지로", "식약처", "공단"]


@dataclass
class SearchResult:
    verdict_hint: str = "needs_check"   # needs_check | partially_matched | no_source_found
    signals: List[dict] = field(default_factory=list)
    references: List[dict] = field(default_factory=list)


def detect_signals(text: str) -> List[dict]:
    """텍스트에서 '확인이 필요한 지점'을 규칙으로 뽑는다. 키 없이 동작한다."""
    text = text or ""
    out: List[dict] = []
    for key, keywords, label in SIGNAL_RULES:
        if key == "source_missing":
            if not any(h in text for h in _PUBLISHER_HINTS):
                out.append({"key": key, "label": label, "severity": "attention"})
            continue
        if any(k in text for k in keywords):
            severity = "info" if key == "contact_in_image" else "attention"
            out.append({"key": key, "label": label, "severity": severity})
    return out


def search_corpus(query: str, domain: str | None = None, limit: int = 5) -> List[dict]:
    """로컬 공공데이터 코퍼스에서 관련 문서를 찾는다 (키 불필요).

    현재는 corpus/public_data/*.json 을 단순 키워드 매칭한다.
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


def collect_evidence(text: str, domain: str | None = None) -> SearchResult:
    """근거 수집 파이프라인. 코퍼스만으로도 최소 동작하도록 설계했다."""
    signals = detect_signals(text)
    refs = search_corpus(text, domain=domain)

    if not refs:
        # ★ 출처를 못 찾았을 때 '가짜'라고 하지 않는다. '못 찾았다'는 사실만 남긴다.
        hint = "no_source_found"
        signals.append({
            "key": "no_official_source",
            "label": "공식 자료에서 같은 내용을 찾지 못했습니다. 찾지 못했다는 것 자체가 확인 신호입니다.",
            "severity": "attention",
        })
    else:
        hint = "partially_matched" if signals else "needs_check"

    return SearchResult(verdict_hint=hint, signals=signals, references=refs)
