"""
로컬 OCR·임베딩 3조합(A/B/C) 벤치마크 (2026-08, 8/2 멘토 지적 대응)
실행(격리 컨테이너 안에서만):
    python3 tools/bench_local_pipeline.py                 # 전체 벤치마크
    python3 tools/bench_local_pipeline.py memprobe ocr tesseract     # 메모리 단독 측정
    python3 tools/bench_local_pipeline.py memprobe emb e5-small

  A. 현재        : 상용 OCR(Claude Vision) + 상용 임베딩(Upstage)
  B. 로컬 OCR    : 로컬 OCR + 상용 임베딩(Upstage)
  C. 완전 로컬   : 로컬 OCR + 로컬 임베딩          ← 이미지·텍스트 모두 외부 미전송

★ 프로덕션 코드(services/ocr.py, embeddings.py, search.py)를 수정하지 않는다.
  A 조합은 실제 collect_evidence() 를 그대로 호출하고, B·C 조합은 '공식문서 검색'
  부분만 갈아 끼운 뒤 나머지 판정 로직(refs 구성 → risky → confident → hint)은
  프로덕션과 문자 그대로 같은 순서로 재현한다. 아래 evaluate_pipeline() 의
  주석 참고 - 이 부분이 어긋나면 A/B/C 비교 자체가 무의미해진다.

★ 임계값을 두 개 쓰는 이유(중요): 프로덕션 임베딩은
    EMBEDDING_MIN_SCORE(0.45)      = 이 밑이면 근거로 아예 보여주지 않는다(잡음 바닥)
    CONFIDENT_MATCH_THRESHOLD(0.52)= 이 밑이면 근거는 보여주되 '확인됨'으로 단정 안 한다
  두 개를 함께 쓴다. 로컬 임베딩에도 같은 구조로 두 임계값을 실측 보정해서 적용한다.
  (하나만 쓰면 어떤 입력에도 최근접 문서가 항상 나와 '근거 검색 성공률'이
   가짜로 100% 가 된다 - 상용 임베딩 도입 때 실제로 겪었던 함정이다.)

측정 지표
  - 텍스트 추출 정확도 : difflib.SequenceMatcher(정답 vs 추출) 비율
  - 근거 검색 성공률   : references 가 1건 이상인 비율
  - 기대판단 일치율    : verdict_hint 가 기대판단과 일치하는 비율
  - 정상 10건 오판     : 정상 케이스 중 partially_matched 로 나온 건수(절대 0 이어야 함)
  - 응답 시간          : OCR + 검색 합산(초)
  - 메모리 사용량      : 모델별 피크 RSS(별도 프로세스에서 단독 측정 - memprobe)
"""
from __future__ import annotations

import csv
import difflib
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
IMG_DIR = Path("/app/tests/fixtures/ocr_eval")
OUT_PATH = Path("/app/data/local_pipeline_bench_raw.json")

SENDER_NAME = "정부지원금 안내센터"

# 잡음 바닥(min_score) 보정용 - 공공 복지 문서와 아무 관련 없는 문장들.
# 이 문장들에서 나오는 최고 유사도가 '아무 근거도 없을 때 나오는 점수'다.
JUNK_PROBES = [
    "어제 저녁에 김치찌개를 끓여 먹었는데 조금 짰다",
    "고양이가 소파 위에서 하루 종일 잠만 잔다",
    "이번 주말에 자전거를 타고 한강에 다녀올 생각이다",
    "빨래를 널었는데 갑자기 비가 쏟아져서 다 젖었다",
    "축구 경기가 연장전까지 가서 밤늦게 끝났다",
]


def peak_rss_mb() -> float:
    """이 프로세스의 피크 RSS(MB). ru_maxrss 는 '현재'가 아니라 '최대치'다 -
    모델 로드처럼 한 번 크게 잡는 사용량을 재는 데 적합하다."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def text_accuracy(expected: str, got: str) -> float:
    if not expected and not got:
        return 1.0
    return difflib.SequenceMatcher(None, expected, got).ratio()


def load_rows() -> list[dict]:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건"
    return rows


# ============================================================ 메모리 단독 측정(하위 프로세스)
def memprobe(kind: str, provider: str) -> None:
    """모델 하나만 올려서 피크 RSS 를 잰다. 한 프로세스에서 여러 모델을 연달아
    올리면 앞 모델 메모리가 남아 뒤 모델 측정치가 오염되므로, 반드시 이 함수를
    별도 프로세스로 띄워서 측정한다."""
    base = peak_rss_mb()
    if kind == "ocr":
        from services import local_ocr
        img = sorted(IMG_DIR.glob("*.jpg"))[0]
        local_ocr.extract(img, provider=provider, sender_name=SENDER_NAME)
    else:
        from services import local_embeddings
        local_embeddings.embed_query("기초연금 신청 대상", provider=provider)
    print(json.dumps({"kind": kind, "provider": provider,
                      "baseline_mb": round(base, 1), "peak_rss_mb": round(peak_rss_mb(), 1),
                      "model_mb": round(peak_rss_mb() - base, 1)}))


def run_memprobe(kind: str, provider: str) -> dict:
    out = subprocess.run(
        [sys.executable, __file__, "memprobe", kind, provider],
        capture_output=True, text=True, cwd="/app",
    )
    for line in out.stdout.strip().splitlines()[::-1]:
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return {"kind": kind, "provider": provider, "error": out.stderr[-400:]}


# ============================================================ 후보 비교
def compare_ocr_candidates(rows: list[dict]) -> dict:
    from services import local_ocr

    sample = rows[:8]   # 후보 선정은 8건 표본으로 빠르게(최종 비교는 30건 전수)
    results = {}
    for provider in ("tesseract", "easyocr"):
        accs, times = [], []
        for row in sample:
            img_path = IMG_DIR / f"{row['case_id']}.jpg"
            r = local_ocr.extract(img_path, provider=provider, sender_name=SENDER_NAME)
            accs.append(text_accuracy(row["평가용_제시문구"], r.text))
            times.append(r.elapsed_sec)
        mem = run_memprobe("ocr", provider)
        results[provider] = {
            "avg_accuracy": round(sum(accs) / len(accs), 3),
            "avg_time_sec": round(sum(times) / len(times), 3),
            "peak_rss_mb": mem.get("peak_rss_mb"),
            "sample_n": len(sample),
        }
        print(f"[OCR 후보] {provider}: 정확도={results[provider]['avg_accuracy']} "
              f"시간={results[provider]['avg_time_sec']}s 피크RSS={results[provider]['peak_rss_mb']}MB")
    return results


def compare_embedding_candidates() -> dict:
    """후보별로 '정상 문구 vs 잡음 문구'의 유사도 분리도를 본다 - 단순히 유사도가
    높은 모델이 좋은 게 아니라, 진짜 관련 문서와 무관한 문서의 점수 차이가 벌어지는
    모델이 좋다(임계값을 놓을 자리가 생긴다)."""
    from services import corpus_index, local_embeddings

    sample_chunks = corpus_index._OFFICIAL_CHUNKS[:300]
    real_queries = [
        "기초연금 신청 대상과 금액이 궁금합니다",
        "장애인 일자리 지원 신청 방법",
        "노후준비서비스 상담 안내",
    ]
    results = {}
    for provider in ("e5-small", "ko-sroberta"):
        t0 = time.perf_counter()
        vecs = local_embeddings.embed_passages([c.text for c in sample_chunks], provider=provider)
        index_time = time.perf_counter() - t0

        real_top = [float((vecs @ local_embeddings.embed_query(q, provider=provider)).max()) for q in real_queries]
        junk_top = [float((vecs @ local_embeddings.embed_query(q, provider=provider)).max()) for q in JUNK_PROBES]
        separation = min(real_top) - max(junk_top)
        mem = run_memprobe("emb", provider)
        results[provider] = {
            "sample_index_sec": round(index_time, 2),
            "sample_chunks": len(sample_chunks),
            "peak_rss_mb": mem.get("peak_rss_mb"),
            "real_query_top_sims": [round(x, 3) for x in real_top],
            "junk_query_top_sims": [round(x, 3) for x in junk_top],
            "separation": round(separation, 3),
        }
        print(f"[임베딩 후보] {provider}: 색인{len(sample_chunks)}건={results[provider]['sample_index_sec']}s "
              f"피크RSS={results[provider]['peak_rss_mb']}MB 실제최소={min(real_top):.3f} "
              f"잡음최대={max(junk_top):.3f} 분리도={separation:.3f}")
    return results


# ============================================================ 로컬 검색 (프로덕션 구조 재현)
def local_official_search(text: str, local_index, provider: str, min_score: float,
                          confident_threshold: float, limit: int = 2):
    """services/embeddings.py match_embedding_docs() + search.py 의 확신 판정을
    로컬 모델로 그대로 재현한다. 반환: (matched_docs, top_score, confident)"""
    from services import corpus_index, local_embeddings

    qv = local_embeddings.embed_query(text, provider=provider)
    ranked = local_index.search_docs(qv, limit=limit, min_score=min_score)
    docs = [corpus_index._OFFICIAL_DOCS_BY_ID[rid] for _s, rid in ranked
            if rid in corpus_index._OFFICIAL_DOCS_BY_ID]
    top_score = ranked[0][0] if ranked else None
    confident = top_score is not None and top_score >= confident_threshold
    return docs, top_score, confident


EXPECTED_HINT = {"정상": "needs_check", "사칭": "partially_matched", "경계": "no_source_found"}


def evaluate_pipeline(text: str, mode: str, local_index=None, local_provider=None,
                      local_min_score=None, local_confident=None):
    """★ 프로덕션 collect_evidence() 와 판정 로직이 100% 같아야 한다.
    A 는 실제 함수를 호출하고, B·C 는 '공식문서 검색'만 바꾸고 나머지는 아래처럼
    같은 순서로 재현한다(refs 는 to_reference()+_dedup_refs 까지 동일하게 구성 -
    _dedup_refs 는 URL 없는 근거를 버리므로 개수를 단순 합산하면 refs==0 판정이
    어긋날 수 있다)."""
    from services import corpus_index, search

    if mode == "A":
        result = search.collect_evidence(text)
        return result.verdict_hint, len(result.references)

    signals = search.detect_signals(text)
    matched_evidence = corpus_index.match_evidence(text)
    matched_scam = corpus_index.match_scam_cases(text)
    legacy_refs = search.search_corpus(text)

    if mode == "B":   # 로컬 OCR + 상용(Upstage) 임베딩 = 프로덕션 검색 그대로
        matched_official, official_mode, official_top_score = search.match_official_docs_safe(text)
        if official_mode == "embedding":
            official_confident = (official_top_score is not None
                                  and official_top_score >= search.CONFIDENT_MATCH_THRESHOLD)
        else:
            official_confident = bool(matched_official)
    else:             # mode == "C" : 로컬 OCR + 로컬 임베딩
        matched_official, official_top_score, official_confident = local_official_search(
            text, local_index, local_provider, local_min_score, local_confident
        )

    for _doc in matched_official:
        signals.append({"key": "official_source_found", "severity": "info"})
    for _doc in matched_evidence:
        signals.append({"key": "official_source_found", "severity": "info"})
    for _case in matched_scam:
        signals.append({"key": "similar_scam_case", "severity": "attention"})

    refs = search._dedup_refs(
        [d.to_reference() for d in matched_official]
        + [d.to_reference() for d in matched_evidence]
        + [c.to_reference() for c in matched_scam]
        + legacy_refs
    )

    risky = any(s["severity"] == "attention" for s in signals)
    has_confident_source = official_confident or bool(matched_evidence) or bool(matched_scam)

    if not refs:
        hint = "no_source_found"
    elif risky:
        hint = "partially_matched"
    elif not has_confident_source:
        hint = "no_source_found"
    else:
        hint = "needs_check"
    return hint, len(refs)


def run_combo(rows, mode, ocr_provider=None, local_index=None, local_provider=None,
              local_min_score=None, local_confident=None) -> dict:
    from services import local_ocr, ocr as prod_ocr

    per_case = []
    for row in rows:
        case_id, ytype = row["case_id"], row["유형"]
        expected_text = row["평가용_제시문구"]
        img_path = IMG_DIR / f"{case_id}.jpg"

        t0 = time.perf_counter()
        if mode == "A":
            r = prod_ocr.extract_from_image(img_path.read_bytes())
        else:
            r = local_ocr.extract(img_path, provider=ocr_provider, sender_name=SENDER_NAME)
        extracted_text, ocr_status = r.text, r.status
        ocr_elapsed = time.perf_counter() - t0

        acc = text_accuracy(expected_text, extracted_text)

        t1 = time.perf_counter()
        # ★ OCR 이 실패해 빈 문자열이 나오면 그대로 흘려보낸다 - "인식 실패가 뒷단
        #   판정에 어떤 영향을 주는지"까지 포함해서 보는 게 이 실험의 목적이다.
        hint, refs_count = evaluate_pipeline(
            extracted_text, mode, local_index=local_index, local_provider=local_provider,
            local_min_score=local_min_score, local_confident=local_confident,
        )
        search_elapsed = time.perf_counter() - t1

        per_case.append({
            "case_id": case_id, "유형": ytype, "기대판단": EXPECTED_HINT[ytype],
            "ocr_status": ocr_status, "text_accuracy": round(acc, 3),
            "extracted_preview": extracted_text[:80],
            "verdict_hint": hint, "refs_count": refs_count,
            "ocr_sec": round(ocr_elapsed, 3), "search_sec": round(search_elapsed, 3),
        })
        print(f"  [{mode}] {case_id}({ytype}) acc={acc:.2f} hint={hint} refs={refs_count} "
              f"ocr={ocr_elapsed:.2f}s search={search_elapsed:.2f}s")

    normal = [c for c in per_case if c["유형"] == "정상"]
    normal_wrong = [c for c in normal if c["verdict_hint"] == "partially_matched"]
    return {
        "mode": mode, "per_case": per_case,
        "avg_text_accuracy": round(sum(c["text_accuracy"] for c in per_case) / len(per_case), 3),
        "refs_found_rate": round(sum(1 for c in per_case if c["refs_count"] > 0) / len(per_case), 3),
        "expected_match_rate": round(sum(1 for c in per_case if c["verdict_hint"] == c["기대판단"]) / len(per_case), 3),
        "normal_10_false_positive": len(normal_wrong),
        "normal_10_false_positive_ids": [c["case_id"] for c in normal_wrong],
        "avg_time_sec": round(sum(c["ocr_sec"] + c["search_sec"] for c in per_case) / len(per_case), 3),
        "ocr_failed_count": sum(1 for c in per_case if c["ocr_status"] == "failed"),
    }


def calibrate_local_thresholds(rows, local_index, provider) -> dict:
    """프로덕션과 같은 방식으로 두 임계값을 실측 보정한다.
      min_score  : 잡음 문장 최고점 vs 정상 케이스 최저점 사이
      confident  : 경계 케이스 최고점 vs 정상 케이스 최저점 사이
    """
    from services import local_embeddings

    def top_sim(text: str) -> float:
        qv = local_embeddings.embed_query(text, provider=provider)
        ranked = local_index.search_docs(qv, limit=1, min_score=0.0)
        return ranked[0][0] if ranked else 0.0

    junk = [top_sim(t) for t in JUNK_PROBES]
    normal = [top_sim(r["평가용_제시문구"]) for r in rows if r["유형"] == "정상"]
    boundary = [top_sim(r["평가용_제시문구"]) for r in rows if r["유형"] == "경계"]

    junk_max, normal_min, boundary_max = max(junk), min(normal), max(boundary)
    min_score = (junk_max + normal_min) / 2 if junk_max < normal_min else junk_max
    confident = (boundary_max + normal_min) / 2 if boundary_max < normal_min else normal_min

    print(f"[임계값 보정] 잡음최대={junk_max:.4f} 정상최소={normal_min:.4f} 경계최대={boundary_max:.4f}")
    print(f"             -> min_score={min_score:.4f} confident={confident:.4f}")
    if junk_max >= normal_min:
        print("             ⚠ 잡음과 정상이 겹친다 - 임계값으로 분리할 수 없는 상태")
    if boundary_max >= normal_min:
        print("             ⚠ 경계와 정상이 겹친다 - 확신 임계값으로 분리할 수 없는 상태")

    return {
        "junk_max": round(junk_max, 4), "normal_min": round(normal_min, 4),
        "boundary_max": round(boundary_max, 4),
        "min_score": round(min_score, 4), "confident": round(confident, 4),
        "junk_sims": [round(x, 4) for x in junk],
        "normal_sims": [round(x, 4) for x in normal],
        "boundary_sims": [round(x, 4) for x in boundary],
        "separable_junk_vs_normal": junk_max < normal_min,
        "separable_boundary_vs_normal": boundary_max < normal_min,
    }


def main() -> None:
    rows = load_rows()
    report: dict = {}

    print("\n=== 0) OCR 후보 비교(8건 표본) ===")
    report["ocr_candidates"] = compare_ocr_candidates(rows)
    ocr_winner = max(report["ocr_candidates"], key=lambda p: report["ocr_candidates"][p]["avg_accuracy"])
    report["ocr_winner"] = ocr_winner
    print(f"-> OCR 후보 선정: {ocr_winner}")

    print("\n=== 0) 임베딩 후보 비교(300청크 표본) ===")
    report["embedding_candidates"] = compare_embedding_candidates()
    emb_winner = max(report["embedding_candidates"], key=lambda p: report["embedding_candidates"][p]["separation"])
    report["embedding_winner"] = emb_winner
    print(f"-> 임베딩 후보 선정: {emb_winner} (잡음 대비 분리도 기준)")

    from services import corpus_index, local_embeddings
    n_chunks = len(corpus_index._OFFICIAL_CHUNKS)
    print(f"\n=== 1) 로컬 임베딩({emb_winner}) 전체 색인 {n_chunks}청크 ===")
    t0 = time.perf_counter()
    local_embeddings.build_index(corpus_index._OFFICIAL_CHUNKS, provider=emb_winner)
    report["local_index_build_sec"] = round(time.perf_counter() - t0, 1)
    local_index = local_embeddings.LocalIndex.load(emb_winner)
    print(f"색인 완료: {report['local_index_build_sec']}초")

    print("\n=== 1-1) 로컬 임베딩 임계값 실측 보정 ===")
    report["local_thresholds"] = calibrate_local_thresholds(rows, local_index, emb_winner)

    print("\n=== 2) A) 현재(상용 OCR + 상용 임베딩) ===")
    report["A"] = run_combo(rows, "A")

    print("\n=== 2) B) 로컬 OCR + 상용 임베딩 ===")
    report["B"] = run_combo(rows, "B", ocr_provider=ocr_winner)

    print("\n=== 2) C) 로컬 OCR + 로컬 임베딩(완전 로컬) ===")
    report["C"] = run_combo(rows, "C", ocr_provider=ocr_winner, local_index=local_index,
                            local_provider=emb_winner,
                            local_min_score=report["local_thresholds"]["min_score"],
                            local_confident=report["local_thresholds"]["confident"])

    report["bench_process_peak_rss_mb"] = round(peak_rss_mb(), 1)

    Path("/app/data").mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_PATH}")

    print("\n=== 요약 ===")
    for mode in ("A", "B", "C"):
        r = report[mode]
        print(f"{mode}: 추출정확도={r['avg_text_accuracy']} 근거검색성공률={r['refs_found_rate']} "
              f"기대판단일치율={r['expected_match_rate']} 정상오판={r['normal_10_false_positive']}/10 "
              f"평균응답시간={r['avg_time_sec']}s OCR실패={r['ocr_failed_count']}")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "memprobe":
        memprobe(sys.argv[2], sys.argv[3])
    else:
        main()
