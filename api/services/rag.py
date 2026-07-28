"""
곁눈(Gyeotnun) - 훈련카드 생성 (RAG)
담당: 장지석 (RAG·코퍼스)

흐름
  corpus/public_data (공공데이터 577건)
    → 사용자의 dominant_error_type 에 맞는 원문 선택
    → 원문을 5분 안에 읽히는 2지선다 카드로 변환
    → training_cards 테이블 저장 → GET /training/today 로 제공

★ 카드 지문은 반드시 실제 공공데이터에서 나와야 한다.
  '있을 법한 가짜 뉴스'를 LLM에게 창작시키면 훈련 자체가 허구가 된다.
  변형은 '조건 문장을 지운다', '숫자를 바꾼다' 같은 결정적 규칙으로만 만든다.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from config import MissingKeyError, settings

CARDS_PATH = Path(__file__).resolve().parents[2] / "corpus" / "training_cards" / "sample_cards.json"


def load_sample_cards() -> list[dict]:
    """샘플 훈련카드 로드 (키 불필요). 코퍼스 확보 전까지의 기본 공급원."""
    if not CARDS_PATH.exists():
        return []
    try:
        return json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def pick_today_card(error_type: Optional[str] = None) -> Optional[dict]:
    """오늘의 카드 선택. 사용자의 취약 유형을 우선하고, 없으면 첫 카드를 준다."""
    cards = load_sample_cards()
    if not cards:
        return None
    if error_type:
        for c in cards:
            if c.get("target_error_type") == error_type:
                return c
    return cards[0]


def generate_card_from_corpus(doc: dict, target_error_type: str) -> dict:
    """TODO(장지석): 공공데이터 원문 1건 → 훈련카드 1장 변환.

    규칙 기반 변형(권장, 검증 가능)::
        number_condition        : 원문에서 조건절('~인 경우', '~이하') 을 지운 문장을 오답으로
        overgeneralization      : '일부'/'해당자' → '누구나'/'전원' 으로 치환한 문장을 오답으로
        authority_impersonation : 발행 기관명을 지운 문장을 오답으로
        title_dependent         : 제목만 남기고 본문 조건을 지운 문장을 오답으로

    LLM 은 '문장 다듬기'에만 쓰고, 정답 판정 근거는 항상 원문에 남긴다.
    """
    if not settings.has_llm:
        raise MissingKeyError("ANTHROPIC_API_KEY", owner="장지석")
    raise NotImplementedError("generate_card_from_corpus 미구현. sample_cards.json 을 사용하세요.")


def build_weekly_message(checks: int, training: int, streak: int) -> str:
    """주간 리포트 문구. 못한 것을 지적하지 않고 한 것만 세어 준다."""
    if checks == 0 and training == 0:
        return "이번 주는 쉬어 가셨네요. 오늘 5분 연습부터 다시 시작해 보시겠어요?"
    return (
        f"이번 주에는 {checks}건을 직접 확인하셨고, {streak}일 연속으로 연습을 이어가셨습니다. "
        f"연습은 모두 {training}회 마치셨어요."
    )
