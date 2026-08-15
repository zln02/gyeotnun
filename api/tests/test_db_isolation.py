"""테스트가 운영 DB 를 건드리지 않는지 검증한다 (2026-08-15).

■ 왜 필요한가
  2026-08-14 감사에서, pytest 를 한 번 돌릴 때마다 운영 postgres 의 error_logs 에
  행이 들어가는 것을 확인했다(누적 GN-001 150 / EX-003 135). log_incident() 가
  best-effort 로 INSERT 하는데, 그 호출부를 지나가는 테스트가 있기 때문이다.
  결과적으로 GET /errors/summary 가 "실제 사용자에게 난 장애"를 말하지 못했다.

  conftest.py 가 DATABASE_URL 을 임시 SQLite 로 덮어써서 분리했다. 이 파일은
  **그 분리가 앞으로도 유지되는지** 를 지킨다. 누군가 conftest 의 줄 순서를 바꾸거나
  덮어쓰기를 지우면 여기서 먼저 빨간불이 켜진다.

■ 덤으로 얻는 것
  분리된 SQLite 에서는 "장애가 실제로 DB 에 기록되는가" 를 모의 없이 검증할 수 있다.
  아래 두 번째 테스트가 그것이다 - 예전에는 운영 DB 를 더럽히지 않고서는
  확인할 수 없던 경로다.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import ErrorLog, SessionLocal, engine     # noqa: E402
from services.incident_log import log_incident           # noqa: E402


def test_engine_is_not_production_db():
    """테스트 세션의 DB 엔진은 반드시 SQLite 다."""
    url = str(engine.url)
    assert url.startswith("sqlite"), f"운영 DB 에 붙어 있다: {url.split('@')[-1]}"
    assert "postgresql" not in url


def test_log_incident_writes_a_row_to_the_test_db():
    """장애 기록이 실제로 DB 에 남는가 - 분리된 SQLite 에서 확인한다."""
    code = "SYS-000"  # 실제 사용 코드와 겹치지 않는 진단용 코드
    db = SessionLocal()
    try:
        before = db.query(ErrorLog).filter(ErrorLog.code == code).count()
    finally:
        db.close()

    log_incident(code, screen="S1", device_id="test-device", detail="테스트 격리 확인")

    db = SessionLocal()
    try:
        rows = db.query(ErrorLog).filter(ErrorLog.code == code).all()
        assert len(rows) == before + 1, "log_incident 가 DB 에 행을 남기지 못했다"
        row = rows[-1]
        # device_id 는 해시로만 저장된다(원문이 남으면 안 된다).
        assert row.device_hash and row.device_hash != "test-device"
        assert len(row.device_hash) == 64
    finally:
        db.close()
