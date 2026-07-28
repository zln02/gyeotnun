"""
곁눈(Gyeotnun) - FastAPI 엔트리포인트
담당: 박진영

실행
    uvicorn app.main:app --reload --port 8000
문서
    http://localhost:8000/docs

서비스 개요
    시니어 정보판단 AI 코치.
    카톡 캡처·링크·음성으로 들어온 의심 정보를 AI가 **판정하지 않고**,
    스스로 확인할 질문을 단계적으로 제시한다.
    사용자가 판단을 내리면 오판유형을 태깅해 맞춤 훈련으로 연결한다.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import checks, dialogue, evidence, reports, training, verdict

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """기동 시 테이블 생성. (해커톤 기간엔 alembic 생략)"""
    init_db()
    logger.info("곁눈 API 기동 완료 (env=%s)", settings.ENV)
    if not settings.has_anthropic:
        logger.warning("ANTHROPIC_API_KEY 없음 → 질문 생성이 목업으로 동작합니다.")
    if not settings.has_naver:
        logger.warning("NAVER 키 없음 → 출처 검색이 목업으로 동작합니다.")
    yield


app = FastAPI(
    title="곁눈(Gyeotnun) API",
    description=(
        "시니어 정보판단 AI 코치.\n\n"
        "**이 API는 진위를 판정하지 않습니다.** "
        "사용자가 스스로 확인할 수 있도록 단계적 질문을 제시하고, "
        "판단 후 오판유형을 태깅해 맞춤 훈련으로 연결합니다."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(checks.router)
app.include_router(evidence.router)
app.include_router(dialogue.router)
app.include_router(verdict.router)
app.include_router(training.router)
app.include_router(reports.router)


@app.get("/health", tags=["system"], summary="헬스체크")
def health() -> dict:
    """컨테이너 헬스체크 및 배포 확인용."""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "anthropic": settings.has_anthropic,
        "naver": settings.has_naver,
    }


@app.get("/", tags=["system"], include_in_schema=False)
def root() -> dict:
    return {"service": "곁눈(Gyeotnun)", "docs": "/docs", "health": "/health"}
