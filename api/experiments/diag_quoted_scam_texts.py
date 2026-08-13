"""경보문 속 '사기 문자 인용 원문' 추출 조사 (2026-08-13)

실행: docker compose exec api python3 experiments/diag_quoted_scam_texts.py

★ 조사만 한다. 탐지 어휘를 만들지 않는다.
★ 추출물을 검색 코퍼스·SCAM_CASES 에 넣지 않는다.
  출력은 corpus/collect/ 에만 쓴다 - corpus_index 가 자동으로 읽는 경로
  (corpus/public_data/gyeotnun_data/records_*.jsonl)가 아니다.

■ 왜 이걸 조사하나
  #43 어휘 보강의 전제가 막혀 있다. 경보문은 수법을 **3인칭으로 서술**하고
  ("가짜 고객센터 번호를 알려주고 전화를 하도록 권유한다"), 실제 사기 문자는
  **1인칭 명령형**이다("아래 번호로 즉시 회신 바랍니다"). 겹치는 단어가 거의 없어
  경보문 본문을 그대로 어휘 원천으로 쓸 수 없다
  (docs/evaluation/위험행동_전화회신유도_2026-08-13.md §4).

  그런데 경보문 **안에 인용된 문자 원문**은 1인칭 명령형 그대로일 수 있다.
  그게 사실인지, 규모가 얼마인지를 재는 것이 이 스크립트의 전부다.
"""
from __future__ import annotations

import collections
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/app")

# ★ 컨테이너에서는 /corpus 가 읽기 전용 마운트라 쓸 수 없다. 호스트에서 돌린다.
#   호스트: python3 api/experiments/diag_quoted_scam_texts.py
ROOT = Path("/corpus") if Path("/corpus").exists() else Path(__file__).resolve().parents[2] / "corpus"
OUT = ROOT / "collect" / "quoted_scam_texts_2026-08-13.jsonl"
COLLECT = ROOT / "collect" / "fsc_보도자료_2026-08-13.jsonl"

# ── 인용 표지. 넓게 잡고, 뒤에서 걸러 낸다.
QUOTE_PATTERNS = [
    ("낫표", re.compile(r"[「『]([^」』]{8,300})[」』]")),
    ("겹따옴표", re.compile(r"[“\"]([^”\"]{8,300})[”\"]")),
    ("홑따옴표", re.compile(r"[‘']([^’']{8,300})[’']")),
    ("각괄호", re.compile(r"[〔\[]([^\]〕]{8,300})[\]〕]")),
]
# "다음과 같은 문자" 류 유도 문구 뒤에 오는 덩어리
LEAD_IN = re.compile(
    r"(다음과 같은|아래와 같은|아래 같은|예시|문자 내용|문자는 다음|내용의 문자|"
    r"사칭 문자|스미싱 문자|같은 내용으로)[^\n]{0,20}[\n:：]\s*(.{15,300})"
)

# ── 이게 '문자 원문'인지 가르는 표지 (문자 고유의 흔적)
SMS_MARKS = [
    "[Web발신]", "[web발신]", "[국제발신]", "[국외발신]", "Web발신", "국제발신",
    "http://", "https://", "www.", "bit.ly", "☎", "고객님", "안내드립니다",
]
# ── 1인칭 명령형(수신자에게 시키는 말투)
IMPERATIVE = re.compile(
    r"(하세요|하십시오|해주세요|해 주세요|바랍니다|바람|주세요|주십시오|"
    r"하시기 바랍|확인요망|클릭|접속|눌러|설치하|입력하|송금하|회신|연락 주|"
    r"신청하|등록하|다운로드)"
)
# ── 3인칭 서술(기관이 수법을 설명하는 말투). 인용이 아니라 본문일 확률이 높다.
NARRATIVE = re.compile(
    r"(유도한다|유도하는|권유한다|기망하|사칭하여|가장하여|것으로 나타났|"
    r"당부(하|했)|주의를 요|밝혔다|배포하고 있|발생하고 있|피해가 |수법이 )"
)


def load_sources() -> list[dict]:
    """조사 대상. 경보문 전체 + 금융위 수집분."""
    recs: dict[str, dict] = {}
    for p in glob.glob(str(ROOT / "public_data/gyeotnun_data/records_*.jsonl")):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            recs[r["id"]] = r
    out = []
    for r in recs.values():
        if r.get("data_type") in ("warning_case", "press_release"):
            out.append({
                "doc_id": r["id"], "agency": r.get("source_agency", ""),
                "title": r.get("title", ""), "published_at": r.get("published_at", ""),
                "text": f"{r.get('title','')}\n{r.get('content','')}",
                "bucket": "KISA" if "인터넷진흥원" in (r.get("source_agency") or "")
                          else "통합대응단",
            })
    if COLLECT.exists():
        for line in COLLECT.open(encoding="utf-8"):
            r = json.loads(line)
            out.append({
                "doc_id": r["id"], "agency": "금융위원회", "title": r["title"],
                "published_at": r["published_at"],
                "text": f"{r['title']}\n{r['content']}", "bucket": "금융위",
            })
    return out


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def extract(doc: dict) -> list[dict]:
    seen, out = set(), []
    cands: list[tuple[str, str]] = []
    for label, pat in QUOTE_PATTERNS:
        for m in pat.finditer(doc["text"]):
            cands.append((label, m.group(1)))
    for m in LEAD_IN.finditer(doc["text"]):
        cands.append(("유도문구", m.group(2)))

    for marker, raw in cands:
        q = clean(raw)
        if len(q) < 12 or q in seen:
            continue
        seen.add(q)
        out.append({
            "doc_id": doc["doc_id"], "bucket": doc["bucket"], "agency": doc["agency"],
            "doc_title": doc["title"][:60], "published_at": doc["published_at"],
            "marker": marker, "quote": q, "len": len(q),
            "sms_marks": [k for k in SMS_MARKS if k in q],
            "imperative": bool(IMPERATIVE.search(q)),
            "narrative": bool(NARRATIVE.search(q)),
        })
    return out


def main() -> None:
    docs = load_sources()
    print("=" * 78)
    print("0. 조사 대상")
    print("=" * 78)
    print(f"  총 {len(docs)}건  " + str(dict(collections.Counter(d["bucket"] for d in docs))))

    quotes = [q for d in docs for q in extract(d)]
    docs_with = {q["doc_id"] for q in quotes}

    print()
    print("=" * 78)
    print("1. 인용문 추출 결과 (넓게 잡은 원시 후보)")
    print("=" * 78)
    print(f"  인용문 {len(quotes)}개 · 인용문이 나온 문서 {len(docs_with)}/{len(docs)}건")
    print(f"  표지별 {dict(collections.Counter(q['marker'] for q in quotes))}")
    for b in ("KISA", "통합대응단", "금융위"):
        sel = [q for q in quotes if q["bucket"] == b]
        nd = len({q["doc_id"] for q in sel})
        tot = len([d for d in docs if d["bucket"] == b])
        ln = [q["len"] for q in sel]
        avg = sum(ln) / len(ln) if ln else 0
        print(f"    [{b:6}] 인용문 {len(sel):4}개 · 문서 {nd}/{tot} · 평균 {avg:.0f}자")

    print()
    print("=" * 78)
    print("2. 그중 '문자 원문'으로 보이는 것 (문자 표지 or 명령형, 서술문 제외)")
    print("=" * 78)
    real = [q for q in quotes
            if (q["sms_marks"] or q["imperative"]) and not q["narrative"]]
    print(f"  {len(real)}개 · 문서 {len({q['doc_id'] for q in real})}건")
    for b in ("KISA", "통합대응단", "금융위"):
        sel = [q for q in real if q["bucket"] == b]
        ln = [q["len"] for q in sel]
        avg = sum(ln) / len(ln) if ln else 0
        med = sorted(ln)[len(ln) // 2] if ln else 0
        imp = sum(1 for q in sel if q["imperative"])
        sms = sum(1 for q in sel if q["sms_marks"])
        print(f"    [{b:6}] {len(sel):4}개 · 평균 {avg:.0f}자 중앙 {med}자 · "
              f"1인칭 명령형 {imp} · 문자표지 {sms}")

    print()
    print("  ── 실제 표본 (앞 20개) ──")
    for q in real[:20]:
        flag = ("명령형" if q["imperative"] else "") + ("+표지" if q["sms_marks"] else "")
        print(f"    [{q['bucket']}/{q['marker']}/{flag}] {q['quote'][:96]}")

    print()
    print("  ── KISA 인용문 표본 (문자 원문으로 안 걸린 이유를 보기 위해) ──")
    for q in [x for x in quotes if x["bucket"] == "KISA"][:12]:
        print(f"    [{q['marker']}] {q['quote'][:88]}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for q in quotes:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"\n저장(스테이징, 인덱스 아님): {OUT}  원시 후보 {len(quotes)}개")
    print("※ 조사만 했다. 탐지 어휘를 만들지 않았다. 코퍼스에 넣지 않았다.")


if __name__ == "__main__":
    main()
