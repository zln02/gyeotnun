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

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
    NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")
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
        return bool(self.GOOGLE_VISION_API_KEY)


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
