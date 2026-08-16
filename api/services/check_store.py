"""확인 기록 저장소 — 프로세스 메모리에서 Postgres 로 (2026-08-16, #33 3단계).

■ 무엇이 바뀌었나
  전에는 routers/checks.py 의 `_MEMORY_STORE` (파이썬 dict) 하나가 전부였다.
  그래서 두 가지가 따라왔다.
    1) **재시작하면 진행 중인 확인이 전부 사라졌다.**
    2) 워커를 1개보다 늘릴 수 없었다 - create 한 워커와 evidence/dialogue 를 받는
       워커가 달라지면 404 가 났다.
  이제 checks 테이블에 담는다. 둘 다 풀린다.

■ ★★ device_id 는 원문을 저장하지 않는다 ★★
  README 7장이 "사용자 식별은 device_id 의 SHA-256 해시만 사용합니다"라고 못박고
  있다. 메모리 dict 시절엔 원문을 들고 있었지만 그건 프로세스 안에서만 살다 사라졌다.
  **DB 로 옮기면서 원문을 넣으면 그 서술이 그날로 거짓이 된다.**
  그래서 여기서는 sha256 만 저장하고, 소유자 대조도 해시끼리 한다
  (events·error_logs·users 가 이미 쓰는 방식과 같다).

■ ★ 원문 텍스트는 여전히 저장하지 않는다
  담는 것은 masked_text 뿐이다. Check 모델에 원문 컬럼은 없고, 만들지 않는다.

■ 보관 기간
  tools/purge_old_records.py 가 90일 초과분을 지운다. checks 를 지울 때
  evidence·taggings 를 먼저 지운다(FK 순서).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from models.db import Check, SessionLocal, Tagging

log = logging.getLogger("gyeotnun.check_store")


def hash_device(device_id: Optional[str]) -> Optional[str]:
    """device_id → sha256. 원문은 어디에도 남기지 않는다."""
    if not device_id:
        return None
    return hashlib.sha256(device_id.encode()).hexdigest()


def create(
    check_id: str,
    *,
    device_id: Optional[str],
    input_type: str,
    masked_text: str,
    masked_items: list,
    detected_domain: Optional[str],
    status: str,
    source_url: Optional[str] = None,
) -> None:
    """확인 1건을 저장한다. ★ 원문 텍스트·원문 device_id 는 넣지 않는다."""
    db = SessionLocal()
    try:
        db.merge(Check(
            id=check_id,
            device_hash=hash_device(device_id),
            input_type=input_type,
            source_url=source_url,
            masked_text=masked_text,
            masked_items=masked_items or [],
            detected_domain=detected_domain,
            status=status,
            history=[],
        ))
        db.commit()
    finally:
        db.close()


def get(check_id: str) -> Optional[dict]:
    """확인 1건을 dict 로 돌려준다. 없으면 None.

    ★ 반환 모양은 예전 _MEMORY_STORE 항목과 같게 맞췄다(masked_text/domain/history).
      다른 점은 device_id 대신 **device_hash** 가 들어간다는 것뿐이다.
    """
    db = SessionLocal()
    try:
        row = db.get(Check, check_id)
        if row is None:
            return None
        return {
            "masked_text": row.masked_text or "",
            "domain": row.detected_domain,
            "device_hash": row.device_hash,
            "history": list(row.history or []),
            "status": row.status,
        }
    finally:
        db.close()


def append_history(check_id: str, lines: list[str]) -> None:
    """대화 이력을 덧붙인다.

    ★ JSON 컬럼은 제자리 수정(list.append)을 SQLAlchemy 가 못 알아챈다.
      **새 리스트를 대입**해야 UPDATE 가 나간다. 예전 메모리 dict 는 그냥 append 로
      됐기 때문에 여기서 실수하기 쉽다 - 조용히 이력이 안 쌓인다.
    """
    if not lines:
        return
    db = SessionLocal()
    try:
        row = db.get(Check, check_id)
        if row is None:
            return
        row.history = list(row.history or []) + list(lines)
        db.commit()
    finally:
        db.close()


def save_tagging(check_id: str, *, device_id: Optional[str], decision: str,
                 error_type: str, confidence: float, reason_tags: Optional[list] = None) -> None:
    """판단 + 오판유형 태깅 1건을 남긴다 (2026-08-16 신설).

    ★ 전에는 어디에도 저장하지 않고 응답만 했다. 저장소를 DB 로 옮기는 김에 함께
      담는다 - 그래야 purge 의 'taggings 90일' 이 빈 약속이 아니게 된다.
    ★ 실패해도 화면 흐름을 막지 않는다. 태깅은 부가 기록이지 응답의 조건이 아니다.
    """
    db = SessionLocal()
    try:
        db.add(Tagging(
            check_id=check_id,
            device_hash=hash_device(device_id),
            decision=decision,
            reason_tags=reason_tags or [],
            error_type=error_type,
            confidence=float(confidence or 0.0),
        ))
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("[check_store] 태깅 저장 실패(무시하고 계속): %s", type(e).__name__)
    finally:
        db.close()
