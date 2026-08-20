"""근거_검증표(EVIDENCE) 경로를 껐을 때의 전수 영향 (2026-08-19)

실행: docker compose exec -T api python3 experiments/exp_evidence_path_off.py

★ LLM 호출 없음. 같은 프로세스에서 스위치를 켜고/끄고 두 번 계산해 비교한다.

무엇을 보나 (지시받은 항목)
  1) verdict_hint 변화 전수 — 유형별로
  2) ★ 정상 문자 중 "못 찾았어요"로 바뀌는 건수 (정상이다. 세기만 한다)
  3) ★★ 사칭 건에서 근거가 사라져 tier 가 내려가는 건 — **한 건이라도 있으면 멈춘다**
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

SETS = [
    ("확대 112건", Path("/corpus/곁눈_평가세트_120건.csv"), True),
    ("홀드아웃 30건", Path("/app/tests/fixtures/holdout/holdout_30.csv"), True),
    ("실사용 11건", Path("/corpus/real_sms_normal_11.csv"), False),
]


def measure(rows, on: bool):
    search.EVIDENCE_TABLE_AS_REFERENCE = on
    out = {}
    for r in rows:
        t = mask_text(r["평가용_제시문구"]).text
        ev = search.collect_evidence(t)
        out[r["case_id"]] = {
            "hint": ev.verdict_hint,
            "refs": len(ev.references),
            "attention": sorted(s["key"] for s in ev.signals if s["severity"] == "attention"),
            "유형": r.get("유형", "-"),
        }
    return out


def main() -> None:
    total_changed = 0
    danger = []
    for label, path, drop_voice in SETS:
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        if drop_voice:
            rows = [r for r in rows if r.get("입력채널") != "음성"]
        before = measure(rows, on=True)
        after = measure(rows, on=False)

        changed = [c for c in before if before[c] != after[c]]
        hint_changed = [c for c in before if before[c]["hint"] != after[c]["hint"]]
        att_changed = [c for c in before if before[c]["attention"] != after[c]["attention"]]

        print(f"■ {label} (n={len(rows)})")
        print(f"   무언가 바뀐 건        {len(changed)}건")
        print(f"   ★ verdict_hint 변화  {len(hint_changed)}건")
        print(f"   attention 신호 변화   {len(att_changed)}건  ← 0 이어야 tier 가 안 움직인다")
        if hint_changed:
            by = Counter(before[c]["유형"] for c in hint_changed)
            print(f"   hint 변화 유형별: {dict(by)}")
            for c in hint_changed:
                b, a = before[c], after[c]
                flag = ""
                if b["유형"] == "사칭":
                    flag = "  ★★ 사칭"
                    danger.append((label, c, b, a))
                print(f"      {c:<5} [{b['유형']}] {b['hint']}(refs {b['refs']}) "
                      f"→ {a['hint']}(refs {a['refs']}){flag}")
        total_changed += len(hint_changed)
        print()

    print("=" * 64)
    print(f"hint 가 바뀐 건 합계: {total_changed}건")
    if danger:
        print(f"★★ 사칭 건에서 hint 가 바뀐 것이 {len(danger)}건 있다 — 멈추고 사람에게 보고할 것")
        for label, c, b, a in danger:
            print(f"   {label} {c}: {b['hint']} → {a['hint']} · attention {b['attention']} → {a['attention']}")
    else:
        print("✓ 사칭 건에서 hint 변화 0건")


if __name__ == "__main__":
    main()
