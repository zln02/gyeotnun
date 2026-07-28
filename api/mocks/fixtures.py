"""
곁눈(Gyeotnun) - ?mock=1 고정 응답 픽스처
담당: 박진영 (계약) / 전원 사용

왜 필요한가
- 해커톤 특성상 API 키 발급이 늦거나 한도가 막힐 수 있다.
- 프론트(조희진)는 백엔드 완성을 기다리지 않고 화면을 끝까지 만들어야 한다.
- 시연 도중 외부 API가 죽어도 데모는 끝까지 돌아가야 한다.
→ 모든 엔드포인트는 ?mock=1 을 받으면 아래 고정값을 그대로 반환한다.

데모 시나리오 (팀 공용 1개로 통일)
  카카오톡으로 받은 이미지 한 장:
  "★긴급★ 65세 이상 어르신 전원 매달 40만원 지급 확정!
   신청 안 하면 못 받습니다. 접수: 010-1234-5678 / 입금계좌 123-456-789012"
  → 곁눈은 "가짜입니다"라고 말하지 않는다.
    대신 "이 금액이 어디에 적혀 있는지 함께 찾아볼까요?" 라고 묻는다.
"""
from __future__ import annotations

# 데모 고정 ID (프론트 라우팅과 맞춰져 있으니 변경 시 조희진에게 공유)
DEMO_CHECK_ID = "chk_demo"
DEMO_USER_ID = "usr_demo"
DEMO_CARD_ID = "card_demo_001"

# 원문(마스킹 전) — 참고용 주석. 실제 저장/반환되지 않는다.
_RAW_FOR_REFERENCE = (
    "★긴급★ 65세 이상 어르신 전원 매달 40만원 지급 확정! "
    "신청 안 하면 못 받습니다. 접수: 010-1234-5678 / 입금계좌 123-456-789012"
)

# ------------------------------------------------------- POST /checks
CHECK_CREATE = {
    "check_id": DEMO_CHECK_ID,
    "extracted_text": (
        "★긴급★ 65세 이상 어르신 전원 매달 40만원 지급 확정! "
        "신청 안 하면 못 받습니다. 접수: 010-****-**** / 입금계좌 ***-***-******"
    ),
    "masked": True,
    "masked_items": [
        {"type": "phone", "original_hint": "010-****-****", "count": 1},
        {"type": "account", "original_hint": "***-***-******", "count": 1},
    ],
    "detected_domain": "policy",
    "status": "extracted",
}

# --------------------------------------- GET /checks/{id}/evidence
# ★ verdict_hint 는 절대 true/false 가 아니다. '확인이 필요한 정도'만 담는다.
EVIDENCE = {
    "check_id": DEMO_CHECK_ID,
    "verdict_hint": "partially_matched",
    "signals": [
        {
            "key": "number_mismatch",
            "label": "글에 적힌 '40만원'과 공식 자료의 금액 기준이 서로 다릅니다.",
            "severity": "attention",
        },
        {
            "key": "condition_omitted",
            "label": "'전원'이라고 적혀 있지만, 공식 자료에는 소득 기준 조건이 있습니다.",
            "severity": "attention",
        },
        {
            "key": "source_missing",
            "label": "이 글에는 어느 기관이 발표했는지가 적혀 있지 않습니다.",
            "severity": "attention",
        },
        {
            "key": "contact_in_image",
            "label": "이미지 안에 개인 연락처와 계좌번호가 들어 있어 가려 두었습니다.",
            "severity": "info",
        },
    ],
    # ★ 아래 URL 만이 prompt_chain.validate_question() 의 allowed_refs 가 된다.
    "references": [
        {
            "title": "기초연금 제도 안내 - 지급 대상과 금액 기준",
            "url": "https://basicpension.mohw.go.kr/",
            "publisher": "보건복지부 기초연금",
            "published_at": "2026-01-02",
            "source_type": "gov",
        },
        {
            "title": "복지로 - 기초연금 모의계산 및 신청 방법",
            "url": "https://www.bokjiro.go.kr/",
            "publisher": "복지로(한국사회보장정보원)",
            "published_at": "2026-01-15",
            "source_type": "gov",
        },
        {
            "title": "정책브리핑 - 확인되지 않은 복지 지원금 안내 메시지 주의 안내",
            "url": "https://www.korea.kr/",
            "publisher": "대한민국 정책브리핑",
            "published_at": "2026-03-11",
            "source_type": "gov",
        },
    ],
}

# ------------------------------------- POST /checks/{id}/dialogue
# 턴별 고정 질문. 모두 2문장 이내 + 금지어 없음 (validate_question 통과 확인됨).
DIALOGUE_TURNS = {
    1: {
        "turn": 1,
        "question": "이 글에 적힌 '매달 40만원'이라는 금액은 어디에서 발표한 내용일까요? 글 안에서 기관 이름을 한번 찾아봐 주세요.",
        "why": "숫자가 크게 적혀 있을수록, 그 숫자를 누가 말했는지부터 확인하면 판단이 쉬워집니다.",
        "evidence_refs": ["https://basicpension.mohw.go.kr/"],
        "options": [
            {"id": "found", "label": "기관 이름이 적혀 있어요"},
            {"id": "not_found", "label": "찾지 못하겠어요"},
            {"id": "unsure", "label": "잘 모르겠어요"},
        ],
        "is_final": False,
    },
    2: {
        "turn": 2,
        "question": "출처를 찾지 못했다는 것 자체가 한 번 더 확인해 볼 신호입니다. 공식 안내 페이지에 적힌 금액과 나란히 놓고 비교해 보시겠어요?",
        "why": "출처를 못 찾는 상황은 그 자체로 중요한 정보입니다. 원래 자료와 숫자를 나란히 놓고 보면 차이가 보입니다.",
        "evidence_refs": [
            "https://basicpension.mohw.go.kr/",
            "https://www.bokjiro.go.kr/",
        ],
        "options": [
            {"id": "different", "label": "금액이 달라요"},
            {"id": "same", "label": "금액이 같아요"},
            {"id": "hard", "label": "비교가 어려워요"},
        ],
        "is_final": False,
    },
    3: {
        "turn": 3,
        "question": "글에는 '전원'이라고 적혀 있는데, 공식 안내에는 소득 기준이 함께 적혀 있습니다. 두 설명 중 어느 쪽이 조건을 더 자세히 알려 주고 있나요?",
        "why": "'모두에게'라는 표현은 조건을 지운 표현일 때가 많습니다. 조건이 적혀 있는 쪽이 원래 자료에 가깝습니다.",
        "evidence_refs": ["https://www.bokjiro.go.kr/"],
        "options": [
            {"id": "official", "label": "공식 안내 쪽이 자세해요"},
            {"id": "message", "label": "받은 글 쪽이 자세해요"},
        ],
        "is_final": True,
    },
}

# -------------------------------------- POST /checks/{id}/verdict
VERDICT = {
    "check_id": DEMO_CHECK_ID,
    "tagged_error_type": "number_condition",
    "confidence": 0.82,
    "message": (
        "직접 확인해 보신 점이 좋았습니다. 이번 글은 금액과 자격 조건이 빠져 있어 헷갈리기 쉬운 형태였어요. "
        "내일 5분 연습에서 '숫자와 조건 찾기'를 함께 해 보시면 더 편해집니다."
    ),
}

# ----------------------------------------- GET /training/today
TRAINING_TODAY = {
    "card_id": DEMO_CARD_ID,
    "target_error_type": "number_condition",
    "content": (
        "다음 두 문장을 읽고, 조건이 빠져 있는 문장을 골라 주세요.\n\n"
        "(가) 65세 이상이면 누구나 매달 40만원을 받습니다.\n"
        "(나) 65세 이상 중 소득인정액이 기준액 이하인 분이 기초연금을 받습니다."
    ),
    "items": [
        {"id": "a", "label": "(가) 65세 이상이면 누구나"},
        {"id": "b", "label": "(나) 소득인정액이 기준액 이하인 분"},
    ],
    "answer": "a",
    "explanation": (
        "(가)에는 '누구나'라는 말만 있고 소득 조건이 없습니다. "
        "'누구나·전원·무조건' 같은 말이 보이면 빠진 조건이 없는지 한 번 더 살펴보세요."
    ),
    "estimated_sec": 300,
}

# ----------------------------------------- GET /reports/weekly
WEEKLY_REPORT = {
    "week": "2026-W30",
    "checks_count": 4,
    "training_completed": 5,
    "error_type_trend": {
        "title_dependent": 1,
        "authority_impersonation": 1,
        "number_condition": 2,
        "overgeneralization": 0,
    },
    "streak_days": 5,
    "message": (
        "이번 주에는 4건을 직접 확인하셨고, 5일 연속으로 연습을 이어가셨습니다. "
        "숫자와 조건을 확인하는 습관이 지난주보다 늘었습니다."
    ),
}

# ------------------------------------ POST /onboarding/diagnosis
ONBOARDING_DIAGNOSIS = {
    "user_id": DEMO_USER_ID,
    "dominant_error_type": "number_condition",
    "score": {
        "title_dependent": 0.25,
        "authority_impersonation": 0.20,
        "number_condition": 0.40,
        "overgeneralization": 0.15,
    },
    "starter_card_id": DEMO_CARD_ID,
    "message": (
        "숫자와 조건이 함께 나올 때 조금 더 살펴보시면 좋겠습니다. "
        "첫 연습 카드를 준비해 두었어요."
    ),
}


def dialogue_for(turn: int) -> dict:
    """요청 턴에 해당하는 고정 질문을 돌려준다. 범위를 넘으면 마지막 턴을 반환."""
    if turn in DIALOGUE_TURNS:
        return DIALOGUE_TURNS[turn]
    return DIALOGUE_TURNS[max(DIALOGUE_TURNS)]


def allowed_refs() -> list[str]:
    """mock 근거의 URL 목록. validate_question() 의 allowed_refs 로 그대로 쓴다."""
    return [r["url"] for r in EVIDENCE["references"]]
