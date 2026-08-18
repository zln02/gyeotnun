"""
match_scam_cases() 수정 검증 - 반드시 두 세트로 (2026-08-05)
실행: docker compose exec api python3 experiments/verify_scam_fix.py

지시: "평가셋 30건 : 경계 검출이 떨어지지 않는지 (현재 사칭 10/10 신호 검출)
      홀드아웃 5건 : H05 의심이 해소되는지
      한쪽만 좋아지면 채택하지 마라."

★ 홀드아웃을 보고 파라미터를 맞추지 않았다. 수정 근거는 매칭 로직 자체다
  (중복 계상·df 불일치·수법 무시). 홀드아웃은 결과 확인에만 쓴다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci, search  # noqa: E402
from services.scam_taxonomy import detect_categories  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLDOUT_CSV = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")
OUT = Path("/app/data/verify_scam_fix.json")

VK = {"needs_check": "정상", "no_source_found": "확인불가", "partially_matched": "의심"}


def run(rows, label_key, text_key, id_key):
    out = []
    for r in rows:
        text = r[text_key]
        ev = search.collect_evidence(text)
        scam = ci.match_scam_cases(text)
        att = [s["key"] for s in ev.signals if s["severity"] == "attention"]
        out.append({
            "id": r[id_key], "유형": r.get(label_key, "정상"),
            "verdict": ev.verdict_hint, "verdict_ko": VK.get(ev.verdict_hint, ev.verdict_hint),
            "scam_matches": [c.id for c in scam],
            "categories": sorted(detect_categories(text)),
            "attention": att,
            "refs": len(ev.references),
        })
    return out


def main() -> None:
    print("=" * 76)
    print("SET 1  평가셋 30건 - 검출력이 떨어지지 않는가")
    print("=" * 76)
    erows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig")))
    ev_res = run(erows, "유형", "평가용_제시문구", "case_id")

    print(f"{'ID':<5}{'유형':<6}{'판정':<10}{'사기매칭':<14}{'검출수법'}")
    print("-" * 76)
    for c in ev_res:
        print(f"{c['id']:<5}{c['유형']:<6}{c['verdict_ko']:<10}"
              f"{','.join(c['scam_matches']) or '-':<14}{','.join(c['categories']) or '-'}")

    for grp in ("정상", "사칭", "경계"):
        g = [c for c in ev_res if c["유형"] == grp]
        sig = [c for c in g if c["attention"]]
        susp = [c for c in g if c["verdict"] == "partially_matched"]
        print(f"\n  {grp} {len(g)}건: 위험신호 검출 {len(sig)}건 / 의심판정 {len(susp)}건")
        if grp == "정상" and susp:
            print(f"    ★ 정상 오판: {[c['id'] for c in susp]}")

    print("\n" + "=" * 76)
    print("SET 2  홀드아웃 5건 - H05 의심이 해소됐는가")
    print("=" * 76)
    hrows = list(csv.DictReader(HOLDOUT_CSV.open(encoding="utf-8-sig")))
    h_res = run(hrows, "_none", "평가용_제시문구", "case_id")
    for c in h_res:
        mark = "통과" if c["verdict"] != "partially_matched" else "★실패★"
        print(f"  {c['id']}  {c['verdict_ko']:<8}{mark:<8}사기매칭={c['scam_matches'] or '-'}  "
              f"수법={c['categories'] or '-'}")

    fail = [c["id"] for c in h_res if c["verdict"] == "partially_matched"]
    normal_fail = [c["id"] for c in ev_res
                   if c["유형"] == "정상" and c["verdict"] == "partially_matched"]
    scam_sig = sum(1 for c in ev_res if c["유형"] == "사칭" and c["attention"])
    bound_sig = sum(1 for c in ev_res if c["유형"] == "경계" and c["attention"])

    print("\n" + "=" * 76)
    print("판정")
    print("=" * 76)
    print(f"  SET1 사칭 위험신호 검출 : {scam_sig}/10   (수정 전 10/10)")
    print(f"  SET1 경계 위험신호 검출 : {bound_sig}/10   (수정 전 7/10)")
    print(f"  SET1 정상 오판          : {len(normal_fail)}건 {normal_fail}")
    print(f"  SET2 홀드아웃 실패      : {len(fail)}건 {fail}")
    ok = (not fail) and (not normal_fail) and scam_sig >= 10
    print(f"\n  → 채택 가능: {'예' if ok else '아니오 - 한쪽만 좋아졌거나 검출이 떨어졌다'}")

    OUT.write_text(json.dumps({"eval": ev_res, "holdout": h_res,
                               "scam_sig": scam_sig, "bound_sig": bound_sig,
                               "normal_fail": normal_fail, "holdout_fail": fail},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
