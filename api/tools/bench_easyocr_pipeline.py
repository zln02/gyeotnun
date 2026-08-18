"""
easyocr 채택 검증 - 정확도 + 파이프라인 30건 (2026-08)
실행(격리 컨테이너 안): python3 tools/bench_easyocr_pipeline.py

검증 항목(사용자 지시 1순위)
  1) 텍스트 추출 정확도 : 깨끗한 표본 30건 + 실촬영 열화 시뮬레이션 30건
  2) 파이프라인 30건    : 근거검색 성공률 / 기대판단 일치율 / 정상 10건 오판(0건 절대조건)
  3) Claude Vision 경로와 같은 표에서 비교

★ services/ocr.py 등 프로덕션 코드는 호출만 하고 수정하지 않는다.
★ 판정 로직은 프로덕션 collect_evidence() 와 동일하게 재현한다
  (mode A 는 실제 함수를 그대로 호출, mode B 는 OCR 텍스트만 바꿔 같은 함수 호출).
  → 둘 다 search.collect_evidence() 를 쓰므로 '검색 계층'은 완전히 동일하고,
    차이는 오직 '입력 텍스트를 어느 OCR 이 만들었는가' 뿐이다.
"""
from __future__ import annotations

import csv
import difflib
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, "/app")

import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
CLEAN_DIR = Path("/app/tests/fixtures/ocr_eval")
HARD_DIR = Path("/app/tests/fixtures/ocr_eval_hard")
OUT_PATH = Path("/app/data/easyocr_pipeline_bench.json")
SENDER = "정부지원금 안내센터"

EXPECTED_HINT = {"정상": "needs_check", "사칭": "partially_matched", "경계": "no_source_found"}


def acc(expected: str, got: str) -> float:
    return difflib.SequenceMatcher(None, expected, got).ratio()


def run(rows, img_dir: Path, engine: str) -> dict:
    from services import local_ocr, ocr as prod_ocr, search

    per_case = []
    for row in rows:
        cid, ytype = row["case_id"], row["유형"]
        expected_text = row["평가용_제시문구"]
        path = img_dir / f"{cid}.jpg"

        t0 = time.perf_counter()
        if engine == "vision":
            r = prod_ocr.extract_from_image(path.read_bytes())
            text, status = r.text, r.status
        else:
            r = local_ocr.extract(path, provider="easyocr", sender_name=SENDER)
            text, status = r.text, r.status
        ocr_sec = time.perf_counter() - t0

        t1 = time.perf_counter()
        result = search.collect_evidence(text)     # ★ 프로덕션 판정 로직 그대로
        search_sec = time.perf_counter() - t1

        per_case.append({
            "case_id": cid, "유형": ytype, "기대판단": EXPECTED_HINT[ytype],
            "ocr_status": status, "text_accuracy": round(acc(expected_text, text), 3),
            "extracted": text[:90],
            "verdict_hint": result.verdict_hint, "refs_count": len(result.references),
            "ocr_sec": round(ocr_sec, 2), "search_sec": round(search_sec, 2),
        })
        print(f"  [{engine}/{img_dir.name}] {cid}({ytype}) acc={per_case[-1]['text_accuracy']:.2f} "
              f"hint={result.verdict_hint} refs={len(result.references)}", flush=True)

    normal = [c for c in per_case if c["유형"] == "정상"]
    wrong = [c for c in normal if c["verdict_hint"] == "partially_matched"]
    return {
        "engine": engine, "image_set": img_dir.name, "per_case": per_case,
        "avg_text_accuracy": round(sum(c["text_accuracy"] for c in per_case) / len(per_case), 3),
        "refs_found_rate": round(sum(1 for c in per_case if c["refs_count"] > 0) / len(per_case), 3),
        "expected_match_rate": round(sum(1 for c in per_case if c["verdict_hint"] == c["기대판단"]) / len(per_case), 3),
        "normal_false_positive": len(wrong),
        "normal_false_positive_ids": [c["case_id"] for c in wrong],
        "ocr_failed": sum(1 for c in per_case if c["ocr_status"] == "failed"),
        "avg_ocr_sec": round(sum(c["ocr_sec"] for c in per_case) / len(per_case), 2),
    }


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30

    report = {}
    for img_dir in (CLEAN_DIR, HARD_DIR):
        for engine in ("vision", "easyocr"):
            key = f"{engine}_{img_dir.name}"
            print(f"\n=== {key} ===", flush=True)
            report[key] = run(rows, img_dir, engine)

    Path("/app/data").mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== 요약 ===")
    hdr = f"{'조합':<28} {'추출정확도':>8} {'근거검색':>8} {'일치율':>7} {'정상오판':>8} {'OCR실패':>7}"
    print(hdr)
    for k, r in report.items():
        print(f"{k:<28} {r['avg_text_accuracy']:>8.3f} {r['refs_found_rate']:>8.3f} "
              f"{r['expected_match_rate']:>7.3f} {r['normal_false_positive']:>6}/10 {r['ocr_failed']:>7}")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
