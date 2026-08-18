"""사칭 재라벨 반영 + 분모 수정 + 하한선 실험 (2026-08-12)
실행: docker compose exec api python3 experiments/exp_relabel_threshold.py

★ services/ 를 고치지 않는다. 읽기만 하고 실험 안에서만 임계를 바꿔 본다.
★ 확신선(CONFIDENT_MATCH_THRESHOLD=0.679)은 건드리지 않는다. 하한선만 본다.

■ 1 사칭 재라벨 반영
  사칭의 정답근거를 doc(사칭당한 제도의 진짜 안내문) / scam(수법 경보문)으로 나눈다.
  corpus/사칭_정답근거_재라벨_2026-08-12.csv 를 읽어 덮어쓴다(원본 CSV 는 그대로).

■ 2 분모 수정
  근거 검색 성공률의 분모에 scam·none·no_ref 가 섞여 있었다. 이들은 공식문서를
  못 찾는 게 정상이라, 실사용 문자가 늘수록 수치가 자동으로 나빠지는 구조였다.
  분모를 doc 라벨로 한정하고 구 방식과 나란히 낸다.

■ 3 하한선 실험
  0.6155(현재) / 0.60 / 0.58 / 0.55 각각에 대해
    · doc 근거 검색 성공률
    · ★ 확신(0.679) 이상 오답 — 1건이라도 늘면 그 값은 기각
    · 하한~확신 구간의 오답 건수 — 새로 생기는 비용
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")
RELABEL = Path("/corpus/사칭_정답근거_재라벨_2026-08-12.csv")
CONF = search.CONFIDENT_MATCH_THRESHOLD          # 0.679 — 읽기만
CUR = emb.EMBEDDING_MIN_SCORE                    # 0.6155 — 읽기만
CANDS = [CUR, 0.60, 0.58, 0.55]
MAXK = 5


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


def base_gold(row: dict) -> tuple[str, set]:
    """구 라벨 — 출처_URL 하나로 판정."""
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


RE: dict[str, dict] = {}
if RELABEL.exists():
    RE = {r["case_id"]: r for r in csv.DictReader(RELABEL.open(encoding="utf-8-sig"))}


def new_gold(row: dict) -> tuple[str, set]:
    """신 라벨 — 사칭은 재라벨 표를 따른다. 나머지는 구 라벨과 같다."""
    cid = row["case_id"]
    if row["유형"] == "사칭" and cid in RE:
        du = (RE[cid].get("정답doc_URL") or "").strip()
        if du:
            ids = {d.id for d in _DOC_BY_KEY.get(url_key(du), [])}
            if ids:
                return "doc", ids
        return "scam_only", set()      # doc 정답이 없음 → 공식문서 검색 모수에서 제외
    return base_gold(row)


def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]


def measure(rows: list[dict], gold_fn, min_score: float) -> dict:
    doc_n = found = hit = 0
    conf_wrong = band_wrong = 0
    all_n = all_found = 0
    for r in rows:
        kind, gold = gold_fn(r)
        hits = emb.match_embedding_docs(r["평가용_제시문구"], limit=MAXK, min_score=min_score)
        ids = [d.id for _, d in hits]
        top = hits[0][0] if hits else None

        all_n += 1
        if ids:
            all_found += 1
        if kind == "doc":
            doc_n += 1
            if ids:
                found += 1
            if gold & set(ids):
                hit += 1
        # ---- 오답 비용: 근거를 붙였는데 정답이 아닌 경우
        if ids and not (gold & set(ids)):
            if top is not None and top >= CONF:
                conf_wrong += 1
            elif top is not None and top >= min_score:
                band_wrong += 1
    return {"doc_n": doc_n, "found": found, "hit": hit,
            "all_n": all_n, "all_found": all_found,
            "conf_wrong": conf_wrong, "band_wrong": band_wrong}


def pc(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b * 100:.1f}%)" if b else "—"


def main() -> None:
    ev, ho = load(EVAL), load(HOLD)
    print(f"하한 현재={CUR} · 확신={CONF}(건드리지 않음) · 재라벨표 {len(RE)}건 로드")

    # ---------------- 1·2. 라벨/분모
    print("\n" + "=" * 78)
    print("1·2. 사칭 재라벨 + 분모 수정 (하한 현재값 유지)")
    print("=" * 78)
    for name, rows in (("확대 112건", ev), ("홀드아웃 30건", ho)):
        old = measure(rows, base_gold, CUR)
        new = measure(rows, new_gold, CUR)
        print(f"\n  ── {name}")
        print(f"     {'':30}{'구 라벨':>20}{'신 라벨':>20}")
        print(f"     {'doc 모수':30}{old['doc_n']:>20}{new['doc_n']:>20}")
        print(f"     {'근거 검색 성공률(doc 분모)':30}"
              f"{pc(old['found'], old['doc_n']):>20}{pc(new['found'], new['doc_n']):>20}")
        print(f"     {'Top-5 정답 포함(doc 분모)':30}"
              f"{pc(old['hit'], old['doc_n']):>20}{pc(new['hit'], new['doc_n']):>20}")
        print(f"     {'(구 방식) 전체 분모 성공률':30}"
              f"{pc(old['all_found'], old['all_n']):>20}{pc(new['all_found'], new['all_n']):>20}")
        print(f"     {'확신 오답':30}{old['conf_wrong']:>20}{new['conf_wrong']:>20}")

    # ---------------- 3. 하한선
    print("\n" + "=" * 78)
    print("3. 하한선 실험 (신 라벨 기준, 확신선 0.679 고정)")
    print("=" * 78)
    for name, rows in (("확대 112건", ev), ("홀드아웃 30건", ho)):
        base = measure(rows, new_gold, CUR)
        print(f"\n  ── {name}   (doc 모수 {base['doc_n']}건)")
        print(f"     {'하한':>8}{'검색 성공률':>18}{'Top-5':>18}"
              f"{'확신오답':>10}{'구간오답':>10}")
        for th in CANDS:
            m = measure(rows, new_gold, th)
            tag = " ←현재" if th == CUR else ""
            verdict = ""
            if th != CUR and m["conf_wrong"] > base["conf_wrong"]:
                verdict = "  ★기각(확신오답 증가)"
            print(f"     {th:>8.4f}{pc(m['found'], m['doc_n']):>18}"
                  f"{pc(m['hit'], m['doc_n']):>18}"
                  f"{m['conf_wrong']:>10}{m['band_wrong']:>10}{tag}{verdict}")


if __name__ == "__main__":
    main()
