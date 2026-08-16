"""확인 기록 저장소 (DB) 검증 (2026-08-16, #33 3단계).

실행: cd api && python -m pytest tests/test_check_store.py -q

■ 이 파일이 지키는 것
  저장소를 프로세스 메모리에서 DB 로 옮기면서 **깨지면 안 되는 것 두 가지**가 있다.
    1) 소유자 대조(IDOR 방지)가 그대로 막는가
    2) ★ device_id 원문이 DB 에 저장되지 않는가
       README 7장이 "device_id 는 SHA-256 해시만 사용"이라고 못박고 있다.
       메모리 dict 시절엔 원문을 들고 있었지만 프로세스 안에서만 살다 사라졌다.
       DB 로 옮기며 원문을 넣으면 그 서술이 그날로 거짓이 된다.

  conftest.py 가 DATABASE_URL 을 임시 SQLite 로 덮으므로 운영 DB 를 건드리지 않는다.
"""
from __future__ import annotations

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import Check, SessionLocal  # noqa: E402
from routers.checks import require_owner  # noqa: E402
from services import check_store  # noqa: E402

DEVICE = "device-uuid-abcdef-0123456789"


def _make(check_id: str, device_id=DEVICE, text="마스킹된 본문"):
    check_store.create(
        check_id, device_id=device_id, input_type="text", masked_text=text,
        masked_items=[], detected_domain="policy", status="extracted",
    )


# ──────────────────────────────────────────── 저장·조회
def test_create_and_get_roundtrip():
    _make("chk_roundtrip")
    got = check_store.get("chk_roundtrip")
    assert got["masked_text"] == "마스킹된 본문"
    assert got["domain"] == "policy"
    assert got["history"] == []


def test_get_missing_returns_none():
    assert check_store.get("chk_does_not_exist") is None


# ──────────────────────────────────────────── ★ 개인정보
def test_device_id_is_never_stored_in_plaintext():
    """★★ 원문 device_id 가 DB 어디에도 없어야 한다. ★★

    컬럼 하나만 보는 게 아니라 **행 전체를 문자열로 만들어** 원문이 섞여 있는지 본다.
    나중에 누가 컬럼을 하나 더 만들어 원문을 흘리면 여기서 걸린다.
    """
    _make("chk_privacy")
    db = SessionLocal()
    try:
        row = db.get(Check, "chk_privacy")
        dump = " ".join(str(getattr(row, c.name)) for c in row.__table__.columns)
    finally:
        db.close()
    assert DEVICE not in dump, "device_id 원문이 DB 에 저장됐다"
    assert hashlib.sha256(DEVICE.encode()).hexdigest() in dump, "해시가 저장돼 있어야 한다"


def test_hash_device_matches_the_project_convention():
    """events·error_logs·users 와 같은 방식이어야 한다 - 규칙이 갈리면 안 된다."""
    assert check_store.hash_device(DEVICE) == hashlib.sha256(DEVICE.encode()).hexdigest()
    assert check_store.hash_device(None) is None
    assert check_store.hash_device("") is None


# ──────────────────────────────────────────── 소유자 대조 (IDOR)
def test_owner_passes():
    _make("chk_owner")
    assert require_owner("chk_owner", DEVICE)["masked_text"] == "마스킹된 본문"


@pytest.mark.parametrize("requester", [None, "", "anonymous", "다른-기기-uuid"])
def test_non_owner_is_rejected_with_404(requester):
    """★ 없는 id · 남의 id · 미제공 · 익명을 **전부 같은 404** 로 막는다.

    구분하면 check_id 존재 여부가 새어나간다.
    """
    _make("chk_idor")
    with pytest.raises(Exception) as e:
        require_owner("chk_idor", requester)
    assert getattr(e.value, "status_code", None) == 404


def test_anonymous_owner_record_is_readable_by_nobody():
    """익명으로 만들어진 기록은 익명 요청자에게도 열리지 않는다."""
    _make("chk_anon", device_id="anonymous")
    for requester in ("anonymous", DEVICE, "아무거나"):
        with pytest.raises(Exception) as e:
            require_owner("chk_anon", requester)
        assert getattr(e.value, "status_code", None) == 404


def test_missing_check_and_wrong_owner_are_indistinguishable():
    _make("chk_exists")
    codes = []
    for cid, dev in (("chk_exists", "남의-기기"), ("chk_없음", DEVICE)):
        with pytest.raises(Exception) as e:
            require_owner(cid, dev)
        codes.append(e.value.detail)
    assert codes[0] == codes[1], "존재 여부가 응답으로 새어나간다"


# ──────────────────────────────────────────── 대화 이력
def test_append_history_persists():
    """★ JSON 컬럼은 제자리 append 를 SQLAlchemy 가 못 알아챈다.

    새 리스트를 대입해야 UPDATE 가 나간다. 그걸 안 하면 이력이 **조용히** 안 쌓인다.
    """
    _make("chk_hist")
    check_store.append_history("chk_hist", ["질문1: 어디서 오셨나요?"])
    check_store.append_history("chk_hist", ["사용자 답변: 문자로 왔어요", "질문2: 확인하셨나요?"])
    assert check_store.get("chk_hist")["history"] == [
        "질문1: 어디서 오셨나요?", "사용자 답변: 문자로 왔어요", "질문2: 확인하셨나요?"]


def test_append_history_on_missing_check_is_silent():
    check_store.append_history("chk_없는건", ["질문1: ..."])   # 예외가 나면 안 된다


# ──────────────────────────────────────────── 태깅
def test_save_tagging_stores_hash_not_raw_device_id():
    _make("chk_tag")
    check_store.save_tagging("chk_tag", device_id=DEVICE, decision="hold",
                             error_type="title_dependent", confidence=0.8)
    from models.db import Tagging
    db = SessionLocal()
    try:
        row = db.query(Tagging).filter(Tagging.check_id == "chk_tag").one()
        dump = " ".join(str(getattr(row, c.name)) for c in row.__table__.columns)
    finally:
        db.close()
    assert DEVICE not in dump
    assert check_store.hash_device(DEVICE) in dump


# ──────────────────────────────────────────── purge
def test_purge_deletes_children_before_parent():
    """★ evidence·taggings 가 checks 를 FK 로 물고 있다. 순서가 틀리면 통째로 실패한다."""
    import datetime as dt

    from models.db import Evidence
    from tools.purge_old_records import purge

    _make("chk_old")
    check_store.save_tagging("chk_old", device_id=DEVICE, decision="hold",
                             error_type="title_dependent", confidence=0.5)
    db = SessionLocal()
    try:
        db.add(Evidence(check_id="chk_old", verdict_hint="needs_check"))
        row = db.get(Check, "chk_old")
        row.created_at = dt.datetime.utcnow() - dt.timedelta(days=200)   # 오래된 것으로 만든다
        db.commit()
    finally:
        db.close()

    result = purge(retention_days=90)

    assert result["checks"] >= 1
    assert result["taggings"] >= 1
    assert result["evidence"] >= 1
    assert check_store.get("chk_old") is None


def test_purge_keeps_recent_records():
    _make("chk_recent")
    from tools.purge_old_records import purge
    purge(retention_days=90)
    assert check_store.get("chk_recent") is not None
