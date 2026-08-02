"""
곁눈(Gyeotnun) API 엔트리포인트
팀 Second Look (6인) - 해커톤 프로젝트

무엇을 하는 서비스인가
  시니어가 카카오톡·유튜브에서 받은 의심스러운 정보를 사진이나 링크로 올리면,
  AI가 **진위를 판정하지 않고** 스스로 확인할 수 있는 질문을 하나씩 던져 판단을 돕는다.
  판단이 끝나면 오판유형(4종)을 태깅해, 매일 5분 훈련으로 연결한다.

왜 판정하지 않는가
  판정해 주는 순간 사용자는 판단을 AI에 위임하게 되고, 틀린 판정 한 번에 신뢰가 무너진다.
  곁눈의 목표는 '이번 한 건을 걸러 주는 것'이 아니라 '스스로 거를 수 있게 되는 것'이다.

실행
  cd api && uvicorn main:app --reload --port 8000
  문서: http://localhost:8000/docs
  ★ API 키가 하나도 없어도 모든 엔드포인트에 ?mock=1 을 붙이면 전 플로우가 동작한다.
"""
from __future__ import annotations

import logging

# ★ 이 로깅 설정은 반드시 아래 `from routers import ...` 보다 먼저 와야 한다.
#   routers → services.search → services.corpus_index 로 이어지는 임포트 체인이
#   모듈 임포트 시점(코퍼스 적재 시점)에 곧바로 log.info() 를 찍는데, 핸들러를 이
#   임포트보다 뒤에 붙이면 그 시점엔 아직 핸들러가 없어 로그가 조용히 사라진다
#   (Python logging 은 호출 시점의 핸들러로 즉시 처리하며 나중을 위해 버퍼링하지 않는다).
#   가드레일/LLM 로그(prompt_chain 의 'gyeotnun.*')와 코퍼스 적재 로그
#   (corpus_index 의 'gyeotnun.corpus_index') 모두 이 핸들러 하나로 받는다.
_log = logging.getLogger("gyeotnun")
_log.setLevel(logging.INFO)
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    _log.addHandler(_handler)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.schemas import HealthResponse
from routers import (
    checks_router,
    dialogue_router,
    errors_router,
    events_router,
    onboarding_router,
    reports_router,
    training_router,
    verdict_router,
)

app = FastAPI(title=settings.APP_NAME, description=settings.APP_DESC, version=settings.VERSION)

# 해커톤 개발 편의를 위한 전체 허용. TODO(박진영): 배포 시 도메인 화이트리스트로 좁힐 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (checks_router, dialogue_router, verdict_router, training_router, reports_router, onboarding_router, events_router, errors_router):
    app.include_router(r, prefix=settings.API_PREFIX)


@app.get("/health", response_model=HealthResponse, tags=["system"], summary="헬스체크")
async def health():
    """서버 상태 + 어떤 키가 설정되어 있는지 (키 값은 절대 노출하지 않는다)."""
    return HealthResponse(
        app=settings.APP_NAME,
        version=settings.VERSION,
        env=settings.APP_ENV,
        mock_available=True,
        keys_configured={
            "anthropic": settings.has_llm,
            "naver_search": settings.has_search,
            # 이미지 인식(OCR)은 Claude Vision 을 쓴다 - anthropic 과 동일한 값이지만
            # "이미지 업로드가 될까?"를 바로 확인할 수 있도록 별도 키로 남겨 둔다.
            "vision": settings.has_vision,
        },
    )


@app.on_event("startup")
async def _startup() -> None:
    """개발 편의: 테이블 자동 생성. DB가 없어도 서버는 떠야 하므로 실패를 삼킨다."""
    try:
        from models.db import init_db

        init_db()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] DB 초기화 생략: {e} (mock 플로우에는 영향 없음)")
