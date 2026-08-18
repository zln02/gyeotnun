"""
일반 행정 어휘(불용어) 도출 (2026-08-05)
실행: docker compose exec api python3 experiments/derive_admin_stopwords.py

지시: "불용어 목록은 정상 코퍼스에서 문서빈도가 높은 순으로 도출하라.
      평가셋이나 홀드아웃을 보고 만들지 마라."

★ 입력은 corpus/ 의 공식 안내 문서(OFFICIAL_DOCS)뿐이다.
  평가세트 30건과 홀드아웃 5건은 읽지 않는다 - 이 스크립트는 두 파일 경로를
  아예 참조하지 않는다.

방법
  1) 정상 코퍼스 각 문서를 match_scam_cases 와 같은 방식으로 토큰화
     (extract_keywords - 동일한 조사 제거 규칙을 써야 결과가 일치한다)
  2) 문서빈도(DF) 를 세고 DF 비율이 임계 이상인 토큰을 '일반 행정 어휘'로 본다
  3) 임계는 데이터에서 정한다: DF 비율 분포의 급락 지점을 찾는다
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402

OUT_PATH = Path("/app/data/admin_stopwords.json")


def main() -> None:
    # ★ '정상' 코퍼스만 쓴다. warning_case(사기 경보)는 사기 어휘가 들어 있어
    #   불용어 도출에 섞으면 '사기 어휘까지 불용어로' 만들어 버린다.
    docs = [d for d in ci.OFFICIAL_DOCS if d.data_type != "warning_case"]
    n = len(docs)
    print(f"정상 코퍼스 {n}건 기준 문서빈도 산출 "
          f"(전체 {len(ci.OFFICIAL_DOCS)}건에서 warning_case "
          f"{len(ci.OFFICIAL_DOCS)-n}건 제외)")
    print("※ 평가셋·홀드아웃은 읽지 않는다.\n")

    df = Counter()
    for d in docs:
        # ★ content(본문)를 반드시 포함한다. 제목만 쓰면 기관명만 잡히고
        #   '계좌·지급·신청' 같은 본문 어휘가 안 잡힌다.
        blob = f"{d.title} {d.content or ''} {d.source_agency}"
        toks = set(ci.extract_keywords(blob))
        df.update(toks)

    ranked = [(t, c, c / n) for t, c in df.most_common()]

    print(f"{'순위':<5}{'토큰':<16}{'DF':>6}{'DF비율':>9}")
    print("─" * 40)
    for i, (t, c, r) in enumerate(ranked[:45], 1):
        print(f"{i:<5}{t:<16}{c:>6}{r:>8.1%}")

    # ---- 임계 결정: DF 비율이 급락하는 지점을 찾는다(내가 고르지 않고 데이터가 고르게)
    print(f"\n{'='*50}\nDF비율 구간별 토큰 수")
    for lo, hi in [(0.30, 1.01), (0.20, 0.30), (0.15, 0.20),
                   (0.10, 0.15), (0.05, 0.10), (0.02, 0.05)]:
        k = [t for t, c, r in ranked if lo <= r < hi]
        print(f"  {lo:.0%} ~ {hi:.0%} : {len(k):>4}개   {k[:8]}")

    # 5% 이상을 후보로 잡는다 - 정상 문서 20건 중 1건 이상에 나오는 어휘는
    # '이 문서가 사기다'를 가릴 변별력이 없다고 본다.
    THRESHOLD = 0.05
    cand = [t for t, c, r in ranked if r >= THRESHOLD]
    print(f"\n임계 DF≥{THRESHOLD:.0%} → 후보 {len(cand)}개")

    # 이미 STOPWORDS 에 있는 것과 새로 추가되는 것을 구분
    new = [t for t in cand if t not in ci.STOPWORDS]
    print(f"  기존 STOPWORDS({len(ci.STOPWORDS)}개)에 없는 신규: {len(new)}개")
    print(f"  {new}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "n_docs": n, "threshold": THRESHOLD,
        "existing_stopwords": sorted(ci.STOPWORDS),
        "candidates": cand, "new": new,
        "df_table": [{"token": t, "df": c, "ratio": round(r, 4)} for t, c, r in ranked[:200]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
