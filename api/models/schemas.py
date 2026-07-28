"""
곁눈(Gyeotnun) - API 요청/응답 Pydantic 스키마
담당: 박진영 (API 계약)

이 파일이 프론트(조희진)와 백엔드의 유일한 계약서다.
필드명을 바꿀 때는 반드시 팀 채널에 공지할 것.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 공통 타입
Decision = Literal["apply", "not_apply", "hold", "ask_family"]
"""사용자의 최종 '행동' 선택.
apply=따라해본다 / not_apply=따라하지 않는다 / hold=일단 보류 / ask_family=가족에게 물어본다.
※ '진짜/가짜'가 아니라 '내가 어떻게 할지'를 고른다는 점이 곁눈의 핵심 설계다."""

ErrorType = Literal[
    "title_dependent",         # 제목 의존형: 본문 확인 없이 제목만 보고 믿음
    "authority_impersonation", # 권위 사칭형: 기관/전문가 이름이 붙으면 믿음
    "number_condition",        # 숫자·조건 누락형: 금액/기간/자격 조건을 놓침
    "overgeneralization",      # 과잉 일반화형: 일부 사례를 전체로 확대 해석
]

VerdictHint = Literal["needs_check", "partially_matched", "no_source_found"]
"""★ 절대 true/false 를 담지 않는다. '판정'이 아니라 '확인이 필요한 정도'만 표현한다."""


# ---------------------------------------------------------------- S1: 업로드
class MaskedItem(BaseModel):
    """비식별화된 항목 1건 (박진 - masking.py)."""
    type: Literal["phone", "account", "rrn", "face", "card"] = Field(..., description="비식별 대상 유형")
    original_hint: str = Field(..., description="어떤 형태였는지 힌트(원문 저장 아님, 예: '010-****-****')")
    count: int = Field(1, ge=1, description="같은 유형이 몇 건 마스킹되었는지")


class CheckCreateResponse(BaseModel):
    """POST /api/v1/checks 응답."""
    check_id: str = Field(..., examples=["chk_demo"])
    extracted_text: str = Field(..., description="OCR/본문에서 추출한 텍스트 (마스킹 적용 후)")
    masked: bool = Field(..., description="비식별 처리가 1건 이상 적용되었는지")
    masked_items: List[MaskedItem] = Field(default_factory=list)
    detected_domain: Optional[str] = Field(None, description="추정 주제 영역 (health/finance/policy/news/unknown)")
    status: Literal["extracted", "needs_input", "failed"] = "extracted"
    message: Optional[str] = Field(
        None, description="status 가 extracted 가 아닐 때 사용자에게 보여줄 안내 문구 (예: 재촬영/직접입력 유도)"
    )


# ---------------------------------------------------------------- S2: 근거 수집
class Signal(BaseModel):
    """'확인이 필요한 지점' 1건. 진위 판정이 아니라 관찰된 신호만 적는다."""
    key: str = Field(..., description="신호 코드 (예: source_missing, number_mismatch)")
    label: str = Field(..., description="사람이 읽는 한 줄 설명")
    severity: Literal["info", "attention"] = "info"


class Reference(BaseModel):
    """실제로 존재하는 출처. ★ LLM이 지어낸 링크는 여기에 들어올 수 없다."""
    title: str
    url: str
    publisher: str = Field(..., description="발행 기관/매체명")
    published_at: Optional[str] = Field(None, description="YYYY-MM-DD")
    source_type: Literal["public_data", "news", "gov", "unknown"] = "unknown"


class EvidenceResponse(BaseModel):
    """GET /api/v1/checks/{check_id}/evidence 응답."""
    check_id: str
    verdict_hint: VerdictHint = Field(..., description="★ 참/거짓이 아닌 '확인 필요 정도'")
    signals: List[Signal] = Field(default_factory=list)
    references: List[Reference] = Field(default_factory=list)


# ---------------------------------------------------------------- S3: 질문 대화
class DialogueRequest(BaseModel):
    """POST /api/v1/checks/{check_id}/dialogue 요청."""
    turn: int = Field(1, ge=1, le=5, description="현재 몇 번째 질문인지 (1부터)")
    user_reply: Optional[str] = Field(None, description="직전 질문에 대한 사용자의 답(첫 턴은 null)")


class DialogueOption(BaseModel):
    """시니어가 타이핑 없이 고를 수 있는 답변 보기."""
    id: str
    label: str


class DialogueResponse(BaseModel):
    """POST /api/v1/checks/{check_id}/dialogue 응답.

    ★ question 은 반드시 prompt_chain.validate_question() 을 통과한 문장이다.
      - 금지어(가짜/사기/진짜입니다 등) 없음
      - evidence_refs 는 evidence.references 에 실제로 존재하는 URL 만
      - 2문장 이내
    """
    turn: int
    question: str = Field(..., description="AI가 던지는 확인 질문 (2문장 이내)")
    why: str = Field(..., description="이 질문을 왜 하는지 한 줄 설명")
    evidence_refs: List[str] = Field(default_factory=list, description="검증된 실제 출처 URL 목록")
    options: List[DialogueOption] = Field(default_factory=list)
    is_final: bool = False


# ---------------------------------------------------------------- S4: 판단 기록
class VerdictRequest(BaseModel):
    """POST /api/v1/checks/{check_id}/verdict 요청.
    ★ decision 은 사용자가 고른다. AI가 대신 고르지 않는다."""
    decision: Decision
    reason_tags: List[str] = Field(default_factory=list, description="사용자가 고른 이유 태그")


class VerdictResponse(BaseModel):
    """POST /api/v1/checks/{check_id}/verdict 응답."""
    check_id: str
    tagged_error_type: ErrorType = Field(..., description="이번 건에서 관찰된 오판 유형 (장지석 - tagger.py)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="태깅 신뢰도")
    message: str = Field(..., description="비난하지 않는 톤의 마무리 문장")


# ---------------------------------------------------------------- S5: 훈련
class TrainingItem(BaseModel):
    id: str
    label: str


class TrainingCardResponse(BaseModel):
    """GET /api/v1/training/today 응답 (장지석 - rag.py)."""
    card_id: str
    target_error_type: ErrorType
    content: str = Field(..., description="훈련 지문 (5분 안에 읽히는 짧은 글)")
    items: List[TrainingItem] = Field(default_factory=list)
    answer: str = Field(..., description="정답 item id")
    explanation: str
    estimated_sec: int = Field(300, description="예상 소요 시간(초). 기본 5분")


class WeeklyReportResponse(BaseModel):
    """GET /api/v1/reports/weekly 응답."""
    week: str = Field(..., examples=["2026-W30"])
    checks_count: int
    training_completed: int
    error_type_trend: dict = Field(default_factory=dict, description="{error_type: 건수}")
    streak_days: int
    message: str


# ---------------------------------------------------------------- 온보딩
class DiagnosisAnswer(BaseModel):
    question_id: str
    choice_id: str


class DiagnosisRequest(BaseModel):
    """POST /api/v1/onboarding/diagnosis 요청."""
    device_id: str = Field(..., description="비회원 식별자(닉네임/전화번호 대신 사용)")
    answers: List[DiagnosisAnswer] = Field(default_factory=list)


class DiagnosisResponse(BaseModel):
    user_id: str
    dominant_error_type: ErrorType
    score: dict = Field(default_factory=dict, description="{error_type: 0~1 점수}")
    starter_card_id: str
    message: str


# ---------------------------------------------------------------- 기타
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    version: str
    env: str
    mock_available: bool = True
    keys_configured: dict = Field(default_factory=dict)
