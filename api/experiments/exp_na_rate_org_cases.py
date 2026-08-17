"""(나) 발생률 — 기관명이 있는 입력만 골라 2회씩 (2026-08-16, #보류했던 질문 검사기)

실행: docker compose exec -T api python3 experiments/exp_na_rate_org_cases.py

■ 왜 이 표본인가
  (나)는 "입력에 그 사실이 **있어야**" 발생한다. 확대 112건 중 기관 이름이 있는
  입력은 26건뿐이라, 1/112 라는 수치는 표본 탓일 수 있다. 그 26건만 골라 2회씩
  생성해 실제 발생률을 본다.

■ ★ 이미 확인된 것 (이 측정 전에 코드를 읽고 알아낸 것)
  라이브에서 나온 그 질문은 **prompt_chain.FALLBACK_QUESTION 과 글자 그대로 같다.**
  즉 LLM 이 만든 문장이 아니라, 3회 재생성이 모두 실패했을 때 내려가는 고정 문장이다.
  그리고 그 고정 문장은 "기관 이름이 보이지 않는다면" 을 **하드코딩**하고 있다.
      → 입력에 기관명이 있으면 폴백은 **반드시** (나)가 된다. 확률이 아니라 구조다.

  그래서 이 측정이 실제로 가르는 것은 이것이다:
      (a) 폴백이 아닌, **모델이 생성한** 질문도 (나)를 내는가?
      (b) 폴백은 얼마나 자주 일어나는가?

■ 비용: 26건 × 2회 = 52건 (승인됨). LLM_BUDGET 으로 상한을 건다.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/app")

from services import prompt_chain, question_check, search  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
OUT = Path("/app/data/na_rate_org_cases.json")
REPEATS = int(os.getenv("REPEATS", "2"))
LLM_BUDGET = int(os.getenv("LLM_BUDGET", "60"))
WORKERS = int(os.getenv("WORKERS", "4"))

_used = 0
_lock = threading.Lock()


def _take() -> bool:
    global _used
    with _lock:
        if _used >= LLM_BUDGET:
            return False
        _used += 1
        return True


def one(job: tuple[dict, int]) -> dict | None:
    row, rep = job
    if not _take():
        return None
    masked = mask_text(row["평가용_제시문구"]).text
    ev = search.collect_evidence(masked, domain=None)
    vq = prompt_chain.generate_question(
        extracted_text=masked, signals=ev.signals, references=ev.references, history=[])
    chk = question_check.check_question(vq.question, masked, vq.why or "")
    return {
        "case_id": row["case_id"], "유형": row["유형"], "회차": rep + 1,
        "입력": masked, "질문": vq.question, "why": vq.why,
        "fallback": bool(vq.fallback),
        "na": [f.fact for f in chk.findings if f.direction == "나"],
        "ga": [f.fact for f in chk.findings if f.direction == "가"],
    }


def main() -> None:
    rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]
    org_rows = [r for r in rows
                if question_check._has_org(mask_text(r["평가용_제시문구"]).text)]
    print(f"기관명이 있는 입력 {len(org_rows)}건 × {REPEATS}회 = {len(org_rows) * REPEATS}건 "
          f"(LLM 상한 {LLM_BUDGET})")
    print(f"유형별: {dict(Counter(r['유형'] for r in org_rows))}\n")

    jobs = [(r, i) for r in org_rows for i in range(REPEATS)]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = [x for x in ex.map(one, jobs) if x]
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    fb = [r for r in res if r["fallback"]]
    gen = [r for r in res if not r["fallback"]]
    na_fb = [r for r in fb if r["na"]]
    na_gen = [r for r in gen if r["na"]]

    print(f"생성 {len(res)}건")
    print(f"  폴백           {len(fb):>3}건  → 그중 (나) {len(na_fb)}건")
    print(f"  모델이 생성    {len(gen):>3}건  → 그중 (나) {len(na_gen)}건")
    print()
    print(f"★ (나) 전체 {len(na_fb) + len(na_gen)}/{len(res)} "
          f"= {(len(na_fb) + len(na_gen)) / max(1, len(res)) * 100:.1f}%")
    print(f"★ 폴백일 때 (나) 비율      {len(na_fb)}/{len(fb) or 1} "
          f"= {len(na_fb) / max(1, len(fb)) * 100:.0f}%")
    print(f"★ 모델 생성일 때 (나) 비율 {len(na_gen)}/{len(gen) or 1} "
          f"= {len(na_gen) / max(1, len(gen)) * 100:.1f}%")

    if na_gen:
        print("\n■ 모델이 생성한 질문에서 나온 (나) — 폴백이 아닌 진짜 생성 오류")
        for r in na_gen:
            print(f"  {r['case_id']} ({r['회차']}회차) {r['na']}")
            print(f"     입력: {r['입력'][:64]}")
            print(f"     질문: {r['질문'][:76]}")

    if fb:
        print(f"\n■ 폴백이 난 건: {sorted({r['case_id'] for r in fb})}")

    print(f"\nLLM 실호출 {_used}건 · 저장 {OUT}")


if __name__ == "__main__":
    main()
