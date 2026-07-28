"""
곁눈(Gyeotnun) - Pydantic 요청/응답 스키마
담당: 박진영  (수정 시 팀 공지 · 공용 파일)

프론트(조희진)는 이 파일의 응답 스키마를 계약으로 삼아 개발합니다.
필드명을 바꾸면 프론트가 깨지므로, 변경 시 반드시 사전 공지하세요.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ============================================================
# 공통
# ============================================================
ErrorTypeCode = Literal[
    "TITLE_DEPENDENT",
    "AUTHORITY_SPOOF",
    "NUMBER_CONDITION",
    "OVERGENERALIZATION",
]

CheckStatus = Literal["pending", "extracting", "searching", "questioning", "judged", "failed"]
UserVerdict = Literal["trust", "suspect", "unsure"]


class Ok(BaseModel):
    ok: bool = True
    message: str = ""


# ============================================================
# checks  (담당: 박진)
# ============================================================
class CheckCreateText(BaseModel):
    """이미지 대신 텍스트/URL로 검사 생성 (개발·데모 편의용)."""

    source_type: Literal["text", "url", "voice"] = "text"
    content: str = Field(..., description="원문 텍스트 또는 URL. 서버에서 즉시 마스킹됩니다.")
    device_id: str | None = None


class CheckOut(BaseModel):
    """검사 조회 응답. 원본 이미지는 어디에도 포함되지 않습니다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_url: str | None = None
    ocr_text_masked: str
    masked_kinds: list[str] | None = None
    status: CheckStatus
    user_verdict: UserVerdict | None = None
    dialogue_log: list[dict] | None = None
    created_at: datetime


class CheckCreateOut(BaseModel):
    """업로드 직후 응답. 프론트는 이 id로 Checking 화면에서 폴링합니다."""

    check_id: int
    status: CheckStatus
    ocr_text_masked: str
    masked_kinds: list[str] = []
    next: str = "/api/checks/{check_id}/evidence"


# ============================================================
# evidence  (담당: 김유리)
# ============================================================
class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    source: str                     # gov24 | korea_kr | naver_news
    source_label: str = ""          # "정부24"
    found: bool = True
    title: str | None = None
    url: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    is_official: bool = False
    rank: int = 0


class EvidenceListOut(BaseModel):
    check_id: int
    query_used: str = ""
    official_found: bool = False    # 공식 출처에서 확인되었는가
    items: list[EvidenceOut] = []
    # 공식 출처에서 못 찾은 경우 프론트에 띄울 안내 문구
    note: str = ""


# ============================================================
# dialogue  (담당: 김태희)
# ============================================================
class DialogueIn(BaseModel):
    """사용자 답변을 담아 다음 질문을 요청."""

    user_message: str | None = Field(None, description="직전 질문에 대한 사용자 답변. 첫 요청이면 null")
    step: int = Field(0, ge=0, le=10, description="현재 단계 (0=시작)")


class DialogueOut(BaseModel):
    """
    질문형 가이드 응답.

    ※ questions 에는 절대 단정형 판정문이 들어가면 안 됩니다.
      ("가짜입니다", "사기입니다" 등) - prompt_chain.py 가드 참조
    """

    check_id: int
    step: int
    stage: str = ""                     # source | timing | publisher | basis | urgency | wrap
    questions: list[str] = []           # 한 번에 1~2개
    hint: str = ""                      # 짧은 보조 설명 (판정 아님)
    evidence_links: list[EvidenceOut] = []   # 근거는 링크로만 제시
    is_final: bool = False              # True면 프론트가 판단 입력 UI 노출
    mocked: bool = False                # API 키 없어 목업으로 생성된 응답인지


# ============================================================
# verdict  (담당: 장지석)
# ============================================================
class VerdictIn(BaseModel):
    verdict: UserVerdict
    reason: str | None = Field(None, description="사용자가 그렇게 판단한 이유 (선택)")


class VerdictOut(BaseModel):
    check_id: int
    user_verdict: UserVerdict
    error_type: ErrorTypeCode | None = None
    error_type_label: str = ""
    confidence: int = 0
    feedback: str = ""                  # 격려 중심 피드백 (정답 통보 아님)
    training_card_id: int | None = None


# ============================================================
# training  (담당: 장지석)
# ============================================================
class TrainingCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    corpus_slug: str = ""
    error_type: ErrorTypeCode
    error_type_label: str = ""
    difficulty: int = 1
    domain: str = ""
    title: str = ""
    content: str = ""
    checkpoints: list[str] = []
    explanation: str = ""
    completed: bool = False
    issued_for: date | None = None


class TrainingCompleteIn(BaseModel):
    user_answer: str | None = None
    is_correct: bool | None = None


class TrainingCompleteOut(BaseModel):
    card_id: int
    completed: bool
    streak_days: int = 0
    message: str = ""


# ============================================================
# reports  (담당: 장지석)
# ============================================================
class ErrorTypeCount(BaseModel):
    error_type: ErrorTypeCode
    label: str
    count: int


class WeeklyReportOut(BaseModel):
    week_start: date
    week_end: date
    checks_count: int = 0
    trainings_completed: int = 0
    accuracy_rate: int = 0
    error_type_counts: list[ErrorTypeCount] = []
    top_error_type: ErrorTypeCode | None = None
    top_error_type_label: str = ""
    summary: str = ""
