"""'전화 회신 유도' 위험행동 유형 진단 (2026-08-13)

실행: docker compose exec api python3 experiments/diag_callback_lexicon.py

★ 진단만 한다. services/ 를 고치지 않는다. 어휘를 추가하지 않는다.

■ 순서를 지킨다 (이게 이 스크립트의 핵심이다)
  1단계  **공개 자료에서만** 후보 어휘를 뽑는다.
         출처: OFFICIAL_DOCS 의 사기 경보문(warning_case + 허용목록 press_release)
              + 2026-08-13 수집한 금융위 보도자료 133건
  2단계  그 어휘로 평가셋·홀드아웃을 **센다**.

  ★ 순서를 뒤집으면 안 된다. 평가셋 문구를 먼저 보고 어휘를 만들면 그건
    평가셋 맞춤이고, 그렇게 만든 재현율은 아무것도 말해 주지 않는다.
    "수정 근거는 로직이나 공개 자료에서 나와야 한다"는 기준 그대로다.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index as ci  # noqa: E402
from services import search  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
HOLD = Path("/app/tests/fixtures/holdout/holdout_30.csv")
COLLECT = Path("/corpus/collect/fsc_보도자료_2026-08-13.jsonl")

# 1단계에서 '전화로 걸게 만드는' 서술을 찾기 위한 넓은 그물.
#   ★ 이건 후보 어휘가 아니라 **공개 자료를 훑기 위한 조사용 패턴**이다.
#     여기서 실제로 나온 표현만 후보로 올린다.
PROBE = re.compile(
    r"[^.\n]{0,40}"
    r"(회신|다시 전화|전화 주|전화주|연락 주|연락주|연락 바|상담원|상담사|"
    r"고객센터|콜센터|안내센터|대표번호|이 번호로|아래 번호|해당 번호|"
    r"전화하도록|전화를 걸도록|통화를 유도|전화 유도|전화로 유도)"
    r"[^.\n]{0,40}"
)


def public_sources() -> list[tuple[str, str]]:
    """(출처라벨, 텍스트) - 공개 자료만."""
    out: list[tuple[str, str]] = []
    recs = {}
    for p in glob.glob("/corpus/public_data/gyeotnun_data/records_*.jsonl"):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            recs[r["id"]] = r
    for d in ci.OFFICIAL_DOCS:
        if not search._is_alert_doc(d):
            continue
        r = recs.get(d.id, {})
        out.append((f"경보문:{r.get('title','')[:30]}",
                    f"{r.get('title','')} {r.get('content','')}"))
    if COLLECT.exists():
        for line in COLLECT.open(encoding="utf-8"):
            r = json.loads(line)
            out.append((f"금융위:{r['title'][:30]}", f"{r['title']} {r['content']}"))
    return out


# ── 2단계에서 쓸 후보 어휘. 1단계 결과를 사람이 읽고 정하는 것이 원칙이나,
#    측정을 위해 '공개 자료에 실제로 나온 표현'만 그대로 옮겨 둔다.
#    ★ 평가셋 문구를 보고 만들지 않았다. 1단계 출력이 그 증거다.
CANDIDATE = {
    "회신 요구": ["회신", "연락 주", "연락주", "연락 바", "전화 주", "전화주",
                  "다시 전화", "전화 부탁", "통화 가능"],
    "번호 지정": ["이 번호로", "아래 번호", "해당 번호", "하단 번호", "번호로 전화",
                  "번호로 연락"],
    "창구 사칭": ["상담원", "상담사", "고객센터", "콜센터", "안내센터", "대표번호",
                  "민원실", "담당자에게 연락"],
}


def hit_type(text: str) -> tuple[str | None, list[str]]:
    t = text or ""
    for label, kws in CANDIDATE.items():
        got = [k for k in kws if k in t]
        if got:
            return label, got
    return None, []


def load(p: Path) -> list[dict]:
    return [r for r in csv.DictReader(p.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]


def main() -> None:
    print("=" * 78)
    print("0. 지금 상태 — detect_risk_action 이 아는 유형")
    print("=" * 78)
    print(f"  {list(search.RISK_ACTION_KEYWORDS)}")
    print("  → '전화 회신 유도' 는 없다. 평가셋 위험행동 컬럼에도 없다"
          "(없음/계좌이체/앱설치/인증번호/개인정보요구/확인 필요).")

    print()
    print("=" * 78)
    print("1단계. 공개 자료에서만 뽑은 근거 (평가셋을 보기 전이다)")
    print("=" * 78)
    srcs = public_sources()
    print(f"  훑은 공개 문서 {len(srcs)}건 (사기 경보문 + 금융위 수집분)")
    phrases = collections.Counter()
    docs_with = 0
    examples: list[tuple[str, str]] = []
    for label, text in srcs:
        found = PROBE.findall(text)
        if not found:
            continue
        docs_with += 1
        for m in set(found):
            phrases[m] += 1
        for snip in PROBE.finditer(text):
            if len(examples) < 12:
                examples.append((label, re.sub(r"\s+", " ", snip.group(0)).strip()))
    print(f"  '전화로 걸게 만드는' 서술이 나온 문서 {docs_with}/{len(srcs)}건")
    print(f"  가장 자주 나온 표현 상위 12: {phrases.most_common(12)}")
    print("  실제 문장 예시(공개 자료 원문):")
    for label, snip in examples:
        print(f"    [{label}] …{snip}…")

    print()
    print("=" * 78)
    print("2단계. 그 어휘로 평가셋·홀드아웃을 센다")
    print("=" * 78)
    for name, rows in (("확대 평가셋 112건", load(EVAL)), ("홀드아웃 30건", load(HOLD))):
        hits = []
        for r in rows:
            lab, got = hit_type(r["평가용_제시문구"])
            if lab:
                hits.append((r, lab, got))
        print(f"\n■ [{name}]  해당 {len(hits)}/{len(rows)}건")
        print(f"    유형별 {dict(collections.Counter(h[1] for h in hits))}")
        print(f"    기대판단별 {dict(collections.Counter(h[0]['기대판단'] for h in hits))}")
        print(f"    현재 위험행동 라벨별 "
              f"{dict(collections.Counter(h[0].get('위험행동', '') for h in hits))}")

        # ★ 실제 공백은 여기다 - 지금 detect_risk_action 이 아무것도 못 잡는 건.
        gap = [h for h in hits if search.detect_risk_action(h[0]["평가용_제시문구"]) is None]
        print(f"    ★ 그중 detect_risk_action 미검출 {len(gap)}건 "
              f"(= 지금 urgency_pressure 가 info 로 내려가는 건)")
        for r, lab, got in hits:
            cur = search.detect_risk_action(r["평가용_제시문구"])
            mark = "★" if cur is None else " "
            print(f"    {mark} {r['case_id']:>4} {r['유형']:2} {r['기대판단']:4} "
                  f"라벨={r.get('위험행동', ''):6} 현재검출={cur or '-':6} "
                  f"{lab}({','.join(got)}) | {r['평가용_제시문구'][:44]}")

    print("\n※ 진단만 했다. 어휘를 추가하지 않았다. 채택은 사람이 정한다.")


if __name__ == "__main__":
    main()
