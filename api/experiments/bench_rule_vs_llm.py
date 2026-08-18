"""
LLM 생성 vs 규칙 생성 비교 (실험, 2026-08-04)
실행: docker compose exec api python3 experiments/bench_rule_vs_llm.py

★ services/ 를 수정하지 않는다. LLM 쪽은 프로덕션 generate_question() 을
  그대로 호출하고, 규칙 쪽은 experiments/rule_questions.py 를 쓴다.
  채점은 양쪽 모두 experiments/score_questions.py 로 동일하게 한다.

측정
  1) 기준선  : 현재 LLM 질문의 4지표 점수 (30건)
  2) 규칙    : 같은 30건, 같은 채점
  3) 정상 10건에서 불필요한 의심 질문이 나오는지 ← 절대 조건
  4) 하이브리드 적용률 : 근거 문서 인용이 필요해 LLM 을 불러야 하는 비율
"""
from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
from experiments.rule_questions import detect_rule_signals, generate_questions  # noqa: E402
from experiments.score_questions import score_question, summarize  # noqa: E402
from services import prompt_chain, search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
OUT_PATH = Path("/app/data/rule_vs_llm.json")

# 규칙 질문이 '의심을 유도하는가' 판정용 - 정상 10건에서 이런 표현이 나오면 안 된다.
# ★ 금지어(FORBIDDEN_PATTERNS)와는 다르다. 금지어는 '판정'이고, 이건 '의심 유도'다.
#   정상 안내문에 "돈을 먼저 보내라는 요구" 같은 질문이 나가면 사용자를 불필요하게
#   불안하게 만든다 - 곁눈의 원칙상 이건 실패다.
SUSPICION_SIGNAL_KEYS = {"prepay", "account", "personal_info", "short_url",
                         "nonofficial_url", "phone"}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30

    report = {"cases": []}
    llm_scores, rule_scores = [], []
    need_llm = 0      # (가) 근거검색 성공 건수 - 참고용
    need_llm_b = 0    # (나) 규칙 질문 4지표 미달 건수 - 정식 지표

    for i, row in enumerate(rows, 1):
        cid, ytype = row["case_id"], row["유형"]
        text = row["평가용_제시문구"]
        print(f"[{i:>2}/30] {cid} ({ytype})", flush=True)

        ev = search.collect_evidence(text)

        # ---- 1) LLM (프로덕션 경로 그대로)
        t0 = time.perf_counter()
        vq = prompt_chain.generate_question(text, ev.signals, ev.references, [])
        llm_sec = time.perf_counter() - t0
        ls = score_question(vq.question, text)
        llm_scores.append(ls)

        # ---- 2) 규칙
        t1 = time.perf_counter()
        rqs = generate_questions(text, max_q=2)
        rule_sec = time.perf_counter() - t1
        rs = score_question(rqs[0].question, text)
        rule_scores.append(rs)

        # ---- 4) 하이브리드
        #  ★ 정의 (나) 가 정식 정의다 (2026-08-05 교정).
        #     (나) LLM 필요 = 규칙 질문이 4지표에 미달한 비율.
        #         규칙으로 충분하면 LLM 을 부를 이유가 없다 - 이것이 원가 절감 판단의 근거다.
        #     (가) 근거 문서가 검색된 비율 ← 이건 LLM 필요 조건이 아니다.
        #         근거가 붙었다는 사실과 "규칙 질문으로 부족하다"는 사실은 별개다.
        #         비교용으로만 함께 기록한다.
        cite_needed = len(ev.references) > 0   # (가) 참고 지표
        if cite_needed:
            need_llm += 1
        if not rs.passed_all:                  # (나) 정식 지표
            need_llm_b += 1

        sig_keys = [s.key for s in detect_rule_signals(text)]
        report["cases"].append({
            "case_id": cid, "유형": ytype,
            "llm": {"question": vq.question, "fallback": getattr(vq, "fallback", False),
                    "sec": round(llm_sec, 2), "score": ls.__dict__},
            "rule": {"question": rqs[0].question, "signal": rqs[0].signal_key,
                     "all_signals": sig_keys, "sec": round(rule_sec, 5),
                     "score": rs.__dict__},
            "refs_count": len(ev.references), "cite_needed": cite_needed,
        })

    # ---- 3) 정상 10건 의심 유도 검사
    normal = [c for c in report["cases"] if c["유형"] == "정상"]
    rule_susp = [c for c in normal if c["rule"]["signal"] in SUSPICION_SIGNAL_KEYS]

    report["summary"] = {
        "llm": summarize(llm_scores),
        "rule": summarize(rule_scores),
        "정상10건_규칙_의심유도": {
            "건수": len(rule_susp),
            "케이스": [{"case_id": c["case_id"], "signal": c["rule"]["signal"],
                        "question": c["rule"]["question"][:60]} for c in rule_susp],
        },
        "하이브리드": {
            "정식정의_나_규칙미달": {
                "LLM필요_건수": need_llm_b, "전체": len(rows),
                "LLM필요_비율": round(need_llm_b / len(rows), 3),
            },
            "참고정의_가_근거검색성공": {
                "건수": need_llm, "전체": len(rows),
                "비율": round(need_llm / len(rows), 3),
                "주의": "이것은 LLM 필요 조건이 아니다. 원가 판단에 쓰지 말 것.",
            },
        },
        "평균_생성시간": {
            "llm_sec": round(sum(c["llm"]["sec"] for c in report["cases"]) / 30, 2),
            "rule_sec": round(sum(c["rule"]["sec"] for c in report["cases"]) / 30, 5),
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    s = report["summary"]
    print("\n════ 4지표 비교 ════")
    print(f"{'지표':<14}{'LLM':>10}{'규칙':>10}")
    for k in ("판정안함", "2문장이내", "신호대응", "확인가능", "전부통과"):
        a, b = s["llm"].get(k), s["rule"].get(k)
        fa = f"{a:.3f}" if isinstance(a, float) else str(a)
        fb = f"{b:.3f}" if isinstance(b, float) else str(b)
        print(f"{k:<14}{fa:>10}{fb:>10}")
    print(f"\n정상 10건 규칙 의심유도: {s['정상10건_규칙_의심유도']['건수']}건")
    for c in s["정상10건_규칙_의심유도"]["케이스"]:
        print(f"  ⚠ {c['case_id']} [{c['signal']}] {c['question']}")
    b = s["하이브리드"]["정식정의_나_규칙미달"]
    g = s["하이브리드"]["참고정의_가_근거검색성공"]
    print(f"\n하이브리드 (나) LLM 필요 = 규칙 4지표 미달"
          f" : {b['LLM필요_건수']}/{b['전체']} ({b['LLM필요_비율']*100:.1f}%)")
    print(f"           (가) 근거검색 성공(참고, 원가판단에 쓰지 말 것)"
          f" : {g['건수']}/{g['전체']} ({g['비율']*100:.1f}%)")
    print(f"평균 생성시간: LLM {s['평균_생성시간']['llm_sec']}s / 규칙 {s['평균_생성시간']['rule_sec']}s")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
