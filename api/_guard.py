"""실험·벤치 스크립트가 운영 DB 에 쓰지 못하게 막는다 (2026-08-17 신설).

사용 — ★ 반드시 services/models 보다 **먼저** 임포트할 것

    import sys
    sys.path.insert(0, "/app")
    import _guard  # noqa: F401  ★ services/models 보다 먼저

    from services import search   # 이 아래부터 안전하다

■ ★★ 왜 순서가 중요한가 ★★
  `models.db` 는 **임포트 시점**에 DATABASE_URL 을 읽어 engine 을 만든다.
  services 를 먼저 임포트하면 그 순간 이미 운영 DB 로 연결이 굳는다.
  이 파일을 나중에 임포트해 봐야 아무것도 못 막는다.
  (tests/conftest.py 가 같은 이유로 맨 위에서 DATABASE_URL 을 덮는다.)

■ 무엇을 막는가
  실험 스크립트는 DB 를 쓰려는 의도가 없다. 그런데 그 안에서 부르는
  collect_evidence · generate_question · extract_from_image · tag_error_type_llm 이
  실패 경로에서 log_incident() 를 부르고, 그게 **운영 error_logs 에 쌓인다.**

  2026-08-16~17 실측: 운영 error_logs 의 GN-001 8건 중 **7건이 실험 산물**이었다.
  실사용자가 만든 것은 1건뿐이다. 사고 기록이 내 실험으로 희석됐다.

■ 무엇을 막지 않는가
  운영 DB 를 건드리는 것이 **목적인** 도구는 대상이 아니다. 가드를 걸면 도구가 죽는다.
      tools/purge_old_records.py · tools/migrate_check_store.py · tools/delete_rows.py

■ 기각한 다른 방식과 이유 (기록해 둔다)
  - sitecustomize.py 로 모든 파이썬 프로세스에 자동 적용
      → 기각. uvicorn 도 같은 인터프리터다. 조건 판정이 한 번만 틀려도
        **운영 서버가 sqlite 로 뜬다.** 운영 데이터가 조용히 사라지는 방향의 실패다.
  - services/incident_log.py 가 호출자를 보고 기록을 건너뛴다
      → 기각. 한 곳만 고치면 32개가 덮이는 장점은 크다. 그러나 판정이 틀리면
        **진짜 사고의 기록이 조용히 사라진다.** 이 프로젝트가 가장 피해야 할
        실패 방식이다 - 우리는 사고를 기록으로 남겨 배우는 쪽을 택해 왔다.
  - 문서·실행 래퍼로만 강제
      → 기각. 사람이 안 쓰면 그만이다. 2026-08-16 사고의 교훈("출력과 차단은
        다르다")과 정면으로 어긋난다.

■ 빠뜨림은 테스트가 막는다
  tests/test_experiment_db_guard.py 가 experiments/ · tools/ 를 훑어
  "services/models 를 임포트하는데 _guard 를 먼저 임포트하지 않은 파일"을 잡는다.
  새 실험을 만들며 잊으면 매일 05:00 회귀 검사가 실패한다.
  ★ 사람의 기억이 아니라 검사가 지킨다.
"""
from __future__ import annotations

import os
import tempfile

# 운영 DB 로 볼 스킴. 이 중 하나면 임시 SQLite 로 덮는다.
_PROD_SCHEMES = ("postgresql", "postgres", "mysql")

EXPERIMENT_DB_PATH = os.path.join(tempfile.gettempdir(), "gyeotnun_experiment.db")


def install() -> str:
    """운영 DB 를 가리키고 있으면 임시 SQLite 로 덮는다. 최종 DATABASE_URL 을 돌려준다."""
    url = os.environ.get("DATABASE_URL", "")
    if any(url.startswith(s) for s in _PROD_SCHEMES):
        safe = f"sqlite:///{EXPERIMENT_DB_PATH}"
        os.environ["DATABASE_URL"] = safe
        print(f"[_guard] 실험용 DB 로 전환: {url.split('@')[-1]} -> {EXPERIMENT_DB_PATH}")
        print("[_guard] ★ 운영 DB 에는 아무것도 쓰지 않는다.")
        return safe
    return url


CURRENT_DATABASE_URL = install()
