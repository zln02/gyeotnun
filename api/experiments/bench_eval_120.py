"""확대 평가셋 기준선 측정 (2026-08-11)
실행: docker compose exec api python3 experiments/bench_eval_120.py

★ 프로덕션 코드를 고치지 않는다. services/ 의 함수를 호출만 한다.
★ 임계값(EMBEDDING_MIN_SCORE=0.6155)을 건드리지 않는다.
★ 이 스크립트는 '지금 상태'를 재는 자다. 좋게 보이려고 조건을 바꾸지 않는다.

■ 2축으로 따로 잰다. 합치지 않는다.
  축1 판정  기대판단(정상/의심/확인불가)과 시스템 verdict_hint 가 맞는가
  축2 안전  위험행동이 있는 건에서 위험 경고(severity=attention)가 떴는가

  두 축을 합치면 안 되는 이유: 경계 40건은 기대판단이 전부 '확인불가'라,
  판정만 재면 시스템이 위험 경고를 올바로 띄워도 점수가 안 붙고 조용히
  확인불가만 내도 만점이 된다. 기준이 거꾸로가 된다.

■ 음성 8건은 제외한다(기획서 2.3 대로 본선 대상). 120 - 8 = 112건 기준.

■ ★★ 이 스크립트의 '경고'는 전부 **신호 기준**이다 — 화면 tier 가 아니다 ★★
  여기서 세는 것은 `severity == "attention"` 신호가 붙었는가뿐이다.
  화면은 그 신호를 그대로 쓰지 않는다 - `web/src/verdict.js` 의 **ATTENTION_KEYS
  허용 목록**을 통과한 신호만 단계(danger/warn/act/hold/ok)를 올린다.

  실측 차이(2026-08-21): 확대셋 정상 37건 중 attention 신호 **11건**,
  그중 화면 단계를 올린 것 **2건**. 허용 목록이 9건을 막았다.

  ★ 2026-08-21 에 이 수치(11/37 = 29.7%)를 README 의 "정상 문자를 의심으로 표시"
    행에 그대로 옮겨 적는 오류가 났다. **이름이 화면을 가리키는데 값은 신호였다.**
    회귀로 오인돼 원인 추적까지 갔다. 그래서 출력 라벨에 기준을 박아 둔다.
    → 화면 기준이 필요하면 experiments/dump_screen_payloads.py +
      tools/render_verdict.mjs 로 tier 를 뽑을 것.
    기록: docs/reports/2026-08-21_정상오판_두정의_재측정.txt
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_120건.csv")
BASE_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLD_CSV = Path("/app/tests/fixtures/holdout/holdout_30.csv")
OUT = Path("/app/data/bench_eval_120.json")

TOPKS = (1, 3, 5)
MAXK = max(TOPKS)
RISK_REAL = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}   # '없음'·'확인 필요' 제외

# 기대판단 → 시스템 verdict_hint
EXPECT = {"정상": "needs_check", "의심": None, "확인불가": "no_source_found"}


# ==================================================== 정답 라벨 (exp_query_rewrite 와 동일 규칙)
def url_key(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return ""
    if not p.netloc:
        return ""
    base = (p.netloc.lower().replace("www.", "") + p.path.rstrip("/")).lower()
    return f"{base}?{p.query}" if p.query else base


def is_portal_home(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return bool(p.netloc) and p.path.rstrip("/") == "" and not p.query


_DOC_BY_KEY: dict[str, list] = defaultdict(list)
for _d in ci.OFFICIAL_DOCS:
    if (k := url_key(_d.source_url)):
        _DOC_BY_KEY[k].append(_d)
_SCAM_KEYS = {url_key(getattr(c, "url", "") or "") for c in ci.SCAM_CASES} - {""}


def gold_of(row: dict) -> tuple[str, set]:
    url = (row.get("출처_URL") or "").strip()
    # ★ 실사용 원문 11건은 코퍼스에 대조 문서가 없다(출처_URL 이 빈칸).
    #   '근거 없음이 정답'(none)과 섞으면 안 된다 - 성격이 다르다.
    if not url:
        return "no_ref", set()
    if is_portal_home(url):
        return "none", set()
    k = url_key(url)
    if k in _DOC_BY_KEY:
        return "doc", {d.id for d in _DOC_BY_KEY[k]}
    if k in _SCAM_KEYS:
        return "scam", set()
    return "missing", set()


# ==================================================== 실행
def run_case(row: dict) -> dict:
    text = row["평가용_제시문구"]
    kind, gold_ids = gold_of(row)

    res = search.collect_evidence(text)
    risky = any(s.get("severity") == "attention" for s in res.signals)

    try:
        ranked = [d.id for _, d in emb.match_embedding_docs(text, limit=MAXK)]
    except emb.EmbeddingUnavailableError:
        ranked = []

    expect = EXPECT.get(row["기대판단"])
    if row["기대판단"] == "의심":
        # 사칭은 '의심 쪽으로 기울었는가'로 본다. 곁눈은 판정하지 않으므로
        # needs_check(확인됨) 이 아니면서 위험 경고가 떴으면 맞은 것으로 센다.
        verdict_ok = risky or res.verdict_hint != "needs_check"
    else:
        verdict_ok = res.verdict_hint == expect

    # ★ 정상 케이스는 지표를 둘로 나눠야 한다. 합치면 해석이 틀어진다.
    #   (1) 근거확인  verdict_hint == needs_check. 코퍼스에 대조 문서가 있어야만
    #       가능하다 → 실사용 원문 11건(no_ref)은 구조적으로 달성할 수 없다.
    #   (2) 오판없음  위험 경고를 띄우지 않았는가. 팀이 써 온 "정상 오판 0건"이
    #       이쪽이다. 대조 문서 유무와 무관하게 모든 정상에 적용된다.
    #   → verdict_ok(엄격)는 그대로 두고 오판 지표를 따로 기록한다.
    #      수치를 좋게 만들려고 기준을 바꾸지 않는다. 둘 다 보고한다.
    misjudged = (row["기대판단"] == "정상") and risky

    return {
        "id": row["case_id"], "유형": row["유형"], "문구_성격": row["문구_성격"],
        "입력채널": row["입력채널"], "위험행동": row.get("위험행동", "없음"),
        "gold_kind": kind, "기대판단": row["기대판단"],
        "verdict_hint": res.verdict_hint, "verdict_ok": verdict_ok,
        "risky": risky, "misjudged": misjudged, "n_refs": len(res.references),
        "hit": {f"top{k}": bool(gold_ids & set(ranked[:k])) for k in TOPKS},
        "found_any": bool(ranked),
        # ★ 오답 근거를 두 정의로 잰다. 정의가 다르면 숫자도 다르다 - 섞지 않는다.
        #  (A) 예선 정의  '확신(needs_check) 상태로' 오답 근거를 내놨는가.
        #      prelim_final_20260810.md 3절이 쓴 정의이고 기획서 2.3 의 "0건"이 이것이다.
        #      사용자에게 "확인됐다"고 잘못 말한 건수라, 서비스 관점에서 가장 무겁다.
        #  (B) 넓은 정의  확신 여부와 무관하게, 근거를 붙였는데 정답이 없는 경우.
        "wrong_confident": res.verdict_hint == "needs_check"
                           and kind in ("doc", "none")
                           and not (gold_ids & set(ranked[:MAXK])),
        "wrong_evidence": bool(res.references) and kind == "doc"
                          and not (gold_ids & set(ranked[:MAXK])),
    }


def summarize(name: str, cases: list[dict]) -> dict:
    n = len(cases)
    docs = [c for c in cases if c["gold_kind"] == "doc"]
    risk = [c for c in cases if c["위험행동"] in RISK_REAL]
    norisk = [c for c in cases if c["위험행동"] == "없음"]

    by_type = {}
    for t in ("정상", "사칭", "경계"):
        sel = [c for c in cases if c["유형"] == t]
        by_type[t] = {"n": len(sel), "ok": sum(c["verdict_ok"] for c in sel)}

    by_lane = {}
    for lane in sorted({c["문구_성격"] for c in cases}):
        sel = [c for c in cases if c["문구_성격"] == lane]
        by_lane[lane] = {"n": len(sel), "ok": sum(c["verdict_ok"] for c in sel)}

    normals = [c for c in cases if c["기대판단"] == "정상"]
    norm_doc = [c for c in normals if c["gold_kind"] == "doc"]
    return {
        "name": name, "n": n,
        "정상_지표": {
            "오판없음": {"n": len(normals),
                         "ok": sum(1 for c in normals if not c["misjudged"])},
            "근거확인": {"n": len(norm_doc),
                         "ok": sum(1 for c in norm_doc if c["verdict_hint"] == "needs_check")},
        },
        "축1_판정": {"ok": sum(c["verdict_ok"] for c in cases), "n": n,
                     "by_type": by_type, "by_lane": by_lane},
        "축2_안전": {
            "위험행동있음": {"n": len(risk), "경고뜸": sum(c["risky"] for c in risk)},
            "위험행동없음": {"n": len(norisk), "경고뜸": sum(c["risky"] for c in norisk)},
        },
        "근거검색": {
            "doc_n": len(docs),
            "found": sum(c["found_any"] for c in docs),
            **{f"top{k}": sum(c["hit"][f"top{k}"] for c in docs) for k in TOPKS},
        },
        "잘못된_근거_제시_확신": sum(c["wrong_confident"] for c in cases),
        "잘못된_근거_제시_넓은": sum(c["wrong_evidence"] for c in cases),
        "none_확인불가정확": {
            "n": len([c for c in cases if c["gold_kind"] == "none"]),
            "ok": sum(1 for c in cases if c["gold_kind"] == "none"
                      and c["verdict_hint"] == "no_source_found"),
        },
        "gold_kind": dict(Counter(c["gold_kind"] for c in cases)),
    }


def load(p: Path, drop_voice: bool = True) -> list[dict]:
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    return [r for r in rows if not (drop_voice and r["입력채널"] == "음성")]


def base_from_expanded() -> list[dict]:
    """기존 30건은 원본 CSV 에 위험행동 컬럼이 없다. 같은 case_id 를 확대셋에서
    뽑아 쓴다(문구는 동일하고 컬럼만 채워진 상태다)."""
    ids = {r["case_id"] for r in csv.DictReader(BASE_CSV.open(encoding="utf-8-sig"))}
    return [r for r in load(EVAL_CSV) if r["case_id"] in ids]


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b * 100:.1f}%)" if b else f"{a}/0 (—)"


def report(s: dict) -> None:
    print(f"\n{'=' * 66}\n[{s['name']}]  {s['n']}건 (음성 제외)\n{'=' * 66}")
    a1 = s["축1_판정"]
    print(f"■ 축1 판정  전체 {pct(a1['ok'], a1['n'])}")
    for t, v in a1["by_type"].items():
        print(f"    {t:4} {pct(v['ok'], v['n'])}")
    print("  갈래별")
    for lane, v in a1["by_lane"].items():
        print(f"    {lane:16} {pct(v['ok'], v['n'])}")

    nm = s["정상_지표"]
    print(f"■ 정상 지표  오판없음(경고 안 뜸) {pct(nm['오판없음']['ok'], nm['오판없음']['n'])}"
          f"   근거확인(doc 한정) {pct(nm['근거확인']['ok'], nm['근거확인']['n'])}")
    print("             ★ 위 '오판없음' 은 **신호 기준 · 화면 tier 아님** — "
          "severity=attention 신호 유무만 센다.")
    print("               화면 기준이 필요하면 tools/render_verdict.mjs 로 tier 를 뽑을 것.")

    a2 = s["축2_안전"]
    print(f"■ 축2 안전  위험행동 있음 → 경고 {pct(a2['위험행동있음']['경고뜸'], a2['위험행동있음']['n'])}"
          f"   ← 신호 기준")
    print(f"             위험행동 없음 → 경고 {pct(a2['위험행동없음']['경고뜸'], a2['위험행동없음']['n'])}  "
          f"(낮을수록 좋다)  ← 신호 기준")

    g = s["근거검색"]
    print(f"■ 근거검색  doc 모수 {g['doc_n']}건")
    print(f"    검색 성공률 {pct(g['found'], g['doc_n'])}")
    for k in TOPKS:
        print(f"    Top-{k} 정답 포함 {pct(g[f'top{k}'], g['doc_n'])}")
    nn = s["none_확인불가정확"]
    print(f"■ 잘못된 근거 제시  확신 오답 {s['잘못된_근거_제시_확신']}건  ← 예선 정의, 0 유지가 가장 중요")
    print(f"                    넓은 정의 {s['잘못된_근거_제시_넓은']}건  (확신 아니어도 근거를 붙인 경우)")
    print(f"■ 확인불가 정확 처리(none)  {pct(nn['ok'], nn['n'])}")
    print(f"  라벨 분포: {s['gold_kind']}")


def main() -> None:
    print(f"OFFICIAL_DOCS={len(ci.OFFICIAL_DOCS)}  SCAM_CASES={len(ci.SCAM_CASES)}")
    print(f"임계값 EMBEDDING_MIN_SCORE={emb.EMBEDDING_MIN_SCORE} (변경 없음)")

    sets = [
        ("평가셋 112건(확대)", load(EVAL_CSV)),
        ("기존 30건(예선 비교선)", base_from_expanded()),
        ("홀드아웃 30건", load(HOLD_CSV)),
    ]
    out = {}
    for name, rows in sets:
        cases = [run_case(r) for r in rows]
        s = summarize(name, cases)
        report(s)
        out[name] = {"summary": s, "cases": cases}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
