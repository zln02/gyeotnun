"""
로컬 임베딩 후보 실측 비교 (2026-08-03)
실행(격리 컨테이너 안): python3 tools/bench_local_embeddings.py [후보...]
  예) python3 tools/bench_local_embeddings.py bge-m3 bge-m3-ko e5-large

후보(우선순위 순)
  bge-m3     BAAI/bge-m3            MIT. 한국어 검색 벤치마크 상위. ★ dense 만 사용
  bge-m3-ko  dragonkue/BGE-m3-ko    위를 한국어 파인튜닝(같은 아키텍처)
  e5-large   intfloat/multilingual-e5-large   ★ query:/passage: 접두어 필수
  koe5       nlpai-lab/KoE5                   ★ 접두어 필수

★ sparse·colbert 는 쓰지 않는다. 하이브리드는 이미 실측으로 기각됐고
  (docs/evaluation/hybrid_search_report.md), 임베딩 단독이 더 나았다.
  sentence-transformers 로 로드하면 dense 표현만 나오므로 이 조건이 자동으로 지켜진다.

★ 후보마다 인덱스를 새로 만든다(local_index_{provider}.npz). 모델이 다르면 벡터
  공간이 달라서 기존 인덱스를 재사용하면 결과가 무의미하다. 파일 메타데이터에
  provider·모델명·차원수를 기록하고 로드 시 검증한다(services/local_embeddings.py).

★ services/embeddings.py, search.py 의 기본 경로는 건드리지 않는다. 여기서는
  '공식문서 검색' 부분만 로컬 모델로 갈아 끼우고 나머지 판정 로직은 프로덕션과
  동일하게 재현한다.

지표: Recall@3 / 근거검색 성공률 / 기대판단 일치율 / 정상10건 오판(절대조건) /
      질의 1건당 응답시간 / 전체 인덱싱 시간 / 상주 메모리 / 인덱스 파일 크기
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# ★ 경로 자동 판별(2026-08-04): 격리 컨테이너(/app, /corpus)와 맥·리눅스 로컬
#   체크아웃(<repo>/api, <repo>/corpus) 양쪽에서 같은 스크립트가 돌아야 한다.
#   컨테이너에서는 /app 이 존재하고, 로컬에서는 이 파일 기준 상대경로를 쓴다.
if Path("/app/services").is_dir():                 # 격리 컨테이너
    API_DIR, CORPUS_DIR = Path("/app"), Path("/corpus")
else:                                              # 맥/리눅스 로컬 체크아웃
    API_DIR = Path(__file__).resolve().parents[1]   # <repo>/api
    CORPUS_DIR = API_DIR.parent / "corpus"
sys.path.insert(0, str(API_DIR))

CSV_PATH = CORPUS_DIR / "곁눈_평가세트_30건.csv"
OUT_PATH = API_DIR / "data" / "local_embeddings_bench.json"

EXPECTED_HINT = {"정상": "needs_check", "사칭": "partially_matched", "경계": "no_source_found"}

# 잡음 바닥(min_score) 보정용 - 공공 복지 문서와 무관한 문장들
JUNK_PROBES = [
    "어제 저녁에 김치찌개를 끓여 먹었는데 조금 짰다",
    "고양이가 소파 위에서 하루 종일 잠만 잔다",
    "이번 주말에 자전거를 타고 한강에 다녀올 생각이다",
    "빨래를 널었는데 갑자기 비가 쏟아져서 다 젖었다",
    "축구 경기가 연장전까지 가서 밤늦게 끝났다",
]


def rss_mb() -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return float(line.split()[1]) / 1024
    return 0.0


def load_rows() -> list[dict]:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건"
    return rows


def calibrate(rows, index, provider) -> dict:
    """프로덕션과 같은 방식으로 두 임계값을 실측 보정한다.
      min_score : 잡음 문장 최고점 vs 정상 케이스 최저점 사이 (근거로 보여줄 최저선)
      confident : 경계 케이스 최고점 vs 정상 케이스 최저점 사이 (확인됨으로 볼 최저선)
    모델마다 유사도 분포가 달라서, 임계값을 고정하면 비교가 불공정해진다."""
    from services import local_embeddings

    def top(text: str) -> float:
        qv = local_embeddings.embed_query(text, provider=provider)
        r = index.search_docs(qv, limit=1, min_score=0.0)
        return r[0][0] if r else 0.0

    junk = [top(t) for t in JUNK_PROBES]
    normal = [top(r["평가용_제시문구"]) for r in rows if r["유형"] == "정상"]
    boundary = [top(r["평가용_제시문구"]) for r in rows if r["유형"] == "경계"]
    jmax, nmin, bmax = max(junk), min(normal), max(boundary)
    return {
        "junk_max": round(jmax, 4), "normal_min": round(nmin, 4), "boundary_max": round(bmax, 4),
        "min_score": round((jmax + nmin) / 2 if jmax < nmin else jmax, 4),
        "confident": round((bmax + nmin) / 2 if bmax < nmin else nmin, 4),
        "separable_junk": jmax < nmin, "separable_boundary": bmax < nmin,
    }


def evaluate(rows, index, provider, th) -> dict:
    """프로덕션 collect_evidence() 의 판정 로직을 그대로 재현하되, 공식문서 검색만
    로컬 모델로 바꾼다(services/search.py 는 수정하지 않는다)."""
    from services import corpus_index, local_embeddings, search

    per_case, latencies = [], []
    recall_hit = recall_total = 0
    _INDEXED_URLS = {d.source_url for d in corpus_index.OFFICIAL_DOCS if d.source_url}

    for row in rows:
        text = row["평가용_제시문구"]
        gt_url = (row.get("출처_URL") or "").strip()

        t0 = time.perf_counter()
        qv = local_embeddings.embed_query(text, provider=provider)
        ranked = index.search_docs(qv, limit=3, min_score=th["min_score"])
        latency = time.perf_counter() - t0
        latencies.append(latency)

        docs = [corpus_index._OFFICIAL_DOCS_BY_ID[rid] for _s, rid in ranked
                if rid in corpus_index._OFFICIAL_DOCS_BY_ID]

        # Recall@3 - 정답 URL 이 OFFICIAL_DOCS 에 실제로 색인된 케이스만 분모로 센다
        # (OfficialDoc 의 URL 필드명은 source_url 이다)
        if gt_url and gt_url in _INDEXED_URLS:
            recall_total += 1
            if any(d.source_url == gt_url for d in docs[:3]):
                recall_hit += 1

        top2 = docs[:2]
        top_score = ranked[0][0] if ranked else None
        official_confident = top_score is not None and top_score >= th["confident"]

        signals = search.detect_signals(text)
        matched_evidence = corpus_index.match_evidence(text)
        matched_scam = corpus_index.match_scam_cases(text)
        legacy = search.search_corpus(text)

        for _ in top2:
            signals.append({"key": "official_source_found", "severity": "info"})
        for _ in matched_evidence:
            signals.append({"key": "official_source_found", "severity": "info"})
        for _ in matched_scam:
            signals.append({"key": "similar_scam_case", "severity": "attention"})

        refs = search._dedup_refs(
            [d.to_reference() for d in top2]
            + [d.to_reference() for d in matched_evidence]
            + [c.to_reference() for c in matched_scam] + legacy
        )
        risky = any(s["severity"] == "attention" for s in signals)
        confident_src = official_confident or bool(matched_evidence) or bool(matched_scam)

        if not refs:
            hint = "no_source_found"
        elif risky:
            hint = "partially_matched"
        elif not confident_src:
            hint = "no_source_found"
        else:
            hint = "needs_check"

        per_case.append({
            "case_id": row["case_id"], "유형": row["유형"], "기대판단": EXPECTED_HINT[row["유형"]],
            "verdict_hint": hint, "refs_count": len(refs),
            "top_score": round(top_score, 4) if top_score is not None else None,
            "latency_ms": round(latency * 1000, 1),
        })

    normal = [c for c in per_case if c["유형"] == "정상"]
    fp = [c for c in normal if c["verdict_hint"] == "partially_matched"]
    return {
        "per_case": per_case,
        "recall_at_3": round(recall_hit / recall_total, 3) if recall_total else None,
        "recall_basis": f"{recall_hit}/{recall_total}",
        "refs_found_rate": round(sum(1 for c in per_case if c["refs_count"] > 0) / len(per_case), 3),
        "expected_match_rate": round(sum(1 for c in per_case if c["verdict_hint"] == c["기대판단"]) / len(per_case), 3),
        "normal_false_positive": len(fp),
        "normal_false_positive_ids": [c["case_id"] for c in fp],
        "latency_ms_avg": round(statistics.mean(latencies) * 1000, 1),
        "latency_ms_median": round(statistics.median(latencies) * 1000, 1),
        "latency_ms_max": round(max(latencies) * 1000, 1),
    }


def run_provider(rows, provider: str) -> dict:
    from services import corpus_index, local_embeddings

    print(f"\n{'='*60}\n=== {provider} ({local_embeddings._MODEL_NAMES[provider]}) ===", flush=True)
    base_rss = rss_mb()

    t0 = time.perf_counter()
    local_embeddings._get_model(provider)          # 모델 로드만 먼저 재기
    load_sec = time.perf_counter() - t0
    loaded_rss = rss_mb()
    print(f"  모델 로드 {load_sec:.1f}s, 상주 {loaded_rss:.0f}MB (+{loaded_rss-base_rss:.0f}MB)", flush=True)

    chunks = corpus_index._OFFICIAL_CHUNKS
    t1 = time.perf_counter()
    path = local_embeddings.build_index(chunks, provider=provider)
    index_sec = time.perf_counter() - t1
    size_mb = path.stat().st_size / 1024 / 1024
    print(f"  인덱싱 {len(chunks)}청크 {index_sec:.1f}s, 파일 {size_mb:.1f}MB", flush=True)

    index = local_embeddings.LocalIndex.load(provider)
    if not index.ready:
        return {"provider": provider, "error": "인덱스 로드 실패(메타 불일치)"}

    th = calibrate(rows, index, provider)
    print(f"  임계값 보정: min_score={th['min_score']} confident={th['confident']} "
          f"(잡음max={th['junk_max']} 정상min={th['normal_min']} 경계max={th['boundary_max']})", flush=True)

    res = evaluate(rows, index, provider, th)
    res.update({
        "provider": provider, "model": local_embeddings._MODEL_NAMES[provider],
        "dimensions": int(index.vectors.shape[1]),
        "model_load_sec": round(load_sec, 1),
        "index_build_sec": round(index_sec, 1),
        "index_file_mb": round(size_mb, 1),
        "rss_after_load_mb": round(loaded_rss, 1),
        "rss_peak_mb": round(rss_mb(), 1),
        "thresholds": th,
    })
    print(f"  >> Recall@3={res['recall_at_3']} 근거검색={res['refs_found_rate']} "
          f"일치율={res['expected_match_rate']} 정상오판={res['normal_false_positive']}/10 "
          f"응답 평균={res['latency_ms_avg']}ms", flush=True)
    return res


def main() -> None:
    providers = sys.argv[1:] or ["bge-m3"]
    rows = load_rows()
    report = {}
    if OUT_PATH.exists():
        report = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    for p in providers:
        try:
            report[p] = run_provider(rows, p)
        except Exception as e:  # noqa: BLE001 - 실패한 후보도 원인을 남긴다
            import traceback
            report[p] = {"provider": p, "error": f"{type(e).__name__}: {e}",
                         "traceback": traceback.format_exc()[-800:]}
            print(f"  !! {p} 실패: {type(e).__name__}: {e}", flush=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")

    print(f"\n{'후보':<12}{'Recall@3':>9}{'근거검색':>9}{'일치율':>8}{'정상오판':>9}{'응답ms':>8}{'색인s':>8}{'상주MB':>8}")
    for p, r in report.items():
        if "error" in r:
            print(f"{p:<12}  실패: {r['error'][:60]}")
            continue
        print(f"{p:<12}{str(r['recall_at_3']):>9}{r['refs_found_rate']:>9.3f}{r['expected_match_rate']:>8.3f}"
              f"{r['normal_false_positive']:>7}/10{r['latency_ms_avg']:>8.1f}{r['index_build_sec']:>8.0f}"
              f"{r['rss_after_load_mb']:>8.0f}")


if __name__ == "__main__":
    main()
