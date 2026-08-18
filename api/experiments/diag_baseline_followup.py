"""기준선 해석 보조 진단 (2026-08-12) — 읽기 전용.
실행: docker compose exec api python3 experiments/diag_baseline_followup.py

★ 아무것도 고치지 않는다. services/ 함수를 호출해 읽기만 한다.

1. 정상 실패를 A(확인불가 계열) / B(의심 계열) 로 가른다. 합치지 않는다.
2. 넓은 정의 오답근거 14건(사칭)의 verdict_hint·references 조합을 뽑는다.
   프론트가 어떤 갈래로 렌더링하는지 판정하기 위한 원자료다.
3. detected_domain 분포를 센다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402
from services.ocr import detect_domain  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
MAXK = 5


def url_key(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    if not p.netloc:
        return ""
    base = (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()
    return f"{base}?{p.query}" if p.query else base


_DOC_BY_KEY: dict[str, list] = {}
for _d in ci.OFFICIAL_DOCS:
    if (k := url_key(_d.source_url)):
        _DOC_BY_KEY.setdefault(k, []).append(_d)


def gold_ids(url: str) -> set:
    return {d.id for d in _DOC_BY_KEY.get(url_key(url), [])}


rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig"))
        if r["입력채널"] != "음성"]

recs = []
for r in rows:
    text = r["평가용_제시문구"]
    res = search.collect_evidence(text)
    sig_att = [s["key"] for s in res.signals if s.get("severity") == "attention"]
    try:
        ranked = [d.id for _, d in emb.match_embedding_docs(text, limit=MAXK)]
    except emb.EmbeddingUnavailableError:
        ranked = []
    g = gold_ids(r["출처_URL"])
    recs.append({
        "id": r["case_id"], "유형": r["유형"], "lane": r["문구_성격"],
        "domain": detect_domain(text),
        "hint": res.verdict_hint, "refs": len(res.references),
        "att": sig_att, "risky": bool(sig_att),
        "gold": bool(g), "hit": bool(g & set(ranked)),
        "top_score": round(res.references[0].get("score", 0), 4) if res.references
                     and isinstance(res.references[0], dict) else None,
    })

print("=" * 74)
print("1. 정상 축1 실패의 유형 분리 (A 확인불가 계열 / B 의심 계열)")
print("=" * 74)
for lane_name, pred in (("실사용원문 11건", lambda c: c["lane"] == "실사용원문"),
                        ("합성 정상 26건", lambda c: c["유형"] == "정상" and c["lane"] != "실사용원문")):
    sel = [c for c in recs if pred(c)]
    # 축1 정상 기준 = verdict_hint == needs_check
    fail = [c for c in sel if c["hint"] != "needs_check"]
    a = [c for c in fail if not c["risky"]]
    b = [c for c in fail if c["risky"]]
    print(f"\n[{lane_name}]  총 {len(sel)}건 · 축1 실패 {len(fail)}건")
    print(f"   A 확인불가 계열(경고 없음, 근거 못 찾음) : {len(a)}건  "
          + (", ".join(c["id"] for c in a) or "-"))
    print(f"   B 의심 계열(위험 신호 잡힘)             : {len(b)}건  "
          + (", ".join(c["id"] for c in b) or "-"))
    if b:
        print("   ── B 내역 (잡힌 attention 신호)")
        for c in b:
            print(f"      {c['id']:5} hint={c['hint']:18} refs={c['refs']}  신호={','.join(c['att'])}")

print("\n" + "=" * 74)
print("2. 넓은 정의 오답근거(사칭)의 verdict_hint × references 조합")
print("=" * 74)
wide = [c for c in recs if c["유형"] == "사칭" and c["refs"] and c["gold"] and not c["hit"]]
print(f"대상 {len(wide)}건")
print(f"  hint 분포: {dict(Counter(c['hint'] for c in wide))}")
for c in wide:
    print(f"   {c['id']:5} hint={c['hint']:18} refs={c['refs']} risky={c['risky']} "
          f"신호={','.join(c['att']) or '-'}")

print("\n" + "=" * 74)
print("3. detected_domain 분포")
print("=" * 74)
print(f"\n[실사용 11건]")
for c in [c for c in recs if c["lane"] == "실사용원문"]:
    print(f"   {c['id']:5} domain={str(c['domain']):9} hint={c['hint']:18} refs={c['refs']}")
print(f"\n  집계: {dict(Counter(c['domain'] for c in recs if c['lane'] == '실사용원문'))}")

print(f"\n[확대 112건 전체] {dict(Counter(c['domain'] for c in recs))}")
print("\n  유형별 domain 교차:")
for t in ("정상", "사칭", "경계"):
    sub = [c for c in recs if c["유형"] == t]
    print(f"   {t:4} {dict(Counter(c['domain'] for c in sub))}")

print("\n  domain 별 '근거 못 찾음(refs=0)' 비율:")
for d in sorted({c["domain"] for c in recs}, key=str):
    sub = [c for c in recs if c["domain"] == d]
    z = sum(1 for c in sub if c["refs"] == 0)
    print(f"   {str(d):9} {z}/{len(sub)}")
