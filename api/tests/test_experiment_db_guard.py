"""실험·벤치 스크립트의 DB 가드 누락을 잡는다 (2026-08-17 신설).

실행: cd api && python -m pytest tests/test_experiment_db_guard.py -q

■ ★★ 이 테스트가 존재하는 이유 ★★
  2026-08-16~17, 내 실험 스크립트가 운영 error_logs 에 GN-001 7건을 쌓았다.
  스크립트는 DB 를 쓰려는 의도가 없었다 - 안에서 부른 collect_evidence /
  generate_question 이 실패 경로에서 log_incident() 를 부른 것이다.
  **간접 경로**라 스크립트를 하나씩 고쳐서는 막을 수 없고, 새 실험을 쓰면 또 뚫린다.

  그래서 `_guard.py` 를 만들었는데, 가드는 **빠뜨리면 그만**이다.
  → 빠뜨림 자체를 여기서 잡는다. 사람의 기억이 아니라 검사가 지킨다.

■ 규칙
  experiments/ · tools/ 아래 파일이 services 또는 models 를 임포트한다면,
  **_guard 를 그보다 먼저** 임포트해야 한다.
  (models.db 는 임포트 시점에 DATABASE_URL 을 읽는다. 순서가 곧 전부다.)

■ 면제
  운영 DB 를 건드리는 것이 **목적인** 도구는 면제한다. 가드를 걸면 도구가 죽는다.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_DIR = pathlib.Path(__file__).resolve().parents[1]
SCAN_DIRS = ("experiments", "tools")

# ★ 운영 DB 를 건드리는 것이 목적인 도구. 가드 대상이 아니다.
#   여기에 이름을 더할 때는 "이 파일이 운영 DB 를 **의도적으로** 쓰는가"만 본다.
EXEMPT = {
    "tools/purge_old_records.py",      # 보관기간 초과분 삭제 (매일 04:00 cron)
    "tools/migrate_check_store.py",    # 컬럼 추가 마이그레이션
    "tools/delete_rows.py",            # 행 삭제 도구(백업·리허설·--expect 내장)
    "tools/migrate_judgment_logs.py",  # judgment_logs 테이블 생성 (2026-08-20)
}

# ★ 정규식으로 소스를 훑지 않는다. 독스트링 안의 예시 명령어("from services import …")를
#   진짜 임포트로 잘못 읽는다 - 실제로 diag_warning_case_c.py 에서 그렇게 오탐이 났다.
#   ast 로 파싱해 **실제 임포트 노드**만 본다.
_APP_ROOTS = ("services", "models")


def _first_line(src: str, kind: str) -> int | None:
    """kind='app'이면 services/models 임포트, 'guard'면 _guard 임포트의 첫 줄 번호."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    best = None
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        want = _APP_ROOTS if kind == "app" else ("_guard",)
        if any(n in want for n in names):
            best = node.lineno if best is None else min(best, node.lineno)
    return best


def _targets() -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for d in SCAN_DIRS:
        for f in sorted((API_DIR / d).rglob("*.py")):
            if "__pycache__" in str(f) or f.name == "__init__.py":
                continue
            out.append(f)
    return out


def _rel(f: pathlib.Path) -> str:
    return str(f.relative_to(API_DIR))


@pytest.mark.parametrize("path", _targets(), ids=_rel)
def test_scripts_touching_the_app_import_the_guard_first(path: pathlib.Path):
    """★ services/models 를 쓰는 실험은 _guard 를 **먼저** 임포트해야 한다."""
    rel = _rel(path)
    src = path.read_text(encoding="utf-8", errors="ignore")

    app_line = _first_line(src, "app")
    if app_line is None:
        return                      # 앱을 안 쓰는 스크립트(HTTP 클라이언트 등)는 대상 아님
    if rel in EXEMPT:
        return                      # 운영 DB 를 쓰는 것이 목적인 도구

    guard_line = _first_line(src, "guard")
    assert guard_line is not None, (
        f"{rel} 이 services/models 를 임포트하는데 `import _guard` 가 없다.\n"
        "  → 파일 위쪽 sys.path.insert 바로 뒤에 `import _guard  # noqa: F401` 를 넣을 것.\n"
        "  → 운영 DB 를 쓰는 것이 목적이라면 tests/test_experiment_db_guard.py 의 EXEMPT 에 추가."
    )
    assert guard_line < app_line, (
        f"{rel} 의 `import _guard` 가 services/models 임포트보다 **뒤에** 있다.\n"
        "  → models.db 는 임포트 시점에 DATABASE_URL 을 읽는다. 늦으면 아무것도 못 막는다."
    )


def test_exempt_list_only_contains_files_that_exist():
    """면제 목록이 낡아 유명무실해지지 않게 한다."""
    for rel in EXEMPT:
        assert (API_DIR / rel).exists(), f"면제 목록에 없는 파일이 있다: {rel}"


def test_guard_rewrites_a_production_url(monkeypatch):
    """★ 가드가 실제로 운영 URL 을 덮는지. 안 덮으면 이 모든 게 장식이다."""
    import _guard

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://u:p@db:5432/gyeotnun")
    out = _guard.install()
    assert out.startswith("sqlite:///"), "운영 URL 이 그대로 남았다"
    assert os.environ["DATABASE_URL"] == out


def test_guard_leaves_a_non_production_url_alone(monkeypatch):
    """이미 sqlite 면 건드리지 않는다 - 테스트가 지정한 경로를 뺏으면 안 된다."""
    import _guard

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/mine.db")
    assert _guard.install() == "sqlite:////tmp/mine.db"
