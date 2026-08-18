"""근거 검색 실패 건의 원인을 케이스별로 분류한다 (2026-08-09)
실행: docker compose exec api python3 experiments/diag_search_failures.py

★ 측정·관찰만 한다. 검색 로직을 고치지 않는다.

분류 기준 (지시서)
  a) 커버리지  : 정답 근거 문서 자체가 색인에 없다
  b) 유사도 미달: 문서는 있으나 최고 청크 유사도 < EMBEDDING_MIN_SCORE
  c) 청킹 경계  : 문서 전문(全文)으로는 임계를 넘는데 청크로 쪼개면 못 넘는다
                 (= 근거 신호가 청크 경계에서 희석됐다)
  d) 기타

정답 문서 판정
  평가셋 CSV 의 출처_URL 로 코퍼스를 찾는다(호스트+경로 기준). 못 찾으면
  참고_출처 제목의 형태소 겹침으로 후보를 찾고, 그것도 없으면 커버리지 없음이다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")

import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
import numpy as np  # noqa: E402

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
OUT = Path("/app/data/diag_search_failures.json")

MIN_SCORE = emb.EMBEDDING_MIN_SCORE
CONF = search.CONFIDENT_MATCH_THRESHOLD


# ------------------------------------------------------------------ 정답 문서 찾기
def _url_key(url: str) -> str:
    """★ 쿼리스트링까지 포함해야 한다. counterscam112 는 경로가 전부
    /bbs00N/board/boardDetail.do 로 같고 ?pstSn=N 만 다르다 - 경로만 비교하면
    전혀 다른 게시글이 같은 문서로 잡힌다(첫 실행에서 실제로 그랬다)."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    if not p.netloc:
        return ""
    base = (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()
    return f"{base}?{p.query}" if p.query else base


_DOC_BY_URLKEY: dict[str, list] = {}
for _d in ci.OFFICIAL_DOCS:
    k = _url_key(_d.source_url)
    if k:
        _DOC_BY_URLKEY.setdefault(k, []).append(_d)

# 공식문서에서 못 찾았을 때 "사기사례로 옮겨졌는가"를 구분하려고 별도 색인도 만든다.
# corpus_index 는 warning_case/press_release 중 200자 이하 문서를 SCAM_CASES 로
# 의도적으로 옮긴다 - 그 경우는 '커버리지 없음'이 아니라 '다른 인덱스에 있음'이다.
_SCAM_BY_URLKEY: dict[str, list] = {}
for _c in ci.SCAM_CASES:
    k = _url_key(getattr(_c, "url", "") or "")
    if k:
        _SCAM_BY_URLKEY.setdefault(k, []).append(_c)


def find_gold_docs(row: dict) -> tuple[list, str]:
    """정답 근거 문서 후보와 판정 방법을 돌려준다."""
    url = (row.get("출처_URL") or "").strip()
    key = _url_key(url)
    if key and key in _DOC_BY_URLKEY:
        return _DOC_BY_URLKEY[key], "url_exact"

    # 경로가 달라도 같은 호스트의 같은 서비스일 수 있다 - 호스트 + 제목 겹침
    host = urlparse(url).netloc.lower().replace("www.", "") if url else ""
    title = (row.get("참고_출처") or "").strip()
    t_tokens = {t for t in ci.extract_keywords(title) if t not in ci.STOPWORDS}
    if not t_tokens:
        return [], "no_gold_label"

    scored = []
    for d in ci.OFFICIAL_DOCS:
        d_tokens = {t for t in ci.extract_keywords(d.title) if t not in ci.STOPWORDS}
        if not d_tokens:
            continue
        overlap = len(t_tokens & d_tokens) / len(t_tokens)
        same_host = bool(host) and host in (d.source_url or "").lower()
        if overlap >= 0.6 or (same_host and overlap >= 0.4):
            scored.append((overlap, same_host, d))
    if not scored:
        return [], "not_found"
    scored.sort(key=lambda x: (-x[0], not x[1]))
    return [d for _, _, d in scored[:3]], "title_overlap"


# ------------------------------------------------------------------ 유사도 계산
def query_vec(text: str) -> np.ndarray:
    v, _ = emb.embed_texts([text], input_type="query")
    q = np.array(v[0], dtype=np.float32)
    return q / (np.linalg.norm(q) or 1.0)


def doc_chunk_scores(q: np.ndarray, record_id: str) -> list[float]:
    """색인에 들어 있는 그 문서 청크들의 유사도(내림차순)."""
    idx = [i for i, rid in enumerate(emb._INDEX.record_ids) if str(rid) == record_id]
    if not idx:
        return []
    sims = emb._INDEX.vectors[idx] @ q
    return sorted((float(s) for s in sims), reverse=True)


def fulldoc_score(q: np.ndarray, doc) -> float:
    """문서를 쪼개지 않고 통째로 임베딩했을 때의 유사도.

    청크 경계 때문에 신호가 희석됐는지 보려고 잰다. 색인과 같은 규약으로
    제목을 앞에 붙인다(_rechunk_official_docs 와 동일).
    """
    text = f"{doc.title}\n{doc.content}".strip()
    v, _ = emb.embed_texts([text], input_type="document")
    d = np.array(v[0], dtype=np.float32)
    return float(d @ q / (np.linalg.norm(d) or 1.0))


# ------------------------------------------------------------------ 본체
def classify(row: dict, q: np.ndarray) -> dict:
    gold, how = find_gold_docs(row)

    # 공식문서에서 못 찾았다면, 사기사례 인덱스로 옮겨진 것인지 먼저 구분한다.
    if not gold or how == "title_overlap":
        key = _url_key(row.get("출처_URL") or "")
        if key and key in _SCAM_BY_URLKEY:
            c = _SCAM_BY_URLKEY[key][0]
            return {"cause": "a) 커버리지(설계상 이관)",
                    "detail": "정답 문서가 공식문서 인덱스가 아니라 SCAM_CASES 로 "
                              "이관돼 있다(짧은 경보문 규칙). 공식문서 검색으로는 "
                              "구조적으로 찾을 수 없다.",
                    "gold": f"[사기사례] {getattr(c, 'id', '')}", "gold_id": getattr(c, "id", ""),
                    "gold_url": getattr(c, "url", ""), "match_how": "scam_index",
                    "best_chunk": None, "full_doc": None, "n_chunks": None}

    if not gold:
        return {"cause": "a) 커버리지", "detail": f"정답 문서를 색인에서 찾지 못함({how})",
                "gold": None, "best_chunk": None, "full_doc": None, "n_chunks": None,
                "match_how": how}

    best = None
    for d in gold:
        scores = doc_chunk_scores(q, d.id)
        if not scores:
            continue
        if best is None or scores[0] > best[1]:
            best = (d, scores[0], len(scores))
    if best is None:
        return {"cause": "a) 커버리지", "detail": f"문서는 있으나 임베딩 색인에 청크가 없음({how})",
                "gold": gold[0].title, "best_chunk": None, "full_doc": None, "n_chunks": 0}

    doc, best_chunk, n_chunks = best
    full = fulldoc_score(q, doc)

    if best_chunk >= MIN_SCORE:
        cause = "d) 기타"
        detail = (f"정답 문서 청크가 임계({MIN_SCORE:.4f})를 넘는데도 상위 2건에 못 들었다"
                  " - 다른 문서에 밀림(랭킹 문제)")
    elif full >= MIN_SCORE:
        cause = "c) 청킹 경계"
        detail = (f"문서 전문은 {full:.4f} 로 임계를 넘지만 최고 청크는 {best_chunk:.4f} 로 미달"
                  f" - 근거가 {n_chunks}개 청크로 쪼개지며 희석됐다")
    else:
        cause = "b) 유사도 미달"
        detail = (f"문서는 색인에 있으나 최고 청크 {best_chunk:.4f} < 임계 {MIN_SCORE:.4f}"
                  f" (전문도 {full:.4f}) - 질의와 문서의 표현이 다르다")

    return {"cause": cause, "detail": detail, "gold": doc.title, "gold_id": doc.id,
            "gold_url": doc.source_url, "match_how": how,
            "best_chunk": round(best_chunk, 4), "full_doc": round(full, 4),
            "n_chunks": n_chunks}


def main() -> None:
    rows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig")))
    print(f"평가셋 {len(rows)}건 / 임계값 min_score={MIN_SCORE:.4f} confident={CONF:.4f}\n")

    results = []
    for r in rows:
        text = r["평가용_제시문구"]
        ev = search.collect_evidence(text)
        official = [ref for ref in ev.references]
        hits = []
        try:
            hits = emb.match_embedding_docs(text, limit=3)
        except emb.EmbeddingUnavailableError:
            pass
        results.append({
            "id": r["case_id"], "유형": r.get("유형", ""), "text": text,
            "n_refs": len(official),
            "verdict": ev.verdict_hint,
            "top1": round(hits[0][0], 4) if hits else None,
            "top3_titles": [d.title[:40] for _, d in hits],
            "gold_label": r.get("참고_출처", ""), "gold_url": r.get("출처_URL", ""),
        })

    fails = [x for x in results if x["n_refs"] == 0]
    print(f"근거 검색 성공 {len(results) - len(fails)}/{len(results)} "
          f"(실패 {len(fails)}건)\n")
    print(f"{'ID':<6}{'유형':<7}{'refs':>5}{'top1':>9}  판정")
    print("-" * 60)
    for x in results:
        top1 = f"{x['top1']:.4f}" if x["top1"] is not None else "-"
        print(f"{x['id']:<6}{x['유형']:<7}{x['n_refs']:>5}{top1:>9}  {x['verdict']}")

    print("\n" + "=" * 78)
    print("실패 건 원인 분류")
    print("=" * 78)
    by_row = {r["case_id"]: r for r in rows}
    diag = []
    for x in fails:
        q = query_vec(x["text"])
        c = classify(by_row[x["id"]], q)
        c["id"] = x["id"]
        c["유형"] = x["유형"]
        c["top1"] = x["top1"]
        c["text"] = x["text"]
        c["gold_label"] = x["gold_label"]
        diag.append(c)
        print(f"\n[{x['id']}] {x['유형']}  → {c['cause']}")
        print(f"  입력  : {x['text'][:70]}")
        print(f"  정답  : {x['gold_label']}  → 색인문서: {c.get('gold')}")
        print(f"  점수  : 최고청크={c['best_chunk']} 전문={c['full_doc']} 청크수={c['n_chunks']} 전체top1={x['top1']}")
        print(f"  원인  : {c['detail']}")

    print("\n" + "=" * 78)
    tally: dict[str, int] = {}
    for d in diag:
        tally[d["cause"]] = tally.get(d["cause"], 0) + 1
    for k in sorted(tally):
        print(f"  {k}: {tally[k]}건")

    OUT.write_text(json.dumps({"all": results, "failures": diag, "tally": tally},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
