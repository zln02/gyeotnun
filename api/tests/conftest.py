"""테스트 공통 준비.

■ 1) 테스트는 운영 DB 를 건드리지 않는다 (2026-08-15)
  이 파일 맨 위에서 DATABASE_URL 을 **임시 SQLite 파일**로 덮어쓴다.
  2026-08-11 보관기간 자동삭제 검증 때 쓴 방식과 같다
  (docs/reports/2026-08-11_보관기간_자동삭제_동작확인.txt - sqlite:////tmp/purge_verify.db).

  왜 필요했나: log_incident() 는 best-effort 로 error_logs 에 INSERT 한다.
  그 호출부를 지나가는 테스트가 있으면 **운영 postgres 에 행이 쌓인다.**
  2026-08-14 감사에서 실제로 쌓인 것을 확인했다(GN-001 150 / EX-003 135).
  그러면 GET /errors/summary 의 집계가 "실제 사용자에게 난 장애"를 말하지 못한다.

  ★ 순서가 전부다. models/db.py 는 **import 시점에** settings.DATABASE_URL 로
    엔진을 만든다(models/db.py:216). 그래서 env 덮어쓰기는 config 를 import 하는
    그 어떤 코드보다 먼저 와야 한다. 아래 코드의 줄 순서를 바꾸지 말 것.

  ★ 가드: 덮어쓰기가 어떤 이유로든 늦으면(다른 conftest 가 먼저 돈다든지)
    조용히 운영 DB 로 붙는다. 그래서 엔진 URL 을 확인해서 sqlite 가 아니면
    **테스트를 즉시 중단**한다. 실패보다 조용한 오염이 나쁘다.

  이 분리 덕분에 "장애가 실제로 DB 에 기록되는가" 를 모의(mock) 없이
  이 SQLite 에서 그대로 검증할 수 있다.

■ 2) 폴백률 관측 상태 초기화 (2026-08-13)
  search.py 의 폴백률 관측(EX-006)은 최근 N건을 프로세스 메모리(deque)에 들고
  본다. 폴백을 모의하는 테스트가 남긴 기록이 그다음 테스트까지 따라가면
  관계없는 테스트가 도는 중에 임계를 넘어 EX-006 이 발생하고, 실행 순서에 따라
  결과가 달라져 테스트가 불안정해진다. 그래서 매 테스트 앞뒤로 관측 상태만
  초기화한다. 관측 로직도, 임계값도, 판정 로직도 건드리지 않는다.
"""
from __future__ import annotations

import os
import sys
import tempfile

# ---------------------------------------------------------------- (1) 운영 DB 분리
# ★★ 이 블록은 반드시 프로젝트 코드 import 보다 위에 있어야 한다. ★★
_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "gyeotnun_test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from models.db import Base, engine  # noqa: E402

# 가드 - 여기서 걸리면 위 덮어쓰기가 늦은 것이다. 운영 DB 로 한 행이라도
# 들어가기 전에 수집 단계에서 멈춘다.
_ENGINE_URL = str(engine.url)
if not _ENGINE_URL.startswith("sqlite"):
    raise RuntimeError(
        "테스트가 운영 DB 에 붙으려 한다. 중단한다. "
        f"engine={_ENGINE_URL.split('@')[-1]} / 기대값=sqlite. "
        "conftest.py 의 DATABASE_URL 덮어쓰기가 프로젝트 import 보다 뒤로 밀렸는지 확인할 것."
    )

# 매 실행마다 깨끗한 상태에서 시작한다. sqlite 임을 위에서 확인한 뒤에만 부른다.
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _assert_not_production_db():
    """세션 내내 엔진이 바뀌지 않았는지 한 번 더 확인한다."""
    assert str(engine.url).startswith("sqlite"), "테스트 도중 엔진이 운영 DB 로 바뀌었다"
    yield


# ---------------------------------------------------------------- (2) 관측 상태 초기화
@pytest.fixture(autouse=True)
def _reset_search_fallback_observer():
    from services import search

    search._recent_search_fallbacks.clear()
    search._search_fallback_alerted = False
    yield
    search._recent_search_fallbacks.clear()
    search._search_fallback_alerted = False
