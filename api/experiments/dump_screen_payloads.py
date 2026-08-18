"""화면 입력(evidence + checkData)을 평가셋 전수로 떠 둔다 (2026-08-13)

실행: docker compose exec api python3 experiments/dump_screen_payloads.py <출력이름>

★ verdict.js 를 고치기 전후로 화면 출력을 대조하기 위한 것이다.
  tier 뿐 아니라 '사실 한 줄'까지 바뀌는 변경이라 파이썬 재현으로는 부족하다.
  실제 verdict.js 를 node 로 돌려 비교한다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

SETS = [("확대112", "/corpus/곁눈_평가세트_120건.csv"),
        ("홀드30", "/app/tests/fixtures/holdout/holdout_30.csv")]


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "payloads"
    out = []
    for label, path in SETS:
        rows = [r for r in csv.DictReader(open(path, encoding="utf-8-sig"))
                if r["입력채널"] != "음성"]
        for r in rows:
            text = r["평가용_제시문구"]
            m = mask_text(text)
            res = search.collect_evidence(m.text)
            out.append({
                "id": f"{label}:{r['case_id']}",
                "유형": r["유형"], "기대판단": r["기대판단"],
                "위험행동": r.get("위험행동", ""),
                "evidence": {
                    "verdict_hint": res.verdict_hint,
                    "signals": res.signals,
                    "references": res.references,
                },
                "checkData": {"masked_items": m.masked_items},
            })
    p = Path(f"/app/data/screen_{name}.json")
    p.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"저장 {p} — {len(out)}건")


if __name__ == "__main__":
    main()
