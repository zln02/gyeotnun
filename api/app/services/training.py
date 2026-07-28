"""
곁눈(Gyeotnun) - 훈련카드 (RAG)
담당: 장지석

태깅된 오판유형에 맞는 훈련 문항을 corpus에서 골라 제공한다.

동작
    1차: DB의 corpus 테이블에서 조회 (운영)
    폴백: corpus/seed.json 파일에서 직접 로드 (개발 초기 / DB 미적재)

TODO (장지석)
    [ ] 난이도 적응: 연속 정답 시 difficulty +1, 오답 시 -1
    [ ] 중복 방지: 최근 7일 내 발급한 corpus는 제외
    [ ] 임베딩 기반 유사 문항 검색 (RAG 고도화, 여유 있으면)
    [ ] seed.json 을 DB corpus 테이블로 적재하는 스크립트 (load_corpus)
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date
from pathlib import Path
from typing import Any

from .tagger import ERROR_TYPE_LABELS, TITLE_DEPENDENT

logger = logging.getLogger(__name__)

__all__ = ["get_today_card", "load_seed_corpus", "SEED_PATH"]

# api/app/services/training.py → 프로젝트 루트 → corpus/seed.json
SEED_PATH = Path(__file__).resolve().parents[3] / "corpus" / "seed.json"

_seed_cache: list[dict[str, Any]] | None = None


def load_seed_corpus() -> list[dict[str, Any]]:
    """corpus/seed.json 을 읽어 리스트로 반환 (프로세스 내 캐시)."""
    global _seed_cache
    if _seed_cache is not None:
        return _seed_cache

    try:
        with SEED_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        _seed_cache = data.get("items", []) if isinstance(data, dict) else data
    except FileNotFoundError:
        logger.warning("seed.json 을 찾지 못했습니다: %s", SEED_PATH)
        _seed_cache = []
    except json.JSONDecodeError as exc:
        logger.error("seed.json 파싱 실패: %s", exc)
        _seed_cache = []

    return _seed_cache


def get_today_card(user_id: int | None, error_type: str | None = None) -> dict[str, Any]:
    """
    오늘의 훈련카드 1장을 반환한다.

    Args:
        user_id:    사용자 id. None이면 비로그인(디바이스) 사용자.
        error_type: 태깅된 오판유형. None이면 무작위 유형.

    Returns:
        schemas.TrainingCardOut 과 키가 일치하는 딕셔너리.
        {
          "id": None,
          "corpus_slug": "TD-001",
          "error_type": "TITLE_DEPENDENT",
          "error_type_label": "제목의존형",
          "difficulty": 1,
          "domain": "공공지원금",
          "title": "...",
          "content": "...",
          "checkpoints": ["...", "..."],
          "explanation": "...",
          "completed": False,
          "issued_for": date.today(),
        }

    TODO(장지석): DB corpus 테이블 우선 조회 + 최근 발급 이력 제외로 교체.
    """
    items = load_seed_corpus()

    if not items:
        return _empty_card(error_type)

    target = error_type or TITLE_DEPENDENT
    pool = [i for i in items if i.get("error_type") == target] or items
    picked = random.choice(pool)

    return {
        "id": None,
        "corpus_slug": picked.get("id", ""),
        "error_type": picked.get("error_type", target),
        "error_type_label": ERROR_TYPE_LABELS.get(picked.get("error_type", target), ""),
        "difficulty": picked.get("difficulty", 1),
        "domain": picked.get("domain", ""),
        "title": picked.get("title", ""),
        "content": picked.get("content", ""),
        "checkpoints": picked.get("checkpoints", []),
        "explanation": picked.get("explanation", ""),
        "completed": False,
        "issued_for": date.today(),
    }


def _empty_card(error_type: str | None) -> dict[str, Any]:
    """코퍼스를 못 읽었을 때의 안전한 빈 카드 (화면이 죽지 않도록)."""
    et = error_type or TITLE_DEPENDENT
    return {
        "id": None,
        "corpus_slug": "",
        "error_type": et,
        "error_type_label": ERROR_TYPE_LABELS.get(et, ""),
        "difficulty": 1,
        "domain": "",
        "title": "오늘의 훈련을 준비 중입니다",
        "content": "잠시 후 다시 확인해 주세요.",
        "checkpoints": [],
        "explanation": "",
        "completed": False,
        "issued_for": date.today(),
    }


def compute_streak(user_id: int | None) -> int:
    """
    TODO(장지석): 연속 훈련 일수 계산.
    training_cards 에서 completed=True 인 issued_for 날짜를 역순으로 세면 된다.
    """
    return 0


def load_corpus_to_db(db) -> int:  # noqa: ANN001
    """
    TODO(장지석): seed.json → corpus 테이블 적재.

    slug(=seed의 id) 기준 upsert. main.py 기동 시 1회 호출하도록 붙일 예정.
    반환값은 적재된 건수.
    """
    raise NotImplementedError
