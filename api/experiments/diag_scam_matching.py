"""
match_scam_cases() 오매칭 진단 (2026-08-05)
실행: docker compose exec api python3 experiments/diag_scam_matching.py

목적: H05(정상 기초연금 안내)와 경계 케이스들이 사기 사례와 매칭된 경로를
      토큰 단위로 분해해, 어떤 토큰이 얼마의 가중치로 기여했는지 표로 낸다.

★ 코드를 바꾸지 않는다. 진단만 한다.
★ 현재 구현(corpus_index.match_scam_cases)의 채점식을 그대로 재현한다:
    kws   = extract_keywords(text) - STOPWORDS
    match = [k for k in kws if k in case._blob]   # ← 부분 문자열 포함
    score = sum(_keyword_weight(k) for k in match)
    _keyword_weight(k) = log((N_DOCS+1)/(df_scam(k)+1)) + 1.0
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index as ci  # noqa: E402

OUT_PATH = Path("/app/data/diag_scam_matching.json")
EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLDOUT_CSV = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")


def decompose(text: str, limit: int = 3):
    """현재 채점식을 그대로 재현해 토큰별 기여도를 돌려준다."""
    kws = [k for k in ci.extract_keywords(text) if k not in ci.STOPWORDS]
    rows = []
    for case in ci.SCAM_CASES:
        matched = [k for k in kws if k in case._blob]
        if not matched:
            continue
        parts = [(k, round(ci._keyword_weight(k), 3), ci._SCAM_DOC_FREQ.get(k, 0))
                 for k in matched]
        parts.sort(key=lambda x: -x[1])
        score = sum(p[1] for p in parts)
        rows.append({"case_id": case.id, "score": round(score, 3),
                     "tokens": parts, "blob": case.text[:70]})
    rows.sort(key=lambda r: -r["score"])
    return kws, rows[:limit]


def show(label: str, text: str) -> dict:
    kws, rows = decompose(text)
    print(f"\n{'='*78}\n[{label}]  {text[:66]}")
    print(f"  추출 키워드({len(kws)}): {kws[:14]}")
    for r in rows:
        over = "★임계 5.0 초과" if r["score"] >= 5.0 else " (미달)"
        print(f"\n  └ {r['case_id']}  점수 {r['score']}{over}")
        print(f"     사례: {r['blob']}")
        print(f"     {'토큰':<14}{'가중치':>8}{'사기코퍼스 df':>14}")
        for k, w, df in r["tokens"]:
            print(f"     {k:<14}{w:>8.3f}{df:>14}")
    return {"label": label, "text": text, "keywords": kws, "matches": rows}


def main() -> None:
    print(f"SCAM_CASES {ci._SCAM_N_DOCS}건 / 임계값 5.0")
    print("가중치식: log((N+1)/(df+1))+1  ← df 는 '사기 코퍼스' 내 문서빈도다")
    out = {"cases": []}

    # ---- 1) 홀드아웃 H05 (정상인데 의심으로 오판)
    hrows = list(csv.DictReader(HOLDOUT_CSV.open(encoding="utf-8-sig")))
    for r in hrows:
        if r["case_id"] == "H05":
            out["cases"].append(show("H05 정상(오판)", r["평가용_제시문구"]))

    # ---- 2) 평가셋에서 사기사례 매칭이 판정을 바꾼 건들
    erows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig")))
    basis = json.load(open("/app/data/judgment_basis.json", encoding="utf-8"))
    scam_driven = [c["case_id"] for c in basis["cases"]
                   if "similar_scam_case" in c["attention_signals"]]
    print(f"\n\n{'#'*78}\n# 사기사례 매칭이 판정을 바꾼 {len(scam_driven)}건: {scam_driven}\n{'#'*78}")
    for r in erows:
        if r["case_id"] in scam_driven:
            out["cases"].append(show(f"{r['case_id']} {r['유형']}", r["평가용_제시문구"]))

    # ---- 3) 단일 토큰만으로 임계를 넘길 수 있는가 (구조적 취약점 확인)
    print(f"\n\n{'#'*78}\n# 구조 점검: 토큰 1개로 5.0 을 넘길 수 있는가\n{'#'*78}")
    solo = [(k, ci._keyword_weight(k), df) for k, df in ci._SCAM_DOC_FREQ.items()]
    solo.sort(key=lambda x: -x[1])
    can_solo = [s for s in solo if s[1] >= 5.0]
    print(f"  단독으로 5.0 이상인 토큰: {len(can_solo)}개 / 전체 {len(solo)}개")
    print(f"  최고 가중치: {solo[0][1]:.3f} (df={solo[0][2]}, '{solo[0][0]}')")
    print(f"  df=1 인 토큰의 가중치: {ci._keyword_weight('__없는단어__'):.3f} 미만"
          f" (df=0 일 때 {ci._keyword_weight('__없는단어__'):.3f})")
    print(f"  → 토큰 2개면 {solo[0][1]*2:.1f} 까지 나온다. 임계 5.0 은 사실상 '희귀 토큰 2개'다.")
    out["solo_over_threshold"] = len(can_solo)
    out["max_weight"] = round(solo[0][1], 3)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
