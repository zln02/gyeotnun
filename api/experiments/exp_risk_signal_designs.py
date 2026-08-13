"""위험행동 신호 — 탐지기 수정 + 두 설계안 tier 측정 (2026-08-13)

실행: docker compose exec api python3 experiments/exp_risk_signal_designs.py

★ services/ 를 고치지 않는다. 메모리에서만 바꿔 재고, 결과만 보고한다.

■ 네 상태를 잰다
  0. 현재                          기준선
  1. 탐지기 수정만                 유형 정확도 수정이 tier 를 흔드는지 (신호는 아직 없음)
  2. 탐지기 수정 + 안A(tier 올림)  risk_action_requested severity=attention + 허용목록 추가
  3. 탐지기 수정 + 안B(이유만 교체) severity=info. 이미 warn/danger 인 건의 '사실 한 줄'만 바꾼다
                                   → tier 는 원리적으로 안 바뀐다. 정상 오판도 원리적으로 안 는다

■ 반드시 따로 보는 것
  ★ 정상인데 위험행동이 있는 케이스(R10 인증번호 · R11 앱설치)
    안A 는 이걸 warn 으로 올린다 → 축1(판정)로는 오판이 늘고 축2(안전)로는 정답이다.
    min_score 결정 때 R11 에서 본 것과 같은 충돌이다. 두 축을 분리해 적는다.
"""
from __future__ import annotations

import collections
import csv
import re
import sys

sys.path.insert(0, "/app")

from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

sys.path.insert(0, "/app/experiments")
from exp_risk_action_fix import detect_fixed  # noqa: E402

FRONT = {"similar_scam_case", "urgency_pressure", "condition_omitted",
         "official_alert_matched"}
RISK = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}
SETS = [("확대112", "/corpus/곁눈_평가세트_120건.csv"),
        ("홀드30", "/app/tests/fixtures/holdout/holdout_30.csv")]


def load(p: str) -> list[dict]:
    return [r for r in csv.DictReader(open(p, encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]


def masked(text: str) -> str:
    m = mask_text(text)
    return getattr(m, "text", None) or getattr(m, "masked", None) or text


def quote_of(text: str, keyword: str) -> str:
    """★ 인용은 마스킹된 텍스트에서만 뽑는다. 원문에서 뽑으면 전화번호·계좌가 살아 나간다."""
    if not keyword:
        return ""
    mt = masked(text)
    if keyword not in mt:
        return ""            # 마스킹으로 구절이 사라졌으면 인용하지 않는다
    for sent in re.split(r"(?<=[.!?])\s|\n", mt):
        if keyword in sent:
            s = sent.strip()
            return s if len(s) <= 60 else s[:57] + "…"
    return ""


def evaluate(text: str, mode: str) -> tuple[str, str, list]:
    """(tier, 화면 '사실 한 줄'의 근거, attention 신호들)"""
    res = search.collect_evidence(text)
    signals = [dict(s) for s in res.signals]
    hint = res.verdict_hint

    risk, kw = (None, "")
    if mode != "base":
        risk, kw = detect_fixed(text)
        # 탐지기 수정은 urgency_pressure 강등 판단에 영향을 준다 - 그것부터 반영한다.
        if search.URGENCY_REQUIRES_ACTION and risk is None:
            for s in signals:
                if s["key"] == "urgency_pressure":
                    s["severity"] = "info"
        elif risk is not None:
            for s in signals:
                if s["key"] == "urgency_pressure":
                    s["severity"] = "attention"

    if mode == "A" and risk:
        signals.append({"key": "risk_action_requested", "severity": "attention",
                        "detail": risk})
    if mode == "B" and risk:
        signals.append({"key": "risk_action_requested", "severity": "info",
                        "detail": risk})

    keys = [s["key"] for s in signals if s.get("severity") == "attention"]
    if any(s.get("severity") == "attention" for s in signals) and hint != "no_source_found":
        hint = "partially_matched" if res.references else hint

    m = mask_text(text)
    types = [i.get("type") for i in (getattr(m, "items", None) or [])]
    if "account" in types or "card" in types:
        tier = "danger"
    elif any(k in FRONT | ({"risk_action_requested"} if mode == "A" else set())
             for k in keys):
        tier = "warn"
    elif hint != "needs_check":
        tier = "hold"
    else:
        tier = "ok"

    # 화면 '사실 한 줄'이 무엇을 근거로 나가는가
    if tier in ("danger", "warn") and mode == "B" and risk:
        reason = f"위험행동:{risk}"        # 안B - tier 유지, 이유만 교체
    elif mode == "A" and risk and tier == "warn":
        reason = f"위험행동:{risk}"
    else:
        reason = (keys[0] if keys else "-")
    return tier, reason, [risk, kw]


def main() -> None:
    modes = [("0.현재", "base"), ("1.탐지기수정만", "fix"),
             ("2.안A tier올림", "A"), ("3.안B 이유만", "B")]
    data: dict = {}
    for name, path in SETS:
        for r in load(path):
            k = f"{name}:{r['case_id']}"
            data[k] = {"row": r, **{m: evaluate(r["평가용_제시문구"], m) for _, m in
                                    [(a, b) for a, b in modes]}}

    print("=" * 78)
    print("A. tier 변경 — 현재 대비")
    print("=" * 78)
    for label, m in modes[1:]:
        ch = [(k, v["base"][0], v[m][0]) for k, v in data.items() if v["base"][0] != v[m][0]]
        print(f"\n  [{label}] tier 변경 {len(ch)}건")
        for k, a, b in ch:
            r = data[k]["row"]
            print(f"      {k:16} {a}→{b}  ({r['유형']}/{r['기대판단']}/라벨={r.get('위험행동')})"
                  f"  {r['평가용_제시문구'][:40]}")

    print()
    print("=" * 78)
    print("B. 네 지표 (화면 기준)")
    print("=" * 78)
    for name, path in SETS:
        rows = [(f"{name}:{r['case_id']}", r) for r in load(path)]
        nor = [x for x in rows if x[1]["기대판단"] == "정상"]
        sc = [x for x in rows if x[1]["유형"] == "사칭"]
        ry = [x for x in rows if x[1].get("위험행동") in RISK]
        rn = [x for x in rows if x[1].get("위험행동") == "없음"]
        print(f"\n  [{name}]  {'':16}{'정상오판↓':>10}{'사칭경고↑':>10}{'축2있음↑':>10}{'축2없음↓':>10}")
        for label, m in modes:
            def c(sel):
                w = sum(1 for k, _ in sel if data[k][m][0] in ("danger", "warn"))
                return f"{w}/{len(sel)}"
            print(f"    {label:20}{c(nor):>10}{c(sc):>10}{c(ry):>10}{c(rn):>10}")

    print()
    print("=" * 78)
    print("C. ★ 정상인데 위험행동이 있는 케이스 — 두 축이 충돌한다")
    print("=" * 78)
    conflict = [(k, v) for k, v in data.items()
                if v["row"]["기대판단"] == "정상" and v["row"].get("위험행동") in RISK]
    print(f"  해당 {len(conflict)}건")
    for k, v in conflict:
        r = v["row"]
        risk, kw = v["A"][2]
        print(f"\n    {k}  라벨={r.get('위험행동')}  ({r.get('문구_성격','')})")
        print(f"      원문 : {r['평가용_제시문구'][:70]}")
        print(f"      현재 {v['base'][0]}({v['base'][1]}) → 안A {v['A'][0]}({v['A'][1]})"
              f" → 안B {v['B'][0]}({v['B'][1]})")
        print(f"      검출 : {risk}  근거구절={quote_of(r['평가용_제시문구'], kw)!r}")
        a1 = "오판" if v["A"][0] in ("danger", "warn") else "정답"
        a2 = "정답" if v["A"][0] in ("danger", "warn") else "놓침"
        print(f"      안A 기준 축1(판정) {a1} / 축2(안전) {a2}   ← 같은 한 건이 반대로 세어진다")

    print()
    print("=" * 78)
    print("D. 안B — 이유 문구가 바뀌는 건수 (tier 는 안 바뀐다)")
    print("=" * 78)
    for name, path in SETS:
        rows = [(f"{name}:{r['case_id']}", r) for r in load(path)]
        chg = [(k, data[k]["base"][1], data[k]["B"][1]) for k, _ in rows
               if data[k]["B"][0] in ("danger", "warn")
               and data[k]["base"][1] != data[k]["B"][1]]
        print(f"  [{name}] 이유 교체 {len(chg)}건 / warn·danger {sum(1 for k,_ in rows if data[k]['B'][0] in ('danger','warn'))}건")
        for k, a, b in chg:
            print(f"      {k:16} {a} → {b}")

    print()
    print("=" * 78)
    print("E. 인용 구절 안전 확인 — 마스킹된 텍스트에서만 뽑았는가")
    print("=" * 78)
    bad = []
    quoted = 0
    for k, v in data.items():
        risk, kw = v["A"][2]
        q = quote_of(v["row"]["평가용_제시문구"], kw)
        if not q:
            continue
        quoted += 1
        if re.search(r"\d{2,3}-\d{3,4}-\d{4}|\d{6}-\d{7}|\d{3,}-\d{2,}-\d{4,}", q):
            bad.append((k, q))
    print(f"  인용 구절이 만들어진 건 {quoted}건 · 숫자 잔존 의심 {len(bad)}건")
    for k, q in bad:
        print(f"      ❌ {k}: {q}")
    if not bad:
        print("      ✅ 전화번호·계좌·주민번호 패턴 잔존 없음")
    print("\n  표본 8건:")
    for k, v in list(data.items()):
        risk, kw = v["A"][2]
        q = quote_of(v["row"]["평가용_제시문구"], kw)
        if q and quoted:
            print(f"      [{risk}] {q}")
            quoted -= 1
            if quoted <= max(0, len(data) - 8):
                break

    print("\n※ 측정만 했다. services/ 무변경. 채택은 사람이 정한다.")


if __name__ == "__main__":
    main()
