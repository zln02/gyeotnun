"""
곁눈(Gyeotnun) - SQLAlchemy 테이블 정의 (9테이블)
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
    # ★ 2026-08-16 (#33 3단계). 비회원 소유자 대조용. **원문 device_id 는 넣지 않는다** -
    #   README 7장의 "device_id 는 SHA-256 해시만 사용" 서술을 지키기 위해서다
    #   (events·error_logs·users 와 같은 방식). services/check_store.py 참고.
    device_hash = Column(String(64), nullable=True, index=True)     # sha256(device_id)
    input_type = Column(String(16), nullable=False)                 # image | link | text
    source_url = Column(Text, nullable=True)                        # link 입력 시 원본 URL
    masked_text = Column(Text, nullable=False, default="")          # ★ 마스킹 완료 텍스트만 저장
    masked_items = Column(JSON, default=list)                       # [{type, original_hint, count}]
    detected_domain = Column(String(32), nullable=True)             # health/finance/policy/news
    status = Column(String(24), default="extracted")
    image_discarded = Column(Boolean, default=True, nullable=False) # 원본 파기 여부 감사 플래그
    # ★ 2026-08-16. 확인 질문 대화 이력(["질문1: ...", "사용자 답변: ...", ...]).
    #   전에는 프로세스 메모리 dict 안에 있어 재시작 시 사라졌다.
    history = Column(JSON, default=list)
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
    # ★ 2026-08-16. 비회원 태깅의 주체. 원문이 아니라 해시다(checks.device_hash 와 동일).
    device_hash = Column(String(64), nullable=True, index=True)     # sha256(device_id)
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


# ------------------------------------------------------------------ 8. events
class Event(Base):
    """사용자 행동 계측 1건 (8/5 60대 사용성 테스트 정량 지표용).

    ★ 개인정보 원칙: 화면에 입력된 텍스트(붙여넣은 글, 자유 서술 답변 등)는
      절대 저장하지 않는다. device_id 도 원문이 아니라 SHA-256 해시로만 남긴다
      (users.device_hash 와 같은 방식). target/meta 도 자유 텍스트가 아니라
      버튼 id·화면 이름·오류 유형처럼 미리 정해진 짧은 값만 들어온다 - 정제는
      routers/events.py 에서 한다(여기 도달한 값은 이미 정제된 값이라고 가정).
    """

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_hash = Column(String(64), nullable=False, index=True)   # sha256(device_id)
    # ★ "device_id 기준으로만 묶는다"는 원칙의 그룹핑 키는 device_hash 다. session_id 는
    #   개인정보가 아니라 브라우저 세션(같은 기기를 여러 참가자가 돌려 쓸 수 있는 사용성
    #   테스트 특성상) 단위로 화면 흐름을 정확히 재구성하기 위한 임의 UUID일 뿐이다 -
    #   이게 없으면 같은 기기의 서로 다른 방문이 하나로 뒤섞여 체류시간/이탈지점이 틀어진다.
    session_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(24), nullable=False)                # screen_enter|screen_leave|click|evidence_link_click|error
    screen = Column(String(8), nullable=True)                      # S1~S5
    target = Column(String(64), nullable=True)                     # 버튼 id / 오류 유형 등 (자유 텍스트 아님)
    client_ts = Column(DateTime, nullable=True)                    # 클라이언트가 기록한 발생 시각(참고용)
    meta = Column(JSON, default=dict)                              # 소량의 구조화된 부가정보만
    created_at = Column(DateTime, default=_now, index=True)        # 서버 수신 시각 - 집계는 이 값을 기준으로 한다


# ------------------------------------------------------------------ 9. error_logs
class ErrorLog(Base):
    """장애 로그 1건 (2026-08 오류 코드 체계 도입, 8/2 보안 멘토링 지시사항).

    ★ 멘토 조언의 직접 구현: "저장 실패 시 사용자에게 조치를 요구하지 말고, 서버가
      로그를 받아 장애를 인지하고 상태를 공지한 뒤 수정하는 방식으로 가라." - 이 표는
      클라이언트 요청 없이도 서버 코드 스스로가 자기 실패를 여기에 남긴다
      (services/incident_log.py 참고).
    ★ 개인정보 원칙: events 테이블과 동일하다 - device_hash 만 남기고 원문은 저장하지
      않는다. detail 은 예외 메시지를 그대로 넣지 않고 길이를 짧게 자른 진단 정보만
      담는다(services/incident_log.py 에서 자름).
    """

    __tablename__ = "error_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), nullable=False, index=True)           # 예: EX-001 (services/error_codes.py)
    screen = Column(String(8), nullable=True)                       # S1~S5, 알 수 없으면 null
    device_hash = Column(String(64), nullable=True, index=True)     # sha256(device_id), 없으면 null
    detail = Column(String(200), nullable=True)                     # 짧은 진단 정보만 (개인정보 절대 금지)
    created_at = Column(DateTime, default=_now, index=True)


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
