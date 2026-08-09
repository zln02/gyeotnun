#!/usr/bin/env python3
"""마스킹 파이프라인 재현율 측정 (2026-08-09)

실행:
  python3 tests/eval/eval_masking.py                  # 측정만
  python3 tests/eval/eval_masking.py --label before   # 결과를 라벨 붙여 저장(전/후 비교용)

무엇을 재는가
  · 누락(miss)  — pii_spans 의 value 가 마스킹 결과에 **원문 그대로** 남아 있는 경우.
                  재현율 = 1 - 누락/전체. 이것이 핵심 지표다.
  · 부분누출     — value 전체는 사라졌지만 그 안의 연속 숫자 4자리 이상이 남은 경우.
                  "356 0492 0731 93" 에서 앞 3자리만 남기고 마스킹되는 식의 절반 성공을
                  '성공'으로 세지 않기 위한 보조 지표다(참고치).
  · 과잉(over)   — non_pii 토큰이 마스킹 결과에서 사라진 경우(참고치).
                  ★ 곁눈에서 과잉 마스킹은 단순 미관 문제가 아니다. masked_text 가
                    그대로 search.collect_evidence() 와 질문 생성 입력으로 들어가므로
                    (routers/checks.py:126→164), 과하게 지우면 판정 근거가 사라진다.

★ 이 스크립트는 마스킹 로직을 호출만 한다. 고치지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))

from services.masking import mask_text  # noqa: E402

CASES_PATH = Path(__file__).resolve().parent / "masking_cases.json"
TYPES = ["name", "phone", "account", "rrn", "address"]

DIGIT_RUN_RE = re.compile(r"\d{4,}")


def digit_runs(value: str) -> list[str]:
    """값 안의 연속 숫자 4자리 이상 덩어리(공백·하이픈은 끊어서 본다)."""
    return DIGIT_RUN_RE.findall(re.sub(r"[^\d]", " ", value))


def evaluate() -> dict:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    per_type = {t: {"fields": 0, "miss": 0, "partial": 0} for t in TYPES}
    misses: list[dict] = []
    partials: list[dict] = []
    overs: list[dict] = []
    over_total = 0
    non_pii_total = 0

    for case in data["cases"]:
        text = case["text"]
        result = mask_text(text)
        out = result.text

        for span in case["pii_spans"]:
            typ, val = span["type"], span["value"]
            per_type.setdefault(typ, {"fields": 0, "miss": 0, "partial": 0})
            per_type[typ]["fields"] += 1
            if val in out:
                per_type[typ]["miss"] += 1
                misses.append({"id": case["id"], "type": typ, "value": val,
                               "text": text, "masked": out})
            else:
                leaked = [r for r in digit_runs(val) if r in out]
                if leaked:
                    per_type[typ]["partial"] += 1
                    partials.append({"id": case["id"], "type": typ, "value": val,
                                     "leaked": leaked, "masked": out})

        for tok in case.get("non_pii", []):
            non_pii_total += 1
            if tok not in out:
                over_total += 1
                overs.append({"id": case["id"], "token": tok,
                              "text": text, "masked": out})

    for t, s in per_type.items():
        s["hit"] = s["fields"] - s["miss"]
        s["recall"] = (s["hit"] / s["fields"]) if s["fields"] else 0.0

    total_fields = sum(s["fields"] for s in per_type.values())
    total_miss = sum(s["miss"] for s in per_type.values())
    return {
        "cases": len(data["cases"]),
        "per_type": per_type,
        "total": {
            "fields": total_fields,
            "miss": total_miss,
            "recall": (total_fields - total_miss) / total_fields if total_fields else 0.0,
            "partial": sum(s["partial"] for s in per_type.values()),
            "non_pii_tokens": non_pii_total,
            "over_mask": over_total,
        },
        "misses": misses,
        "partials": partials,
        "overs": overs,
    }


def report(res: dict) -> None:
    print(f"케이스 {res['cases']}건 / PII 필드 {res['total']['fields']}개\n")
    print(f"{'유형':<10}{'필드':>6}{'누락':>6}{'재현율':>9}{'부분누출':>9}")
    print("-" * 42)
    for t in TYPES:
        s = res["per_type"][t]
        if not s["fields"]:
            continue
        print(f"{t:<10}{s['fields']:>6}{s['miss']:>6}{s['recall']*100:>8.1f}%{s['partial']:>9}")
    tot = res["total"]
    print("-" * 42)
    print(f"{'전체':<10}{tot['fields']:>6}{tot['miss']:>6}{tot['recall']*100:>8.1f}%{tot['partial']:>9}")
    print(f"\n과잉 마스킹(참고): {tot['over_mask']} / 비-PII 토큰 {tot['non_pii_tokens']}개")

    if res["misses"]:
        print(f"\n{'='*70}\n누락 {len(res['misses'])}건\n{'='*70}")
        for m in res["misses"]:
            print(f"[{m['id']}] {m['type']:<8} {m['value']!r}")
    if res["partials"]:
        print(f"\n{'='*70}\n부분 누출 {len(res['partials'])}건\n{'='*70}")
        for p in res["partials"]:
            print(f"[{p['id']}] {p['type']:<8} {p['value']!r} → 남은 숫자 {p['leaked']}")
    if res["overs"]:
        print(f"\n{'='*70}\n과잉 마스킹 {len(res['overs'])}건\n{'='*70}")
        for o in res["overs"]:
            print(f"[{o['id']}] {o['token']!r}")
            print(f"    → {o['masked']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="", help="결과 JSON 을 이 라벨로 저장(before/after 등)")
    args = ap.parse_args()

    res = evaluate()
    report(res)

    if args.label:
        out = Path(__file__).resolve().parent / f"masking_eval_{args.label}.json"
        out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
