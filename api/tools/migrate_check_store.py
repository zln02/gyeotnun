"""checks/taggings 에 컬럼을 더한다 (2026-08-16, #33 3단계).

실행: (컨테이너 안)  python -m tools.migrate_check_store
      (호스트)       docker compose exec -T api python -m tools.migrate_check_store
      ★ 반드시 -m 으로 실행할 것 (purge_old_records.py 와 같은 이유 - sys.path).

■ 왜 별도 스크립트인가
  models.db.init_db() 는 `Base.metadata.create_all` 이다. **없는 테이블은 만들지만
  있는 테이블에 컬럼을 더하지는 않는다.** checks 테이블은 이미 있으므로(행 0건),
  모델에 컬럼만 추가하면 운영 DB 는 그대로 남고 첫 INSERT 에서 터진다.

■ 무엇을 더하나
    checks.device_hash   varchar(64)   소유자 대조용 sha256 (원문 device_id 아님)
    checks.history       json          확인 질문 대화 이력
    taggings.device_hash varchar(64)

■ 안전
  - ADD COLUMN IF NOT EXISTS 라 여러 번 돌려도 안전하다(멱등).
  - 컬럼 추가만 한다. **지우거나 바꾸지 않는다.** 기존 행은 NULL 로 남는다.
  - SQLite(테스트용)에는 IF NOT EXISTS 가 없어, 컬럼 목록을 먼저 보고 없을 때만 더한다.
"""
from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from models.db import engine

log = logging.getLogger("gyeotnun.migrate")

# (테이블, 컬럼, 타입)
_COLUMNS = [
    ("checks", "device_hash", "VARCHAR(64)"),
    ("checks", "history", "JSON"),
    ("taggings", "device_hash", "VARCHAR(64)"),
]
_INDEXES = [
    ("ix_checks_device_hash", "checks", "device_hash"),
    ("ix_taggings_device_hash", "taggings", "device_hash"),
]


def migrate() -> dict[str, int]:
    insp = inspect(engine)
    is_sqlite = engine.url.get_backend_name() == "sqlite"
    added, skipped = 0, 0

    with engine.begin() as conn:
        for table, column, coltype in _COLUMNS:
            if table not in insp.get_table_names():
                print(f"  [건너뜀] 테이블 {table} 이 없다 - create_all 이 만들 것이다")
                skipped += 1
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if column in existing:
                print(f"  [이미 있음] {table}.{column}")
                skipped += 1
                continue
            # SQLite 는 IF NOT EXISTS 를 지원하지 않는다 - 위에서 이미 확인했다.
            clause = "" if is_sqlite else "IF NOT EXISTS "
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {clause}{column} {coltype}"))
            print(f"  [추가] {table}.{column} {coltype}")
            added += 1

        for name, table, column in _INDEXES:
            if table not in insp.get_table_names():
                continue
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
            except Exception as e:  # noqa: BLE001 - 인덱스는 있으면 좋고 없어도 동작한다
                print(f"  [인덱스 생략] {name}: {type(e).__name__}")

    return {"added": added, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(f"[migrate] 대상 DB: {engine.url.get_backend_name()}")
    r = migrate()
    print(f"[migrate] 완료 - 추가 {r['added']}개 / 이미 있음·건너뜀 {r['skipped']}개")
