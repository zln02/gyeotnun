"""
화면 문구 분기 집계 (2026-08-05)
실행: docker compose exec api python3 experiments/verify_screen_wording.py

목적: 배지 아래 한 줄 요약문(evidenceSummary)이 어느 갈래로 나가는지,
      평가셋 30건 + 홀드아웃 5건에서 각각 몇 건인지 센다.

★ web/src/pages/Question.jsx 의 verdictTier()/evidenceSummary() 분기를
  파이썬으로 옮긴 것이다. JS 를 실행할 수 없어 미러링했으며, 분기 조건은
  원본과 1:1 로 맞췄다(원본 줄 번호를 주석에 남긴다).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import search  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLDOUT_CSV = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")
OUT = Path("/app/data/screen_wording.json")

# 위험 표현 신호(사기사례 매칭이 아닌 것). Question.jsx 가 이 키들로 문구를 고른다.
_RISK_PHRASE = {
    "condition_omitted": "조건이 빠졌을 수 있는 표현",
    "urgency_pressure": "서두르게 만드는 표현",
}


def branch(ev) -> tuple:
    """(갈래 키, 사람이 읽는 설명)."""
    # Question.jsx:58 verdictTier()
    if ev.verdict_hint == "no_source_found":
        tier = "unknown"
    else:
        tier = ("suspicious"
                if any(s["severity"] == "attention" for s in ev.signals)
                else "confirmed")

    if tier == "unknown":
        return "A_못찾음", "공식 자료를 찾지 못함"
    if tier == "suspicious":
        if any(s["key"] == "similar_scam_case" for s in ev.signals):
            return "C_사기사례유사", "알려진 사기 사례와 수법이 겹침"
        return "B_위험표현", "근거는 찾았고, 글에 위험 표현이 있음"
    return "D_근거찾음", "근거를 찾았고 위험 표현 없음"


def run(rows, id_key, text_key):
    out = []
    for r in rows:
        ev = search.collect_evidence(r[text_key])
        key, desc = branch(ev)
        risks = [s["key"] for s in ev.signals
                 if s["severity"] == "attention" and s["key"] in _RISK_PHRASE]
        out.append({"id": r[id_key], "유형": r.get("유형", "정상(홀드아웃)"),
                    "branch": key, "desc": desc,
                    "refs": len(ev.references), "risk_keys": risks,
                    "verdict": ev.verdict_hint})
    return out


def main() -> None:
    ev_rows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig")))
    h_rows = list(csv.DictReader(HOLDOUT_CSV.open(encoding="utf-8-sig")))
    ev_res = run(ev_rows, "case_id", "평가용_제시문구")
    h_res = run(h_rows, "case_id", "평가용_제시문구")

    for name, res in (("평가셋 30건", ev_res), ("홀드아웃 5건", h_res)):
        print(f"\n════ {name} ════")
        for c in res:
            print(f"  {c['id']:<5}{c['유형']:<14}{c['branch']:<16}"
                  f"근거{c['refs']}건  {','.join(c['risk_keys']) or '-'}")

    print("\n════ 갈래별 건수 ════")
    print(f"  {'갈래':<18}{'평가셋':>8}{'홀드아웃':>10}{'합계':>8}")
    allk = ["D_근거찾음", "B_위험표현", "C_사기사례유사", "A_못찾음"]
    ce, ch = Counter(c["branch"] for c in ev_res), Counter(c["branch"] for c in h_res)
    for k in allk:
        print(f"  {k:<18}{ce[k]:>8}{ch[k]:>10}{ce[k]+ch[k]:>8}")

    b = [c["id"] for c in ev_res + h_res if c["branch"] == "B_위험표현"]
    print(f"\n  ★ 문제의 문구(B갈래)가 나가던 케이스: {b or '없음'}")

    OUT.write_text(json.dumps({"eval": ev_res, "holdout": h_res},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
