"""
min_score 적용을 **코드 수정 없이** 시뮬레이션해 판정 변화를 잰다 (2026-08-08)
실행: docker compose exec api python3 experiments/sim_scam_min_score.py [임계값]

diag_scam_min_score.py 가 '어떤 매칭이 사라지는가'를 봤다면, 이 스크립트는
'그래서 판정이 어떻게 바뀌는가'를 본다. match_scam_cases 를 런타임에만 감싸
(원본 코드는 그대로) collect_evidence 전체를 다시 돌린다.

절대조건
  ★ 정상 10건 오판(=의심 판정) 0건 유지
  ★ 사칭 10건 위험신호(attention) 검출 10/10 유지
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402
from services import search  # noqa: E402
from services.scam_taxonomy import detect_categories  # noqa: E402
from experiments.diag_scam_min_score import REAL_SMS, score_candidates  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLDOUT_CSV = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")
OUT = Path("/app/data/sim_scam_min_score.json")

VK = {"needs_check": "정상", "no_source_found": "확인불가", "partially_matched": "의심"}

_orig = ci.match_scam_cases


def patched(min_score: float):
    def f(text, limit=2, min_score_=min_score):
        return [c for _, lx, _, c in score_candidates(text) if lx >= min_score_][:limit]
    return f


def snapshot(rows):
    out = []
    for cid, typ, text in rows:
        ev = search.collect_evidence(text)
        att = [s["key"] for s in ev.signals if s["severity"] == "attention"]
        out.append({
            "id": cid, "유형": typ,
            "verdict": ev.verdict_hint, "verdict_ko": VK.get(ev.verdict_hint, ev.verdict_hint),
            "attention": att,
            "scam": [c.id for c in ci.match_scam_cases(text)],
            "refs": [r.get("url", "")[:60] for r in ev.references],
            "n_refs": len(ev.references),
        })
    return out


def diff(before, after, label):
    print("=" * 80)
    print(label)
    print("=" * 80)
    print(f"{'ID':<7}{'유형':<7}{'전 판정':<10}{'후 판정':<10}{'전 attention':<32}{'후 attention'}")
    print("-" * 80)
    changed = 0
    for b, a in zip(before, after):
        mark = ""
        if b["verdict"] != a["verdict"] or b["attention"] != a["attention"]:
            mark = "  ★"
            changed += 1
        print(f"{b['id']:<7}{b['유형']:<7}{b['verdict_ko']:<10}{a['verdict_ko']:<10}"
              f"{','.join(b['attention']) or '-':<32}{','.join(a['attention']) or '-'}{mark}")
    print(f"\n  변화: {changed}건")
    return changed


def verdict_summary(res, tag):
    for grp in sorted({c["유형"] for c in res}):
        g = [c for c in res if c["유형"] == grp]
        sig = [c for c in g if c["attention"]]
        susp = [c for c in g if c["verdict"] == "partially_matched"]
        print(f"  [{tag}] {grp} {len(g)}건: 위험신호 {len(sig)}건 / 의심판정 {len(susp)}건"
              + (f"  ★오판 {[c['id'] for c in susp]}" if grp == "정상" and susp else ""))


def main() -> None:
    th = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    erows = [(r["case_id"], r.get("유형", ""), r["평가용_제시문구"])
             for r in csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig"))]
    hrows = [(r["case_id"], "홀드아웃", r["평가용_제시문구"])
             for r in csv.DictReader(HOLDOUT_CSV.open(encoding="utf-8-sig"))]
    rrows = [(cid, "실사용", t) for cid, t in REAL_SMS]
    brows = [("B07img", "OCR", "은행 직원이 정부지원 대출상품을설명하고지점방문상담을권")]

    print(f"\n### 시뮬레이션 임계값 min_score = {th}\n")

    before = {k: snapshot(v) for k, v in
              (("eval", erows), ("holdout", hrows), ("real", rrows), ("b07", brows))}
    ci.match_scam_cases = patched(th)
    search.corpus_index.match_scam_cases = ci.match_scam_cases
    after = {k: snapshot(v) for k, v in
             (("eval", erows), ("holdout", hrows), ("real", rrows), ("b07", brows))}
    ci.match_scam_cases = _orig

    diff(before["eval"], after["eval"], "SET1 평가셋 30건")
    print()
    verdict_summary(before["eval"], "전")
    verdict_summary(after["eval"], "후")
    print()
    diff(before["holdout"], after["holdout"], "SET2 홀드아웃 5건")
    print()
    diff(before["real"], after["real"], "SET3 실사용 SMS 11건(재구성)")
    print()
    diff(before["b07"], after["b07"], "SET4 B07 실제 OCR")
    print("  전 refs:", before["b07"][0]["refs"])
    print("  후 refs:", after["b07"][0]["refs"])

    scam_sig_b = sum(1 for c in before["eval"] if c["유형"] == "사칭" and c["attention"])
    scam_sig_a = sum(1 for c in after["eval"] if c["유형"] == "사칭" and c["attention"])
    norm_fail_a = [c["id"] for c in after["eval"]
                   if c["유형"] == "정상" and c["verdict"] == "partially_matched"]
    hold_fail_a = [c["id"] for c in after["holdout"] if c["verdict"] == "partially_matched"]

    print("\n" + "=" * 80)
    print("절대조건 판정")
    print("=" * 80)
    print(f"  사칭 위험신호 검출 : {scam_sig_b}/10 → {scam_sig_a}/10   "
          f"{'OK' if scam_sig_a >= 10 else '★깨짐★'}")
    print(f"  정상 오판          : {len(norm_fail_a)}건 {norm_fail_a}  "
          f"{'OK' if not norm_fail_a else '★깨짐★'}")
    print(f"  홀드아웃 의심      : {len(hold_fail_a)}건 {hold_fail_a}  "
          f"{'OK' if not hold_fail_a else '★깨짐★'}")
    ok = scam_sig_a >= 10 and not norm_fail_a and not hold_fail_a
    print(f"\n  → 적용 가능: {'예' if ok else '아니오'}")

    OUT.write_text(json.dumps({"threshold": th, "before": before, "after": after},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
