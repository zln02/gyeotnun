"""NIA 297건이 검색 후보군을 얼마나 차지하는가 (2026-08-12)
실행: docker compose exec api python3 experiments/exp_nia_exclusion.py

★ 측정만 한다. 문서를 지우지 않는다. 인덱스도 다시 만들지 않는다.
  검색 결과에서 제외해 보는 실험일 뿐이고, 파일과 인덱스는 그대로 둔다.
  1,052 는 기획서 2.3 에 실려 제출된 수치라 바꾸려면 정정 이력이 필요하다.

■ 왜 재나
  NIA(한국지능정보사회진흥원) 자료가 코퍼스 1,052건 중 297건(28%)인데
  검색 '기여'는 0% 였다. 그런데 기여 0% 는 **정답으로 채택된 적이 없다**는
  뜻이지 후보에 안 들어온다는 뜻이 아니다. 후보 자리를 차지하고 있으면
  정답이 밀려나므로, 후보군 점유율을 따로 재야 한다.

■ 후보 제외 = 인덱스 제외 (동치)
  순수 top-k 코사인 검색에서는 '전체를 뽑아 NIA 를 걸러내고 상위 k' 와
  '애초에 NIA 없는 인덱스에서 상위 k' 의 결과가 같다. 순위가 문서 간
  독립적으로 정해지기 때문이다. 그래서 인덱스를 다시 만들지 않는다.
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
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")
NIA = "한국지능정보사회진흥원"
FRONT = {"similar_scam_case", "urgency_pressure", "condition_omitted"}
RISK_LABELS = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}
TOPKS = (1, 3, 5)

_AGENCY = {d.id: (d.source_agency or "") for d in ci.OFFICIAL_DOCS}


def url_key(u: str) -> str:
    try:
        p = urlparse((u or "").strip())
    except ValueError:
        return ""
    if not p.netloc:
        return ""
    b = (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()
    return f"{b}?{p.query}" if p.query else b


_DOC_BY_KEY: dict[str, list] = {}
for _d in ci.OFFICIAL_DOCS:
    if (k := url_key(_d.source_url)):
        _DOC_BY_KEY.setdefault(k, []).append(_d)
_SCAM_KEYS = {url_key(getattr(c, "url", "") or "") for c in ci.SCAM_CASES} - {""}


def gold_of(row: dict) -> tuple[str, set]:
    u = (row.get("출처_URL") or "").strip()
    if not u:
        return "no_ref", set()
    p = urlparse(u)
    if p.netloc and p.path.rstrip("/") == "" and not p.query:
        return "none", set()
    k = url_key(u)
    if k in _DOC_BY_KEY:
        return "doc", {d.id for d in _DOC_BY_KEY[k]}
    if k in _SCAM_KEYS:
        return "scam", set()
    return "missing", set()


def ranked(text: str, k: int, drop_nia: bool) -> list[tuple[float, object]]:
    """상위 k. drop_nia 면 NIA 문서를 빼고 나서 k 개를 채운다."""
    try:
        hits = emb.match_embedding_docs(text, limit=k * 6 if drop_nia else k)
    except emb.EmbeddingUnavailableError:
        return []
    if drop_nia:
        hits = [h for h in hits if _AGENCY.get(h[1].id, "") != NIA]
    return hits[:k]


def run(rows: list[dict], drop_nia: bool) -> dict:
    cases = []
    for r in rows:
        text = r["평가용_제시문구"]
        kind, gold = gold_of(r)

        # ---- 판정 재현 (collect_evidence 와 동일 순서, 공식문서만 필터링)
        signals = search.detect_signals(text)
        hits = ranked(text, 2, drop_nia)
        matched_official = [d for _, d in hits]
        top_score = hits[0][0] if hits else None
        matched_evidence = ci.match_evidence(text)
        matched_scam = ci.match_scam_cases(text)
        for _ in matched_scam:
            signals.append({"key": "similar_scam_case", "severity": "attention"})
        refs = search._dedup_refs(
            [d.to_reference() for d in matched_official]
            + [d.to_reference() for d in matched_evidence]
            + [c.to_reference() for c in matched_scam]
        )
        official_confident = top_score is not None and top_score >= search.CONFIDENT_MATCH_THRESHOLD
        confident = official_confident or bool(matched_scam)
        risky = any(s["severity"] == "attention" for s in signals)
        if not refs:
            hint = "no_source_found"
            signals.append({"key": "no_official_source", "severity": "attention"})
        elif risky:
            hint = "partially_matched"
        elif not confident:
            hint = "no_source_found"
        else:
            hint = "needs_check"

        m = mask_text(text)
        items = [i.get("type") for i in (getattr(m, "items", None) or [])]
        tier = ("danger" if ("account" in items or "card" in items)
                else "warn" if any(s["severity"] == "attention" and s["key"] in FRONT for s in signals)
                else "hold" if hint != "needs_check" else "ok")

        top20 = ranked(text, 20, drop_nia)
        ids5 = [d.id for _, d in ranked(text, 5, drop_nia)]
        cases.append({
            "id": r["case_id"], "유형": r["유형"], "위험행동": r.get("위험행동", "없음"),
            "gold_kind": kind, "기대판단": r["기대판단"],
            "hint": hint, "tier": tier, "n_refs": len(refs),
            "nia20": sum(1 for _, d in top20 if _AGENCY.get(d.id, "") == NIA),
            "n20": len(top20),
            "hit": {f"top{n}": bool(gold & set(ids5[:n])) for n in TOPKS},
            "found": bool(ids5),
            "wrong_conf": hint == "needs_check" and kind in ("doc", "none")
                          and not (gold & set(ids5)),
        })
    return summarize(cases)


def summarize(cases: list[dict]) -> dict:
    docs = [c for c in cases if c["gold_kind"] == "doc"]
    normals = [c for c in cases if c["기대판단"] == "정상"]
    warned = lambda c: c["tier"] in ("danger", "warn")   # noqa: E731
    ry = [c for c in cases if c["위험행동"] in RISK_LABELS]
    rn = [c for c in cases if c["위험행동"] == "없음"]
    ok = lambda c: (c["hint"] != "needs_check" or warned(c)) if c["기대판단"] == "의심" \
        else c["hint"] == ("needs_check" if c["기대판단"] == "정상" else "no_source_found")  # noqa: E731
    by = {}
    for t in ("정상", "사칭", "경계"):
        s = [c for c in cases if c["유형"] == t]
        by[t] = (sum(ok(c) for c in s), len(s))
    return {
        "cases": cases,
        "축1": (sum(ok(c) for c in cases), len(cases)), "by_type": by,
        "정상오판": (sum(warned(c) for c in normals), len(normals)),
        "축2있음": (sum(warned(c) for c in ry), len(ry)),
        "축2없음": (sum(warned(c) for c in rn), len(rn)),
        "doc_n": len(docs), "found": sum(c["found"] for c in docs),
        **{f"top{n}": sum(c["hit"][f"top{n}"] for c in docs) for n in TOPKS},
        "확신오답": sum(c["wrong_conf"] for c in cases),
    }


def pc(t) -> str:
    a, b = t
    return f"{a}/{b} ({a / b * 100:.1f}%)" if b else "—"


def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]


def main() -> None:
    ev, ho = load(EVAL), load(HOLD)
    print(f"OFFICIAL_DOCS={len(ci.OFFICIAL_DOCS)} · NIA={sum(1 for a in _AGENCY.values() if a == NIA)}건 "
          f"(문서는 지우지 않는다. 검색 결과에서만 제외)")

    base = run(ev, drop_nia=False)

    # ---------- 1. Top-20 후보군 점유율
    cs = base["cases"]
    tot20 = sum(c["n20"] for c in cs)
    nia20 = sum(c["nia20"] for c in cs)
    print("\n" + "=" * 70)
    print("1. Top-20 후보군에 NIA 가 몇 개 들어오는가 (확대 112건)")
    print("=" * 70)
    print(f"  후보 총 {tot20}개 중 NIA {nia20}개 = {nia20 / tot20 * 100:.1f}%")
    print(f"  케이스당 평균 {nia20 / len(cs):.2f}개 / 20")
    print(f"  NIA 가 1개 이상 낀 케이스: {sum(1 for c in cs if c['nia20'])}/{len(cs)}건")
    print(f"  분포: {dict(sorted(Counter(c['nia20'] for c in cs).items()))}")

    # ---------- 2. 실패 케이스에서 더 높은가
    print("\n" + "=" * 70)
    print("2. Top-5 실패 케이스에서 NIA 점유가 더 높은가 (doc 라벨)")
    print("=" * 70)
    docs = [c for c in cs if c["gold_kind"] == "doc"]
    succ = [c for c in docs if c["hit"]["top5"]]
    fail = [c for c in docs if not c["hit"]["top5"]]
    for name, grp in (("Top-5 성공", succ), ("Top-5 실패", fail)):
        if grp:
            print(f"  {name} {len(grp):3}건: 케이스당 NIA 평균 "
                  f"{sum(c['nia20'] for c in grp) / len(grp):.2f}개  "
                  f"(1개 이상 낀 비율 {sum(1 for c in grp if c['nia20']) / len(grp) * 100:.0f}%)")

    # ---------- 3. NIA 제외 재측정
    print("\n" + "=" * 70)
    print("3. NIA 를 검색 대상에서만 제외하고 재측정")
    print("=" * 70)
    for label, rows in (("확대 112건", ev), ("홀드아웃 30건", ho)):
        b = run(rows, False)
        a = run(rows, True)
        print(f"\n  ── {label}")
        print(f"     {'지표':22} {'현재':>18} {'NIA 제외':>18}")
        for k, name in (("축1", "축1 판정"), ("정상오판", "정상 오판"),
                        ("축2있음", "축2 위험행동 있음"), ("축2없음", "축2 위험행동 없음")):
            print(f"     {name:22} {pc(b[k]):>18} {pc(a[k]):>18}")
        for t in ("정상", "사칭", "경계"):
            print(f"     {'  ' + t:22} {pc(b['by_type'][t]):>18} {pc(a['by_type'][t]):>18}")
        for k, name in (("found", "근거 검색 성공"), ("top1", "Top-1"), ("top3", "Top-3"), ("top5", "Top-5")):
            print(f"     {name:22} {pc((b[k], b['doc_n'])):>18} {pc((a[k], a['doc_n'])):>18}")
        print(f"     {'확신 오답근거':22} {b['확신오답']:>18}건 {a['확신오답']:>17}건")


if __name__ == "__main__":
    main()
