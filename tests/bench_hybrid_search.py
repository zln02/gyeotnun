"""
곁눈(Gyeotnun) - 공식 문서 검색 3방식 벤치마크 (BM25 / 임베딩 / 하이브리드)
실행: cd tests && python3 bench_hybrid_search.py   (컨테이너 안, api/ 가 PYTHONPATH에 있어야 함)
      실제로는 docker compose exec api 로 api/ 안에서 실행한다.

corpus/곁눈_평가세트_30건.csv 의 30건에 대해 세 검색 방식을 각각 돌려 비교한다.
LLM(Claude) 을 쓰지 않는다 - 순수하게 corpus_index/embeddings/search 의 검색·매칭
계층만 측정한다(응답 시간도 이 계층만의 시간이다, dialogue 생성 시간이 아니다).

★ 평가세트의 '출처_URL' 컬럼을 정답(ground truth)으로 쓴다. 이 URL 이 실제로
  OFFICIAL_DOCS 에 색인돼 있는 케이스에서만 Recall@3 를 계산한다 - 없는 케이스를
  "못 찾음=0점"으로 넣으면 애초에 코퍼스에 없는 것을 못 찾았다고 검색 방식을
  탓하는 셈이라 부정확하다(예: B03~B10 은 정답이 도메인 홈페이지 수준이라 특정
  페이지로 색인돼 있지 않다, S01/S03 은 정답이 OFFICIAL_DOCS 가 아니라 SCAM_CASES
  쪽에 들어 있다 - 이 스크립트는 OFFICIAL_DOCS 검색 방식만 비교하므로 제외한다).
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index as ci  # noqa: E402
from services import embeddings, search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
# ★ docs/ 는 컨테이너에 마운트돼 있지 않다 - /app(=host의 api/) 밑에 썼다가
#   실행 후 `docker cp` 로 host 의 docs/evaluation/ 으로 꺼낸다.
OUT_PATH = Path("/app/data/hybrid_bench_raw.json")

# ---- 평가세트 URL -> OFFICIAL_DOCS 색인 여부로 Recall@3 계산 대상 케이스를 가른다.
GT = {}
for row in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")):
    GT[row["case_id"]] = {"url": row["출처_URL"].strip(), "유형": row["유형"], "기대판단": row["기대판단"]}

OFFICIAL_URL_TO_ID = {d.source_url: d.id for d in ci.OFFICIAL_DOCS}
for cid, info in GT.items():
    info["gt_doc_id"] = OFFICIAL_URL_TO_ID.get(info["url"])  # None 이면 이 케이스는 Recall@3 대상 제외


def recall_at_3(docs, gt_doc_id) -> "bool | None":
    if gt_doc_id is None:
        return None  # 이 케이스는 정답이 OFFICIAL_DOCS 밖이라 평가 대상이 아니다
    return any(d.id == gt_doc_id for d in docs[:3])


def bm25_search(text, limit=3):
    return ci.match_official_docs(text, limit=limit)


def embedding_search(text, limit=3):
    hits = embeddings.match_embedding_docs(text, limit=limit)
    return [d for _score, d in hits]


def hybrid_search(text, limit=3, w_bm25=1.0, w_emb=1.0):
    return search.match_official_docs_hybrid(text, limit=limit, weight_bm25=w_bm25, weight_embedding=w_emb)


def full_verdict(text: str, official_docs: list) -> dict:
    """search.collect_evidence() 와 같은 판정 로직을, official 검색 방식만 바꿔서 재현한다.
    SCAM_CASES/detect_signals 는 세 방식 모두 동일하게 적용한다(변수를 official 검색
    방식 하나로만 좁히기 위해서)."""
    signals = search.detect_signals(text)
    matched_evidence = ci.match_evidence(text)
    matched_scam = ci.match_scam_cases(text)

    for doc in official_docs:
        signals.append({"key": "official_source_found", "severity": "info"})
    for doc in matched_evidence:
        signals.append({"key": "official_source_found", "severity": "info"})
    for case in matched_scam:
        signals.append({"key": "similar_scam_case", "severity": "attention"})

    refs = official_docs or matched_evidence or matched_scam  # 존재 여부만 필요
    has_refs = bool(official_docs) or bool(matched_evidence) or bool(matched_scam)
    risky = any(s["severity"] == "attention" for s in signals)

    if not has_refs:
        hint = "no_source_found"
    elif risky:
        hint = "partially_matched"
    else:
        hint = "needs_check"
    return {"verdict_hint": hint, "refs_count": (len(official_docs) + len(matched_evidence) + len(matched_scam))}


MAPPING = {"정상": "needs_check", "사칭": "partially_matched", "경계": "no_source_found"}


def run_mode(mode_name: str, search_fn) -> dict:
    rows = list(GT.items())
    results = []
    for case_id, info in rows:
        text_row = next(r for r in csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")) if r["case_id"] == case_id)
        text = text_row["평가용_제시문구"]

        t0 = time.time()
        docs = search_fn(text)
        dt = time.time() - t0

        recall = recall_at_3(docs, info["gt_doc_id"])
        verdict = full_verdict(text, docs)

        results.append({
            "case_id": case_id, "유형": info["유형"], "기대판단": info["기대판단"],
            "recall_at_3": recall, "verdict_hint": verdict["verdict_hint"],
            "refs_count": verdict["refs_count"], "elapsed_sec": round(dt, 4),
        })

    n = len(results)
    recall_eligible = [r for r in results if r["recall_at_3"] is not None]
    recall_rate = sum(1 for r in recall_eligible if r["recall_at_3"]) / len(recall_eligible) if recall_eligible else None
    refs_found = sum(1 for r in results if r["refs_count"] > 0)
    match_rate = sum(1 for r in results if r["verdict_hint"] == MAPPING.get(r["유형"])) / n
    normal_fp = sum(1 for r in results if r["유형"] == "정상" and r["verdict_hint"] == "partially_matched")
    avg_time = sum(r["elapsed_sec"] for r in results) / n

    return {
        "mode": mode_name,
        "recall_at_3": round(recall_rate, 3) if recall_rate is not None else None,
        "recall_at_3_n": len(recall_eligible),
        "refs_found_rate": round(refs_found / n, 3),
        "expected_match_rate": round(match_rate, 3),
        "normal_false_positive": normal_fp,
        "avg_elapsed_sec": round(avg_time, 4),
        "cases": results,
    }


def main():
    print(f"Recall@3 평가 대상: {sum(1 for v in GT.values() if v['gt_doc_id'])}/30건 "
          f"(정답 URL 이 OFFICIAL_DOCS 에 색인된 케이스만)\n")

    print("=== BM25 단독 ===")
    bm25_result = run_mode("bm25", bm25_search)
    print(json.dumps({k: v for k, v in bm25_result.items() if k != "cases"}, ensure_ascii=False, indent=2))

    print("\n=== 임베딩 단독 ===")
    emb_result = run_mode("embedding", embedding_search)
    print(json.dumps({k: v for k, v in emb_result.items() if k != "cases"}, ensure_ascii=False, indent=2))

    print("\n=== 하이브리드(RRF, 1:1) ===")
    hybrid_result = run_mode("hybrid_1_1", lambda t: hybrid_search(t, w_bm25=1.0, w_emb=1.0))
    print(json.dumps({k: v for k, v in hybrid_result.items() if k != "cases"}, ensure_ascii=False, indent=2))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps([bm25_result, emb_result, hybrid_result], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n원본 저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
