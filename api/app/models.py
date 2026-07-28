"""
곁눈(Gyeotnun) - DB 모델
담당: 박진영  (수정 시 반드시 팀 공지 · 공용 파일)

테이블
    users           사용자
    checks          의심정보 검사 건
    evidence        출처 교차대조 결과
    taggings        오판유형 태깅
    training_cards  발급된 훈련카드
    corpus          훈련 문항 코퍼스 (corpus/seed.json 적재)
    weekly_reports  주간 리포트 집계

────────────────────────────────────────────────────────────
[보안 정책 - 필독]
1. 업로드된 **원본 이미지는 어떤 컬럼에도 저장하지 않는다.**
   - 이미지는 요청 처리 중 메모리에서만 존재하고, OCR 후 즉시 폐기한다.
   - S3/디스크/BLOB 컬럼 어디에도 남기지 않는다.
2. checks 테이블에는 `ocr_text_masked` (마스킹 완료 텍스트)만 저장한다.
   - services/masking.mask_pii() 를 반드시 통과시킨 값이어야 한다.
   - 전화번호·계좌번호·주민등록번호·카드번호는 마스킹된 상태로 들어간다.
3. 원문(마스킹 전) 텍스트를 저장하는 컬럼은 의도적으로 두지 않았다.
   추가하지 말 것. 디버깅이 필요하면 로그 레벨 DEBUG로 로컬에서만 확인.
────────────────────────────────────────────────────────────
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
# 오판유형 4종 (tagger.py 와 값이 일치해야 함)
# ============================================================
ERROR_TYPES = (
    "TITLE_DEPENDENT",       # 제목의존형
    "AUTHORITY_SPOOF",       # 권위자사칭수용형
    "NUMBER_CONDITION",      # 숫자조건혼동형
    "OVERGENERALIZATION",    # 과잉일반화형
)


# ============================================================
# users
# ============================================================
class User(Base):
    """사용자. 해커톤 단계에서는 로그인 없이 device_id로 식별."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    age_group: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 60대/70대/80대+
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    checks: Mapped[list["Check"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    taggings: Mapped[list["Tagging"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    training_cards: Mapped[list["TrainingCard"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    weekly_reports: Mapped[list["WeeklyReport"]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ============================================================
# checks
# ============================================================
class Check(Base):
    """
    의심정보 검사 1건.

    ※ 원본 이미지는 저장하지 않는다. (상단 보안 정책 참조)
      - image_* 컬럼 없음 (의도적)
      - ocr_text_masked 만 보관
    """

    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)

    # 입력 종류: image | url | text | voice
    source_type: Mapped[str] = mapped_column(String(20), default="image")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)  # url 입력일 때만

    # [보안] 마스킹 완료 텍스트만 저장. masking.mask_pii() 통과 필수.
    ocr_text_masked: Mapped[str] = mapped_column(Text, default="")
    # 마스킹으로 가려진 항목 종류 (예: ["phone", "account"]) - 통계·보안 배점 근거
    masked_kinds: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # 처리 상태: pending | extracting | searching | questioning | judged | failed
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    # 사용자가 내린 최종 판단: trust | suspect | unsure  (AI가 아닌 사용자의 판단)
    user_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_verdict_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 대화 로그 [{"role": "assistant"|"user", "content": "...", "step": 1}, ...]
    dialogue_log: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped["User | None"] = relationship(back_populates="checks")
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="check", cascade="all, delete-orphan", order_by="Evidence.rank"
    )
    tagging: Mapped["Tagging | None"] = relationship(
        back_populates="check", cascade="all, delete-orphan", uselist=False
    )


# ============================================================
# evidence
# ============================================================
class Evidence(Base):
    """
    출처 교차대조 결과 1건. (담당: 김유리)

    LLM이 내용을 지어내지 않도록 **링크·제목·게시일만** 저장한다.
    본문 요약을 넣지 않는다.

    found=False 레코드도 저장한다.
    "정부24에서 찾지 못했다"는 사실 자체가 사용자에게 중요한 확인 신호이기 때문.
    """

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), index=True)

    # gov24 | korea_kr(정책브리핑) | naver_news | naver_web
    source: Mapped[str] = mapped_column(String(30))
    source_label: Mapped[str] = mapped_column(String(50), default="")  # 화면 표기용 "정부24"
    found: Mapped[bool] = mapped_column(Boolean, default=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 원본 표기 그대로

    # 공식 출처 여부 (go.kr / or.kr 등) - 화면에서 뱃지 표시
    is_official: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    query_used: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    check: Mapped["Check"] = relationship(back_populates="evidence")


# ============================================================
# taggings
# ============================================================
class Tagging(Base):
    """오판유형 태깅 결과. (담당: 장지석)"""

    __tablename__ = "taggings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), unique=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)

    error_type: Mapped[str] = mapped_column(String(30), index=True)  # ERROR_TYPES 중 하나
    error_type_label: Mapped[str] = mapped_column(String(40), default="")  # "제목의존형"
    confidence: Mapped[int] = mapped_column(Integer, default=0)  # 0~100
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)  # 왜 이 유형인지 (내부용)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    check: Mapped["Check"] = relationship(back_populates="tagging")
    user: Mapped["User | None"] = relationship(back_populates="taggings")


# ============================================================
# corpus
# ============================================================
class Corpus(Base):
    """
    훈련 문항 코퍼스. corpus/seed.json 을 적재한다. (담당: 장지석)
    content 는 반드시 가상 기관명을 사용한 예시여야 한다. (실제 기관 사칭 금지)
    """

    __tablename__ = "corpus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # seed.json의 id

    error_type: Mapped[str] = mapped_column(String(30), index=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=1)  # 1~3
    domain: Mapped[str] = mapped_column(String(30), index=True)  # 공공지원금 | 건강 | 금융

    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)          # 사칭 예시 텍스트(가상)
    checkpoints: Mapped[list] = mapped_column(JSON, default=list)  # 확인 포인트 배열
    explanation: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ============================================================
# training_cards
# ============================================================
class TrainingCard(Base):
    """사용자에게 발급된 훈련카드. (담당: 장지석)"""

    __tablename__ = "training_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    corpus_id: Mapped[int | None] = mapped_column(ForeignKey("corpus.id", ondelete="SET NULL"), nullable=True)

    error_type: Mapped[str] = mapped_column(String(30), index=True)
    issued_for: Mapped[datetime] = mapped_column(Date, index=True)  # 어느 날짜의 '오늘의 훈련'인지

    completed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    user_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User | None"] = relationship(back_populates="training_cards")
    corpus: Mapped["Corpus | None"] = relationship()


# ============================================================
# weekly_reports
# ============================================================
class WeeklyReport(Base):
    """주간 리포트 집계 결과. (담당: 장지석)"""

    __tablename__ = "weekly_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)

    week_start: Mapped[datetime] = mapped_column(Date, index=True)  # 해당 주 월요일
    week_end: Mapped[datetime] = mapped_column(Date)

    checks_count: Mapped[int] = mapped_column(Integer, default=0)
    trainings_completed: Mapped[int] = mapped_column(Integer, default=0)
    accuracy_rate: Mapped[int] = mapped_column(Integer, default=0)  # 0~100
    # {"TITLE_DEPENDENT": 3, "AUTHORITY_SPOOF": 1, ...}
    error_type_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_error_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # 시니어용 한 줄 요약

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User | None"] = relationship(back_populates="weekly_reports")
