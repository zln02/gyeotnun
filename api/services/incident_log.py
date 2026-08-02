"""
장애 로그 수집 (2026-08, 8/2 보안 멘토링 지시사항)
담당: 박진영

멘토 조언(원문): "저장 실패 시 사용자에게 조치를 요구하지 말고, 서버가 로그를
받아 장애를 인지하고 상태를 공지한 뒤 수정하는 방식으로 가라."

이 모듈은 그 "서버가 인지" 부분만 담당한다. 어디서 호출하든 두 가지를 한다.
  1) 항상 Python 로깅에 남긴다 - DB 가 죽어 있어도 도커 로그로는 즉시 보인다.
  2) best-effort 로 DB(error_logs 테이블)에도 남겨서 GET /errors/summary 로
     코드별 집계를 볼 수 있게 한다.

★ 이 함수는 절대로 예외를 위로 던지지 않는다. "장애를 기록하려는 코드"가 그
  자체로 또 다른 장애(예: DB 자체가 죽어서 insert 가 실패)를 일으켜 원래
  호출부(사용자 응답 흐름)를 막으면 본말전도이기 때문이다.

호출부는 기존 폴백/응답을 그대로 둔 채 이 함수 호출 한 줄만 추가하면 된다 -
동작을 바꾸는 게 아니라 코드를 부여하고 서버가 스스로 알게 만드는 작업이다.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

log = logging.getLogger("gyeotnun.incidents")

_MAX_DETAIL_LEN = 200


def log_incident(
    code: str,
    *,
    screen: Optional[str] = None,
    device_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    safe_detail = str(detail)[:_MAX_DETAIL_LEN] if detail else None

    # 1) 항상 성공하는 경로 - DB 가 죽어도 이 줄은 남는다.
    log.error("[incident] code=%s screen=%s detail=%s", code, screen, safe_detail)

    # 2) best-effort DB 기록 - 실패해도 위로 전파하지 않는다.
    try:
        from models.db import ErrorLog, SessionLocal

        device_hash = hashlib.sha256(device_id.encode()).hexdigest() if device_id else None
        db = SessionLocal()
        try:
            db.add(ErrorLog(code=code, screen=screen, device_hash=device_hash, detail=safe_detail))
            db.commit()
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 - 장애를 "기록"하는 코드가 서비스를 더 망가뜨리면 안 된다
        log.warning("[incident] DB 기록 실패(로그만 남음): %s", e)
