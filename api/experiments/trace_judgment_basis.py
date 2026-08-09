"""
판정 근거 분해 (감사, 2026-08-05)
실행: docker compose exec api python3 experiments/trace_judgment_basis.py

목적: 평가셋 30건의 판정이 "무엇 때문에" 나왔는지 collect_evidence() 의
      실제 분기를 그대로 재현해 분류한다.

★ 코드를 바꾸지 않는다. 현재 상태를 기술하는 것이 목적이다.
★ 판정 로직을 재구현하지 않고 services/search.py 의 함수를 그대로 호출한 뒤,
  같은 입력으로 분기 조건만 다시 계산해 어느 가지를 탔는지 확인한다.

분류 (지시받은 정의)
  (a) 근거 문서와 내용이 불일치해서
  (b) 위험 신호(계좌·링크·긴급성)가 검출돼서
  (c) 근거를 못 찾아서
  (d) 기타
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index, search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
OUT_PATH = Path("/app/data/judgment_basis.json")


def trace(text: str) -> dict:
    """collect_evidence() 를 호출하고, 같은 입력으로 분기 조건을 다시 계산한다."""
    ev = search.collect_evidence(text)

    matched_official, mode, top_score = search.match_official_docs_safe(text)
    matched_evidence = corpus_index.match_evidence(text)
    matched_scam = corpus_index.match_scam_cases(text)

    # collect_evidence() 안의 판정 변수를 그대로 재현
    risky = any(s["severity"] == "attention" for s in ev.signals)
    if mode == "embedding":
        official_confident = top_score is not None and top_score >= search.CONFIDENT_MATCH_THRESHOLD
    else:
        official_confident = bool(matched_official)
    has_confident = official_confident or bool(matched_evidence) or bool(matched_scam)

    # 어느 attention 신호가 risky 를 만들었는가
    att = [s["key"] for s in ev.signals if s["severity"] == "attention"]

    # 분기 판별 - 소스 순서 그대로
    if not ev.references:
        branch, cause = "1) not refs", "c"
    elif risky:
        branch = "2) risky"
        # 어떤 attention 신호였는지로 세분한다
        cause = "b"
    elif not has_confident:
        branch, cause = "3) not has_confident_source", "d"
    else:
        branch, cause = "4) else", "d"

    return {
        "verdict": ev.verdict_hint, "branch": branch, "cause": cause,
        "attention_signals": att,
        "refs": len(ev.references),
        "official_docs": len(matched_official), "official_mode": mode,
        "top_score": round(top_score, 4) if top_score is not None else None,
        "confident": official_confident,
        "evidence_docs": len(matched_evidence), "scam_cases": len(matched_scam),
        "official_titles": [d.title[:40] for d in matched_official],
        "scam_titles": [c.text[:50] for c in matched_scam],
    }


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    out = {"cases": [], "threshold": search.CONFIDENT_MATCH_THRESHOLD}

    print(f"{'ID':<5}{'유형':<6}{'판정':<18}{'분기':<30}{'원인':<5}{'attention 신호'}")
    print("─" * 110)
    for r in rows:
        t = trace(r["평가용_제시문구"])
        t["case_id"], t["유형"] = r["case_id"], r["유형"]
        out["cases"].append(t)
        print(f"{t['case_id']:<5}{t['유형']:<6}{t['verdict']:<18}{t['branch']:<30}"
              f"({t['cause']}) {','.join(t['attention_signals']) or '-'}")

    print()
    print("════ 원인별 집계 ════")
    for c in ("a", "b", "c", "d"):
        hit = [x["case_id"] for x in out["cases"] if x["cause"] == c]
        print(f"  ({c}) {len(hit):>2}건  {hit}")

    print()
    print("════ (b) 를 유발한 attention 신호 분포 ════")
    from collections import Counter
    cnt = Counter(k for x in out["cases"] if x["cause"] == "b" for k in x["attention_signals"])
    for k, v in cnt.most_common():
        print(f"  {k:<24}{v}건")

    print()
    print("════ 근거 문서를 찾았는데도 needs_check 가 아닌 건 ════")
    for x in out["cases"]:
        if x["official_docs"] > 0 and x["verdict"] != "needs_check":
            print(f"  {x['case_id']} ({x['유형']}) verdict={x['verdict']} "
                  f"score={x['top_score']} confident={x['confident']} "
                  f"attention={x['attention_signals']}")
            print(f"      찾은 문서: {x['official_titles']}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
