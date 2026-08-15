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
    error_code: Optional[str] = Field(
        None, description="status='failed' 일 때의 오류 코드 (예: IN-001, RC-001) - services/error_codes.py 참고"
    )


# ---------------------------------------------------------------- S2: 근거 수집
class Signal(BaseModel):
    """'확인이 필요한 지점' 1건. 진위 판정이 아니라 관찰된 신호만 적는다."""
    key: str = Field(..., description="신호 코드 (예: source_missing, number_mismatch)")
    label: str = Field(..., description="사람이 읽는 한 줄 설명")
    severity: Literal["info", "attention"] = "info"
    # ★ 2026-08-13 추가. risk_action_requested 하나가 유형 4종을 담기 위한 필드다.
    #   유형마다 키를 따로 만들지 않은 이유: verdict.js 의 ATTENTION_KEYS 는 허용목록
    #   방식이라(2026-08-12) 키가 늘 때마다 넣는 걸 잊으면 그 글이 조용히 초록으로
    #   내려간다. 키는 하나로 두고 유형은 이 필드로 나른다.
    detail: Optional[str] = Field(
        None, description="유형 (예: 앱설치/계좌이체/인증번호/개인정보요구)")
    # ★ 검출 근거가 된 원문 구절. 화면이 이걸 그대로 인용한다 - 유형 라벨이 만에 하나
    #   어긋나도 사용자는 실제 문장을 본다. 거짓말이 구조적으로 어려워진다.
    #   ★ 이미 마스킹된 텍스트에서만 나온다(collect_evidence 입력이 masked_text 다).
    quote: Optional[str] = Field(None, description="검출 근거가 된 원문 구절(마스킹 후)")


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
    # ★ 소유권 확인용: 이 check_id 를 만든 기기의 device_id 와 일치해야 한다(IDOR 방지).
    #   위조 가능한 값이라는 한계는 문서에 기록돼 있다 - 새 인증 체계는 뒤에 다룬다.
    device_id: Optional[str] = Field(None, description="이 확인 건을 만든 기기 식별자")


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
    # ★ 소유권 확인용(IDOR 방지) - DialogueRequest.device_id 와 같은 목적.
    device_id: Optional[str] = Field(None, description="이 확인 건을 만든 기기 식별자")


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
    # ★ 2026-08-05 추가. sample_cards.json 에는 source_url 이 처음부터 들어 있었는데
    #   이 스키마에 필드가 없어 응답에서 조용히 탈락했다. 그래서 사용자가 훈련 카드를
    #   풀고 나서 근거 원문으로 돌아갈 방법이 없었다(docs/evaluation/judgment_basis.md §4).
    #   근거 없는 학습은 곁눈이 하지 않기로 한 것이므로 노출한다.
    #   Optional 인 이유: 카드에 URL 이 없을 수도 있고, 없다고 훈련이 막히면 안 된다.
    source_url: Optional[str] = Field(
        None, description="이 카드의 근거 원문 URL. 없으면 화면에서 링크를 감춘다")


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


# ---------------------------------------------------------------- 사용자 행동 계측
EventType = Literal["screen_enter", "screen_leave", "click", "evidence_link_click", "error"]

_SCREENS = Literal["S1", "S2", "S3", "S4", "S5"]


class EventIn(BaseModel):
    """POST /api/v1/events 요청 1건.

    ★ 화면에 입력된 텍스트(붙여넣은 글, 질문 답변 자유 서술 등)는 절대 담지 않는다.
      target/meta 는 버튼 id·화면 이름·오류 유형처럼 짧고 정해진 값만 담아야 한다
      (그 외는 서버가 정제/폐기한다 - routers/events.py).
    """
    device_id: str = Field(..., description="비회원 식별자 (서버에서 SHA-256 해시로만 저장)")
    session_id: str = Field(..., description="브라우저 세션(SPA 로드) 단위 UUID - 개인정보 아님")
    event_type: EventType
    screen: Optional[_SCREENS] = Field(None, description="S1~S5 중 하나")
    target: Optional[str] = Field(None, max_length=64, description="버튼 id 또는 오류 유형 등")
    ts: Optional[str] = Field(None, description="클라이언트 발생 시각(ISO 8601). 없으면 서버 수신 시각을 쓴다")
    meta: Optional[dict] = Field(None, description="소량의 구조화된 부가정보 (자유 텍스트 금지)")


class EventAckResponse(BaseModel):
    """POST /api/v1/events 응답. fire-and-forget 이라 프론트는 이 값을 보지 않는다."""
    accepted: int = Field(..., description="1이면 기록됨, 0이면 무시됨(실패해도 200을 돌려준다)")


class EventSummaryResponse(BaseModel):
    """GET /api/v1/events/summary 응답. 8/5 사용성 테스트 정량 집계용."""
    total_sessions: int = Field(..., description="이벤트가 1건이라도 있는 세션 수")
    screen_reached_sessions: dict = Field(default_factory=dict, description="{screen: 그 화면에 도달한 세션 수}")
    screen_avg_dwell_sec: dict = Field(default_factory=dict, description="{screen: 평균 체류시간(초)}")
    screen_dwell_sample_count: dict = Field(default_factory=dict, description="{screen: 체류시간 표본 수(leave 기록이 없는 세션은 제외됨)}")
    screen_drop_off_rate: dict = Field(default_factory=dict, description="{screen: 그 화면이 마지막이었던 세션 비율(0~1)}")
    screen_avg_time_to_first_click_sec: dict = Field(default_factory=dict, description="{screen: 진입~첫 클릭 평균초} - 시니어 UX 핵심 지표")
    screen_median_time_to_first_click_sec: dict = Field(default_factory=dict, description="{screen: 진입~첫 클릭 중앙값(초)} - 평균은 소수 이상치에 쉽게 흔들리므로 함께 본다")
    screen_time_to_first_click_samples_sec: dict = Field(default_factory=dict, description="{screen: [진입~첫 클릭 초, ...]} - 표본 수가 적은 사용성 테스트 특성상 분포(퍼짐) 자체를 눈으로 봐야 하므로 원본값을 그대로 반환한다")
    click_counts: dict = Field(default_factory=dict, description="{버튼 target: 클릭 수}")
    evidence_link_click_sessions: int = Field(0, description="근거 링크를 1번이라도 누른 세션 수")
    evidence_link_click_rate: float = Field(0.0, description="S3 도달 세션 중 근거 링크 클릭 비율(0~1) - '공식 출처 확인률'")
    error_counts: dict = Field(default_factory=dict, description="{오류 유형: 발생 수}")


# ---------------------------------------------------------------- 오류 코드 체계 (2026-08)
class ErrorCodeItem(BaseModel):
    """GET /api/v1/errors/codes 의 원소 1개.

    ★ 2026-08-15: 이 엔드포인트는 무인증 공개다(프론트가 앱 시작 시 받아 쓴다).
      그래서 **프론트가 실제로 쓰는 두 필드만** 내보낸다.
      전에는 services/error_codes.py 의 6개 필드를 그대로 실어 보냈는데,
      그중 situation·internal_handling 은 "어떤 실패에 어떤 폴백을 타는지"를
      적어 둔 내부 문서다. 누구나 읽을 수 있는 자리에 둘 이유가 없다.
      단일 소스 원칙은 그대로다 - 정의처는 여전히 error_codes.py 한 곳이고,
      여기서 무엇을 공개할지만 고른다. 전체 표는 docs/error_codes.md 에 있다.

      프론트 사용처 전수 확인(web/src/errorCodes.js): `c.code` 와
      `found?.user_message` 둘뿐이다. area·situation·recovery·internal_handling 은
      web/src 어디에서도 참조되지 않는다.
    """
    code: str = Field(..., examples=["EX-001"])
    user_message: str = Field(..., description="시니어가 이해할 수 있는 안내 문구 (빈 문자열이면 화면에 노출 안 됨 - 자동 폴백)")


class ErrorSummaryItem(BaseModel):
    """GET /api/v1/errors/summary 의 원소 1개 - 코드 하나에 대한 집계."""
    code: str
    area: str
    situation: str
    user_message: str
    recovery: str
    count: int = Field(..., description="server_count + client_count")
    server_count: int = Field(..., description="서버가 스스로 인지한 건수 (error_logs 테이블)")
    client_count: int = Field(..., description="프론트가 신고한 건수 (events 테이블, event_type=error)")
    last_occurred_at: Optional[str] = Field(None, description="가장 최근 발생 시각(ISO 8601)")


class ErrorSummaryResponse(BaseModel):
    """GET /api/v1/errors/summary 응답 - 최근 오류를 코드별로 집계한다."""
    items: List[ErrorSummaryItem] = Field(default_factory=list, description="발생 건수 내림차순 정렬")
    total_count: int = 0


# ---------------------------------------------------------------- 기타
class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    version: str
    env: str
    mock_available: bool = True
    keys_configured: dict = Field(default_factory=dict)
