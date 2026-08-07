"""보관 기간이 지난 관측 로그를 삭제한다 (events / error_logs).

배경: 두 테이블은 device_hash(원문 아님)만 남기지만, 지금까지 나이 기준 삭제가
      없어 무기한 축적됐다. settings.RETENTION_DAYS(기본 90일)보다 오래된 행을 지운다.

- 삭제 대상은 **관측 로그 2종만**이다. checks/taggings 등 서비스 데이터는 현재
  DB 에 쓰이지 않으므로(인메모리) 대상이 아니다. 이후 DB 로 옮기면 여기 추가할 것.
- created_at 은 naive UTC(models.db._now = datetime.utcnow())라 컷오프도 UTC 로 맞춘다.
- 멱등하다: 여러 번 돌려도 안전하고, 지울 게 없으면 0 을 남긴다.

실행: (컨테이너 안)  python -m tools.purge_old_records
      (호스트 cron) sudo docker compose exec -T api python -m tools.purge_old_records
      ★ 반드시 -m 으로 실행할 것. 파일 경로로 실행하면 sys.path 가 /app/tools 가 되어
        `from config import ...` 가 ModuleNotFoundError 로 죽는다(2026-08-07 까지
        04:00 cron 이 이 이유로 매일 실패했다).
"""
from __future__ import annotations

import datetime as _dt
import logging

from config import settings
from models.db import ErrorLog, Event, SessionLocal

log = logging.getLogger("gyeotnun.purge")


def purge(retention_days: int | None = None) -> dict[str, int]:
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        log.info("[purge] RETENTION_DAYS=%s → 삭제 건너뜀", days)
        return {"events": 0, "error_logs": 0, "skipped": 1}

    cutoff = _dt.datetime.utcnow() - _dt.timedelta(days=days)
    deleted: dict[str, int] = {}
    db = SessionLocal()
    try:
        for name, model in (("events", Event), ("error_logs", ErrorLog)):
            n = (
                db.query(model)
                .filter(model.created_at < cutoff)
                .delete(synchronize_session=False)
            )
            deleted[name] = int(n)
        db.commit()
    finally:
        db.close()

    log.info("[purge] cutoff=%s (%d일) 삭제: events=%d error_logs=%d",
             cutoff.isoformat(), days, deleted.get("events", 0), deleted.get("error_logs", 0))
    return deleted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = purge()
    # 실행 시각을 함께 남긴다 - purge.log 는 append 방식이라 시각이 없으면
    # 어제 04:00 실행분과 오늘 수동 실행분을 구분할 수 없다.
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[purge] {now} 보관 {settings.RETENTION_DAYS}일 초과 삭제 완료: "
          f"events={result.get('events', 0)}건, error_logs={result.get('error_logs', 0)}건")
