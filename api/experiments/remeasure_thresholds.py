"""하한선 재측정 — 코퍼스가 바뀐 뒤에도 12.0 · 5.0 이 맞는 값인가 (2026-08-19)

실행: docker compose exec -T api python3 experiments/remeasure_thresholds.py

★ 결과만 낸다. 값을 바꾸지 않는다. 조정은 사람이 정한다.

■ 왜
  두 임계값은 **코퍼스 척도에 따라 움직인다**(실측: 청크 2,036→1,018 이면 같은 질의
  최고점 9.692→5.988). 코드 주석에 "코퍼스가 바뀌면 다시 실측하라"고 적혀 있는데,
  2026-08-15 에 금융위 경보문 7건을 넣고(1,052→1,059) 재측정하지 않았다.

■ 원래 어떻게 정했나 (재현 대상)
  _OFFICIAL_MIN_SCORE = 12.0
      무관한 문장의 최고점(노이즈 바닥) 4.9~10.6  <  12.0  <  확실한 진짜 매칭 14.79~31
  match_scam_cases min_score = 5.0
      기존 기본값을 그대로 쓴 값. 정상 오판 0 / 사칭 위험신호 10-10 유지가 조건이었다.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import corpus_index as ci  # noqa: E402

# 원래 측정에 쓰인 것과 같은 성격의 '완전히 무관한 문장'
NOISE = [
    "오늘 날씨가 좋네요",
    "저녁에 뭐 먹을지 고민이에요",
    "주말에 등산 다녀왔습니다",
    "커피 한잔 하실래요",
    "축구 경기 보셨어요?",
    "고양이가 자고 있어요",
    "버스가 늦게 왔어요",
    "책을 한 권 다 읽었습니다",
]


def bm25_top(text: str) -> float:
    if ci._OFFICIAL_BM25 is None:
        return 0.0
    tokens = ci._bm25_tokenize(text)
    if not tokens:
        return 0.0
    scores = ci._OFFICIAL_BM25.get_scores(tokens)
    return float(max(scores)) if len(scores) else 0.0


def main() -> None:
    print(f"현재 코퍼스: OFFICIAL_DOCS {len(ci.OFFICIAL_DOCS)}건 · "
          f"청크 {len(ci._OFFICIAL_CHUNKS)}개 · SCAM_CASES {len(ci.SCAM_CASES)}건")
    print(f"현재 값: _OFFICIAL_MIN_SCORE={ci._OFFICIAL_MIN_SCORE} · match_scam_cases min_score=5.0")
    print()

    # ── 1) BM25 노이즈 바닥
    print("■ 1) 무관한 문장의 BM25 최고점 (= 노이즈 바닥)")
    noise = []
    for t in NOISE:
        s = bm25_top(t)
        noise.append(s)
        print(f"     {s:>7.3f}  {t}")
    print(f"   → 노이즈 최고 {max(noise):.3f} · 평균 {sum(noise)/len(noise):.3f}")
    print(f"   원래 측정(2026-08 초): 4.9 ~ 10.6")
    print()

    # ── 2) 진짜 매칭이 여전히 높은가
    rows = {r["case_id"]: r["평가용_제시문구"]
            for r in csv.DictReader(Path("/corpus/곁눈_평가세트_120건.csv").open(encoding="utf-8-sig"))}
    print("■ 2) '그 제도가 실제로 있는' 케이스의 BM25 최고점 (원래 19~31점대)")
    real = []
    for cid in ("N03", "N04", "N05", "N06", "N07", "N01", "N02", "N08", "N10"):
        if cid not in rows:
            continue
        s = bm25_top(rows[cid])
        real.append((cid, s))
        flag = "통과" if s >= ci._OFFICIAL_MIN_SCORE else "★ 미달"
        print(f"     {cid}  {s:>7.3f}  {flag}")
    passing = [s for _, s in real if s >= ci._OFFICIAL_MIN_SCORE]
    print(f"   → 12.0 을 넘는 건 {len(passing)}/{len(real)}")
    print()

    # ── 3) 12.0 이 여전히 노이즈와 진짜 사이에 있는가
    print("■ 3) 12.0 은 아직 '노이즈 위 · 진짜 아래' 인가")
    top_noise = max(noise)
    min_real = min((s for _, s in real if s >= ci._OFFICIAL_MIN_SCORE), default=0.0)
    print(f"     노이즈 최고 {top_noise:.3f}  <  12.0  <  통과한 진짜 최저 {min_real:.3f}")
    ok = top_noise < ci._OFFICIAL_MIN_SCORE <= min_real
    print(f"     → {'★ 여전히 유효한 위치다' if ok else '★★ 위치가 어긋났다 - 사람 판단 필요'}")
    print()

    # ── 4) SCAM_CASES 어휘 점수 분포
    print("■ 4) match_scam_cases 어휘 점수 — 5.0 근처 분포")
    print(f"   _SCAM_N_DOCS={ci._SCAM_N_DOCS} (이 값이 _keyword_weight 의 분모다)")
    near = []
    for cid, t in rows.items():
        kws = [k for k in ci.extract_keywords(t) if k not in ci.STOPWORDS]
        if not kws:
            continue
        best = 0.0
        for case in ci.SCAM_CASES:
            matched = [k for k in kws if k in case._blob] if hasattr(case, "_blob") else []
            if matched:
                best = max(best, sum(ci._keyword_weight(k) for k in matched))
        if 3.0 <= best <= 8.0:
            near.append((cid, best))
    near.sort(key=lambda x: x[1])
    print(f"   3.0~8.0 구간(경계)에 있는 케이스 {len(near)}건:")
    for cid, s in near[:14]:
        side = "미달" if s < 5.0 else "통과"
        print(f"     {cid}  {s:>6.2f}  {side}")
    print()
    print("★ 값은 바꾸지 않았다. 조정은 승인 후.")


if __name__ == "__main__":
    main()
