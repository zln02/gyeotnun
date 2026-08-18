"""질문의 잘못된 전제 — 확대 112건 실측 (2026-08-16, 라이브 실사용 발견)

실행: docker compose exec -T api python3 experiments/exp_question_premise.py

★ LLM 실호출이 든다. 케이스당 1건, 112건 = 약 2,527원(회당 22.56원).
  LLM_BUDGET 로 상한을 건다. 결과는 /app/data/question_premise.json 에 저장해
  다시 돈 쓰지 않고 재분석할 수 있게 한다.

측정 대상 두 방향 (services/question_check.py)
  (가) 입력에 **없는** 것을 있다고 전제
  (나) 입력에 **있는** 것을 없다고 전제   ← 라이브에서 실제로 나온 방향
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
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import prompt_chain, question_check, search  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
OUT = Path(os.getenv("OUT", "/app/data/question_premise.json"))
LLM_BUDGET = int(os.getenv("LLM_BUDGET", "120"))
WORKERS = int(os.getenv("WORKERS", "1"))  # ★ 계측 때문에 1로 (전역 패치라 병렬 불가)

_used = 0
_lock = threading.Lock()
_attempts: dict[str, int] = {}
_reasons: dict[str, list] = {}


def _take() -> bool:
    global _used
    with _lock:
        if _used >= LLM_BUDGET:
            return False
        _used += 1
        return True


def one(row: dict) -> dict | None:
    if not _take():
        return None
    cid = row["case_id"]
    text = row["평가용_제시문구"]
    masked = mask_text(text).text
    ev = search.collect_evidence(masked, domain=None)

    # ★ 이 케이스에서 몇 번 호출했고 왜 막혔는지 센다(스레드별로 안전하게 키 분리).
    n = {"i": 0}
    orig_call, orig_record = prompt_chain._call_claude, prompt_chain._record

    def _spy_call(messages):
        n["i"] += 1
        return orig_call(messages)

    def _spy_record(reason, attempt, detail=""):
        _reasons.setdefault(cid, []).append(reason)
        return orig_record(reason, attempt, detail)

    with _lock:
        prompt_chain._call_claude, prompt_chain._record = _spy_call, _spy_record
    try:
        vq = prompt_chain.generate_question(
            extracted_text=masked, signals=ev.signals, references=ev.references, history=[])
    finally:
        with _lock:
            prompt_chain._call_claude, prompt_chain._record = orig_call, orig_record
    _attempts[cid] = n["i"]
    chk = question_check.check_question(vq.question, masked, vq.why or "")
    return {
        "case_id": row["case_id"], "유형": row["유형"],
        "입력": masked, "질문": vq.question, "why": vq.why,
        "fallback": bool(vq.fallback),
        # ★ 2026-08-17: 재생성 횟수·사유 분포를 함께 남긴다. 문장 세기 수정 전후를
        #   비교하려면 "몇 번 만에 통과했나"가 있어야 한다.
        "attempts": _attempts.get(row["case_id"], 0),
        "reasons": _reasons.get(row["case_id"], []),
        "refs": len(ev.references),
        "findings": [{"direction": f.direction, "fact": f.fact,
                      "quote": f.quote, "detail": f.detail} for f in chk.findings],
    }


def main() -> None:
    rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]
    print(f"대상 {len(rows)}건 · LLM 상한 {LLM_BUDGET}건 · 동시 {WORKERS}")

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = [r for r in ex.map(one, rows) if r]

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    fb = sum(1 for r in results if r["fallback"])
    ga = [r for r in results if any(f["direction"] == "가" for f in r["findings"])]
    na = [r for r in results if any(f["direction"] == "나" for f in r["findings"])]

    from collections import Counter as _C
    att = _C(r.get("attempts", 0) for r in results)
    rs = _C(x for r in results for x in r.get("reasons", []))
    print(f"\n생성 {len(results)}건")
    print(f"  ★ 폴백 {fb}건 = {fb / max(1, len(results)) * 100:.1f}%")
    print(f"  재생성 횟수 분포(호출 수별 케이스): {dict(sorted(att.items()))}")
    print(f"  차단 사유 분포: {dict(rs)}")
    print(f"  (가) 입력에 없는 것을 전제 : {len(ga)}건")
    print(f"  (나) 입력에 있는 것을 없다고 전제 : {len(na)}건")

    for label, group in (("가", ga), ("나", na)):
        if not group:
            continue
        print(f"\n■ ({label}) 상세")
        by_type = Counter(r["유형"] for r in group)
        print(f"   유형별: {dict(by_type)}")
        for r in group:
            f = next(x for x in r["findings"] if x["direction"] == label)
            print(f"   {r['case_id']:<5} [{r['유형']}] {f['fact']}")
            print(f"         질문: {r['질문'][:76]}")
            print(f"         근거: {f['detail']}")

    print(f"\nLLM 실호출 {_used}건 · 결과 저장 {OUT}")


if __name__ == "__main__":
    main()
