"""
곁눈(Gyeotnun) - DB 엔진 · 세션
담당: 박진영

- 로컬 개발: SQLite (기본값). 별도 설치 없이 바로 동작.
- Docker/배포: PostgreSQL 16 (compose가 DATABASE_URL 주입)

해커톤 기간에는 마이그레이션 도구(alembic) 없이
main.py 기동 시 create_all()로 테이블을 생성합니다.
스키마 변경이 잦으므로, 변경 시엔 gyeotnun.db 삭제 또는
`docker compose down -v` 후 재기동하세요.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# SQLite는 스레드 체크 옵션이 필요
_connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스 클래스."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성. 라우터에서 `db: Session = Depends(get_db)` 로 사용."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """테이블 생성. main.py 기동 시 1회 호출."""
    from . import models  # noqa: F401  (모델 등록을 위한 import)

    Base.metadata.create_all(bind=engine)
