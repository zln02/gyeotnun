"""
정상 안내문 홀드아웃 5건 측정 (2026-08-05)
실행: docker compose exec api python3 experiments/eval_holdout_normal.py

배경: 기존 평가세트 30건의 정상 10건이 전부 bokjiro.go.kr 한 도메인이다.
      "정상 오판 0건"이 복지로에 한정된 결과인지 다른 5개 기관으로 교차 확인한다.

★★ 절대 지킬 것 (README 의 사용 규칙) ★★
  1. 이 5건을 검색 코퍼스에 넣지 않는다 - 읽기만 한다.
     (corpus_index 는 기동 시 corpus/ 만 읽는다. 이 파일은 api/tests/fixtures/
      아래에 있어 코퍼스 적재 경로가 아니다 - 구조적으로 누수가 불가능하다.)
  2. 기존 30건과 합치지 않는다 - 별도 파일·별도 측정이다.
  3. 이 5건을 보고 코드를 고치지 않는다. 실패하면 실패로 기록한다.

판정 기준
  정상(needs_check)        → 통과
  확인불가(no_source_found) → 통과 (오판 아님. 근거 없으면 단정하지 않는 설계)
  의심(partially_matched)   → 실패 ★ 절대조건 위반
"""
from __future__ import annotations

import csv
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from experiments.rule_questions import detect_rule_signals, generate_questions  # noqa: E402
from services import corpus_index, embeddings, search  # noqa: E402

CSV_PATH = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")
OUT_PATH = Path("/app/data/holdout_normal_result.json")

# 기존 정상 10건의 유사도 분포(2026-08-05 실측, e5-small-ko-v2)
BASELINE_NORMAL = {"min": 0.6820, "median": 0.7677, "max": 0.8601}
CONFIDENT = search.CONFIDENT_MATCH_THRESHOLD

VERDICT_KO = {"needs_check": "정상", "no_source_found": "확인불가", "partially_matched": "의심"}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    print(f"홀드아웃 {len(rows)}건 / 임계값 confident={CONFIDENT}\n")

    # 누수 방지 확인: 홀드아웃 문구가 코퍼스에 들어가 있지 않은지 실제로 검사
    corpus_texts = " ".join(c.text for c in corpus_index._OFFICIAL_CHUNKS)
    leaked = [r["case_id"] for r in rows if r["평가용_제시문구"][:25] in corpus_texts]
    print(f"[누수 검사] 코퍼스에 섞인 홀드아웃: {leaked or '없음 ✓'}\n")

    out = {"cases": [], "leak_check": leaked, "confident_threshold": CONFIDENT}
    for r in rows:
        cid, text = r["case_id"], r["평가용_제시문구"]
        ev = search.collect_evidence(text)

        # 유사도 원점수(임계값 적용 전)를 따로 본다 - 분포 비교용
        try:
            hits = embeddings.match_embedding_docs(text, limit=3, min_score=0.0)
            top = hits[0][0] if hits else None
            docs = [(round(s, 4), d.source_agency, d.title[:38]) for s, d in hits[:2]]
        except Exception as e:  # noqa: BLE001
            top, docs = None, [("오류", str(e)[:40], "")]

        sigs = [s.key for s in detect_rule_signals(text)]
        rq = generate_questions(text, max_q=1)[0]

        c = {
            "case_id": cid, "기관": r.get("참고_출처", ""), "채널": r.get("입력채널", ""),
            "text": text,
            "verdict": ev.verdict_hint, "verdict_ko": VERDICT_KO.get(ev.verdict_hint, ev.verdict_hint),
            "pass": ev.verdict_hint != "partially_matched",
            "refs_count": len(ev.references),
            "top_score": round(top, 4) if top is not None else None,
            "confident": (top is not None and top >= CONFIDENT),
            "top_docs": docs,
            "rule_signals": sigs, "rule_signal_used": rq.signal_key,
            "rule_question": rq.question,
            "signals": [s["key"] for s in ev.signals],
        }
        out["cases"].append(c)

        mark = "통과" if c["pass"] else "★실패★"
        print(f"[{cid}] {c['verdict_ko']:<6} {mark}  근거 {c['refs_count']}건  "
              f"유사도 {c['top_score']}  확신={c['confident']}")
        print(f"   기관: {c['기관'][:40]}")
        print(f"   찾은 문서: {docs}")
        print(f"   규칙 신호: {sigs or '없음'} → 질문신호={rq.signal_key}")
        print(f"   질문: {rq.question[:72]}")
        print()

    n = len(out["cases"])
    failed = [c for c in out["cases"] if not c["pass"]]
    unknown = [c for c in out["cases"] if c["verdict"] == "no_source_found"]
    normal_ok = [c for c in out["cases"] if c["verdict"] == "needs_check"]
    conf = [c for c in out["cases"] if c["confident"]]
    scores = [c["top_score"] for c in out["cases"] if c["top_score"] is not None]

    out["summary"] = {
        "n": n, "정상처리": len(normal_ok), "확인불가": len(unknown),
        "의심_실패": len(failed), "실패_케이스": [c["case_id"] for c in failed],
        "확신판정_건수": len(conf),
        "유사도": {"min": round(min(scores), 4), "median": round(st.median(scores), 4),
                   "max": round(max(scores), 4)} if scores else None,
        "기존정상10건_분포": BASELINE_NORMAL,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    s = out["summary"]
    print("════ 요약 ════")
    print(f"  정상 처리 {s['정상처리']} / 확인불가 {s['확인불가']} / 의심(실패) {s['의심_실패']}")
    print(f"  → 절대조건: {'통과 ✓' if s['의심_실패'] == 0 else '★위반★ ' + str(s['실패_케이스'])}")
    print(f"  확신 판정(≥{CONFIDENT}): {s['확신판정_건수']}/{n}건")
    if s["유사도"]:
        b = BASELINE_NORMAL
        print(f"\n  유사도 비교")
        print(f"    홀드아웃   min {s['유사도']['min']}  median {s['유사도']['median']}  max {s['유사도']['max']}")
        print(f"    기존정상10 min {b['min']}  median {b['median']}  max {b['max']}")
        print(f"    → 홀드아웃 최소가 기존 최소보다 {'낮음(코퍼스 편중 신호)' if s['유사도']['min'] < b['min'] else '높거나 같음'}")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
