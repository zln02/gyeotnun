"""
오류 코드 조회 & 장애 집계
GET /api/v1/errors/codes     오류 코드 전체 정의 (단일 소스 그대로 반환 - 프론트가 이걸로 받아 씀)
GET /api/v1/errors/summary   최근 오류를 코드별로 집계 (8/2 보안 멘토링 지시사항)
담당: 박진영

/errors/codes 가 프론트·백엔드 "단일 소스" 원칙을 실제로 구현하는 지점이다.
services/error_codes.py 를 고치는 것만으로 프론트 화면 문구까지 같이 바뀐다 -
프론트에 같은 표를 복사해 두지 않았기 때문이다(web/src/errorCodes.js 참고).

/errors/summary 는 두 표를 코드 기준으로 합친다.
  - error_logs : 서버 코드 스스로가 자기 실패를 남긴 것(services/incident_log.py)
  - events(event_type=error) : 프론트가 신고한 오류(순수 클라이언트 실패 포함,
    예: IN-003 공유 실패·EX-004 네트워크 끊김은 서버가 볼 수 없다)
두 표를 나누지 않고 코드로 합쳐 보여주되, server_count/client_count 로 출처
구분은 남긴다 - 서버 자체 장애인지 클라이언트에서만 보이는 문제인지 구분에 쓸모있다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.db import ErrorLog, Event, get_db
from models.schemas import ErrorCodeItem, ErrorSummaryItem, ErrorSummaryResponse
from routers._common import AdminTokenHeader, require_operator
from services.error_codes import ERROR_CODES, get_error_code

router = APIRouter(prefix="/errors", tags=["errors"])


@router.get("/codes", response_model=list[ErrorCodeItem], summary="오류 코드 전체 정의 (단일 소스)")
async def codes():
    # ★ 공개 유지: 프론트가 오류 문구 단일 소스로 이걸 받아 쓴다(web/src/errorCodes.js).
    #   개인정보·집계가 아니라 정적 코드표라 인증 대상이 아니다.
    return ERROR_CODES


@router.get("/summary", response_model=ErrorSummaryResponse, summary="오류 코드별 집계")
async def summary(
    db: Session = Depends(get_db),
    x_admin_token: str | None = AdminTokenHeader,
):
    # ★ 운영자 전용. events/summary 와 같은 부류의 무인증 집계라 같은 게이트를 건다.
    #   ADMIN_TOKEN 미설정 시 닫힘(404). 프론트 호출부 없음(백엔드만 고치면 됨).
    require_operator(x_admin_token)
    server_rows = db.query(ErrorLog).all()
    client_rows = db.query(Event).filter(Event.event_type == "error").all()

    server_counts: dict[str, int] = {}
    last_seen: dict[str, object] = {}   # 서버/클라이언트 통틀어 코드별 최신 시각

    for r in server_rows:
        server_counts[r.code] = server_counts.get(r.code, 0) + 1
        if r.code not in last_seen or r.created_at > last_seen[r.code]:
            last_seen[r.code] = r.created_at

    client_counts: dict[str, int] = {}
    for r in client_rows:
        code = r.target or "SYS-000"   # 프론트가 아직 코드를 못 실어 보낸 예전 이벤트용 안전망
        client_counts[code] = client_counts.get(code, 0) + 1
        if code not in last_seen or r.created_at > last_seen[code]:
            last_seen[code] = r.created_at

    all_codes = set(server_counts) | set(client_counts)
    items = []
    for code in all_codes:
        meta = get_error_code(code)
        ts = last_seen.get(code)
        items.append(ErrorSummaryItem(
            code=code,
            area=meta["area"],
            situation=meta["situation"],
            user_message=meta["user_message"],
            recovery=meta["recovery"],
            count=server_counts.get(code, 0) + client_counts.get(code, 0),
            server_count=server_counts.get(code, 0),
            client_count=client_counts.get(code, 0),
            last_occurred_at=ts.isoformat() if ts else None,
        ))
    items.sort(key=lambda x: x.count, reverse=True)
    return ErrorSummaryResponse(items=items, total_count=sum(i.count for i in items))
