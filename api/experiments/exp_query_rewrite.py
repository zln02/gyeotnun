"""작업2 - 질의 재작성 / RRF 하이브리드 실험 (2026-08-09)
실행: docker compose exec api python3 experiments/exp_query_rewrite.py [--no-llm]

★ 프로덕션 코드를 고치지 않는다. 검색 함수를 호출만 한다(실험 모듈).
★ 임계값(EMBEDDING_MIN_SCORE=0.6155)을 절대 낮추지 않는다 - 지시 사항.
   성공률은 임계를 내리면 언제든 올라가지만 오답 근거가 같이 늘어난다.

비교하는 질의/검색 방식
  A baseline      원문 질의 + 임베딩 단독            (현행 프로덕션)
  B rrf           원문 질의 + BM25·임베딩 RRF 병합    (지시 1: 소규모 확인)
  C rewrite_rule  규칙 기반 재작성 질의 + 임베딩       (지시 2: 본명)
  D rewrite_llm   LLM 추출 재작성 질의 + 임베딩        (지시 2: 본명)

지표 (지시 4: 성공률보다 오답 근거가 중요하다)
  · 근거 검색 성공률      references >= 1
  · top-3 정답 포함률     정답 문서가 상위 3위 안에 있는가
  · ★ 오답 근거 제시 건수  근거를 붙였는데 그중 정답이 하나도 없는 케이스
  · 확인불가 정확 처리율   정답 근거가 '문서 없음'인 케이스에서 근거를 안 붙였는가

정답 라벨 3종 (작업1 지시 반영)
  doc   평가셋 출처_URL 이 공식문서 인덱스의 문서를 가리킨다  → 찾아야 성공
  scam  출처_URL 이 SCAM_CASES 로 이관된 경보문이다          → 공식문서 검색 대상 아님
  none  출처_URL 이 포털 홈(경로 없음)이다                    → 근거 없음이 정답
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")

from config import settings  # noqa: E402
from services import corpus_index as ci  # noqa: E402
from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402
from services.scam_taxonomy import describe_categories  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
OUT = Path("/app/data/exp_query_rewrite.json")
TOPK = 3


# ==================================================== 정답 라벨
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
    """경로가 없는 포털 첫 화면(bokjiro.go.kr, gov.kr 등)."""
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return bool(p.netloc) and p.path.rstrip("/") == "" and not p.query


_DOC_BY_KEY: dict[str, list] = {}
for _d in ci.OFFICIAL_DOCS:
    k = url_key(_d.source_url)
    if k:
        _DOC_BY_KEY.setdefault(k, []).append(_d)
_SCAM_KEYS = {url_key(getattr(c, "url", "") or "") for c in ci.SCAM_CASES}
_SCAM_KEYS.discard("")


def gold_of(row: dict) -> tuple[str, set]:
    """(라벨종류, 정답 문서 id 집합)"""
    url = (row.get("출처_URL") or "").strip()
    if is_portal_home(url):
        return "none", set()
    k = url_key(url)
    if k in _DOC_BY_KEY:
        return "doc", {d.id for d in _DOC_BY_KEY[k]}
    if k in _SCAM_KEYS:
        return "scam", set()
    # ★ 포털 홈이 아닌데 어느 인덱스에서도 못 찾은 경우. '근거 없음이 정답'(none)과
    #   섞으면 안 된다 - 이건 코퍼스에 정답이 빠진 것(커버리지 결손)이다.
    return "missing", set()


# ==================================================== 질의 재작성
# 코퍼스에 실제로 존재하는 기관명만 사전으로 쓴다(창작하지 않는다).
_AGENCIES = sorted({(d.source_agency or "").strip() for d in ci.OFFICIAL_DOCS} - {""},
                   key=len, reverse=True)
# 흔히 사칭당하는 기관/포털 표기(코퍼스 기관명과 표기가 달라 별도로 둔다)
_AGENCY_ALIASES = [
    "국민건강보험공단", "건강보험공단", "한국사회보장정보원", "보건복지부", "질병관리청",
    "행정안전부", "경찰청", "금융감독원", "금융위원회", "국세청", "국민연금공단",
    "근로복지공단", "소상공인시장진흥공단", "정부24", "복지로", "주민센터", "시청", "구청",
]
# 제도·급여 이름에 붙는 말머리. 이 앞뒤 어절을 제도명 후보로 본다.
_PROGRAM_SUFFIX = ["지원금", "환급금", "급여", "수당", "바우처", "보조금", "장려금",
                   "대출", "융자", "연금", "보험료", "검진", "예방접종", "지원사업", "서비스"]


def _find_agency(text: str) -> list[str]:
    hits = [a for a in _AGENCY_ALIASES if a in text]
    hits += [a for a in _AGENCIES if a and a in text and a not in hits]
    return hits[:2]


def _find_program(text: str) -> list[str]:
    """제도명 후보: '…지원금/환급금/…' 을 포함한 어절 + 앞 어절."""
    words = text.replace("\n", " ").split()
    out = []
    for i, w in enumerate(words):
        for suf in _PROGRAM_SUFFIX:
            if suf in w:
                phrase = (words[i - 1] + " " + w) if i > 0 else w
                out.append(phrase.strip(".,·/"))
                break
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq[:2]


def rewrite_rule(text: str) -> str:
    """규칙만으로 [기관명 + 제도명 + 주장 요지]를 만든다. LLM 호출 없음."""
    agency = _find_agency(text)
    program = _find_program(text)
    topic = " ".join(sorted(describe_categories(text)))
    parts = agency + program
    if not parts:
        return text          # 뽑을 게 없으면 원문 그대로(재작성이 손해를 끼치지 않게)
    q = " ".join(parts)
    if topic:
        q += " " + topic
    q += " 안내 신청 대상 자격 조건"    # 제도 안내문 쪽으로 질의를 당긴다
    return q


_LLM_SYSTEM = (
    "당신은 검색 질의를 만드는 도우미입니다. 사용자가 받은 문자에서 "
    "'무엇을 주장하는가', '어느 기관을 내세우는가', '어떤 제도를 말하는가' 세 가지만 뽑습니다.\n"
    "규칙:\n"
    "- 글에 실제로 있는 표현만 쓴다. 없는 기관명·제도명을 지어내지 않는다.\n"
    "- 없으면 빈 문자열로 둔다.\n"
    "- 진짜인지 가짜인지 판단하지 않는다. 요약만 한다."
)
_LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {"type": "string", "description": "주장 요지 한 문장"},
        "agency": {"type": "string", "description": "내세운 기관명. 없으면 빈 문자열"},
        "program": {"type": "string", "description": "제도·급여 이름. 없으면 빈 문자열"},
    },
    "required": ["claim", "agency", "program"],
    "additionalProperties": False,
}
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def rewrite_llm(text: str) -> tuple[str, dict]:
    """★ 입력은 이미 마스킹된 텍스트여야 한다(파이프라인상 mask_text 이후 단계).
    평가셋 문구에는 개인정보가 없지만, 실사용 경로에서는 masked_text 를 넘긴다."""
    resp = _get_client().messages.create(
        model="claude-sonnet-5",
        max_tokens=300,
        system=[{"type": "text", "text": _LLM_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _LLM_SCHEMA}},
        messages=[{"role": "user", "content": f"[받은 글]\n{text}\n\n세 가지를 JSON 으로 뽑아 주세요."}],
    )
    raw = "".join(b.text for b in resp.content if b.type == "text")
    d = json.loads(raw)
    q = " ".join(x for x in (d.get("agency", ""), d.get("program", ""), d.get("claim", "")) if x).strip()
    return (q or text), d


# ==================================================== 검색 방식
def run_embedding(q: str, limit: int = TOPK) -> list:
    try:
        return [d for _, d in emb.match_embedding_docs(q, limit=limit)]
    except emb.EmbeddingUnavailableError:
        return []


def run_rrf(q: str, limit: int = TOPK) -> list:
    try:
        return search.match_official_docs_hybrid(q, limit=limit)
    except Exception:  # noqa: BLE001 - 실험 중 한쪽 검색기가 죽어도 계속 잰다
        return []


# ==================================================== 측정
def measure(name: str, rows: list, query_fn, search_fn) -> dict:
    per_case = []
    for r in rows:
        text = r["평가용_제시문구"]
        kind, gold_ids = gold_of(r)
        q = query_fn(text)
        extra = None
        if isinstance(q, tuple):
            q, extra = q
        docs = search_fn(q)
        found = [d.id for d in docs]
        top3_hit = bool(gold_ids & set(found[:TOPK]))
        # ★ 오답 근거: 근거를 붙였는데 정답이 하나도 없는 경우
        wrong = bool(found) and kind == "doc" and not (gold_ids & set(found))
        per_case.append({
            "id": r["case_id"], "유형": r.get("유형", ""), "gold_kind": kind,
            "query": q[:120], "llm": extra,
            "n_docs": len(docs), "found": found[:TOPK],
            "top3_hit": top3_hit, "wrong_evidence": wrong,
        })

    def sub(pred):
        return [c for c in per_case if pred(c)]

    doc_cases = sub(lambda c: c["gold_kind"] == "doc")
    none_cases = sub(lambda c: c["gold_kind"] == "none")
    missing_cases = sub(lambda c: c["gold_kind"] == "missing")
    scam_cases = sub(lambda c: c["gold_kind"] == "scam")

    summary = {
        "name": name,
        "found_rate": sum(1 for c in per_case if c["n_docs"]) / len(per_case),
        "by_type": {
            t: {
                "n": len(sub(lambda c, t=t: c["유형"] == t)),
                "found": sum(1 for c in sub(lambda c, t=t: c["유형"] == t) if c["n_docs"]),
            } for t in ("정상", "사칭", "경계")
        },
        "top3_recall": (sum(1 for c in doc_cases if c["top3_hit"]) / len(doc_cases)) if doc_cases else None,
        "top3_hits": sum(1 for c in doc_cases if c["top3_hit"]),
        "doc_cases": len(doc_cases),
        "wrong_evidence": sum(1 for c in per_case if c["wrong_evidence"]),
        "unknown_ok": sum(1 for c in none_cases if c["n_docs"] == 0),
        "none_cases": len(none_cases),
        "scam_cases": len(scam_cases),
        "missing_cases": len(missing_cases),
    }
    return {"summary": summary, "cases": per_case}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="LLM 재작성(D)을 건너뛴다")
    args = ap.parse_args()

    rows = list(csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig")))
    kinds = {}
    for r in rows:
        k, _ = gold_of(r)
        kinds[k] = kinds.get(k, 0) + 1
    print(f"평가셋 {len(rows)}건 - 정답 라벨: {kinds}")
    print(f"임계값 min_score={emb.EMBEDDING_MIN_SCORE} (고정, 낮추지 않음)\n")

    variants = [
        ("A baseline (원문+임베딩)", lambda t: t, run_embedding),
        ("B rrf (원문+RRF)", lambda t: t, run_rrf),
        ("C rewrite_rule (규칙재작성+임베딩)", rewrite_rule, run_embedding),
    ]
    if not args.no_llm and settings.ANTHROPIC_API_KEY:
        variants.append(("D rewrite_llm (LLM재작성+임베딩)", rewrite_llm, run_embedding))
    else:
        print("※ LLM 변형(D)은 건너뜁니다.\n")

    results = {}
    unmeasured = {}
    for name, qf, sf in variants:
        print(f"측정 중: {name} ...")
        try:
            results[name] = measure(name, rows, qf, sf)
        except Exception as e:  # noqa: BLE001 - LLM 변형은 외부 API 사정으로 못 잴 수 있다
            # ★ 못 잰 것은 '못 쟀다'고 남긴다. 추정치로 채우지 않는다.
            unmeasured[name] = f"{type(e).__name__}: {str(e)[:160]}"
            print(f"  → 측정 실패(기록만 남김): {unmeasured[name]}")

    print("\n" + "=" * 96)
    print(f"{'변형':<34}{'검색성공':>9}{'top3정답':>10}{'★오답근거':>10}{'확인불가정확':>13}")
    print("=" * 96)
    for name, res in results.items():
        s = res["summary"]
        t3 = f"{s['top3_hits']}/{s['doc_cases']}" if s["doc_cases"] else "-"
        unk = f"{s['unknown_ok']}/{s['none_cases']}"
        print(f"{name:<34}{s['found_rate']*100:>8.1f}%{t3:>10}{s['wrong_evidence']:>10}{unk:>13}")

    print("\n유형별 검색 성공")
    print(f"{'변형':<34}{'정상':>10}{'사칭':>10}{'경계':>10}")
    for name, res in results.items():
        b = res["summary"]["by_type"]
        print(f"{name:<34}" + "".join(f"{b[t]['found']}/{b[t]['n']:>9}" for t in ("정상", "사칭", "경계")))

    # 핵심 3건이 살아났는가
    print("\n★ 작업1에서 유사도 미달로 실패한 S02 / S07 / S08")
    for name, res in results.items():
        got = {c["id"]: c for c in res["cases"]}
        line = "  ".join(
            f"{cid}:{'찾음' if got[cid]['n_docs'] else '없음'}"
            f"{'(정답)' if got[cid]['top3_hit'] else ('(오답)' if got[cid]['wrong_evidence'] else '')}"
            for cid in ("S02", "S07", "S08"))
        print(f"  {name:<34}{line}")

    if unmeasured:
        print("\n★ 측정하지 못한 변형")
        for k, v in unmeasured.items():
            print(f"  {k}: {v}")

    OUT.write_text(json.dumps({"measured": results, "unmeasured": unmeasured},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
