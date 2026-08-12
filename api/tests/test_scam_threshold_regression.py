"""사기사례 매칭 하한선 회귀 테스트 (2026-08-12)
실행: cd api && python -m pytest tests/test_scam_threshold_regression.py -q

■ 왜 이 테스트가 있는가
  `_keyword_weight()` = log((N_DOCS + 1) / (df + 1)) + 1.0 이다.
  `SCAM_CASES` 가 늘면 **모든 단어의 가중치가 함께 올라간다.**

    df=1 일 때  N=51 → 4.258 / N=185 → 5.533  (+30%)
    df=3 일 때  N=51 → 3.565 / N=185 → 4.839  (+36%)

  그런데 하한선 `min_score=5.0` 은 절대값이다. 즉 **사례를 늘리는 것만으로
  하한선이 실질적으로 30% 낮아진 것과 같아진다.** 8/8 에 복구한 방어
  (단어 '은행' 하나로 대출사기 사례가 붙던 문제)가 규모 변경만으로 다시 무력해진다.

  실측 근거: docs/evaluation/IDF척도이동_A안_2026-08-12.md §2
    "정상 오판 0 을 유지하는 최소 min_score"
      N=51 → 6.75(확대셋) / 11.00(홀드아웃)
      N=185 → 14.75 / 13.50
    곡선이 로그를 따르지 않고 계단식이라 "N 이 이만큼이면 하한선은 이만큼"
    이라는 공식을 만들 수 없다. 그래서 **매번 재측정**해야 하는데,
    사람이 잊으면 조용히 무너진다(경보가 없다). 이 테스트가 그 경보다.

■ 무엇을 검사하는가
  정상 케이스(확대 평가셋 + 홀드아웃)에서 사기사례가 매칭되는 건수가
  기준선(BASELINE)을 넘지 않는지만 본다.
  ★ 판정 로직은 건드리지 않는다. 읽기만 한다.

■ 기준선을 0 이 아니라 현재값으로 두는 이유
  지금 이미 각 세트에서 1건씩 매칭된다(정상 오판 1건). 0 으로 두면 이 테스트가
  처음부터 빨간불이라 아무도 보지 않게 된다. **현재값에 고정해 두고 "늘어나면"
  실패하게 한다** - 늘어난다는 것은 코퍼스나 척도가 바뀌었다는 뜻이다.

  기준선을 올려야 할 때는 반드시 위 문서처럼 재측정 근거를 남기고 올린다.
  근거 없이 숫자만 올리면 이 테스트는 의미가 없어진다.
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import corpus_index  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "corpus/곁눈_평가세트_120건.csv"
HOLD = Path(__file__).resolve().parent / "fixtures/holdout/holdout_30.csv"

# ★ 2026-08-12 실측 기준선. 올릴 때는 재측정 근거를 함께 남길 것.
BASELINE = {"확대 평가셋": 1, "홀드아웃": 1}


def _normals(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        r["평가용_제시문구"]
        for r in csv.DictReader(path.open(encoding="utf-8-sig"))
        if r["입력채널"] != "음성" and r["기대판단"] == "정상"
    ]


@pytest.mark.parametrize("label,path", [("확대 평가셋", EVAL), ("홀드아웃", HOLD)])
def test_normal_cases_do_not_gain_scam_matches(label: str, path: Path) -> None:
    """정상 문자에 사기사례가 붙는 건수가 기준선을 넘으면 실패한다."""
    if not corpus_index.SCAM_CASES:
        pytest.skip("SCAM_CASES 가 로컬에 없다 - 스킵")
    texts = _normals(path)
    if not texts:
        pytest.skip(f"{path.name} 이 없거나 정상 케이스가 없다 - 스킵")

    hits = [t for t in texts if corpus_index.match_scam_cases(t)]
    assert len(hits) <= BASELINE[label], (
        f"[{label}] 정상 {len(texts)}건 중 사기사례 매칭이 {len(hits)}건으로 "
        f"기준선 {BASELINE[label]}건을 넘었다.\n"
        f"  매칭된 문구: {[t[:34] for t in hits]}\n"
        f"  ★ SCAM_CASES 가 늘었다면 IDF 척도가 이동해 하한선(min_score=5.0)이 "
        f"실질적으로 낮아진 것이다. 하한선을 재교정하거나, 기준선을 올릴 근거를 "
        f"docs/evaluation/ 에 남겨라. 숫자만 올리지 마라."
    )


def test_scam_corpus_size_is_recorded() -> None:
    """SCAM_CASES 규모가 바뀌면 알려 준다 - 위 테스트가 통과해도 척도는 이미 움직였다.

    ★ 이건 '실패시키기 위한' 테스트가 아니라 규모 변경을 눈에 띄게 하기 위한 것이다.
      건수가 바뀌면 이 상수를 갱신하면서 재교정 여부를 함께 판단하게 된다.
    """
    if not corpus_index.SCAM_CASES:
        pytest.skip("SCAM_CASES 가 로컬에 없다 - 스킵")
    EXPECTED = 51  # 2026-08-12 기준 (relabeled 30 + public_data_warning 21)
    assert len(corpus_index.SCAM_CASES) == EXPECTED, (
        f"SCAM_CASES 가 {EXPECTED} → {len(corpus_index.SCAM_CASES)}건으로 바뀌었다.\n"
        f"  ★ _keyword_weight 가 log((N+1)/(df+1))+1 이라 N 이 바뀌면 모든 점수가 "
        f"함께 움직인다. min_score=5.0 은 절대값이라 자동으로 따라가지 않는다.\n"
        f"  재교정 절차: experiments/diag_idf_scale.py 로 '정상 오판 0 유지 최소 "
        f"min_score' 를 다시 재고, 결과를 docs/evaluation/ 에 남긴 뒤 이 상수를 갱신할 것."
    )
