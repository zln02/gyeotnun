"""경보문 허용목록 반영 전후 tier 전수 대조 (2026-08-13)

실행: docker compose exec api python3 experiments/verify_alert_ids.py <라벨>
      <라벨> 을 파일명에 써서 /app/data/tier_<라벨>.json 으로 남긴다.
      두 번째 실행 때 앞 스냅샷과 자동으로 대조한다.

★ 재는 자다. services/ 를 고치지 않는다. 화면 기준(verdict.js)으로 센다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")
OUTDIR = Path("/app/data")

# verdict.js ATTENTION_KEYS 와 1:1
FRONT_KEYS = {"similar_scam_case", "urgency_pressure", "condition_omitted",
              "official_alert_matched"}
RISK_REAL = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}


def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]


def evaluate(text: str) -> dict:
    res = search.collect_evidence(text)
    m = mask_text(text)
    types = [i.get("type") for i in (getattr(m, "items", None) or [])]
    keys = [s["key"] for s in res.signals if s.get("severity") == "attention"]
    if "account" in types or "card" in types:
        tier = "danger"
    elif any(k in FRONT_KEYS for k in keys):
        tier = "warn"
    elif res.verdict_hint != "needs_check":
        tier = "hold"
    else:
        tier = "ok"
    return {"tier": tier, "hint": res.verdict_hint, "attention": keys}


def main(label: str) -> None:
    snap = {}
    for name, rows in (("확대112", load(EVAL)), ("홀드30", load(HOLD))):
        for r in rows:
            snap[f"{name}:{r['case_id']}"] = {
                **evaluate(r["평가용_제시문구"]),
                "유형": r["유형"], "기대판단": r["기대판단"],
                "위험행동": r.get("위험행동", "없음"),
            }
    out = OUTDIR / f"tier_{label}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {out}  ({len(snap)}건)")

    def agg(sel) -> str:
        w = sum(1 for v in sel if v["tier"] in ("danger", "warn"))
        return f"{w}/{len(sel)}"

    for name in ("확대112", "홀드30"):
        v = [x for k, x in snap.items() if k.startswith(name + ":")]
        print(f"  [{name}] 정상 오판 {agg([x for x in v if x['기대판단'] == '정상'])}"
              f" · 사칭 경고 {agg([x for x in v if x['유형'] == '사칭'])}"
              f" · 축2 있음 {agg([x for x in v if x['위험행동'] in RISK_REAL])}"
              f" · 축2 없음(헛경고) {agg([x for x in v if x['위험행동'] == '없음'])}")

    # ---- 앞 스냅샷과 대조
    others = sorted(p for p in OUTDIR.glob("tier_*.json") if p != out)
    if not others:
        return
    prev = json.loads(others[-1].read_text(encoding="utf-8"))
    print(f"\n■ 대조: {others[-1].name} → {out.name}")
    changed = [(k, prev[k], snap[k]) for k in snap
               if k in prev and prev[k]["tier"] != snap[k]["tier"]]
    print(f"  tier 변경 {len(changed)}건")
    for k, a, b in changed:
        print(f"    {k:>16}  {a['tier']} → {b['tier']}   "
              f"attention {a['attention']} → {b['attention']}")
    sig = [(k, prev[k]["attention"], snap[k]["attention"]) for k in snap
           if k in prev and prev[k]["attention"] != snap[k]["attention"]]
    print(f"  신호 변경 {len(sig)}건 (tier 가 안 바뀐 것 포함)")
    for k, a, b in sig:
        if (k, prev[k], snap[k]) not in changed:
            print(f"    {k:>16}  {a} → {b}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "snapshot")
