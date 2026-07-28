"""
곁눈(Gyeotnun) - 출처 교차대조
담당: 김유리

의심정보의 핵심 키워드로 공식 출처와 뉴스를 교차 검색한다.

★ 설계 원칙 ★
    1. **본문 요약을 만들지 않는다.** 제목·링크·게시일만 수집한다.
       LLM이 본문을 받으면 내용을 지어낼 위험이 커지기 때문.
    2. **못 찾은 것도 결과다.** found=False 레코드를 반드시 남긴다.
       "정부24에 없다"는 사실이 사용자에게 가장 중요한 신호이므로.
    3. 공식 도메인(go.kr, or.kr)은 is_official=True 로 표시해 화면에서 구분한다.

TODO (김유리)
    [ ] 키워드 추출: 마스킹 텍스트에서 제도명/기관명 추출 (형태소 or LLM)
    [ ] 정부24 검색 (www.gov.kr) - 오픈API 또는 검색 URL 파싱
    [ ] 정책브리핑 (korea.kr) 검색
    [ ] 네이버 뉴스 검색 API (settings.NAVER_CLIENT_ID/SECRET)
        GET https://openapi.naver.com/v1/search/news.json?query=...&display=5&sort=sim
        헤더: X-Naver-Client-Id / X-Naver-Client-Secret
    [ ] HTML 태그(<b> 등) 제거, 중복 URL 제거
    [ ] 429/타임아웃 재시도 (httpx + 백오프)
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

__all__ = ["cross_check", "extract_query", "OFFICIAL_SOURCES"]

OFFICIAL_SOURCES = {
    "gov24": "정부24",
    "korea_kr": "정책브리핑",
}


def extract_query(masked_text: str) -> str:
    """
    마스킹된 텍스트에서 검색용 핵심 키워드를 뽑는다.

    TODO(김유리): 지금은 앞 30자를 자르는 임시 로직.
                  제도명(OO지원금, OO수당)과 기관명을 우선 추출하도록 개선할 것.
    """
    if not masked_text:
        return ""
    head = masked_text.strip().splitlines()[0]
    head = head.strip("[]【】 ")
    return head[:30]


def cross_check(query: str) -> list[dict[str, Any]]:
    """
    공식 출처 + 뉴스 교차 검색.

    Args:
        query: 검색 키워드 (extract_query 결과).

    Returns:
        Evidence 딕셔너리 리스트. models.Evidence 컬럼과 키가 일치한다.
        [
          {
            "source": "gov24",
            "source_label": "정부24",
            "found": False,          # 못 찾아도 레코드를 남긴다
            "title": None,
            "url": None,
            "publisher": None,
            "published_at": None,
            "is_official": True,
            "rank": 0,
            "query_used": "효도지원금",
          },
          ...
        ]

    API 키가 없으면 목업을 반환한다 (예외를 던지지 않는다).
    """
    if not settings.has_naver:
        logger.info("NAVER 키 없음 → 목업 검색결과 반환 (query=%s)", query)
        return _mock_results(query)

    try:
        # TODO(김유리): 실제 구현
        #   results = []
        #   results += _search_gov24(query)
        #   results += _search_korea_kr(query)
        #   results += _search_naver_news(query)
        #   return results
        logger.warning("search 실구현 미완료 → 목업 반환")
        return _mock_results(query)
    except Exception as exc:  # noqa: BLE001 - 데모 안정성 우선
        logger.exception("교차대조 실패 → 목업 fallback: %s", exc)
        return _mock_results(query)


# ============================================================
# 목업
#   시나리오: '효도지원금'은 공식 출처에 없고, 관련 주의보 뉴스만 나온다.
#   → 프론트는 "공식 출처에서 찾지 못함" UI를 바로 구현할 수 있다.
# ============================================================
def _mock_results(query: str) -> list[dict[str, Any]]:
    q = query or "효도지원금"
    return [
        {
            "source": "gov24",
            "source_label": "정부24",
            "found": False,
            "title": None,
            "url": None,
            "publisher": None,
            "published_at": None,
            "is_official": True,
            "rank": 0,
            "query_used": q,
        },
        {
            "source": "korea_kr",
            "source_label": "정책브리핑",
            "found": False,
            "title": None,
            "url": None,
            "publisher": None,
            "published_at": None,
            "is_official": True,
            "rank": 1,
            "query_used": q,
        },
        {
            "source": "naver_news",
            "source_label": "네이버 뉴스",
            "found": True,
            "title": "'효도지원금' 사칭 문자 주의보… 접수비 요구는 없어",
            "url": "https://news.naver.com/example/article/0000000001",
            "publisher": "예시일보",
            "published_at": "2026-07-18",
            "is_official": False,
            "rank": 2,
            "query_used": q,
        },
        {
            "source": "naver_news",
            "source_label": "네이버 뉴스",
            "found": True,
            "title": "노인 대상 지원금 사칭 피해 신고 증가",
            "url": "https://news.naver.com/example/article/0000000002",
            "publisher": "예시경제",
            "published_at": "2026-07-11",
            "is_official": False,
            "rank": 3,
            "query_used": q,
        },
    ]


# ------------------------------------------------------------
# 실구현 자리 (김유리)
# ------------------------------------------------------------
def _search_gov24(query: str) -> list[dict[str, Any]]:
    """TODO(김유리): 정부24 검색. 결과 없으면 found=False 레코드 1건 반환."""
    raise NotImplementedError


def _search_korea_kr(query: str) -> list[dict[str, Any]]:
    """TODO(김유리): 정책브리핑(korea.kr) 검색."""
    raise NotImplementedError


def _search_naver_news(query: str, display: int = 5) -> list[dict[str, Any]]:
    """
    TODO(김유리): 네이버 뉴스 검색 API.

        headers = {
            "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        }
        r = httpx.get("https://openapi.naver.com/v1/search/news.json",
                      params={"query": query, "display": display, "sort": "sim"},
                      headers=headers, timeout=5.0)

    응답의 title/description에 <b> 태그가 섞여 있으므로 제거할 것.
    description(본문 일부)은 **저장하지 않는다.** (원칙 1)
    """
    raise NotImplementedError
