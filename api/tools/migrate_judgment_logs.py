"""judgment_logs 테이블을 만든다 (2026-08-20, 판단 행동 로그).

실행: (컨테이너 안)  python -m tools.migrate_judgment_logs
      (호스트)       docker compose exec -T api python -m tools.migrate_judgment_logs
      ★ 반드시 -m 으로 실행할 것 (migrate_check_store·purge_old_records 와 같은 이유 - sys.path).

■ 왜 별도 스크립트인가 — create_all 이 있는데도
  models.db.init_db() 는 `Base.metadata.create_all` 이고 **없는 테이블은 만든다.**
  기동 시 자동으로 생기긴 한다. 그런데도 이 스크립트를 두는 이유는 셋이다.
    1) init_db() 는 startup 에서 예외를 삼킨다(main.py). DB 가 잠깐 안 붙으면
       테이블 없이 뜨고, 그 사실이 조용히 지나간다. 여기서는 **결과를 눈으로 본다.**
    2) 인덱스는 create_all 이 모델에 선언된 것만 만든다. 나중에 조회 축이 늘면
       이 파일이 그 자리가 된다(migrate_check_store 와 같은 역할).
    3) 배포 절차에서 "무엇이 언제 생겼나"를 사람이 확인할 수 있어야 한다.

■ 안전
  - CREATE TABLE IF NOT EXISTS 성격이라 **여러 번 돌려도 안전하다**(멱등).
  - 기존 테이블을 건드리지 않는다. 지우거나 바꾸는 구문이 하나도 없다.
  - ★ 데이터를 넣지 않는다. 운영 DB 에 시험 행을 만들지 않는다.

■ 되돌리기
  ★ 이 스크립트는 되돌리지 않는다. 표를 지워야 한다면 tools/delete_rows.py 절차
    (백업 → 복원 리허설 → --expect)를 따른다. deploy/README.md "운영 DB 삭제 규칙".
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from models.db import Base, JudgmentLog, engine

log = logging.getLogger("gyeotnun.migrate")

_INDEXES = [
    ("ix_judgment_logs_user_ref", "judgment_logs", "user_ref"),
    ("ix_judgment_logs_session_type", "judgment_logs", "session_type"),
    ("ix_judgment_logs_created_at", "judgment_logs", "created_at"),
]


def migrate() -> dict[str, object]:
    insp = inspect(engine)
    existed = JudgmentLog.__tablename__ in insp.get_table_names()

    # checkfirst=True 가 기본이다 - 이미 있으면 아무것도 하지 않는다.
    Base.metadata.create_all(bind=engine, tables=[JudgmentLog.__table__])

    made = []
    with engine.begin() as conn:
        for name, table, column in _INDEXES:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
                made.append(name)
            except Exception as e:  # noqa: BLE001 - 인덱스는 있으면 좋고 없어도 동작한다
                print(f"  [인덱스 생략] {name}: {type(e).__name__}")

    insp = inspect(engine)
    columns = [c["name"] for c in insp.get_columns(JudgmentLog.__tablename__)]
    return {"existed": existed, "columns": columns, "indexes": made}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"[migrate] 대상 DB: {engine.url.get_backend_name()}")
    r = migrate()
    print(f"[migrate] judgment_logs: {'이미 있었음' if r['existed'] else '새로 만듦'}")
    print(f"[migrate] 컬럼 {len(r['columns'])}개: {', '.join(r['columns'])}")
    print(f"[migrate] 인덱스 {len(r['indexes'])}개 확인")
    print("[migrate] ★ 자유 텍스트 컬럼 없음 - 개인정보 원칙은 "
          "tests/test_judgment_log.py 가 자동으로 지킨다")
