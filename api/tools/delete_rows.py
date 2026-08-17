"""운영 DB 행 삭제 — **예상 건수가 맞을 때만** 지운다 (2026-08-17 신설).

실행:
    docker compose exec -T api python -m tools.delete_rows \
        --table events --where "device_hash='...'" --expect 17

■ ★★ 왜 만들었나 — 2026-08-16 사고 ★★
  "events 17행을 지워라" 라는 지시를 받고 device_hash 로 범위를 잡아 지웠는데,
  그 해시에는 **262행**이 있었다. 17은 '15:40 이후' 로 시간을 좁혀 센 값이었고,
  삭제에는 그 시간 조건을 넣지 않았다. 8/01~8/06 의 관측 데이터 237행이 함께
  사라졌고 **백업이 없어 복구하지 못했다.**

  더 나쁜 것은 이것이다: 삭제 직전에 `89219851811ea6df|262` 를 **화면에 찍었다.**
  숫자는 눈앞에 있었는데 아무것도 막지 않았다.
      ★ 확인을 '출력' 하는 것과 '차단' 하는 것은 다르다.
        출력은 사람이 읽어야 작동하고, 사람은 읽지 않는다.

  그래서 이 도구는 **예상 건수를 인자로 강제**하고, 실제 건수가 다르면
  **아무것도 지우지 않고 0이 아닌 코드로 끝난다.**

■ 규칙
  - --expect 는 필수다. 생략할 수 없다.
  - 실제 건수 != 예상 건수  → 중단. 지우지 않는다.
  - --dry-run 이 기본이 아니다(그럼 습관적으로 무시하게 된다). 대신 세는 SQL 과
    지우는 SQL 이 **같은 WHERE** 를 쓰도록 코드가 강제한다.
  - 삭제 전 대상 행을 파일로 내보낸다(미추적 경로). 되돌릴 수 있어야 지운다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import sys
from pathlib import Path

from sqlalchemy import text

from models.db import engine

# ★ 반드시 **마운트된** 경로여야 한다. 컨테이너 안 임의 경로(/docs 등)에 쓰면
#   컨테이너를 다시 만드는 순간 사라진다 - 사라지는 백업은 보호처럼 보여서
#   없느니만 못하다. api/ 는 ./api:/app 로 읽기-쓰기 마운트돼 있다.
#   (2026-08-17 초판이 /docs 로 잡혀 있었고, 첫 실행에서 바로 드러났다.)
BACKUP_DIR = Path("/app/data/deleted_rows") if Path("/app/data").is_dir() else (
    Path(__file__).resolve().parents[1] / "data" / "deleted_rows")
_ALLOWED = {"events", "error_logs", "checks", "evidence", "taggings"}


def main() -> int:
    p = argparse.ArgumentParser(description="예상 건수가 맞을 때만 지운다")
    p.add_argument("--table", required=True, choices=sorted(_ALLOWED))
    p.add_argument("--where", required=True, help="WHERE 절 (따옴표로 감쌀 것)")
    p.add_argument("--expect", required=True, type=int, help="★ 지워질 것으로 예상하는 행 수")
    p.add_argument("--yes", action="store_true", help="확인 없이 진행")
    a = p.parse_args()

    with engine.begin() as conn:
        actual = conn.execute(
            text(f"select count(*) from {a.table} where {a.where}")).scalar_one()

    print(f"[delete_rows] {a.table} where {a.where}")
    print(f"             예상 {a.expect}행 · 실제 {actual}행")

    if actual != a.expect:
        print(f"★★ 중단 — 실제({actual})와 예상({a.expect})이 다르다. 아무것도 지우지 않았다.")
        print("   범위가 생각과 다르다는 뜻이다. WHERE 를 다시 보거나 --expect 를 고칠 것.")
        print("   ★ --expect 를 실제값으로 바꾸기 전에, 왜 다른지 먼저 설명할 수 있어야 한다.")
        return 1

    if actual == 0:
        print("지울 행이 없다. 끝낸다.")
        return 0

    # ★ 되돌릴 수 있어야 지운다. 미추적 경로에 통째로 내보낸다.
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"deleted_{a.table}_{stamp}.csv"
    with engine.begin() as conn:
        rows = conn.execute(text(f"select * from {a.table} where {a.where}"))
        cols = list(rows.keys())
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow(list(r))
    print(f"             백업 {out}")

    if not a.yes:
        print("             --yes 가 없어 여기서 멈춘다(백업만 만들었다).")
        return 0

    with engine.begin() as conn:
        n = conn.execute(text(f"delete from {a.table} where {a.where}")).rowcount
    print(f"             삭제 {n}행 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
