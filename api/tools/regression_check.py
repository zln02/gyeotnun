"""회귀 검사 자동 실행 (2026-08-15).

■ 왜 생겼나
  docs/evaluation/하한선_결정_2026-08-13.md 와 IDF척도이동_A안_2026-08-12.md 는
  "CI 가 기준선을 지킨다"를 전제로 min_score=5.0 유지를 결정했다. 그런데
  2026-08-14 감사에서 **CI 가 실재하지 않는다**는 것이 확인됐다. 테스트 파일은
  있었지만 그것을 자동으로 돌리는 것이 아무 데도 없었다. 결정의 전제가
  비어 있던 것이다.

  GitHub Actions 는 쓰지 않는다. 검색 코퍼스가 저장소에 없어 호스트 러너에서는
  회귀 테스트가 전부 skip 되고(=항상 초록불), 공개 저장소에 셀프호스트 러너를
  붙이는 것은 보안 사고 경로다. 그래서 코퍼스가 실제로 있는 이 서버에서
  purge cron 과 같은 방식으로 매일 돌린다.

■ 무엇을 보는가
  1) 회귀 테스트 3건 (tests/test_scam_threshold_regression.py)
     - 정상 오판 기준선 (확대 평가셋 / 홀드아웃)
     - SCAM_CASES 규모 변화
  2) 위 테스트가 skip 되지 않았는지
     ★ 이게 핵심이다. 코퍼스가 없으면 테스트는 '실패'가 아니라 '스킵'이고,
       스킵은 초록불로 보인다. 아무것도 검사하지 않은 초록불이 가장 위험하다.
     ★ 통과/실패만이 아니라 **실측한 숫자 자체**를 로그에 남긴다. 나중에
       "언제부터 늘었나"를 로그만 보고 되짚을 수 있어야 한다.

  판정 로직·임계값·코퍼스는 읽기만 한다. 아무것도 고치지 않는다.

■ 운영 DB 를 건드리지 않는다
  pytest 는 tests/conftest.py 가 DATABASE_URL 을 임시 SQLite 로 덮어쓴 상태에서
  돈다. 이 도구 자체도 DB 에 쓰지 않는다. 결과는 deploy/regression.log 에만 남는다.

실행: (컨테이너 안)  python -m tools.regression_check
      (호스트 cron) sudo docker compose exec -T api python -m tools.regression_check
      ★ 반드시 -m 으로 실행할 것 (purge_old_records.py 와 같은 이유).

종료 코드: 0 = 정상, 1 = 회귀 발생 또는 검사 불능(스킵 포함)
"""
from __future__ import annotations

import csv
import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

APP = Path(__file__).resolve().parents[1]          # /app
REPO = APP.parent
TEST_FILE = "tests/test_scam_threshold_regression.py"

EVAL_CSV = REPO / "corpus/곁눈_평가세트_120건.csv"
HOLDOUT_CSV = APP / "tests/fixtures/holdout/holdout_30.csv"


def _normals(path: Path) -> list[str]:
    """평가셋에서 '정상' 기대판단인 문자만 뽑는다 (회귀 테스트와 같은 규칙)."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig") as fh:
        return [
            r["평가용_제시문구"]
            for r in csv.DictReader(fh)
            if r["입력채널"] != "음성" and r["기대판단"] == "정상"
        ]


def measure() -> list[str]:
    """기준선 숫자를 실측한다 - 통과/실패가 아니라 '지금 몇 건인가'를 남기기 위한 것."""
    lines: list[str] = []
    try:
        from services import corpus_index
    except Exception as e:  # noqa: BLE001
        return [f"측정 불가(import 실패): {type(e).__name__}"]

    lines.append(f"SCAM_CASES={len(corpus_index.SCAM_CASES)}건")
    for label, path in (("확대평가셋", EVAL_CSV), ("홀드아웃", HOLDOUT_CSV)):
        texts = _normals(path)
        if not texts:
            lines.append(f"{label}=측정불가(파일없음)")
            continue
        hits = [t for t in texts if corpus_index.match_scam_cases(t)]
        lines.append(f"{label} 정상오판={len(hits)}/{len(texts)}")
    return lines


def run_tests() -> tuple[bool, int, int, int, str]:
    """회귀 테스트를 돌린다. (성공여부, passed, failed, skipped, 마지막줄)"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_FILE, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(APP),
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    tail = [ln for ln in out.strip().splitlines() if ln.strip()]
    summary = tail[-1] if tail else "(출력 없음)"

    def _n(word: str) -> int:
        m = re.search(rf"(\d+) {word}", out)
        return int(m.group(1)) if m else 0

    passed, failed, skipped = _n("passed"), _n("failed"), _n("skipped")
    # ★ 스킵도 실패로 본다. 코퍼스가 없어 아무것도 검사하지 못한 초록불이
    #   가장 위험하다 - 그게 GitHub Actions 를 안 쓰는 이유이기도 하다.
    ok = proc.returncode == 0 and failed == 0 and skipped == 0 and passed > 0
    return ok, passed, failed, skipped, summary


def main() -> int:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ok, passed, failed, skipped, summary = run_tests()
    metrics = " / ".join(measure())

    status = "OK" if ok else "FAIL"
    print(f"[regression] {now} {status} passed={passed} failed={failed} skipped={skipped} | {metrics}")
    if not ok:
        # ★ 실패 줄은 grep 하기 쉬운 고정 접두어로 남긴다: grep '\[regression\] FAIL'
        print(f"[regression] FAIL 상세: {summary}")
        print("[regression] FAIL 조치: 상수를 고치기 전에 "
              "docs/evaluation/하한선_결정_2026-08-13.md 부터 다시 읽을 것. "
              "skipped>0 이면 코퍼스가 컨테이너에 마운트됐는지 먼저 확인.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
