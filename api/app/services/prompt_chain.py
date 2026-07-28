"""
곁눈(Gyeotnun) - 질문형 가이드 LLM
담당: 김태희

★ 이 모듈이 곁눈의 심장입니다. ★

곁눈은 "이건 가짜입니다"라고 **판정하지 않습니다.**
대신 사용자가 스스로 확인할 수 있도록 **질문만** 건넵니다.

판정을 대신해 주면 사용자는 AI에 의존하게 되고,
다음 번 비슷한 메시지를 받았을 때 또 물어봐야 합니다.
질문을 건네면 확인하는 절차가 몸에 남습니다.

────────────────────────────────────────────────────────────
[설계 원칙]
1. 단정 금지   : "진짜/가짜/사기/피싱입니다" 같은 결론 문장 생성 금지.
2. 단계 진행   : 출처 → 게시시점 → 게시자 → 근거 → 긴급성 압박 5단계.
3. 시니어 화법 : 짧고 쉬운 존댓말. 한 문장 25자 내외. 한 번에 질문 1~2개.
4. 근거는 링크 : 검색으로 찾은 것만 링크로 제시. LLM이 내용을 지어내지 않는다.
5. 못 찾음도 신호 : 공식 출처에서 못 찾았다면 그 사실 자체를 확인 신호로 안내.
────────────────────────────────────────────────────────────

API 키가 없으면(`settings.has_anthropic == False`) 목업 질문을 반환합니다.
개발 초기에 팀원 전원이 키 없이 프론트/백엔드를 붙일 수 있게 하기 위함입니다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_PROMPT_V0",
    "STAGES",
    "generate_questions",
    "contains_verdict_phrase",
]


# ============================================================
# 단계 정의
# ============================================================
STAGES: list[dict[str, str]] = [
    {
        "key": "source",
        "label": "출처 확인",
        "goal": "이 정보가 어디에서 왔는지, 공식 기관 채널인지 사용자가 직접 확인하게 한다.",
    },
    {
        "key": "timing",
        "label": "게시 시점 확인",
        "goal": "언제 올라온 글인지, 신청 기간이 이미 지난 오래된 글은 아닌지 확인하게 한다.",
    },
    {
        "key": "publisher",
        "label": "게시자 확인",
        "goal": "누가 보냈는지, 실제 기관 이름·연락처와 일치하는지 확인하게 한다.",
    },
    {
        "key": "basis",
        "label": "근거 확인",
        "goal": "금액·조건·대상 같은 숫자가 공식 안내와 같은지 확인하게 한다.",
    },
    {
        "key": "urgency",
        "label": "긴급성 압박 확인",
        "goal": "'오늘까지', '지금 안 하면 손해' 같은 재촉이 있는지 스스로 눈치채게 한다.",
    },
    {
        "key": "wrap",
        "label": "판단 정리",
        "goal": "확인한 내용을 짚어주고, 판단은 사용자가 직접 내리도록 넘긴다.",
    },
]


# ============================================================
# 시스템 프롬프트 v0
# ============================================================
SYSTEM_PROMPT_V0 = """\
당신은 '곁눈'이라는 이름의 정보 확인 코치입니다.
주 사용자는 60~80대 어르신입니다.

# 당신의 역할
어르신이 받은 메시지가 믿을 만한지 **당신이 판단해 주는 것이 아닙니다.**
어르신이 **스스로 확인할 수 있도록 질문을 건네는 것**이 당신의 유일한 역할입니다.

판단은 언제나 어르신의 몫입니다. 당신은 확인 절차를 안내할 뿐입니다.

# 절대 규칙 (위반 시 응답 전체가 폐기됩니다)

1. **결론을 말하지 마십시오.**
   금지 표현: "가짜입니다", "진짜입니다", "사기입니다", "피싱입니다",
   "속으신 겁니다", "믿으셔도 됩니다", "위험합니다", "안전합니다",
   "사실이 아닙니다", "삭제하세요", "신고하세요", "절대 누르지 마세요"
   → 이런 문장은 어떤 형태로도 생성하지 마십시오.

2. **확인되지 않은 사실을 서술하지 마십시오.**
   당신은 검색 결과로 주어진 [근거 링크] 외의 어떤 정보도 알지 못합니다.
   기관 이름, 제도 이름, 금액, 신청 기간을 스스로 지어내지 마십시오.
   링크의 본문 내용을 요약하지 마십시오. 제목과 링크만 그대로 전달하십시오.

3. **질문은 한 번에 1개, 많아도 2개입니다.**
   어르신은 여러 질문을 한꺼번에 받으면 압도됩니다.

4. **한 문장은 25자 안팎으로 짧게, 쉬운 존댓말로.**
   어려운 말 금지: '검증', '진위', '출처 신뢰도', '크로스체크', '리터러시'
   쉬운 말 사용:   '어디서 왔는지', '누가 보냈는지', '언제 올라온 글인지'

5. **재촉하거나 겁주지 마십시오.**
   어르신을 불안하게 만들면 오히려 판단력이 떨어집니다.
   차분하고 다정한 말투를 유지하십시오.

# 단계별 질문 (순서대로 진행)

1단계 출처   : 이 글이 어디에서 왔는지 확인하도록 묻습니다.
               예) "이 글을 어디에서 받으셨는지 기억나시나요?"
2단계 시점   : 언제 올라온 글인지 확인하도록 묻습니다.
               예) "글에 날짜가 적혀 있는지 한 번 보아 주시겠어요?"
3단계 게시자 : 보낸 사람이 누구인지 확인하도록 묻습니다.
               예) "보낸 분이 평소 알고 지내던 분인가요?"
4단계 근거   : 금액이나 조건이 공식 안내와 같은지 묻습니다.
               예) "적혀 있는 금액이 어디에 나온 내용인지 적혀 있나요?"
5단계 긴급성 : 재촉하는 표현이 있는지 스스로 찾아보게 합니다.
               예) "'오늘까지'처럼 서두르라는 말이 있나요?"
6단계 정리   : 확인한 내용을 짚고, 판단을 어르신께 넘깁니다.
               예) "여기까지 함께 살펴보았습니다. 어떻게 느끼시나요?"

# 근거 제시 방법

[근거 링크]가 주어지면 제목과 주소만 그대로 보여 드리고,
"직접 눌러서 확인해 보시겠어요?"라고 권합니다.
내용을 대신 요약하거나 해석하지 마십시오.

# 공식 출처에서 찾지 못한 경우

"찾지 못했다"는 결과를 숨기지 말고 있는 그대로 알려 드리십시오.
다만 그것을 근거로 결론을 내리지는 마십시오.
찾지 못했다는 사실 자체가 어르신께 중요한 확인 신호가 됩니다.

예시 표현:
  "정부24에서 같은 이름으로 찾아보았는데, 나오지 않았습니다."
  "공식 안내에 없는 내용은 한 번 더 확인해 보시면 좋겠습니다."
  "혹시 주변에 여쭤볼 만한 분이 계신가요?"

# 출력 형식

반드시 아래 JSON만 출력하십시오. 다른 말은 덧붙이지 마십시오.

{
  "stage": "source|timing|publisher|basis|urgency|wrap",
  "questions": ["질문 1", "질문 2"],
  "hint": "질문을 왜 드리는지 한 문장 설명 (판정 아님, 생략 가능)",
  "is_final": false
}

'wrap' 단계에서는 is_final을 true로 하십시오.
"""


# ============================================================
# 판정문 가드
# ============================================================
_VERDICT_PATTERNS = [
    r"가짜", r"진짜", r"사기", r"피싱", r"보이스\s*피싱", r"스미싱",
    r"거짓", r"허위", r"조작",
    r"속으신", r"속은\s*것", r"당하신",
    r"믿으셔도", r"믿으시면\s*안", r"믿을\s*수\s*없",
    r"안전합니다", r"위험합니다", r"위험해",
    r"사실이\s*아닙니다", r"사실입니다",
    r"삭제하세요", r"신고하세요", r"차단하세요",
    r"누르지\s*마", r"클릭하지\s*마", r"입금하지\s*마",
]
_VERDICT_RE = re.compile("|".join(_VERDICT_PATTERNS))


def contains_verdict_phrase(text: str) -> bool:
    """
    단정형 판정 표현이 섞였는지 검사한다.

    LLM이 규칙을 어기고 결론을 내는 경우를 잡아내는 최종 방어선.
    True가 나오면 해당 응답을 버리고 목업 질문으로 대체한다.
    """
    return bool(_VERDICT_RE.search(text or ""))


def _sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """LLM 응답에서 판정문이 섞인 문장을 제거한다."""
    questions = [q for q in payload.get("questions", []) if not contains_verdict_phrase(q)]
    hint = payload.get("hint", "")
    if contains_verdict_phrase(hint):
        hint = ""

    payload["questions"] = questions[:2]
    payload["hint"] = hint
    return payload


# ============================================================
# 목업 응답 (API 키 없을 때 / 가드 위반 시 fallback)
# ============================================================
_MOCK_BY_STAGE: dict[str, dict[str, Any]] = {
    "source": {
        "stage": "source",
        "questions": [
            "이 글을 어디에서 받으셨는지 기억나시나요?",
            "단체 대화방에서 온 글인가요?",
        ],
        "hint": "어디에서 왔는지가 첫 번째 확인 지점입니다.",
        "is_final": False,
    },
    "timing": {
        "stage": "timing",
        "questions": ["글에 올라온 날짜가 적혀 있는지 한 번 보아 주시겠어요?"],
        "hint": "오래된 글이 다시 도는 경우가 있습니다.",
        "is_final": False,
    },
    "publisher": {
        "stage": "publisher",
        "questions": [
            "보낸 분이 평소 알고 지내시던 분인가요?",
            "글에 적힌 기관 이름이 정확히 무엇인가요?",
        ],
        "hint": "이름이 조금씩 다른 경우가 있어 한 글자씩 보시면 좋습니다.",
        "is_final": False,
    },
    "basis": {
        "stage": "basis",
        "questions": ["적혀 있는 금액이 어디에 나온 내용인지 함께 적혀 있나요?"],
        "hint": "숫자에는 보통 근거가 함께 적혀 있습니다.",
        "is_final": False,
    },
    "urgency": {
        "stage": "urgency",
        "questions": ["'오늘까지'처럼 서두르라는 말이 들어 있나요?"],
        "hint": "급하게 만드는 말이 있으면 한 번 쉬어가시면 좋습니다.",
        "is_final": False,
    },
    "wrap": {
        "stage": "wrap",
        "questions": ["여기까지 함께 살펴보았습니다. 어떻게 느끼시나요?"],
        "hint": "판단은 어르신께서 직접 내려 주시면 됩니다.",
        "is_final": True,
    },
}


def _mock_response(step: int, evidence: list[dict] | None) -> dict[str, Any]:
    """API 키가 없거나 호출에 실패했을 때 쓰는 목업 질문."""
    idx = max(0, min(step, len(STAGES) - 1))
    stage_key = STAGES[idx]["key"]
    payload = dict(_MOCK_BY_STAGE[stage_key])
    payload["questions"] = list(payload["questions"])

    # 공식 출처에서 못 찾은 경우 안내를 덧붙인다 ("못 찾음도 신호")
    if evidence is not None:
        official_found = any(e.get("is_official") and e.get("found") for e in evidence)
        if not official_found and stage_key in ("source", "basis"):
            payload["hint"] = (
                "정부24와 정책브리핑에서 같은 이름으로 찾아보았는데, 나오지 않았습니다. "
                "공식 안내에 없는 내용은 한 번 더 확인해 보시면 좋겠습니다."
            )

    payload["evidence"] = evidence or []
    payload["mocked"] = True
    return payload


# ============================================================
# 메인 진입점
# ============================================================
def generate_questions(
    masked_text: str,
    evidence: list[dict] | None = None,
    dialogue_log: list[dict] | None = None,
    step: int = 0,
) -> dict[str, Any]:
    """
    다음 단계 질문을 생성한다. **판정문은 생성하지 않는다.**

    Args:
        masked_text:  마스킹 완료된 의심정보 텍스트 (masking.mask_pii 통과본).
        evidence:     search.cross_check() 결과. 링크로만 제시된다.
                      [{"source_label": "정부24", "found": False, ...}, ...]
        dialogue_log: 지금까지의 대화. [{"role": "assistant"|"user", "content": "..."}]
        step:         현재 단계 인덱스 (0=출처 ... 5=정리).

    Returns:
        {
          "stage": "source",
          "questions": ["...", "..."],   # 1~2개
          "hint": "...",
          "evidence": [...],             # 링크 원본 그대로
          "is_final": False,
          "mocked": True/False           # 목업으로 생성되었는지
        }

    API 키가 없으면 목업을 반환한다 (예외를 던지지 않는다).
    데모 당일 API 장애에도 화면이 죽지 않도록 하는 것이 의도된 설계다.
    """
    evidence = evidence or []
    dialogue_log = dialogue_log or []

    if not settings.has_anthropic:
        logger.info("ANTHROPIC_API_KEY 없음 → 목업 질문 반환 (step=%s)", step)
        return _mock_response(step, evidence)

    try:
        import anthropic  # 지연 import (키 없는 환경에서 불필요한 로드 방지)

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

        user_content = _build_user_message(masked_text, evidence, step)
        messages: list[dict[str, Any]] = []

        # 이전 대화를 그대로 이어 붙인다 (역할 매핑)
        for turn in dialogue_log:
            role = "assistant" if turn.get("role") == "assistant" else "user"
            content = turn.get("content", "")
            if content:
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_content})

        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=800,
            temperature=0.3,          # 질문 생성이므로 낮게. 창작을 원하지 않는다.
            system=SYSTEM_PROMPT_V0,
            messages=messages,
        )

        raw = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        payload = _parse_json(raw)

        if payload is None:
            logger.warning("LLM 응답 JSON 파싱 실패 → 목업 fallback")
            return _mock_response(step, evidence)

        payload = _sanitize(payload)

        # 가드에 다 걸려 질문이 하나도 안 남으면 목업으로 대체
        if not payload.get("questions"):
            logger.warning("판정문 가드로 질문이 전부 제거됨 → 목업 fallback")
            return _mock_response(step, evidence)

        payload.setdefault("stage", STAGES[min(step, len(STAGES) - 1)]["key"])
        payload.setdefault("is_final", payload["stage"] == "wrap")
        payload["evidence"] = evidence
        payload["mocked"] = False
        return payload

    except Exception as exc:  # noqa: BLE001 - 데모 안정성 우선
        logger.exception("Claude 호출 실패 → 목업 fallback: %s", exc)
        return _mock_response(step, evidence)


# ============================================================
# 내부 헬퍼
# ============================================================
def _build_user_message(masked_text: str, evidence: list[dict], step: int) -> str:
    """LLM에 넘길 유저 메시지를 조립한다."""
    idx = max(0, min(step, len(STAGES) - 1))
    stage = STAGES[idx]

    lines = [
        "[어르신이 받은 메시지] (개인정보는 이미 가려져 있습니다)",
        masked_text or "(텍스트를 읽지 못했습니다)",
        "",
        f"[이번 단계] {idx + 1}단계 - {stage['label']}",
        f"[이번 단계 목표] {stage['goal']}",
        "",
    ]

    if evidence:
        lines.append("[근거 링크] (아래 목록에 있는 것만 사용하십시오. 내용 요약 금지)")
        for e in evidence:
            if e.get("found"):
                lines.append(
                    f"- [{e.get('source_label', e.get('source', ''))}] "
                    f"{e.get('title', '')} | {e.get('url', '')} | {e.get('published_at', '')}"
                )
            else:
                lines.append(
                    f"- [{e.get('source_label', e.get('source', ''))}] 검색했으나 결과 없음"
                )
        lines.append("")
        official_found = any(e.get("is_official") and e.get("found") for e in evidence)
        if not official_found:
            lines.append(
                "[중요] 공식 출처(정부24·정책브리핑)에서 확인되지 않았습니다. "
                "이 사실을 그대로 알려 드리되, 결론을 내리지는 마십시오."
            )
            lines.append("")
    else:
        lines.append("[근거 링크] 없음. 링크를 지어내지 마십시오.")
        lines.append("")

    lines.append("위 내용을 바탕으로 이번 단계의 질문을 JSON으로만 출력하십시오.")
    return "\n".join(lines)


def _parse_json(raw: str) -> dict[str, Any] | None:
    """LLM 응답에서 JSON 객체를 추출한다. 코드펜스가 섞여 있어도 처리."""
    if not raw:
        return None

    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
