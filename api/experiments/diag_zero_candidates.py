"""후보 0개 43건의 원인 진단 (2026-08-12) — 진단만. 아무것도 고치지 않는다.
실행: docker compose exec api python3 experiments/diag_zero_candidates.py

■ 왜
  "임계 통과 후보 0개" 는 세 원인이 가능하고, 처방이 전혀 다르다.
    ① 문서 부재     → 수집으로만 풀린다
    ② 임계값이 높음 → 상수 하나
    ③ 질의 품질     → 검색어 생성 방식
  ②③ 이면 수집을 아무리 해도 안 풀리므로 순서를 먼저 정해야 한다.

★ 라벨 누수 주의
  정답(출처_URL → 문서 id)은 **진단에만** 쓴다. 이 결과를 보고 임계값이나
  질의 생성 규칙을 고치지 않는다. 고칠 근거는 별도로 세워야 한다.
  그래서 이 스크립트는 services/ 를 건드리지 않고 읽기만 한다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")

from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services.scam_taxonomy import describe_categories  # noqa: E402
from services.search import detect_risk_action  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
THRESH = emb.EMBEDDING_MIN_SCORE          # 0.6155 — 읽기만 한다
NEAR_LO = 0.55                            # '바로 아래' 구간 하한
TOP = 20


# ---------------------------------------------------------------- 정답 라벨
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


# ---------------------------------------------------------------- 질의 3종
# exp_query_rewrite.py 의 규칙 기반 추출을 그대로 옮겼다(새 규칙을 만들지 않는다).
_AGENCIES = sorted({(d.source_agency or "").strip() for d in ci.OFFICIAL_DOCS} - {""},
                   key=len, reverse=True)
_ALIASES = ["국민건강보험공단", "건강보험공단", "한국사회보장정보원", "보건복지부", "질병관리청",
            "행정안전부", "경찰청", "금융감독원", "금융위원회", "국세청", "국민연금공단",
            "근로복지공단", "소상공인시장진흥공단", "정부24", "복지로", "주민센터", "시청", "구청"]
_SUFFIX = ["지원금", "환급금", "급여", "수당", "바우처", "보조금", "장려금", "대출", "융자",
           "연금", "보험료", "검진", "예방접종", "지원사업", "서비스"]


def find_agency(t: str) -> list[str]:
    hits = [a for a in _ALIASES if a in t]
    hits += [a for a in _AGENCIES if a and a in t and a not in hits]
    return hits[:2]


def find_program(t: str) -> list[str]:
    words = t.replace("\n", " ").split()
    out, seen = [], set()
    for i, w in enumerate(words):
        if any(s in w for s in _SUFFIX):
            ph = ((words[i - 1] + " " + w) if i > 0 else w).strip(".,·/")
            if ph not in seen:
                seen.add(ph)
                out.append(ph)
    return out[:2]


def q_current(t: str) -> str:
    return t                                    # (가) 지금 코드가 넣는 그대로(원문)


def q_agency_program(t: str) -> str:            # (나) 기관명 + 제도명만
    parts = find_agency(t) + find_program(t)
    return " ".join(parts) if parts else t


def q_agency_action(t: str) -> str:             # (다) 기관명 + 요구행동
    parts = find_agency(t)
    act = detect_risk_action(t)
    if act:
        parts.append(act)
    topic = sorted(describe_categories(t))
    parts += topic[:1]
    return " ".join(parts) if parts else t


def rank_of(text: str, gold: set) -> tuple[int | None, float | None, list]:
    """임계값을 걷어낸 순수 코사인 Top-20 에서 정답 순위와 점수."""
    hits = emb.match_embedding_docs(text, limit=TOP, min_score=-1.0)
    for i, (sc, d) in enumerate(hits, 1):
        if d.id in gold:
            return i, sc, hits
    return None, None, hits


# ---------------------------------------------------------------- 실행
rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]

zero = []
for r in rows:
    if not emb.match_embedding_docs(r["평가용_제시문구"], limit=TOP):
        zero.append(r)

print(f"임계값 EMBEDDING_MIN_SCORE={THRESH} (읽기만 함)")
print(f"후보 0개 케이스: {len(zero)}건 / 전체 {len(rows)}건\n")
print("구성:", dict(Counter(r["유형"] for r in zero)),
      "| 라벨:", dict(Counter(gold_of(r)[0] for r in zero)))

# ================================================== 진단 1 — 임계값
print("\n" + "=" * 74)
print("진단 1 — 임계값을 걷어낸 순수 코사인 Top-20 에 정답이 있는가")
print("=" * 74)
docs_zero = [r for r in zero if gold_of(r)[0] == "doc"]
print(f"대상: 후보 0개 중 doc 라벨 {len(docs_zero)}건 "
      f"(나머지는 대조할 정답 문서가 애초에 없다)\n")

near, found, absent = [], [], []
for r in docs_zero:
    kind, gold = gold_of(r)
    rk, sc, hits = rank_of(r["평가용_제시문구"], gold)
    top1 = hits[0][0] if hits else 0.0
    if rk is None:
        absent.append((r, top1))
    else:
        found.append((r, rk, sc, top1))
        if NEAR_LO <= sc < THRESH:
            near.append((r, rk, sc))

print(f"(a) 정답이 Top-20 안에 있는가 : {len(found)}/{len(docs_zero)}건")
print(f"(c) 그중 0.55~{THRESH} 구간   : {len(near)}건")
print(f"    Top-20 밖 (정답 못 찾음)  : {len(absent)}건\n")
if found:
    print("  (b) 정답이 잡힌 건 — 순위·점수")
    for r, rk, sc, t1 in sorted(found, key=lambda x: -x[2]):
        flag = "★임계근처" if NEAR_LO <= sc < THRESH else ""
        print(f"     {r['case_id']:5} {rk:2}위 {sc:.4f} (Top1 {t1:.4f}) {flag}")
if absent:
    print("\n  Top-20 밖 — 정답 문서에 아예 못 닿음")
    for r, t1 in absent[:12]:
        print(f"     {r['case_id']:5} Top1 {t1:.4f}  {r['평가용_제시문구'][:40]}")

# ================================================== 진단 2 — 질의
print("\n" + "=" * 74)
print("진단 2 — 질의 3종 비교 (정답 순위 / 점수)")
print("=" * 74)
print(f"{'case':6}{'(가) 원문':>18}{'(나) 기관+제도':>20}{'(다) 기관+행동':>20}")
print("-" * 74)
win = Counter()
for r in docs_zero:
    _, gold = gold_of(r)
    cells = []
    best, bestq = -1.0, None
    for tag, fn in (("가", q_current), ("나", q_agency_program), ("다", q_agency_action)):
        rk, sc, hits = rank_of(fn(r["평가용_제시문구"]), gold)
        cells.append(f"{rk}위 {sc:.4f}" if rk else f"- {(hits[0][0] if hits else 0):.4f}")
        if sc is not None and sc > best:
            best, bestq = sc, tag
    win[bestq or "없음"] += 1
    print(f"{r['case_id']:6}{cells[0]:>18}{cells[1]:>20}{cells[2]:>20}")
print(f"\n  질의별 최고점 승수: {dict(win)}")
print(f"  ('-' 는 Top-20 밖. 옆 숫자는 그 질의의 Top-1 점수)")

# ================================================== 진단 3 — 사칭
print("\n" + "=" * 74)
print("진단 3 — 사칭 문자의 정답 문서가 코퍼스에 있는가")
print("=" * 74)
scam_all = [r for r in rows if r["유형"] == "사칭"]
scam_zero = [r for r in zero if r["유형"] == "사칭"]
print(f"사칭 {len(scam_all)}건 중 후보 0개: {len(scam_zero)}건")
print(f"  후보 0개 사칭의 라벨 분포: {dict(Counter(gold_of(r)[0] for r in scam_zero))}")
print(f"  전체 사칭의 라벨 분포    : {dict(Counter(gold_of(r)[0] for r in scam_all))}")
print("\n  ※ 사칭 케이스의 출처_URL 은 '사칭당한 제도의 진짜 안내문'이 아니라")
print("     그 수법이 실린 공개 경보문이다(수집 설계상). 즉 사칭 문자를 정상")
print("     제도 원문과 대조하는 구조가 애초에 없다.")
for r in scam_zero[:10]:
    k, _ = gold_of(r)
    print(f"     {r['case_id']:5} [{k:6}] {r['참고_출처'][:30]:32} {r['평가용_제시문구'][:34]}")

# ================================================== 분류표
print("\n" + "=" * 74)
print("43건 원인 분류")
print("=" * 74)
bucket: dict[str, list] = {"① 문서 부재": [], "② 임계값": [], "③ 질의": [], "복합": [], "해당없음": []}
for r in zero:
    kind, gold = gold_of(r)
    if kind != "doc":
        bucket["해당없음"].append((r["case_id"], f"{kind} — 대조할 정답 문서가 없는 라벨"))
        continue
    rk, sc, _ = rank_of(r["평가용_제시문구"], gold)
    rk2, sc2, _ = rank_of(q_agency_program(r["평가용_제시문구"]), gold)
    rk3, sc3, _ = rank_of(q_agency_action(r["평가용_제시문구"]), gold)
    best_q = max([s for s in (sc2, sc3) if s is not None], default=None)
    if rk is None and best_q is None:
        bucket["① 문서 부재"].append((r["case_id"], "세 질의 모두 Top-20 밖"))
    elif sc is not None and NEAR_LO <= sc < THRESH:
        if best_q is not None and best_q >= THRESH:
            bucket["복합"].append((r["case_id"], f"원문 {sc:.4f}(임계근처)인데 질의 바꾸면 {best_q:.4f}로 통과"))
        else:
            bucket["② 임계값"].append((r["case_id"], f"원문 {sc:.4f} — 0.55~{THRESH} 구간"))
    elif rk is None and best_q is not None:
        bucket["③ 질의"].append((r["case_id"], f"원문은 Top-20 밖, 질의 바꾸면 {best_q:.4f}"))
    elif sc is not None:
        bucket["복합"].append((r["case_id"], f"원문 {sc:.4f} — 0.55 미만이라 임계만의 문제 아님"))
    else:
        bucket["복합"].append((r["case_id"], "판단 애매"))

for k, v in bucket.items():
    print(f"\n[{k}] {len(v)}건")
    for cid, why in v[:14]:
        print(f"   {cid:6} {why}")
    if len(v) > 14:
        print(f"   … 외 {len(v) - 14}건")
