"""테스트 공통 준비.

■ 왜 이 파일이 생겼나 (2026-08-13)
  search.py 에 폴백률 관측(EX-006)을 붙이면서, 그 관측이 **테스트끼리 새는**
  문제가 생겼다. 최근 N건을 프로세스 메모리(deque)에 들고 보므로, 폴백을 모의하는
  테스트가 남긴 기록이 그다음 테스트까지 따라간다. 그러면

    - 관계없는 테스트가 도는 중에 임계를 넘어 EX-006 이 발생하고,
      log_incident 가 **운영 DB(error_logs)에 행을 넣는다.** 테스트가 운영 데이터를
      더럽히면 안 된다.
    - 실행 순서에 따라 결과가 달라져 테스트가 불안정해진다.

  그래서 매 테스트 앞에서 관측 상태만 초기화한다. 관측 로직도, 임계값도,
  판정 로직도 건드리지 않는다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _reset_search_fallback_observer():
    from services import search

    search._recent_search_fallbacks.clear()
    search._search_fallback_alerted = False
    yield
    search._recent_search_fallbacks.clear()
    search._search_fallback_alerted = False
