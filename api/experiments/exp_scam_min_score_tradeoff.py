"""(a) 정상 케이스 사기사례 점수 분포 + (b) min_score 손익표  (2026-08-13)

실행: docker compose exec api python3 experiments/exp_scam_min_score_tradeoff.py

★ 재는 자다. services/ 를 고치지 않는다. 채택을 제안하지 않는다. 표만 낸다.
★ 임계값(EMBEDDING_MIN_SCORE=0.6155 / CONFIDENT=0.6790)은 건드리지 않는다.
  이 스크립트가 움직이는 것은 match_scam_cases 의 min_score 하나뿐이다.

■ (a) 무엇을 재는가
  match_scam_cases 는 게이트(수법 카테고리) → 어휘 하한선(min_score) 순으로 거른다.
  하한선을 정하려면 "정상 문자가 실제로 몇 점을 받는가"를 알아야 하는데,
  match_scam_cases 는 통과/탈락만 돌려주고 점수를 돌려주지 않는다.
  그래서 같은 계산을 여기서 다시 해서 **점수 자체**를 뽑는다(읽기만 한다).

  ★ 뽑는 값은 '게이트를 통과한 사례들 중 최대 어휘점수'다. 하한선은 사례마다
    개별 적용되므로, 최댓값이 하한선 미만이면 그 글은 매칭 0건이 된다.
    match_scam_cases 가 정렬 1순위로 쓰는 수법일치 개수와는 다른 축이라
    "최고점 사례 = 반환되는 사례"는 아니다. 하한선 판단에는 최댓값이 맞다.

  N=51  현재 운영값(relabeled 30 + public_data_warning 21)
  N=185 경보문(warning_case) 134건을 SCAM_CASES 로 옮겼을 경우의 가정값.
        ★ 이설은 채택하지 않았다(docs/evaluation/경보문_이설_시뮬레이션_2026-08-12.md).
          척도가 얼마나 움직이는지 보기 위한 비교 기준으로만 쓴다.

■ (b) 손익표
  min_score 를 5.0 / 6.75 / 9.0 / 11.0 / 13.0 으로 두고 네 지표를 함께 잰다.
  하나만 보면 반드시 틀린다 - 하한선을 올리면 정상 오판은 줄지만 사칭 검출도 준다.
    정상 오판   기대판단이 정상인데 화면이 경고(빨강/주황경고)로 나간 건수 ← 낮을수록 좋다
    사칭 경고   유형이 사칭인데 경고로 나간 건수                        ← 높을수록 좋다
    축2 있음    위험행동이 실제로 있는 건에서 경고가 뜬 비율            ← 높을수록 좋다
    축2 없음    위험행동이 없는 건에서 경고가 뜬 비율(헛경고)           ← 낮을수록 좋다

  ★ 화면 기준으로 센다. 서버 severity=attention 을 그대로 세면 안 된다 -
    verdict.js 는 attention 신호 중 ATTENTION_KEYS 에 있는 것만 경고로 올린다
    (no_official_source 는 경고가 아니다). 2026-08-12 배포분 기준으로 맞췄다.
"""
from __future__ import annotations

import collections
import csv
import functools
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402
from services import search  # noqa: E402
from services.corpus_index import ScamCase  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")

# verdict.js ATTENTION_KEYS 와 1:1 (2026-08-12 배포분)
FRONT_KEYS = {"similar_scam_case", "urgency_pressure", "condition_omitted",
              "official_alert_matched"}
RISK_REAL = {"계좌이체", "앱설치", "인증번호", "개인정보요구"}
THRESHOLDS = (5.0, 6.75, 9.0, 11.0, 13.0)


def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]


SETS = [("확대 평가셋 112건", load(EVAL)), ("홀드아웃 30건", load(HOLD))]


# ══════════════════════════════════════════════ SCAM_CASES 규모 바꾸기 (메모리에서만)
_RECS: dict = {}
for _p in glob.glob("/corpus/public_data/gyeotnun_data/records_*.jsonl"):
    for _l in open(_p, encoding="utf-8"):
        _r = json.loads(_l)
        _RECS[_r["id"]] = _r

_ORIG_SCAM = list(ci.SCAM_CASES)
_WARN_DOCS = sorted(
    [d for d in ci.OFFICIAL_DOCS if _RECS.get(d.id, {}).get("data_type") == "warning_case"],
    key=lambda d: d.id,
)


def _as_case(doc) -> ScamCase:
    r = _RECS[doc.id]
    return ScamCase(
        id=doc.id, text=(r.get("content") or "")[:4000], source_label=r.get("source_agency", ""),
        url=r.get("source_url", ""), published_at=r.get("published_at"), risk_clues=[],
        error_types=[], questions=[], rationale="", origin="public_data_warning",
        _blob=f"{r.get('title', '')} {r.get('content', '')}",
    )


def set_n(n: int) -> None:
    """SCAM_CASES 규모를 n 으로 맞춘다.

    ★ 캐시를 반드시 함께 비운다. _scam_substring_df 는 @lru_cache 이고 SCAM_CASES 를
      직접 훑는다. 8/12 시뮬레이션에서 이걸 빠뜨려 df 는 옛날 값, N 은 새 값으로
      섞인 채 점수가 부풀었고 결론이 뒤집혔다(같은 실수를 반복하지 않는다).
    """
    add = [_as_case(d) for d in _WARN_DOCS[:max(0, n - len(_ORIG_SCAM))]]
    ci.SCAM_CASES[:] = _ORIG_SCAM + add
    ci._SCAM_DOC_FREQ.clear()
    ci._SCAM_DOC_FREQ.update(ci._doc_freq([c._blob for c in ci.SCAM_CASES]))
    ci._SCAM_N_DOCS = len(ci.SCAM_CASES)
    ci._scam_substring_df.cache_clear()
    ci._case_categories.cache_clear()


# ══════════════════════════════════════════════ (a) 점수 뽑기
def top_lexical(text: str) -> tuple[str, float, str, list]:
    """match_scam_cases 와 같은 순서로 계산하되 점수를 돌려준다.

    반환: (상태, 최대어휘점수, 최고점 사례 id, 겹친 단어들)
      상태 no_keyword  키워드가 하나도 안 남음
           gate        사용자 글이 아무 수법도 요구하지 않음 → 대조 자체를 안 한다
           no_pair     게이트는 통과했지만 수법이 겹치는 사례가 없음
           scored      점수 있음
    """
    kws = [k for k in ci.extract_keywords(text) if k not in ci.STOPWORDS]
    if not kws:
        return "no_keyword", 0.0, "", []
    text_cats = ci.scam_taxonomy.detect_categories(text)
    if not text_cats:
        return "gate", 0.0, "", []

    best, best_id, best_words = 0.0, "", []
    for case in ci.SCAM_CASES:
        case_cats = ci._case_categories(case.id)
        if not case_cats or not (text_cats & case_cats):
            continue
        matched = ci._dedup_morph_variants([k for k in kws if k in case._blob])
        if not matched:
            continue
        lex = sum(ci._keyword_weight(k) for k in matched)
        if lex > best:
            best, best_id, best_words = lex, case.id, matched
    if not best_id:
        return "no_pair", 0.0, "", []
    return "scored", best, best_id, best_words


BUCKETS = [(0.0, 3.0), (3.0, 5.0), (5.0, 6.75), (6.75, 9.0), (9.0, 11.0),
           (11.0, 13.0), (13.0, 1e9)]


def bucket_of(v: float) -> int:
    for i, (lo, hi) in enumerate(BUCKETS):
        if lo <= v < hi:
            return i
    return len(BUCKETS) - 1


def part_a() -> None:
    print("=" * 78)
    print("(a) 사기사례 어휘점수 분포 — 게이트 통과분의 최댓값")
    print("=" * 78)
    for n in (51, 185):
        set_n(n)
        print(f"\n■ N = {n}  (SCAM_CASES {len(ci.SCAM_CASES)}건)")
        for label, rows in SETS:
            for grp, sel in (("정상", [r for r in rows if r["기대판단"] == "정상"]),
                             ("사칭", [r for r in rows if r["유형"] == "사칭"])):
                if not sel:
                    continue
                res = [(r["case_id"], *top_lexical(r["평가용_제시문구"])) for r in sel]
                st = collections.Counter(x[1] for x in res)
                scored = [x for x in res if x[1] == "scored"]
                hist = [0] * len(BUCKETS)
                for x in scored:
                    hist[bucket_of(x[2])] += 1
                head = "  ".join(
                    f"{lo:g}~{'∞' if hi > 1e8 else f'{hi:g}'}:{c}"
                    for (lo, hi), c in zip(BUCKETS, hist))
                mx = max((x[2] for x in scored), default=0.0)
                print(f"  [{label} / {grp} {len(sel)}건] 게이트탈락 {st['gate'] + st['no_keyword']}"
                      f" · 짝없음 {st['no_pair']} · 점수있음 {len(scored)} · 최고 {mx:.2f}")
                print(f"      {head}")
                for cid, s, v, case_id, words in sorted(scored, key=lambda x: -x[2])[:6]:
                    print(f"      {cid:>5} {v:6.2f}  ← {case_id} {words}")
    set_n(51)


# ══════════════════════════════════════════════ (b) 손익표
def tier_of(text: str) -> str:
    """verdict.js judgmentState 의 tier 계산을 그대로 옮긴 것(2026-08-12 배포분)."""
    res = search.collect_evidence(text)
    m = mask_text(text)
    types = [i.get("type") for i in (getattr(m, "items", None) or [])]
    if "account" in types or "card" in types:
        return "danger"
    if any(s.get("severity") == "attention" and s.get("key") in FRONT_KEYS
           for s in res.signals):
        return "warn"
    if res.verdict_hint != "needs_check":
        return "hold"
    return "ok"


def part_b() -> None:
    print()
    print("=" * 78)
    print("(b) min_score 손익표 — N=51 (현재 운영 상태, 이설 없음)")
    print("=" * 78)
    orig = ci.match_scam_cases
    set_n(51)
    for label, rows in SETS:
        nor = [r for r in rows if r["기대판단"] == "정상"]
        sc = [r for r in rows if r["유형"] == "사칭"]
        ry = [r for r in rows if r.get("위험행동") in RISK_REAL]
        rn = [r for r in rows if r.get("위험행동") == "없음"]
        print(f"\n■ [{label}]  정상 {len(nor)} · 사칭 {len(sc)} · 위험행동있음 {len(ry)} · 없음 {len(rn)}")
        print(f"  {'min_score':>10}{'정상 오판':>12}{'사칭 경고':>12}"
              f"{'축2 있음':>12}{'축2 없음':>12}   {'현재 대비 tier 변경'}")
        base_tiers = None
        for th in THRESHOLDS:
            ci.match_scam_cases = functools.partial(orig, min_score=th)
            tiers = {r["case_id"]: tier_of(r["평가용_제시문구"]) for r in rows}
            if base_tiers is None:
                base_tiers = dict(tiers)
            def n_warn(sel: list[dict]) -> str:
                hit = sum(1 for r in sel if tiers[r["case_id"]] in ("danger", "warn"))
                return f"{hit}/{len(sel)}"

            chg = [f"{cid} {base_tiers[cid]}→{tiers[cid]}"
                   for cid in tiers if tiers[cid] != base_tiers[cid]]
            print(f"  {th:>10.2f}{n_warn(nor):>12}{n_warn(sc):>12}"
                  f"{n_warn(ry):>12}{n_warn(rn):>12}"
                  f"   {', '.join(chg) if chg else '-'}")
    ci.match_scam_cases = orig


if __name__ == "__main__":
    print(f"OFFICIAL_DOCS={len(ci.OFFICIAL_DOCS)}  SCAM_CASES(원본)={len(_ORIG_SCAM)}  "
          f"warning_case={len(_WARN_DOCS)}")
    part_a()
    part_b()
    print("\n※ 채택 제안 없음. 하한선은 사람이 정한다.")
