"""보관 기간이 지난 기록을 삭제한다 (관측 로그 + 확인 기록).

배경: 이 테이블들은 device_hash(원문 아님)만 남기지만, 지금까지 나이 기준 삭제가
      없어 무기한 축적됐다. settings.RETENTION_DAYS(기본 90일)보다 오래된 행을 지운다.

- ★ 2026-08-16 (#33 3단계): checks·evidence·taggings 를 대상에 추가했다.
  그전까지는 관측 로그 2종(events/error_logs)만 지웠는데, 확인 기록이 프로세스
  메모리에 있어 애초에 DB 에 없었기 때문이다. 이제 checks 가 DB 로 옮겨졌으므로
  **기획서의 "90일 삭제" 서술이 이 잡으로 실제로 참이 된다.**
- ★ 삭제 순서가 중요하다. evidence·taggings 가 checks.id 를 FK 로 참조하므로
  **자식(evidence/taggings) 을 먼저, 부모(checks) 를 나중에** 지운다. 순서가
  거꾸로면 외래키 위반으로 트랜잭션 전체가 실패한다.
  자식은 '자기 나이'가 아니라 **부모 checks 의 나이**를 기준으로 지운다 - 그래야
  부모가 사라지는데 자식만 남는 상태가 생기지 않는다.
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
from models.db import Check, ErrorLog, Event, Evidence, SessionLocal, Tagging

log = logging.getLogger("gyeotnun.purge")


def purge(retention_days: int | None = None) -> dict[str, int]:
    days = settings.RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        log.info("[purge] RETENTION_DAYS=%s → 삭제 건너뜀", days)
        return {"events": 0, "error_logs": 0, "evidence": 0,
                "taggings": 0, "checks": 0, "skipped": 1}

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

        # ★ 확인 기록. 자식 → 부모 순서를 지킨다(위 머리말 참고).
        old_checks = db.query(Check.id).filter(Check.created_at < cutoff).subquery()
        for name, model in (("evidence", Evidence), ("taggings", Tagging)):
            n = (
                db.query(model)
                .filter(model.check_id.in_(db.query(old_checks.c.id)))
                .delete(synchronize_session=False)
            )
            deleted[name] = int(n)
        deleted["checks"] = int(
            db.query(Check).filter(Check.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()

    log.info("[purge] cutoff=%s (%d일) 삭제: events=%d error_logs=%d "
             "evidence=%d taggings=%d checks=%d",
             cutoff.isoformat(), days, deleted.get("events", 0), deleted.get("error_logs", 0),
             deleted.get("evidence", 0), deleted.get("taggings", 0), deleted.get("checks", 0))
    return deleted


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = purge()
    # 실행 시각을 함께 남긴다 - purge.log 는 append 방식이라 시각이 없으면
    # 어제 04:00 실행분과 오늘 수동 실행분을 구분할 수 없다.
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[purge] {now} 보관 {settings.RETENTION_DAYS}일 초과 삭제 완료: "
          f"events={result.get('events', 0)}건, error_logs={result.get('error_logs', 0)}건, "
          f"evidence={result.get('evidence', 0)}건, taggings={result.get('taggings', 0)}건, "
          f"checks={result.get('checks', 0)}건")
