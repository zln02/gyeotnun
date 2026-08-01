"""곁눈 API 라우터 패키지.

공통 규칙
- 모든 엔드포인트는 ?mock=1 을 받으면 mocks/fixtures.py 고정값을 반환한다.
- mock 이 아니면 각 service 를 호출하고, 키가 없으면 501 + 안내 메시지를 준다.
"""
from .checks import router as checks_router          # noqa: F401
from .dialogue import router as dialogue_router      # noqa: F401
from .verdict import router as verdict_router        # noqa: F401
from .training import router as training_router      # noqa: F401
from .reports import router as reports_router        # noqa: F401
from .onboarding import router as onboarding_router  # noqa: F401
from .events import router as events_router          # noqa: F401
