"""
곁눈(Gyeotnun) - 환경설정
담당: 박진영

.env 파일 또는 OS 환경변수에서 값을 읽습니다.
값이 비어 있어도 서버는 정상 기동되며, 각 서비스가 목업으로 동작합니다.
(해커톤 초기에 팀원 전원이 키 없이 개발을 시작할 수 있게 하기 위함)
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 앱 ----------
    APP_NAME: str = "gyeotnun"
    ENV: str = "development"
    DEBUG: bool = True
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- Anthropic (김태희) ----------
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5"

    # ---------- 네이버 검색 (김유리) ----------
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    GOV24_API_KEY: str = ""
    KOREA_KR_API_KEY: str = ""

    # ---------- DB (박진영) ----------
    DATABASE_URL: str = "sqlite:///./gyeotnun.db"

    # ---------- OCR (박진) ----------
    OCR_PROVIDER: str = "mock"  # mock | tesseract | clova | claude_vision
    CLOVA_OCR_URL: str = ""
    CLOVA_OCR_SECRET: str = ""

    # ---------- AWS (선택) ----------
    AWS_REGION: str = "ap-northeast-2"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = ""

    # ---------- 파생 속성 ----------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def has_anthropic(self) -> bool:
        """Claude API 사용 가능 여부. False면 prompt_chain이 목업으로 동작."""
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def has_naver(self) -> bool:
        """네이버 검색 API 사용 가능 여부. False면 search가 목업으로 동작."""
        return bool(self.NAVER_CLIENT_ID and self.NAVER_CLIENT_SECRET)


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. FastAPI Depends 로도 사용 가능."""
    return Settings()


settings = get_settings()
