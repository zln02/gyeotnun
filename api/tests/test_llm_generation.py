"""
곁눈(Gyeotnun) - 질문 생성 루프 테스트
실행: cd api && python -m pytest tests/ -q

두 종류가 들어 있다.
  1) 오프라인: Claude 호출을 스텁으로 갈아 끼워 '재생성 루프'와 '폴백'을 검증한다.
     API 키 없이 항상 돈다. 가드레일이 실제로 막는지 보는 테스트다.
  2) 라이브: 진짜 Claude 를 호출한다. ANTHROPIC_API_KEY 가 없으면 skip 된다.

★ 판정 억제 규칙은 여기서도 완화하지 않는다.
  생성 결과가 validate_question 을 통과하지 못하면 테스트가 깨져야 한다.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import MissingKeyError, settings                # noqa: E402
from services import prompt_chain as pc                     # noqa: E402
from services.prompt_chain import ValidationError           # noqa: E402

ALLOWED_REF = "https://basicpension.mohw.go.kr/"
REFERENCES = [{"title": "기초연금 안내", "url": ALLOWED_REF, "publisher": "보건복지부"}]
SIGNALS = [{"key": "urgency_pressure", "label": "서두르게 만드는 표현이 있습니다."}]
TEXT = "★긴급★ 정부에서 65세 이상 어르신께 100만원 지급! 오늘까지 신청하세요"


def _payload(question: str, why: str = "확인해 보면 판단이 쉬워집니다.", refs=None, options=None):
    """Claude 가 돌려줄 법한 응답 한 벌."""
    return {
        "question": question,
        "why": why,
        "evidence_refs": refs if refs is not None else [ALLOWED_REF],
        "options": options if options is not None else [
            {"id": "found", "label": "찾았어요"},
            {"id": "not_found", "label": "찾지 못하겠어요"},
        ],
        "is_final": False,
    }


GOOD_Q = "이 글에 적힌 금액은 어디에서 발표한 내용일까요? 기관 이름을 한번 찾아봐 주세요."


@pytest.fixture
def fake_llm(monkeypatch):
    """_call_claude 를 스텁으로 갈아 끼우고 통계를 초기화한다."""
    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "test-key-not-real")

    def _install(payloads):
        seq = list(payloads)
        calls = {"n": 0}

        def _stub(messages):
            calls["n"] += 1
            p = seq[min(calls["n"] - 1, len(seq) - 1)]
            return p, "{}"

        monkeypatch.setattr(pc, "_call_claude", _stub)
        return calls

    return _install


# ==================================================== 1) 폴백
def test_fallback_question_passes_validation():
    """★ 폴백 문장도 예외 없이 곁눈의 원칙을 지켜야 한다."""
    r = pc.validate_question(pc.FALLBACK_QUESTION, [ALLOWED_REF])
    assert r.sentence_count <= pc.MAX_SENTENCES
    assert pc.find_forbidden(pc.FALLBACK_QUESTION) is None
    assert pc.find_forbidden(pc.FALLBACK_WHY) is None
    for opt in pc.FALLBACK_OPTIONS:
        assert pc.find_forbidden(opt["label"]) is None


def test_falls_back_after_all_attempts_fail(fake_llm):
    """3회 모두 판정어가 나오면 폴백으로 내려가고, 그 사실이 집계된다."""
    fake_llm([_payload("이 글은 가짜입니다.")])

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert vq.fallback is True
    assert vq.question == pc.FALLBACK_QUESTION
    stats = pc.guardrail_stats()
    assert stats["attempts"] == pc.MAX_ATTEMPTS == 3
    assert stats["regenerated"] == 3
    assert stats["forbidden_word"] == 3
    assert stats["fallback"] == 1
    assert stats["block_rate"] == 1.0


# ==================================================== 2) 재생성 루프
def test_regenerates_on_forbidden_word(fake_llm):
    """판정어가 섞이면 다시 생성하고, 통과한 답을 돌려준다."""
    calls = fake_llm([_payload("이건 사기입니다."), _payload(GOOD_Q)])

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert calls["n"] == 2
    assert vq.fallback is False
    assert vq.question == GOOD_Q
    stats = pc.guardrail_stats()
    assert stats["forbidden_word"] == 1
    assert stats["regenerated"] == 1


def test_regenerates_on_too_long(fake_llm):
    """2문장을 넘기면 재생성한다."""
    fake_llm([_payload("첫 문장. 둘째 문장. 셋째 문장."), _payload(GOOD_Q)])

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert vq.question == GOOD_Q
    assert pc.guardrail_stats()["too_long"] == 1


def test_regenerates_on_bad_ref(fake_llm):
    """★ 허용 목록 밖 링크(지어낸 출처)는 재생성 신호다."""
    bad = _payload(GOOD_Q, refs=["https://fake-gov.example.com/notice"])
    fake_llm([bad, _payload(GOOD_Q)])

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert pc.guardrail_stats()["bad_ref"] == 1
    assert vq.evidence_refs == [ALLOWED_REF]
    assert "https://fake-gov.example.com/notice" not in vq.evidence_refs


def test_bad_ref_on_last_attempt_is_stripped_not_failed(fake_llm):
    """마지막 시도까지 링크가 이상하면, 링크만 빼고 질문은 살린다."""
    fake_llm([_payload(GOOD_Q, refs=["https://fake-gov.example.com/x"])])

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert vq.fallback is False
    assert vq.question == GOOD_Q
    assert vq.evidence_refs == []
    assert "https://fake-gov.example.com/x" in vq.dropped_refs


def test_api_error_is_retried(fake_llm, monkeypatch):
    """호출 자체가 실패해도 재시도하고, 그래도 안 되면 폴백한다."""
    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "test-key-not-real")

    def _boom(messages):
        raise RuntimeError("network down")

    monkeypatch.setattr(pc, "_call_claude", _boom)

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES)

    assert vq.fallback is True
    assert pc.guardrail_stats()["api_error"] == 3


# ==================================================== 3) why / 보기 문구도 검사한다
def test_forbidden_word_in_why_is_blocked():
    """★ 질문이 깨끗해도 why 에 판정이 새면 화면에서는 결국 판정이 된다."""
    with pytest.raises(ValidationError) as e:
        pc._screen_payload(_payload(GOOD_Q, why="이 글은 가짜라서 확인이 필요합니다."), [ALLOWED_REF])
    assert e.value.reason == "forbidden_word"


def test_forbidden_word_in_option_label_is_blocked():
    with pytest.raises(ValidationError):
        pc._screen_payload(
            _payload(GOOD_Q, options=[{"id": "a", "label": "사기인 것 같아요"}]),
            [ALLOWED_REF],
        )


def test_screen_payload_carries_why_and_options():
    vq = pc._screen_payload(_payload(GOOD_Q), [ALLOWED_REF])
    assert vq.why
    assert len(vq.options) == 2
    assert vq.evidence_refs == [ALLOWED_REF]


# ==================================================== 4) 키 없음 / 설정
def test_missing_key_raises_missing_key_error(monkeypatch):
    """키가 없으면 라우터가 501 로 바꿀 수 있는 예외를 던진다."""
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(MissingKeyError):
        pc.generate_question(TEXT, SIGNALS, REFERENCES)


def test_model_is_sonnet_5():
    assert pc.MODEL == "claude-sonnet-5"


def test_system_block_is_cached_and_long_enough():
    """★ 프롬프트 캐싱 설정이 실수로 빠지지 않도록 고정한다.

    Sonnet 5 의 최소 캐시 길이는 1024토큰이다. 실측 1396토큰이라 여유가 있지만,
    누가 few-shot 을 빼면 캐시가 조용히 꺼지므로 길이도 함께 지킨다.
    """
    blocks = pc._system_blocks()
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert "진위를 판정하지" in blocks[0]["text"]
    assert len(blocks[0]["text"]) > 1200      # 대략 1024토큰 이상을 보장하는 하한


# ==================================================== 5) 라이브 (키 있을 때만)
requires_key = pytest.mark.skipif(
    not settings.has_llm,
    reason="ANTHROPIC_API_KEY 가 없습니다. 실제 호출 테스트를 건너뜁니다.",
)


@requires_key
def test_live_generate_question_passes_guardrails():
    """★ 진짜 Claude 응답이 곁눈의 원칙을 지키는지 확인한다."""
    pc.reset_guardrail_stats()

    vq = pc.generate_question(TEXT, SIGNALS, REFERENCES, history=[])

    assert vq.question
    assert vq.sentence_count <= pc.MAX_SENTENCES
    assert pc.find_forbidden(vq.question) is None
    assert pc.find_forbidden(vq.why) is None
    # 지어낸 링크가 최종 응답에 남아 있으면 안 된다
    assert all(u == ALLOWED_REF for u in vq.evidence_refs)
    assert pc.guardrail_stats()["attempts"] >= 1


@requires_key
def test_live_no_references_means_no_invented_links():
    """★ 출처를 못 찾았을 때 링크를 지어내지 않는지 (가장 위험한 실패 모드)."""
    pc.reset_guardrail_stats()

    vq = pc.generate_question(TEXT, SIGNALS, references=[], history=[])

    assert vq.evidence_refs == []
    assert pc.find_forbidden(vq.question) is None


# ==================================================== 5) 비동기판 (2026-08-16, #33 2단계)
#
# ★★ 왜 이 묶음이 필요한가 ★★
#   agenerate_question 은 동기판과 **같은 _question_driver** 를 돌린다. 그래도
#   "같은 드라이버를 쓴다"는 주장을 코드 읽기로만 남겨 두지 않는다 - 언젠가 누가
#   비동기판만 손대면 그 순간 가드레일이 갈라지고, 원칙을 어긴 질문이 화면에 나간다.
#   그래서 **같은 입력에 같은 결과가 나오는지를 직접 단정한다.**
#
# pytest-asyncio 를 쓰지 않는다. asyncio.run 하나면 되고, 의존성을 늘리지 않는다.
import asyncio  # noqa: E402


@pytest.fixture
def fake_async_llm(monkeypatch):
    """_acall_claude 를 비동기 스텁으로 갈아 끼운다. fake_llm 과 같은 규약."""
    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "test-key-not-real")

    def _install(payloads):
        seq = list(payloads)
        calls = {"n": 0}

        async def _stub(messages):
            calls["n"] += 1
            return seq[min(calls["n"] - 1, len(seq) - 1)], "{}"

        monkeypatch.setattr(pc, "_acall_claude", _stub)
        return calls

    return _install


def test_async_falls_back_after_all_attempts_fail(fake_async_llm):
    """비동기판도 판정어 3연속이면 폴백으로 내려간다."""
    fake_async_llm([_payload("이 글은 가짜입니다.")])

    vq = asyncio.run(pc.agenerate_question(TEXT, SIGNALS, REFERENCES))

    assert vq.fallback is True
    assert vq.question == pc.FALLBACK_QUESTION
    stats = pc.guardrail_stats()
    assert stats["attempts"] == pc.MAX_ATTEMPTS == 3
    assert stats["forbidden_word"] == 3
    assert stats["fallback"] == 1


def test_async_regenerates_on_forbidden_word(fake_async_llm):
    calls = fake_async_llm([_payload("이건 사기입니다."), _payload(GOOD_Q)])

    vq = asyncio.run(pc.agenerate_question(TEXT, SIGNALS, REFERENCES))

    assert calls["n"] == 2
    assert vq.fallback is False
    assert vq.question == GOOD_Q
    assert pc.guardrail_stats()["forbidden_word"] == 1


def test_async_api_error_is_retried(fake_async_llm, monkeypatch):
    """호출이 터져도 비동기판이 같은 횟수만큼 재시도하고 폴백한다."""
    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "test-key-not-real")
    calls = {"n": 0}

    async def _boom(messages):
        calls["n"] += 1
        raise RuntimeError("연결 실패")

    monkeypatch.setattr(pc, "_acall_claude", _boom)

    vq = asyncio.run(pc.agenerate_question(TEXT, SIGNALS, REFERENCES))

    assert calls["n"] == pc.MAX_ATTEMPTS
    assert vq.fallback is True
    assert pc.guardrail_stats()["api_error"] == pc.MAX_ATTEMPTS


def test_async_missing_key_raises_missing_key_error(monkeypatch):
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(MissingKeyError):
        asyncio.run(pc.agenerate_question(TEXT, SIGNALS, REFERENCES))


@pytest.mark.parametrize("payloads", [
    [_payload(GOOD_Q)],                                   # 한 번에 통과
    [_payload("이건 사기입니다."), _payload(GOOD_Q)],        # 한 번 재생성
    [_payload("이 글은 가짜입니다.")],                       # 전부 실패 → 폴백
    [_payload(GOOD_Q, refs=["https://evil.example/x"])],   # 허용 밖 링크
])
def test_sync_and_async_agree(payloads, monkeypatch):
    """★ 같은 응답 열에 대해 동기·비동기 결과가 **완전히 같아야** 한다.

    질문·why·보기·링크·폴백 여부까지 본다. 여기가 깨지면 드라이버가 갈라진 것이다.
    """
    monkeypatch.setattr(pc.settings, "ANTHROPIC_API_KEY", "test-key-not-real")

    def _shape(vq):
        return (vq.question, vq.why, vq.evidence_refs, vq.options,
                vq.fallback, vq.dropped_refs, vq.is_final)

    seq = list(payloads)
    n = {"i": 0}

    def _sync_stub(messages):
        n["i"] += 1
        return seq[min(n["i"] - 1, len(seq) - 1)], "{}"

    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc, "_call_claude", _sync_stub)
    sync_out = _shape(pc.generate_question(TEXT, SIGNALS, REFERENCES))
    sync_stats = pc.guardrail_stats()

    n["i"] = 0

    async def _async_stub(messages):
        n["i"] += 1
        return seq[min(n["i"] - 1, len(seq) - 1)], "{}"

    pc.reset_guardrail_stats()
    monkeypatch.setattr(pc, "_acall_claude", _async_stub)
    async_out = _shape(asyncio.run(pc.agenerate_question(TEXT, SIGNALS, REFERENCES)))
    async_stats = pc.guardrail_stats()

    assert sync_out == async_out, "동기·비동기 결과가 다르다 - 가드레일이 갈라졌다"
    assert sync_stats == async_stats, "재생성 통계가 다르다 - 루프가 갈라졌다"
