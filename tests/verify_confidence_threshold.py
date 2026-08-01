"""
CONFIDENT_MATCH_THRESHOLD 도입 후 30건 재검증 (검색·매칭 계층만, LLM 미사용).

실행 위치: api 컨테이너 안 (services.search, services.embeddings 등 의존성이 거기 있음)
    docker compose exec api python /app/../tests/verify_confidence_threshold.py
    (또는 tests/ 를 컨테이너에 마운트하지 않았다면 api/tests/ 밑에 임시로 복사해 실행)

목적: 사용자 지시 5번 - "경계 케이스의 '확인 불가' 판정을 검색 성공 여부와 분리하라"
      를 실제로 배선한 뒤, 절대조건 "정상 오판 0건"이 유지되는지, 그리고
      "경계 확인불가율" 이 BM25 기준(1/10) 대비 개선됐는지 collect_evidence() 를
      직접 호출해(HTTP/LLM 없이) 확인한다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건"

    results = []
    for row in rows:
        text = row["평가용_제시문구"]
        result = search.collect_evidence(text)
        _, official_mode, official_top_score = search.match_official_docs_safe(text)
        results.append({
            "case_id": row["case_id"],
            "유형": row["유형"],
            "기대판단": row["기대판단"],
            "verdict_hint": result.verdict_hint,
            "references_count": len(result.references),
            "official_mode": official_mode,
            "official_top_score": official_top_score,
        })

    by_type: dict[str, list[dict]] = {}
    for r in results:
        by_type.setdefault(r["유형"], []).append(r)

    print("=== 유형별 verdict_hint 분포 ===")
    for t, rs in by_type.items():
        dist: dict[str, int] = {}
        for r in rs:
            dist[r["verdict_hint"]] = dist.get(r["verdict_hint"], 0) + 1
        print(f"{t} ({len(rs)}건): {dist}")

    print("\n=== 정상 10건 상세 (절대조건: partially_matched 0건) ===")
    normal = by_type.get("정상", [])
    normal_bad = [r for r in normal if r["verdict_hint"] == "partially_matched"]
    for r in normal:
        print(f"  {r['case_id']}: {r['verdict_hint']} (refs={r['references_count']})")
    print(f"  -> partially_matched(오판) 건수: {len(normal_bad)}/{len(normal)}")

    print("\n=== 경계 10건 상세 (목표: no_source_found >= 1, BM25 기준) ===")
    boundary = by_type.get("경계", [])
    boundary_no_source = [r for r in boundary if r["verdict_hint"] == "no_source_found"]
    for r in boundary:
        print(f"  {r['case_id']}: {r['verdict_hint']} (refs={r['references_count']})")
    print(f"  -> no_source_found(확인불가) 건수: {len(boundary_no_source)}/{len(boundary)}")

    out_path = Path("/app/data/verify_confidence_threshold.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 결과 저장: {out_path}")


if __name__ == "__main__":
    main()
