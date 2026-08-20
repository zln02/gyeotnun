"""판단 행동 로그 — **기록 지점이 실제로 연결됐는지** HTTP 로 확인한다 (2026-08-20).

test_judgment_log.py 는 services/judgment_log.py 를 직접 부른다. 그것만으로는
"라우터가 그 함수를 실제로 부르는가"를 증명하지 못한다 - 서비스는 완벽한데 호출을
빠뜨린 상태가 그대로 통과한다. 그래서 여기서는 **엔드포인트를 실제로 두드린다.**

★ 운영 DB 를 쓰지 않는다. conftest.py 가 DATABASE_URL 을 임시 SQLite 로 돌려놓고,
  sqlite 가 아니면 수집 단계에서 멈춘다.
★ 외부 호출(LLM·검색)은 monkeypatch 로 끊는다. 이 파일이 재는 것은 판정 품질이
  아니라 **배선**이다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app
from models.db import JudgmentLog, SessionLocal
from services import judgment_log

PREFIX = settings.API_PREFIX


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean():
    db = SessionLocal()
    try:
        db.query(JudgmentLog).delete()
        db.commit()
    finally:
        db.close()
    yield


def _row(key: str):
    db = SessionLocal()
    try:
        return db.get(JudgmentLog, key)
    finally:
        db.close()


@pytest.fixture
def _no_external(monkeypatch):
    """dialogue 가 부르는 외부 의존(검색·LLM)을 끊는다."""
    from services import prompt_chain, search

    class _Ev:
        signals: list = []
        references: list = []
        verdict_hint = "needs_check"

    class _VQ:
        question = "이 안내를 어디서 보셨는지 확인해 볼까요?"
        why = "출처를 먼저 보면 판단이 쉬워집니다."
        evidence_refs: list = []
        options: list = []
        is_final = False
        fallback = False

    monkeypatch.setattr(search, "collect_evidence", lambda *a, **k: _Ev())

    async def _agen(**kwargs):
        return _VQ()

    monkeypatch.setattr(prompt_chain, "agenerate_question", _agen)
    yield


def test_create_check_opens_a_session(client):
    """POST /checks → 세션 행이 열린다."""
    r = client.post(f"{PREFIX}/checks", data={
        "device_id": "dev-route-1", "text": "무료로 지원금을 드립니다. 지금 신청하세요.",
        "session_id": "sess_route_1", "session_type": "baseline",
    })
    assert r.status_code == 200, r.text
    row = _row("sess_route_1")
    assert row is not None, "라우터가 judgment_log.start 를 부르지 않는다"
    assert row.input_type == "text"
    assert row.session_type == "baseline"
    assert row.user_ref == judgment_log.hash_device("dev-route-1")


def test_session_id_falls_back_to_check_id(client):
    """★ 프론트가 아직 session_id 를 안 보내도 기록이 쌓인다."""
    r = client.post(f"{PREFIX}/checks", data={"device_id": "dev-route-2", "text": "안내 문자입니다"})
    check_id = r.json()["check_id"]
    assert _row(f"chk:{check_id}") is not None, "대체 세션 키가 동작하지 않는다"


def test_dialogue_counts_questions(client, _no_external):
    client.post(f"{PREFIX}/checks", data={
        "device_id": "dev-route-3", "text": "지원금 신청 안내입니다", "session_id": "sess_route_3"})
    r = client.post(f"{PREFIX}/checks/{_only_check_id()}/dialogue", json={
        "turn": 1, "device_id": "dev-route-3", "session_id": "sess_route_3"})
    assert r.status_code == 200, r.text
    row = _row("sess_route_3")
    assert row.questions_shown == 1, "라우터가 judgment_log.question_shown 을 부르지 않는다"
    assert row.question_opened is None, "1턴에 답이 없으면 '열었다'고 단정하지 않는다"

    r = client.post(f"{PREFIX}/checks/{_only_check_id()}/dialogue", json={
        "turn": 2, "user_reply": "문자로 받았어요", "device_id": "dev-route-3",
        "session_id": "sess_route_3"})
    assert r.status_code == 200
    row = _row("sess_route_3")
    assert row.questions_shown == 2
    assert row.question_opened is True


def _only_check_id() -> str:
    """직전에 만든 확인 1건의 id (이 파일은 테스트마다 1건만 만든다)."""
    from models.db import Check
    db = SessionLocal()
    try:
        return db.query(Check).order_by(Check.created_at.desc()).first().id
    finally:
        db.close()


def test_verdict_records_decision_and_checks(client, monkeypatch):
    from services import tagger

    monkeypatch.setattr(tagger, "tag_error_type_llm", lambda *a, **k: ("title_dependent", 0.8))
    client.post(f"{PREFIX}/checks", data={
        "device_id": "dev-route-4", "text": "무료 지원금 신청 안내", "session_id": "sess_route_4"})
    r = client.post(f"{PREFIX}/checks/{_only_check_id()}/verdict", json={
        "decision": "hold", "device_id": "dev-route-4", "session_id": "sess_route_4",
        "checked_source": True, "checked_author": False, "checked_date": True,
    })
    assert r.status_code == 200, r.text
    row = _row("sess_route_4")
    assert row.decision == "hold", "라우터가 judgment_log.decided 를 부르지 않는다"
    assert row.misjudge_tag == "title_dependent"
    assert row.check_count == 2
    assert row.checked_condition is None, "보내지 않은 항목은 NULL 이어야 한다(False 아님)"
    assert row.time_to_decision is not None and row.time_to_decision >= 0


def test_training_result_records_card(client):
    r = client.post(f"{PREFIX}/training/result", json={
        "session_id": "sess_route_5", "card_id": "card_07",
        "result": "correct", "device_id": "dev-route-5", "session_type": "posttest"})
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 1}
    row = _row("sess_route_5")
    assert row.card_id == "card_07" and row.card_result == "correct"


def test_training_result_rejects_free_text_result(client):
    """★ 스키마가 자유 텍스트를 막는다(422). 저장 단계까지 가지 않는다."""
    r = client.post(f"{PREFIX}/training/result", json={
        "session_id": "s", "result": "어머니 계좌번호는 110-..."})
    assert r.status_code == 422


def test_summary_is_operator_only(client, monkeypatch):
    """★ 토큰 없이 열리면 안 된다 (events/summary·errors/summary 와 같은 게이트)."""
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")
    assert client.get(f"{PREFIX}/judgments/summary").status_code == 404

    monkeypatch.setattr(settings, "ADMIN_TOKEN", "tkn-for-test")
    assert client.get(f"{PREFIX}/judgments/summary").status_code == 404      # 토큰 없음
    r = client.get(f"{PREFIX}/judgments/summary", headers={"X-Admin-Token": "tkn-for-test"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_sessions"] == 0
    # ★ 표본 수가 응답에 실제로 실려 나오는지 (Pydantic 이 필드를 버리면 여기서 걸린다)
    assert "question_opened_sample" in body and "card_sample" in body


def test_summary_filters_by_session_type(client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "tkn-for-test")
    judgment_log.card_answered("s_base", card_id="c1", result="correct", session_type="baseline")
    judgment_log.card_answered("s_post", card_id="c2", result="wrong", session_type="posttest")
    h = {"X-Admin-Token": "tkn-for-test"}

    assert client.get(f"{PREFIX}/judgments/summary", headers=h).json()["total_sessions"] == 2
    only_post = client.get(f"{PREFIX}/judgments/summary?session_type=posttest", headers=h).json()
    assert only_post["total_sessions"] == 1
    assert only_post["card_correct_rate"] == 0.0
    assert only_post["card_sample"] == 1
