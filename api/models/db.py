"""
곁눈(Gyeotnun) - SQLAlchemy 테이블 정의 (7테이블)
담당: 박진영 (DB)

★★ 개인정보 처리 원칙 (보안 배점 대응) ★★
- 업로드된 **원본 이미지는 처리 후 즉시 파기**한다. 서버 디스크·DB 어디에도 남기지 않는다.
- DB 에는 **마스킹이 끝난 텍스트만** 저장한다. (checks.masked_text)
- 전화번호·계좌번호·주민번호는 masking.py 에서 치환된 뒤에야 이 테이블에 들어온다.
- 사용자 식별은 device_id 해시만 사용한다. 이름·연락처를 수집하지 않는다.
- 원본 텍스트(raw_text) 컬럼은 의도적으로 두지 않았다. 추가하지 말 것.
"""
from __future__ import annotations

import datetime as _dt

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config import settings

Base = declarative_base()


def _now() -> _dt.datetime:
    return _dt.datetime.utcnow()


# ------------------------------------------------------------------ 1. users
class User(Base):
    """비회원 기반 사용자. 이름/전화번호를 저장하지 않고 device_id 해시만 쓴다."""

    __tablename__ = "users"

    id = Column(String(40), primary_key=True)                       # usr_xxx
    device_hash = Column(String(64), unique=True, nullable=False)   # sha256(device_id)
    age_band = Column(String(16), nullable=True)                    # 60s / 70s / 80s+ (통계용, 선택)
    dominant_error_type = Column(String(32), nullable=True)         # 온보딩 진단 결과
    streak_days = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)

    checks = relationship("Check", back_populates="user")


# ----------------------------------------------------------------- 2. checks
class Check(Base):
    """확인 요청 1건. ★ 원본 이미지는 저장하지 않는다(처리 후 파기)."""

    __tablename__ = "checks"

    id = Column(String(40), primary_key=True)                       # chk_xxx
    user_id = Column(String(40), ForeignKey("users.id"), nullable=True)
    input_type = Column(String(16), nullable=False)                 # image | link | text
    source_url = Column(Text, nullable=True)                        # link 입력 시 원본 URL
    masked_text = Column(Text, nullable=False, default="")          # ★ 마스킹 완료 텍스트만 저장
    masked_items = Column(JSON, default=list)                       # [{type, original_hint, count}]
    detected_domain = Column(String(32), nullable=True)             # health/finance/policy/news
    status = Column(String(24), default="extracted")
    image_discarded = Column(Boolean, default=True, nullable=False) # 원본 파기 여부 감사 플래그
    created_at = Column(DateTime, default=_now)

    user = relationship("User", back_populates="checks")
    evidences = relationship("Evidence", back_populates="check")
    taggings = relationship("Tagging", back_populates="check")


# --------------------------------------------------------------- 3. evidence
class Evidence(Base):
    """검색·공공데이터 대조 결과. LLM이 지어낸 링크는 절대 여기 들어오지 않는다."""

    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(String(40), ForeignKey("checks.id"), nullable=False)
    verdict_hint = Column(String(32), default="needs_check")        # ★ true/false 아님
    signals = Column(JSON, default=list)
    references = Column(JSON, default=list)                         # [{title,url,publisher,...}]
    corpus_id = Column(Integer, ForeignKey("corpus.id"), nullable=True)
    created_at = Column(DateTime, default=_now)

    check = relationship("Check", back_populates="evidences")


# --------------------------------------------------------------- 4. taggings
class Tagging(Base):
    """사용자의 판단 + 오판유형 태깅. 훈련 카드 추천의 입력이 된다."""

    __tablename__ = "taggings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_id = Column(String(40), ForeignKey("checks.id"), nullable=False)
    user_id = Column(String(40), ForeignKey("users.id"), nullable=True)
    decision = Column(String(16), nullable=False)                   # apply|not_apply|hold|ask_family
    reason_tags = Column(JSON, default=list)
    error_type = Column(String(32), nullable=False)                 # title_dependent 등 4종
    confidence = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_now)

    check = relationship("Check", back_populates="taggings")


# --------------------------------------------------------- 5. training_cards
class TrainingCard(Base):
    """매일 5분 훈련 카드. corpus 기반 RAG로 생성/보강한다(장지석)."""

    __tablename__ = "training_cards"

    id = Column(String(40), primary_key=True)                       # card_xxx
    target_error_type = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    items = Column(JSON, default=list)
    answer = Column(String(16), nullable=False)
    explanation = Column(Text, nullable=False)
    estimated_sec = Column(Integer, default=300)
    source_corpus_id = Column(Integer, ForeignKey("corpus.id"), nullable=True)
    created_at = Column(DateTime, default=_now)


# ----------------------------------------------------------------- 6. corpus
class Corpus(Base):
    """공공데이터 577건 코퍼스. 대조 근거이자 훈련카드 원천."""

    __tablename__ = "corpus"

    id = Column(Integer, primary_key=True, autoincrement=True)
    doc_key = Column(String(120), unique=True, nullable=False)
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    publisher = Column(String(120), nullable=True)                  # 발행 기관
    url = Column(Text, nullable=True)                               # 실제 원문 링크(필수에 가깝게 유지)
    domain = Column(String(32), nullable=True)                      # health/finance/policy
    published_at = Column(String(10), nullable=True)                # YYYY-MM-DD
    created_at = Column(DateTime, default=_now)


# -------------------------------------------------------- 7. weekly_reports
class WeeklyReport(Base):
    """주간 리포트 스냅샷. 가족 공유 화면의 데이터 소스."""

    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(40), ForeignKey("users.id"), nullable=False)
    week = Column(String(10), nullable=False)                       # 2026-W30
    checks_count = Column(Integer, default=0)
    training_completed = Column(Integer, default=0)
    error_type_trend = Column(JSON, default=dict)
    streak_days = Column(Integer, default=0)
    message = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


# ------------------------------------------------------------------ 엔진/세션
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """개발용 테이블 생성. 운영에서는 Alembic 마이그레이션으로 교체할 것(TODO 박진영)."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI 의존성 주입용 세션 제너레이터."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
