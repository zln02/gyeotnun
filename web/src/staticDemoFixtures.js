// Exported from api/mocks/fixtures.py for the serverless portfolio demo.
// Weekly report numbers are zeroed to avoid presenting fabricated user progress.
export default {
  "CHECK_CREATE": {
    "check_id": "chk_demo",
    "extracted_text": "★긴급★ 65세 이상 어르신 전원 매달 40만원 지급 확정! 신청 안 하면 못 받습니다. 접수: 010-****-**** / 입금계좌 ***-***-******",
    "masked": false,
    "masked_items": [],
    "detected_domain": "policy",
    "status": "extracted"
  },
  "EVIDENCE": {
    "check_id": "chk_demo",
    "verdict_hint": "partially_matched",
    "signals": [
      {
        "key": "number_mismatch",
        "label": "글에 적힌 '40만원'과 공식 자료의 금액 기준이 서로 다릅니다.",
        "severity": "attention"
      },
      {
        "key": "condition_omitted",
        "label": "'전원'이라고 적혀 있지만, 공식 자료에는 소득 기준 조건이 있습니다.",
        "severity": "attention"
      },
      {
        "key": "source_missing",
        "label": "이 글에는 어느 기관이 발표했는지가 적혀 있지 않습니다.",
        "severity": "attention"
      },
      {
        "key": "contact_in_image",
        "label": "이미지 안에 개인 연락처와 계좌번호가 들어 있어 가려 두었습니다.",
        "severity": "info"
      }
    ],
    "references": [
      {
        "title": "기초연금 제도 안내 - 지급 대상과 금액 기준",
        "url": "https://basicpension.mohw.go.kr/",
        "publisher": "보건복지부 기초연금",
        "published_at": "2026-01-02",
        "source_type": "gov"
      },
      {
        "title": "복지로 - 기초연금 모의계산 및 신청 방법",
        "url": "https://www.bokjiro.go.kr/",
        "publisher": "복지로(한국사회보장정보원)",
        "published_at": "2026-01-15",
        "source_type": "gov"
      },
      {
        "title": "정책브리핑 - 확인되지 않은 복지 지원금 안내 메시지 주의 안내",
        "url": "https://www.korea.kr/",
        "publisher": "대한민국 정책브리핑",
        "published_at": "2026-03-11",
        "source_type": "gov"
      }
    ]
  },
  "DIALOGUE_TURNS": {
    "1": {
      "turn": 1,
      "question": "이 글에 적힌 '매달 40만원'이라는 금액은 어디에서 발표한 내용일까요? 글 안에서 기관 이름을 한번 찾아봐 주세요.",
      "why": "숫자가 크게 적혀 있을수록, 그 숫자를 누가 말했는지부터 확인하면 판단이 쉬워집니다.",
      "evidence_refs": [
        "https://basicpension.mohw.go.kr/"
      ],
      "options": [
        {
          "id": "found",
          "label": "기관 이름이 적혀 있어요"
        },
        {
          "id": "not_found",
          "label": "찾지 못하겠어요"
        },
        {
          "id": "unsure",
          "label": "잘 모르겠어요"
        }
      ],
      "is_final": false
    },
    "2": {
      "turn": 2,
      "question": "출처를 찾지 못했다는 것 자체가 한 번 더 확인해 볼 신호입니다. 공식 안내 페이지에 적힌 금액과 나란히 놓고 비교해 보시겠어요?",
      "why": "출처를 못 찾는 상황은 그 자체로 중요한 정보입니다. 원래 자료와 숫자를 나란히 놓고 보면 차이가 보입니다.",
      "evidence_refs": [
        "https://basicpension.mohw.go.kr/",
        "https://www.bokjiro.go.kr/"
      ],
      "options": [
        {
          "id": "different",
          "label": "금액이 달라요"
        },
        {
          "id": "same",
          "label": "금액이 같아요"
        },
        {
          "id": "hard",
          "label": "비교가 어려워요"
        }
      ],
      "is_final": false
    },
    "3": {
      "turn": 3,
      "question": "글에는 '전원'이라고 적혀 있는데, 공식 안내에는 소득 기준이 함께 적혀 있습니다. 두 설명 중 어느 쪽이 조건을 더 자세히 알려 주고 있나요?",
      "why": "'모두에게'라는 표현은 조건을 지운 표현일 때가 많습니다. 조건이 적혀 있는 쪽이 원래 자료에 가깝습니다.",
      "evidence_refs": [
        "https://www.bokjiro.go.kr/"
      ],
      "options": [
        {
          "id": "official",
          "label": "공식 안내 쪽이 자세해요"
        },
        {
          "id": "message",
          "label": "받은 글 쪽이 자세해요"
        }
      ],
      "is_final": true
    }
  },
  "VERDICT": {
    "check_id": "chk_demo",
    "tagged_error_type": "number_condition",
    "confidence": 0.82,
    "message": "직접 확인해 보신 점이 좋았습니다. 이번 글은 금액과 자격 조건이 빠져 있어 헷갈리기 쉬운 형태였어요. 내일 5분 연습에서 '숫자와 조건 찾기'를 함께 해 보시면 더 편해집니다."
  },
  "TRAINING_TODAY": {
    "card_id": "card_demo_001",
    "target_error_type": "number_condition",
    "content": "다음 두 문장을 읽고, 조건이 빠져 있는 문장을 골라 주세요.\n\n(가) 65세 이상이면 누구나 매달 40만원을 받습니다.\n(나) 65세 이상 중 소득인정액이 기준액 이하인 분이 기초연금을 받습니다.",
    "items": [
      {
        "id": "a",
        "label": "(가) 65세 이상이면 누구나"
      },
      {
        "id": "b",
        "label": "(나) 소득인정액이 기준액 이하인 분"
      }
    ],
    "answer": "a",
    "explanation": "(가)에는 '누구나'라는 말만 있고 소득 조건이 없습니다. '누구나·전원·무조건' 같은 말이 보이면 빠진 조건이 없는지 한 번 더 살펴보세요.",
    "estimated_sec": 300,
    "source_url": "https://basicpension.mohw.go.kr/"
  },
  "WEEKLY_REPORT": {
    "week": "데모",
    "checks_count": 0,
    "training_completed": 0,
    "error_type_trend": {
      "title_dependent": 0,
      "authority_impersonation": 0,
      "number_condition": 0,
      "overgeneralization": 0
    },
    "streak_days": 0,
    "message": "합성 예시 화면입니다. 실제 이용 기록이나 판단력 향상 측정 결과가 아닙니다."
  },
  "ONBOARDING_DIAGNOSIS": {
    "user_id": "usr_demo",
    "dominant_error_type": "number_condition",
    "score": {
      "title_dependent": 0.25,
      "authority_impersonation": 0.2,
      "number_condition": 0.4,
      "overgeneralization": 0.15
    },
    "starter_card_id": "card_demo_001",
    "message": "숫자와 조건이 함께 나올 때 조금 더 살펴보시면 좋겠습니다. 첫 연습 카드를 준비해 두었어요."
  }
}
