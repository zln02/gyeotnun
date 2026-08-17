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

■ 규칙 (2026-08-17 확정 — 예외 없음)
      백업  →  복원 리허설  →  --expect 일치  →  삭제
  - **행 수와 무관하다.** "작아서 생략" 이 이번 사고의 원인이다.
  - --expect 는 필수다. 생략할 수 없다. 실제 건수와 다르면 중단한다.
  - 백업과 복원 리허설은 **끌 수 없다.** 플래그로 만들면 습관적으로 끈다.
  - 세는 SQL 과 지우는 SQL 이 **같은 WHERE** 를 쓰도록 코드가 강제한다.

■ ★ 복원 리허설을 왜 넣었나
  2026-08-15 error_logs 정리 때, 백업 SQL 을 grep 으로 골라 담았더니 detail 에
  줄바꿈이 든 행에서 문장이 잘려 **복원 불가능한 백업**이 됐다. 그때는 리허설을
  돌려서 잡았다. 파일이 만들어졌다는 것과 그 파일로 되살릴 수 있다는 것은 다르다.
  → 여기서는 백업 CSV 를 **임시 테이블에 실제로 넣어 보고**, 행 수와 내용
    체크섬이 원본과 같은지 확인한 뒤에야 삭제로 넘어간다. 리허설은 롤백된다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
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


def _encode(v):
    """CSV 한 칸으로 쓴다. ★ JSON 컬럼은 반드시 JSON 으로 쓴다.

    파이썬 기본 str() 은 dict/list 를 repr 로 쓴다(작은따옴표). 그 CSV 로는
    JSON 컬럼을 복원할 수 없다 - 되살릴 수 없는 백업이 된다.
    2026-08-17 복원 리허설이 checks.history 에서 이걸 실제로 잡아냈다.
    """
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return ""
    return v


def _rehearse_restore(table: str, where: str, backup: Path, cols: list[str]) -> tuple[bool, str]:
    """백업 CSV 를 임시 테이블에 실제로 넣어 보고 원본과 같은지 확인한다.

    ★ 트랜잭션 안에서 하고 **롤백한다.** 운영 테이블은 건드리지 않는다.
    ★ 비교는 두 가지다: 행 수, 그리고 정렬된 전체 내용의 체크섬.
      행 수만 보면 값이 깨진 백업을 통과시킨다.
    """
    import hashlib

    with backup.open(encoding="utf-8") as f:
        read = list(csv.reader(f))
    if not read or read[0] != cols:
        return False, f"CSV 머리글이 컬럼과 다르다 ({len(read)}줄)"
    body = read[1:]

    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(
                    f"create temp table _rehearsal (like {table} including defaults) "
                    "on commit drop"))
                collist = ", ".join(f'"{c}"' for c in cols)
                params = ", ".join(f":p{i}" for i in range(len(cols)))
                stmt = text(f"insert into _rehearsal ({collist}) values ({params})")
                for row in body:
                    conn.execute(stmt, {f"p{i}": (None if v == "" else v)
                                        for i, v in enumerate(row)})

                n = conn.execute(text("select count(*) from _rehearsal")).scalar_one()
                if n != len(body):
                    return False, f"복원 행수 {n} != 백업 행수 {len(body)}"

                # 내용 체크섬 - 원본과 복원본을 같은 방식으로 문자열화해 비교한다.
                def digest(src: str, cond: str) -> str:
                    rows = conn.execute(text(
                        f"select {collist} from {src} {cond} order by 1")).fetchall()
                    h = hashlib.md5()
                    for r in rows:
                        h.update("\x1f".join("" if v is None else str(v) for v in r).encode())
                        h.update(b"\x1e")
                    return h.hexdigest()

                a_dig = digest(table, f"where {where}")
                b_dig = digest("_rehearsal", "")
                if a_dig != b_dig:
                    return False, f"내용 체크섬 불일치 (원본 {a_dig[:8]} != 복원 {b_dig[:8]})"
                return True, f"{n}행 복원 · 체크섬 {a_dig[:8]} 일치 (롤백함)"
            finally:
                trans.rollback()
    except Exception as e:  # noqa: BLE001
        return False, f"리허설 중 오류: {type(e).__name__}: {e}"


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
                w.writerow([_encode(v) for v in r])
    print(f"             백업 {out}")

    # ── 복원 리허설. ★ 백업이 만들어진 것과 되살릴 수 있는 것은 다르다.
    ok, detail = _rehearse_restore(a.table, a.where, out, cols)
    print(f"             복원 리허설 {'통과' if ok else '실패'} — {detail}")
    if not ok:
        print("★★ 중단 — 백업으로 되살릴 수 없다. 아무것도 지우지 않았다.")
        return 1

    if not a.yes:
        print("             --yes 가 없어 여기서 멈춘다(백업·리허설까지만 했다).")
        return 0

    with engine.begin() as conn:
        n = conn.execute(text(f"delete from {a.table} where {a.where}")).rowcount
    print(f"             삭제 {n}행 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
