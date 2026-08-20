"""판단 행동 로그(judgment_logs) 시험 (2026-08-20).

무엇을 지키는가
  1) ★★ 개인정보 - 자유 텍스트가 들어갈 자리가 **없다**
     (a) 표에 Text 컬럼이 없고, 문자열 컬럼은 전부 짧은 코드값용이다
     (b) 허용 목록 밖의 값은 **잘라 넣지 않고 버린다**
     (c) 원문 device_id 는 어디에도 남지 않는다
  2) NULL 은 '아니오'가 아니라 '측정하지 않음'이다 - 집계가 NULL 을 0으로 세지 않는다
  3) 계측 실패가 사용자 흐름을 막지 않는다
  4) ★ Pydantic 스키마에 새 필드가 실제로 선언돼 있다
     (2026-08-05 source_url·2026-08-15 public_domain 이 같은 이유로 조용히 탈락했다)
  5) ★ 위 (a) 가 **실패해야 할 때 실패하는지** 스스로 시험한다
     - 실패를 본 적 없는 초록불은 의미가 없다(CLAUDE.md)
"""
from __future__ import annotations

import datetime as _dt

import pytest
from sqlalchemy import String, Text

from models.db import JudgmentLog, SessionLocal
from models.schemas import DialogueRequest, TrainingResultIn, VerdictRequest
from services import judgment_log


@pytest.fixture(autouse=True)
def _clean_table():
    db = SessionLocal()
    try:
        db.query(JudgmentLog).delete()
        db.commit()
    finally:
        db.close()
    yield


def _row(key: str) -> JudgmentLog | None:
    db = SessionLocal()
    try:
        return db.get(JudgmentLog, key)
    finally:
        db.close()


# ══════════════════════════════════════════════ 1. 개인정보 - 자유 텍스트가 없다

# ★ 이 표에서 허용하는 문자열 컬럼과 그 최대 길이.
#   전부 '짧은 코드값' 아니면 '해시/식별자'다. 여기 없는 문자열 컬럼이 새로 생기면
#   아래 시험이 실패한다 - 자유 텍스트가 슬쩍 들어오는 것을 막는 자리다.
_ALLOWED_STRING_COLUMNS = {
    "session_id": 64,      # 임의 UUID (개인정보 아님)
    "user_ref": 64,        # sha256 hex = 64자
    "session_type": 16,    # baseline|training|posttest
    "input_type": 16,      # photo|link|voice|text
    "decision": 16,        # apply|share|hold|not_apply|ask_family
    "misjudge_tag": 32,    # tagger 의 오판 유형 코드
    "card_id": 40,         # card_xxx
    "card_result": 16,     # correct|wrong|skipped
}


def _string_columns(model) -> dict:
    return {c.name: c for c in model.__table__.columns
            if isinstance(c.type, (String, Text))}


def test_no_free_text_columns():
    """★★ 자유 텍스트가 들어갈 컬럼이 없어야 한다."""
    cols = _string_columns(JudgmentLog)
    unknown = set(cols) - set(_ALLOWED_STRING_COLUMNS)
    assert not unknown, (
        f"judgment_logs 에 허가되지 않은 문자열 컬럼이 생겼다: {sorted(unknown)}. "
        "자유 텍스트(입력한 글·답변·URL)를 담으려는 것이라면 넣지 말 것 - "
        "models/db.py JudgmentLog 머리말 참고. 짧은 코드값이라면 "
        "_ALLOWED_STRING_COLUMNS 에 최대 길이와 함께 추가하고 이유를 적을 것."
    )
    for name, col in cols.items():
        assert not isinstance(col.type, Text), f"{name} 이 Text 다 - 자유 텍스트가 들어간다"
        assert col.type.length == _ALLOWED_STRING_COLUMNS[name], (
            f"{name} 의 길이가 {col.type.length} 로 바뀌었다 "
            f"(기대 {_ALLOWED_STRING_COLUMNS[name]}). 길이를 늘렸다면 왜 늘렸는지 확인할 것 - "
            "길이가 늘어나는 것이 자유 텍스트가 들어오는 첫 신호다."
        )


def test_guard_itself_fails_when_free_text_column_added():
    """★ 자기시험 - 위 가드가 **실패해야 할 때 실패하는가.**

    실제 표를 오염시키지 않고, 같은 검사 논리에 Text 컬럼이 있는 가짜 표를 넣어 본다.
    """
    from sqlalchemy import Column, Integer
    from sqlalchemy.orm import declarative_base

    FakeBase = declarative_base()

    class _Bad(FakeBase):                        # noqa: D401 - 시험용 가짜 표
        __tablename__ = "_bad_judgment_logs"
        session_id = Column(String(64), primary_key=True)
        user_note = Column(Text)                 # ← 자유 텍스트
        n = Column(Integer)

    cols = _string_columns(_Bad)
    unknown = set(cols) - set(_ALLOWED_STRING_COLUMNS)
    assert unknown == {"user_note"}, "가드가 자유 텍스트 컬럼을 못 잡았다 - 가드가 고장났다"
    assert isinstance(cols["user_note"].type, Text)


def test_free_text_is_dropped_not_truncated():
    """★ 허용 목록 밖의 값은 **잘라 넣지 않고 버린다.**

    자르면 자유 텍스트의 앞부분이 그대로 남는다("어머니 통장 비밀번호가..." → "어머니 통장 비").
    """
    leak = "어머니께 010-1234-5678 로 전화가 왔는데 통장 비밀번호를 물어봤어요"
    judgment_log.start("s_drop", check_id="chk_x", device_id="dev1",
                       input_type=leak, session_type=leak)
    r = _row("s_drop")
    assert r is not None
    assert r.input_type is None, "허용 목록 밖 input_type 이 저장됐다"
    assert r.session_type is None, "허용 목록 밖 session_type 이 저장됐다"

    judgment_log.decided("s_drop", check_id="chk_x", decision=leak)
    judgment_log.card_answered("s_drop", card_id=None, result=leak)
    r = _row("s_drop")
    assert r.decision is None and r.card_result is None
    # 표 전체를 훑어 원문 조각이 어디에도 없는지 본다
    values = " ".join(str(v) for v in vars(r).values() if v is not None)
    for fragment in ("어머니", "010-", "비밀번호"):
        assert fragment not in values, f"원문 조각 '{fragment}' 이 표에 남았다"


def test_device_id_is_hashed_not_stored():
    """★ 원문 device_id 는 어디에도 남지 않는다. 기존 해시 방식과 값이 같아야 한다."""
    from services import check_store

    judgment_log.start("s_hash", check_id="chk_h", device_id="device-ABC", input_type="image")
    r = _row("s_hash")
    assert r.user_ref == check_store.hash_device("device-ABC"), \
        "check_store 와 다른 해시를 쓰면 같은 사람이 두 사람으로 세어진다"
    assert r.user_ref != "device-ABC"
    assert len(r.user_ref) == 64


# ══════════════════════════════════════════════ 2. NULL 은 '측정하지 않음'이다

def test_unreported_checks_stay_null_not_false():
    """★★ 보고하지 않은 확인 항목은 False(=확인 안 함)가 아니라 NULL 이다."""
    judgment_log.start("s_null", check_id="chk_n", device_id="d", input_type="text")
    judgment_log.decided("s_null", check_id="chk_n", decision="hold")
    r = _row("s_null")
    assert r.checked_source is None, "보고하지 않은 것이 False 로 저장됐다"
    assert r.checked_author is None and r.checked_date is None and r.checked_condition is None
    assert r.check_count is None, "아무것도 보고되지 않았는데 check_count 가 0으로 세어졌다"


def test_reported_checks_are_counted():
    judgment_log.start("s_cnt", check_id="chk_c", device_id="d", input_type="text")
    judgment_log.decided("s_cnt", check_id="chk_c", decision="not_apply",
                         checked_source=True, checked_author=False,
                         checked_date=True, checked_condition=False)
    r = _row("s_cnt")
    assert r.check_count == 2
    assert r.checked_author is False, "보고된 False 는 False 로 남아야 한다(NULL 아님)"


def test_summary_excludes_nulls_from_samples():
    """★ 집계가 NULL 을 0으로 세지 않는다. 표본 수를 함께 돌려준다."""
    judgment_log.start("s1", check_id="c1", device_id="d", input_type="text")
    judgment_log.start("s2", check_id="c2", device_id="d", input_type="text")
    judgment_log.decided("s1", check_id="c1", decision="apply", checked_source=True)
    judgment_log.decided("s2", check_id="c2", decision="hold")     # 미보고

    db = SessionLocal()
    try:
        rows = db.query(JudgmentLog).all()
    finally:
        db.close()
    out = judgment_log.summarize(rows)
    assert out["total_sessions"] == 2
    # 보고한 1건만 표본이다. 2건으로 세면 비율이 0.5 로 반토막 난다.
    assert out["checked_rates"]["checked_source_sample"] == 1
    assert out["checked_rates"]["checked_source"] == 1.0
    assert out["decisions"] == {"apply": 1, "hold": 1}


# ══════════════════════════════════════════════ 3. 기록 지점 동작

def test_session_key_falls_back_to_check_id():
    """★ 프론트가 session_id 를 안 보내도 기록이 쌓인다."""
    assert judgment_log.session_key(None, "chk_abc") == "chk:chk_abc"
    assert judgment_log.session_key("s_real", "chk_abc") == "s_real"
    assert judgment_log.session_key(None, None) is None


def test_questions_shown_counts_and_opened_from_answer():
    judgment_log.start("s_q", check_id="chk_q", device_id="d", input_type="text")
    judgment_log.question_shown("s_q", check_id="chk_q", answered=False)   # 1턴: 답 없음
    r = _row("s_q")
    assert r.questions_shown == 1
    assert r.question_opened is None, "답을 안 했으면 '열었다'고 단정하지 않는다"

    judgment_log.question_shown("s_q", check_id="chk_q", answered=True)    # 2턴: 답함
    r = _row("s_q")
    assert r.questions_shown == 2
    assert r.question_opened is True

    judgment_log.question_shown("s_q", check_id="chk_q", answered=False)   # 3턴
    assert _row("s_q").question_opened is True, "한 번 연 사실이 다음 턴에 지워지면 안 된다"


def test_client_opened_flag_wins():
    judgment_log.start("s_o", check_id="chk_o", device_id="d", input_type="text")
    judgment_log.question_shown("s_o", check_id="chk_o", answered=False, opened=True)
    assert _row("s_o").question_opened is True


def test_time_to_decision_is_recorded():
    judgment_log.start("s_t", check_id="chk_t", device_id="d", input_type="text")
    db = SessionLocal()
    try:                                     # 세션 시작을 30초 전으로 되돌린다
        row = db.get(JudgmentLog, "s_t")
        row.created_at = _dt.datetime.utcnow() - _dt.timedelta(seconds=30)
        db.commit()
    finally:
        db.close()
    judgment_log.decided("s_t", check_id="chk_t", decision="apply", misjudge_tag="title_dependent")
    r = _row("s_t")
    assert 29 <= r.time_to_decision <= 40
    assert r.misjudge_tag == "title_dependent"


def test_existing_session_is_not_clobbered():
    """★ 같은 session_id 로 두 번째 자극이 와도 첫 판단을 덮어쓰지 않는다."""
    judgment_log.start("s_dup", check_id="chk_1", device_id="d", input_type="text")
    judgment_log.decided("s_dup", check_id="chk_1", decision="apply")
    judgment_log.start("s_dup", check_id="chk_2", device_id="d", input_type="link")
    r = _row("s_dup")
    assert r.decision == "apply", "두 번째 start 가 첫 판단을 지웠다"
    assert r.input_type == "text"


def test_card_result_opens_session_without_check():
    """훈련만 한 세션도 기록된다(확인 없이 시작될 수 있다)."""
    assert judgment_log.card_answered("s_card", card_id="card_01", result="correct",
                                      device_id="d", session_type="posttest") is True
    r = _row("s_card")
    assert r.card_id == "card_01" and r.card_result == "correct"
    assert r.session_type == "posttest"


def test_card_result_requires_session_id():
    """★ 이 경로는 check_id 대체 키를 쓸 수 없다 - 조용히 만들지 않고 0을 돌려준다."""
    assert judgment_log.card_answered(None, card_id="c", result="correct") is False


def test_input_type_image_maps_to_photo():
    judgment_log.start("s_img", check_id="chk_i", device_id="d", input_type="image")
    assert _row("s_img").input_type == "photo"


# ══════════════════════════════════════════════ 4. 계측이 흐름을 막지 않는다

def test_recording_failure_never_raises(monkeypatch):
    """★ DB 가 죽어도 예외가 라우터로 올라가면 안 된다."""
    def _boom():
        raise RuntimeError("DB down")

    monkeypatch.setattr(judgment_log, "SessionLocal", _boom)
    # 어느 하나라도 예외를 던지면 이 시험이 실패한다
    judgment_log.start("s_boom", check_id="c", device_id="d", input_type="text")
    judgment_log.question_shown("s_boom", check_id="c", answered=True)
    judgment_log.decided("s_boom", check_id="c", decision="apply")
    assert judgment_log.card_answered("s_boom", card_id="c", result="correct") is False


def test_question_shown_ignores_unknown_session():
    """start 가 안 열린 세션에는 행을 만들지 않는다(고아 행 방지)."""
    judgment_log.question_shown("s_ghost", check_id="chk_g", answered=True)
    assert _row("s_ghost") is None


# ══════════════════════════════════════════════ 5. ★ 스키마에 필드가 선언돼 있다

def test_schema_declares_the_new_fields():
    """★★ 2026-08-05 source_url·2026-08-15 public_domain 이 같은 이유로 조용히 탈락했다.

    Pydantic 은 선언되지 않은 필드를 **에러 없이 버린다.** 라우터가 값을 읽어도
    항상 None 이라 기록이 전부 NULL 로 쌓인다 - 화면도 로그도 아무 말을 하지 않는다.
    """
    for field in ("session_id", "question_opened"):
        assert field in DialogueRequest.model_fields, f"DialogueRequest 에 {field} 선언 누락"
    for field in ("session_id", "checked_source", "checked_author",
                  "checked_date", "checked_condition"):
        assert field in VerdictRequest.model_fields, f"VerdictRequest 에 {field} 선언 누락"
    for field in ("session_id", "card_id", "result", "session_type"):
        assert field in TrainingResultIn.model_fields, f"TrainingResultIn 에 {field} 선언 누락"

    # 실제로 값이 통과하는지도 본다(선언만 있고 타입이 틀리면 여기서 걸린다)
    v = VerdictRequest(decision="hold", session_id="s", checked_source=True, checked_date=False)
    assert v.checked_source is True and v.checked_date is False
    assert v.checked_author is None, "보내지 않은 값이 False 로 채워지면 안 된다"


def test_all_db_columns_are_reachable_from_a_recording_point():
    """★ 컬럼만 만들고 채우는 곳이 없는 상태를 막는다.

    events 표의 교훈이다 - 컬럼은 있는데 아무도 안 넣으면 집계가 조용히 0이 된다.
    """
    judgment_log.start("s_all", check_id="chk_a", device_id="d",
                       input_type="link", session_type="baseline")
    judgment_log.question_shown("s_all", check_id="chk_a", answered=True)
    judgment_log.decided("s_all", check_id="chk_a", decision="share",
                         misjudge_tag="urgency_driven", checked_source=True,
                         checked_author=True, checked_date=True, checked_condition=True)
    judgment_log.card_answered("s_all", card_id="card_9", result="wrong")

    r = _row("s_all")
    for col in JudgmentLog.__table__.columns:
        assert getattr(r, col.name) is not None, (
            f"{col.name} 을 채우는 기록 지점이 없다 - 컬럼만 있고 늘 NULL 이면 "
            "집계가 조용히 0이 된다"
        )
    assert r.check_count == 4 and r.decision == "share"
