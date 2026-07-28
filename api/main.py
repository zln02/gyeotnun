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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from models.schemas import HealthResponse
from routers import (
    checks_router,
    dialogue_router,
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

for r in (checks_router, dialogue_router, verdict_router, training_router, reports_router, onboarding_router):
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
            "google_vision": settings.has_vision,
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
