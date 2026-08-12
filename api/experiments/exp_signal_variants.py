"""실험 1·2 — 신호 결합 조건과 초록 승격 방식 (2026-08-12)
실행: docker compose exec api python3 experiments/exp_signal_variants.py

★ services/ 를 고치지 않는다. 프로덕션 함수를 호출해 판정 로직만 여기서 재현하고,
  그 재현본에 변형을 넣어 비교한다. 채택은 사람이 정한다.
★ 한꺼번에 적용하지 않는다. baseline → V1 → V2 를 각각 따로 잰다.

■ V1 (실험 1)  urgency_pressure 를 위험행동과 결합할 때만 attention 으로 올린다.
■ V2 (실험 2)  초록(ok)을 '확신 매칭(has_confident_source)' 일 때만 허용한다.
               지금은 배제 방식(신호 화이트리스트에 걸리면 초록에서 내림)이라,
               신호가 하나도 안 붙는 partially_matched 가 오면 초록으로 샌다.

■ 위험행동 탐지기 — ★ 평가셋 라벨을 쓰지 않는다
  평가셋의 위험행동 컬럼을 그대로 쓰면 라벨 누수라 배포할 수 없는 결과가 된다.
  텍스트만 보는 탐지기를 따로 만들고, 손라벨과 얼마나 맞는지를 먼저 보고한다.
  키워드는 '요구하는 행동'의 동사에서 뽑았다. 실패 사례를 보고 고르지 않았다.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")

from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")

# 프론트 web/src/verdict.js 의 ATTENTION_KEYS 와 1:1
FRONT_KEYS = {"similar_scam_case", "urgency_pressure", "condition_omitted"}
RISK_LABELS = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}

# ---------------------------------------------------------------- 위험행동 탐지기
_ACTION = {
    "계좌이체": ["입금", "송금", "이체", "선결제", "예치", "상환", "납부",
                 "보내 주", "보내주", "보내줘", "계좌로", "결제해"],
    "앱설치": ["앱을 설치", "앱 설치", "설치하시", "설치해", "설치하고", "다운로드",
               "파일을 설치", "깔아"],
    "인증번호": ["인증번호", "본인인증", "인증서", "공동인증", "본인 인증"],
    "개인정보요구": ["주민등록번호", "주민번호", "신분증", "통장 사본", "통장사본",
                     "계좌번호를 입력", "계좌를 등록", "계좌 등록", "카드번호",
                     "생년월일 뒤", "뒤 7자리", "연락처를 알려", "시세를 먼저 알려",
                     "주소를 다시 입력", "정보를 다시 입력", "사진을 보내", "사진을 업로드"],
}


def detect_risk_action(text: str) -> str:
    """제시문구가 요구하는 행동을 텍스트만 보고 고른다. 없으면 '없음'."""
    t = text or ""
    for label, kws in _ACTION.items():
        if any(k in t for k in kws):
            return label
    return "없음"


# ---------------------------------------------------------------- 판정 재현
def evaluate(text: str, variant: str) -> dict:
    """services.collect_evidence 의 판정부를 그대로 옮기고 변형만 끼워 넣는다."""
    signals = search.detect_signals(text)
    matched_official, mode, top_score = search.match_official_docs_safe(text)
    matched_evidence = search.corpus_index.match_evidence(text)
    matched_scam = search.corpus_index.match_scam_cases(text)
    legacy = search.search_corpus(text)

    for _ in matched_scam:
        signals.append({"key": "similar_scam_case", "severity": "attention"})

    refs = search._dedup_refs(
        [d.to_reference() for d in matched_official]
        + [d.to_reference() for d in matched_evidence]
        + [c.to_reference() for c in matched_scam]
        + legacy
    )

    if mode == "embedding":
        official_confident = top_score is not None and top_score >= search.CONFIDENT_MATCH_THRESHOLD
    else:
        official_confident = bool(matched_official)
    has_confident = official_confident or bool(matched_scam)

    action = detect_risk_action(text)

    # ---- V1: urgency_pressure 단독이면 attention 에서 내린다
    if variant == "V1":
        for s in signals:
            if s["key"] == "urgency_pressure" and action == "없음":
                s["severity"] = "info"

    risky = any(s["severity"] == "attention" for s in signals)

    if not refs:
        hint = "no_source_found"
        signals.append({"key": "no_official_source", "severity": "attention"})
    elif risky:
        hint = "partially_matched"
    elif not has_confident:
        hint = "no_source_found"
    else:
        hint = "needs_check"

    # ---- 화면 tier (web/src/verdict.js judgmentState 재현)
    m = mask_text(text)
    items = [i.get("type") for i in (getattr(m, "items", None) or [])]
    if "account" in items or "card" in items:
        tier = "danger"
    elif any(s["severity"] == "attention" and s["key"] in FRONT_KEYS for s in signals):
        tier = "warn"
    elif hint == "no_source_found":
        tier = "hold"
    else:
        tier = "ok"

    # ---- V2: 초록은 확신 매칭일 때만 허용한다 (배제 → 허용 방식)
    if variant == "V2" and tier == "ok" and not has_confident:
        tier = "hold"

    return {"hint": hint, "tier": tier, "action": action,
            "confident": has_confident, "n_refs": len(refs)}


# ---------------------------------------------------------------- 집계
def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]


def measure(rows: list[dict], variant: str) -> dict:
    out = []
    for r in rows:
        res = evaluate(r["평가용_제시문구"], variant)
        out.append({**r, **res})

    normals = [c for c in out if c["유형"] == "정상"]
    scams = [c for c in out if c["유형"] == "사칭"]
    borders = [c for c in out if c["유형"] == "경계"]
    warned = lambda c: c["tier"] in ("danger", "warn")          # noqa: E731

    risk_y = [c for c in out if c["위험행동"] in RISK_LABELS]
    risk_n = [c for c in out if c["위험행동"] == "없음"]

    return {
        "정상오판": (sum(1 for c in normals if warned(c)), len(normals),
                     [c["case_id"] for c in normals if warned(c)]),
        "사칭판정": (sum(1 for c in scams if warned(c) or c["hint"] != "needs_check"), len(scams)),
        "경계판정": (sum(1 for c in borders if c["hint"] == "no_source_found"), len(borders)),
        "축2있음": (sum(1 for c in risk_y if warned(c)), len(risk_y)),
        "축2없음": (sum(1 for c in risk_n if warned(c)), len(risk_n)),
        "초록": (sum(1 for c in out if c["tier"] == "ok"), len(out),
                 [c["case_id"] for c in out if c["tier"] == "ok"]),
        "tier분포": dict(Counter(c["tier"] for c in out)),
        "rows": out,
    }


def pc(t) -> str:
    a, b = t[0], t[1]
    return f"{a}/{b} ({a / b * 100:.1f}%)" if b else "—"


def main() -> None:
    sets = [("확대 112건", load(EVAL)), ("홀드아웃 30건", load(HOLD))]

    # ---- 탐지기 정확도부터 (라벨 누수 없음을 보이기 위해)
    print("=" * 72)
    print("0. 위험행동 탐지기 vs 손라벨 (평가셋 라벨을 쓰지 않았음을 확인)")
    print("=" * 72)
    for name, rows in sets:
        agree = sum(1 for r in rows if detect_risk_action(r["평가용_제시문구"]) == r["위험행동"])
        yl = [r for r in rows if r["위험행동"] in RISK_LABELS]
        yd = sum(1 for r in yl if detect_risk_action(r["평가용_제시문구"]) in RISK_LABELS)
        print(f"  [{name}] 라벨 완전일치 {agree}/{len(rows)}"
              f" · 위험행동 '있음' 재현 {yd}/{len(yl)}")

    for variant in ("baseline", "V1", "V2"):
        print("\n" + "=" * 72)
        print(f"[{variant}]")
        print("=" * 72)
        for name, rows in sets:
            m = measure(rows, variant)
            print(f"  ── {name}")
            print(f"     정상 오판   {pc(m['정상오판'])}  {m['정상오판'][2]}")
            print(f"     사칭 판정   {pc(m['사칭판정'])}   ★ 떨어지면 기각")
            print(f"     경계 판정   {pc(m['경계판정'])}")
            print(f"     축2 있음    {pc(m['축2있음'])}   없음 {pc(m['축2없음'])}")
            print(f"     초록 건수   {m['초록'][0]}건   tier {m['tier분포']}")


if __name__ == "__main__":
    main()
