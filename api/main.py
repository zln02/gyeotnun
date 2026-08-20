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
    judgments_router,
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

for r in (checks_router, dialogue_router, verdict_router, training_router, reports_router,
          onboarding_router, events_router, errors_router, judgments_router):
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

    _start_prewarm()


def _start_prewarm() -> None:
    """무거운 로컬 모델을 백그라운드로 미리 로드한다 (2026-08-06 지연 점검).

    왜 필요한가 - 실측: 컨테이너 재시작 후 **첫 사용자**만 큰 대기를 떠안았다.
      임베딩 첫 질의 10.2초(이후 0.14초) / 로컬 OCR 첫 장 9.7초(이후 0.6초).
      모델을 게으르게 로드해서 생기는 콜드스타트이지 검색·인식이 느린 게 아니다.
    ★ 백그라운드 스레드로 돌린다 - startup 을 막으면 헬스체크·기동이 그만큼 늦어진다.
      실패해도 서비스는 그대로 뜬다(다음 요청에서 예전처럼 지연 로드될 뿐이다).
    ★ 끄려면 PREWARM=0 (설정 한 줄). 메모리가 빠듯한 환경을 위한 탈출구다.
    """
    if not settings.PREWARM:
        _log.info("[prewarm] PREWARM=0 - 미리 로드하지 않는다")
        return

    import threading

    def _run() -> None:
        import time

        # 1) 임베딩 모델 (근거 검색 경로)
        try:
            t0 = time.perf_counter()
            from services import embeddings

            embeddings.match_embedding_docs("워밍업")
            _log.info("[prewarm] 임베딩 준비 완료 %.1fs", time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 - 워밍업 실패가 서비스를 막으면 안 된다
            _log.warning("[prewarm] 임베딩 준비 실패(무시): %s", e)

        # 2) 로컬 OCR 모델 (OCR_PROVIDER=local 일 때만)
        if settings.OCR_PROVIDER == "local":
            try:
                t0 = time.perf_counter()
                from services import ocr

                # 흰 이미지 1장으로 가중치까지 완전히 초기화한다(디스크 기록 없음).
                # ★ 2026-08-16: 여기서 직접 predict 하지 않는다. 프리워밍은 백그라운드
                #   스레드라, 그 스레드에서 예측기를 만들면 **이후 모든 요청이 죽는다**
                #   (Paddle 예측기는 만들어진 스레드에 묶인다 - services/ocr.py 주석).
                #   전용 스레드에서 만들도록 ocr 쪽 함수를 통해 간다.
                ocr.prewarm_local()
                _log.info("[prewarm] 로컬 OCR 준비 완료 %.1fs", time.perf_counter() - t0)
            except Exception as e:  # noqa: BLE001
                _log.warning("[prewarm] 로컬 OCR 준비 실패(무시): %s", e)

    threading.Thread(target=_run, name="prewarm", daemon=True).start()
