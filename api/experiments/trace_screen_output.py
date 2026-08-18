"""
화면 출력 추적 (감사, 2026-08-05)
실행: docker compose exec api python3 experiments/trace_screen_output.py

목적: 근거 문서를 찾은 케이스에서 사용자 화면에 실제로 무엇이 나가는지 확인한다.

★ 화면 문구는 web/src/pages/Question.jsx 의 함수를 그대로 옮겨 재현한다
  (verdictTier / evidenceSummary / source-block 분기). JS 를 실행할 수 없어
  파이썬으로 옮겼으며, 옮긴 원본 위치를 주석에 남긴다.
★ 코드를 바꾸지 않는다.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import prompt_chain, search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
OUT_PATH = Path("/app/data/screen_output.json")


def verdict_tier(ev) -> str:
    """web/src/pages/Question.jsx:58 verdictTier() 그대로."""
    if ev.verdict_hint == "no_source_found":
        return "unknown"
    return "suspicious" if any(s["severity"] == "attention" for s in ev.signals) else "confirmed"


def evidence_summary(ev, tier: str) -> str:
    """web/src/pages/Question.jsx:65 evidenceSummary() 그대로."""
    refs = ev.references or []
    if tier == "unknown":
        return "공식 자료에서 같은 이름의 공고나 안내를 찾지 못했습니다."
    pubs = []
    for r in refs:
        p = r.get("publisher")
        if p and p not in pubs:
            pubs.append(p)
    publishers = "·".join(pubs[:2])
    if tier == "suspicious":
        scam = next((s for s in ev.signals if s["key"] == "similar_scam_case"), None)
        if scam:
            import re
            m = re.search(r"\(([^)]+)\)", scam["label"])
            return (f"이전에 확인된 사례와 비슷한 점이 있습니다 ({m.group(1)})."
                    if m else "이전에 확인된 사례와 비슷한 점이 있습니다.")
        return (f"{publishers} 자료와 다른 점이 있어 확인이 필요합니다."
                if publishers else "확인할 점이 남아 있습니다.")
    return (f"{publishers}에서 같은 내용을 확인했습니다."
            if publishers else "공식 자료에서 같은 내용을 확인했습니다.")


TIER_LABEL = {"confirmed": "✅ 확인됨 / 공식 자료에서 확인됐습니다.",
              "suspicious": "⚠️ 의심 / 확인할 점이 남아 있습니다.",
              "unknown": "❓ 확인 불가 / 공식 자료에서 확인하지 못했습니다."}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    targets = [r for r in rows if r["유형"] in ("정상", "사칭")]

    out = {"cases": []}
    for r in targets:
        cid, text = r["case_id"], r["평가용_제시문구"]
        ev = search.collect_evidence(text)
        tier = verdict_tier(ev)

        # 1턴째 질문을 실제로 생성해 evidence_refs 를 본다 (화면 링크는 이것으로 결정된다)
        allowed = [x["url"] for x in ev.references if x.get("url")]
        try:
            vq = prompt_chain.generate_question(
                extracted_text=text, signals=ev.signals, references=ev.references, history=[])
            shown = list(vq.evidence_refs)
            fb = getattr(vq, "fallback", False)
        except Exception as e:  # noqa: BLE001
            shown, fb = [f"오류:{e}"], None

        # web/src/pages/Question.jsx:147 - 화면 링크는 evidence_refs 로만 만든다
        ref_titles = []
        for u in shown:
            found = next((x for x in ev.references if x.get("url") == u), None)
            ref_titles.append(found["title"] if found else u)

        c = {
            "case_id": cid, "유형": r["유형"], "verdict_hint": ev.verdict_hint,
            "화면_배지": TIER_LABEL[tier],
            "화면_요약문": evidence_summary(ev, tier),
            "evidence_references_건수": len(ev.references),
            "화면표시_링크_건수": len(shown),
            "화면표시_링크": ref_titles,
            "링크영역_문구": ("링크 표시" if shown else
                              "공식 자료에서 같은 내용을 찾지 못했습니다."),
            "fallback": fb,
        }
        out["cases"].append(c)
        print(f"[{cid}] {r['유형']}  {ev.verdict_hint}")
        print(f"   배지  : {c['화면_배지']}")
        print(f"   요약문: {c['화면_요약문']}")
        print(f"   근거 {len(ev.references)}건 중 화면 표시 {len(shown)}건 → {ref_titles}")
        print()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    normal = [c for c in out["cases"] if c["유형"] == "정상"]
    gap = [c for c in normal if c["evidence_references_건수"] > 0 and c["화면표시_링크_건수"] == 0]
    print("════ 정상 10건 요약 ════")
    print(f"  근거 있음: {sum(1 for c in normal if c['evidence_references_건수']>0)}/10")
    print(f"  화면 링크 표시: {sum(1 for c in normal if c['화면표시_링크_건수']>0)}/10")
    print(f"  ★ 근거는 있는데 화면엔 안 나가는 건: {len(gap)}건 {[c['case_id'] for c in gap]}")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
