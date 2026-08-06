"""
곁눈(Gyeotnun) - 공통 설정 / 환경변수 로더
담당: 박진영 (API·DB·배포)

원칙
- 키는 반드시 환경변수(.env)에서만 읽는다. 코드에 하드코딩 금지.
- 키가 없어도 서버는 기동되어야 한다. (mock=1 데모 플로우 보장)
  키가 필요한 실제 호출 시점에만 501 안내를 던진다.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent


def _load_dotenv() -> None:
    """python-dotenv 없이도 동작하는 초경량 .env 로더."""
    env_path = REPO_DIR / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


class Settings:
    """앱 전역 설정. 값이 비어 있으면 '키 없음'으로 취급한다."""

    APP_NAME = "Gyeotnun API"
    APP_DESC = (
        "곁눈(Gyeotnun) - 시니어가 받은 의심 정보를 AI가 '판정'하지 않고, "
        "스스로 확인할 질문으로 되돌려 주는 판단 보조 서비스. by Second Look"
    )
    VERSION = "0.1.0"
    API_PREFIX = "/api/v1"

    APP_ENV: str = os.getenv("APP_ENV", "local")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "") or f"sqlite:///{REPO_DIR / 'gyeotnun.db'}"
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB") or 10)
    # 운영자 전용 집계 엔드포인트(GET /events/summary, /errors/summary) 보호용 공유 비밀.
    # ★ 비어 있으면(기본) 해당 엔드포인트는 닫힌다(404). 서명 토큰/세션이 아니라
    #   단순 환경변수 게이트다 - .env 에 ADMIN_TOKEN 을 넣고 X-Admin-Token 헤더로 호출한다.
    ADMIN_TOKEN: str = os.getenv("ADMIN_TOKEN", "")
    # 관측 로그 보관 기간(일). events / error_logs 를 이 기간이 지나면 삭제한다
    # (tools/purge_old_records.py, cron 일 1회). device_hash 만 남기지만 무기한 보관을
    # 막기 위한 것이다. 0 이하면 삭제를 건너뛴다.
    RETENTION_DAYS: int = int(os.getenv("RETENTION_DAYS") or 90)

    # OCR 제공자: local(PaddleOCR, 오프라인·이미지 외부 미전송) / vision(Claude Vision).
    # ★ 임베딩(EMBEDDING_PROVIDER)과 같은 구조. 기본값 local. 되돌리기는 이 한 줄:
    #   .env 또는 compose environment 에 OCR_PROVIDER=vision 넣고 백엔드 재시작.
    #   Vision 코드·키는 services/ocr.py 에 그대로 보존한다.
    OCR_PROVIDER: str = os.getenv("OCR_PROVIDER", "local")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
    NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")
    # 임베딩 검색(services/embeddings.py) - 공식 문서 청크 벡터 인덱스 구축·질의용.
    # Upstage Solar Embedding (한국어 특화, 국내 API) - 2026-08 Voyage 에서 전환.
    UPSTAGE_API_KEY: str = os.getenv("UPSTAGE_API_KEY", "")
    # 더 이상 쓰지 않는다: 이미지 인식이 Claude Vision(ANTHROPIC_API_KEY)으로
    # 옮겨 가면서 별도 Vision 키가 필요 없어졌다(services/ocr.py). 과거 .env 에
    # 이 값이 남아 있어도 무시된다. 필드 자체는 하위호환을 위해 남겨 둔다.
    GOOGLE_VISION_API_KEY: str = os.getenv("GOOGLE_VISION_API_KEY", "")

    # 데모/시연 안전장치: True 면 키가 없을 때 자동으로 mock 응답으로 폴백한다.
    DEMO_FALLBACK_TO_MOCK: bool = (os.getenv("DEMO_FALLBACK_TO_MOCK", "0") == "1")

    @property
    def has_llm(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def has_search(self) -> bool:
        return bool(self.NAVER_CLIENT_ID and self.NAVER_CLIENT_SECRET)

    @property
    def has_vision(self) -> bool:
        """이미지 인식(OCR) 가능 여부. Claude Vision 을 쓰므로 has_llm 과 같다."""
        return self.has_llm

    @property
    def has_embeddings(self) -> bool:
        return bool(self.UPSTAGE_API_KEY)


settings = Settings()


class MissingKeyError(RuntimeError):
    """실제 외부 API 호출에 필요한 키가 없을 때. 라우터에서 501로 변환된다."""

    def __init__(self, key_name: str, owner: str = ""):
        self.key_name = key_name
        self.owner = owner
        super().__init__(
            f"환경변수 {key_name} 가(이) 설정되지 않았습니다. "
            f".env.example 을 복사해 .env 를 만들고 키를 채우거나, "
            f"쿼리파라미터 ?mock=1 을 붙여 목업 응답으로 진행하세요."
            + (f" (담당: {owner})" if owner else "")
        )
