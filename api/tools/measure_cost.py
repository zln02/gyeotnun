"""
확인 요청 1건의 실제 처리 비용 측정 (2026-08-04, ROI 산출용)
실행: docker compose exec api python3 tools/measure_cost.py

★ 추정하지 않는다. 실제 API 를 호출해 응답의 usage 를 그대로 기록한다.
★ 프로덕션 코드를 수정하지 않는다 - tagger 는 토큰을 로그로 남기지 않아서,
  같은 파라미터로 호출을 재현해 usage 만 따로 잰다(services/tagger.py 무수정).

측정 단계
  1) 이미지 인식      Claude Vision (services/ocr.py 와 동일한 프롬프트·스키마)
  2) 검색 임베딩      Upstage 질의 1건 (services/embeddings.py embed_texts)
  3) 확인 질문 생성   Claude Sonnet - 근거 문서가 프롬프트에 들어가 가장 클 수 있다
  4) 오판유형 분류    Claude Sonnet
  5) 훈련 카드        LLM 미사용(rag.py 는 로컬 JSON) → 0원

텍스트 입력만인 경우와 이미지가 있는 경우를 나눠 집계한다.
프롬프트 캐싱(cache_read)은 응답에 실제로 실려 오는 값을 그대로 쓴다.
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

import anthropic  # noqa: E402

from config import settings  # noqa: E402
from services import corpus_index, embeddings, ocr, prompt_chain, search, tagger  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
IMG_DIR = Path("/app/tests/fixtures/ocr_eval")
OUT_PATH = Path("/app/data/cost_measure.json")

N_CASES = 5           # 텍스트/이미지 각각 5건
DIALOGUE_TURNS = 3    # 서비스 계약상 최대 3턴


def _client():
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def measure_vision(image_path: Path) -> dict:
    """services/ocr.py extract_from_image() 와 동일한 호출을 재현해 usage 를 잰다."""
    import base64
    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode()
    media = ocr._detect_media_type(raw)
    t0 = time.perf_counter()
    r = _client().messages.create(
        model=ocr.VISION_MODEL, max_tokens=ocr.VISION_MAX_TOKENS,
        system=ocr.VISION_SYSTEM_PROMPT,
        output_config={"effort": ocr.VISION_EFFORT,
                       "format": {"type": "json_schema", "schema": ocr.VISION_SCHEMA}},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
            {"type": "text", "text": "이 메신저 캡처에서 말풍선 본문만 옮겨 적어 주세요."}]}],
    )
    u = r.usage
    return {"model": r.model, "in": u.input_tokens, "out": u.output_tokens,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "sec": round(time.perf_counter() - t0, 2)}


def measure_embedding(text: str) -> dict:
    t0 = time.perf_counter()
    _vecs, tokens = embeddings.embed_texts([text], input_type="query",
                                           timeout=embeddings.QUERY_TIMEOUT_SEC, max_retries=1)
    return {"model": embeddings.EMBEDDING_MODEL_QUERY, "tokens": tokens,
            "sec": round(time.perf_counter() - t0, 2)}


class _LlmLogCapture(logging.Handler):
    """prompt_chain 이 남기는 "[llm] model=... in=... " 로그를 가로채 usage 를 모은다.

    ★ _call_claude() 는 usage 를 반환하지 않고 로그로만 남긴다. 프로덕션 코드를
      고치지 않으려고 로그를 파싱하는 방식을 택했다. 재생성(가드레일 재시도)이
      일어나면 그만큼 줄이 더 쌓이므로, 실제 과금에 해당하는 전체 호출이 다 잡힌다.
    """

    PATTERN = re.compile(
        r"\[llm\] model=(\S+) in=(\d+) cache_write=(\d+) cache_read=(\d+) out=(\d+)")

    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []

    def emit(self, record):
        m = self.PATTERN.search(record.getMessage())
        if m:
            self.calls.append({"model": m.group(1), "in": int(m.group(2)),
                               "cache_write": int(m.group(3)), "cache_read": int(m.group(4)),
                               "out": int(m.group(5))})


def measure_dialogue(text: str, turns: int) -> list[dict]:
    """실제 generate_question() 을 그대로 호출한다 - 가드레일 재생성까지 포함한
    '실제 과금에 해당하는' 호출 전부를 로그로 잡는다."""
    ev = search.collect_evidence(text)
    history: list[str] = []
    out = []
    logger = logging.getLogger("gyeotnun.prompt_chain")
    for turn in range(1, turns + 1):
        cap = _LlmLogCapture()
        logger.addHandler(cap)
        prev = logger.level
        logger.setLevel(logging.INFO)
        t0 = time.perf_counter()
        try:
            vq = prompt_chain.generate_question(text, ev.signals, ev.references, history)
        finally:
            logger.removeHandler(cap)
            logger.setLevel(prev)
        sec = time.perf_counter() - t0
        out.append({"turn": turn, "llm_calls": len(cap.calls),
                    "in": sum(c["in"] for c in cap.calls),
                    "out": sum(c["out"] for c in cap.calls),
                    "cache_write": sum(c["cache_write"] for c in cap.calls),
                    "cache_read": sum(c["cache_read"] for c in cap.calls),
                    "model": cap.calls[0]["model"] if cap.calls else None,
                    "fallback": getattr(vq, "fallback", False),
                    "sec": round(sec, 2)})
        history.append(f"질문{turn}: {vq.question}")
    return out


def measure_tagging(text: str) -> dict:
    """services/tagger.py tag_error_type_llm() 과 동일한 호출을 재현(무수정)."""
    signals = search.detect_signals(text)
    sig_lines = "\n".join(f"- {s.get('label', s)}" for s in signals) or "- (특이 신호 없음)"
    user = (f"[사용자가 확인한 글]\n{text}\n\n[확인 과정에서 감지된 신호]\n{sig_lines}\n\n"
            f"[사용자가 고른 행동] hold\n\n"
            "위 글이 4가지 오판유형 중 어디에 가장 가까운지 하나만 골라 JSON으로 출력하십시오.")
    t0 = time.perf_counter()
    r = _client().messages.create(
        model=tagger.TAG_MODEL, max_tokens=tagger.TAG_MAX_TOKENS,
        system=[{"type": "text",
                 "text": tagger.TAG_SYSTEM_PROMPT + "\n\n" + tagger._few_shot_examples(),
                 "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": tagger.TAG_EFFORT,
                       "format": {"type": "json_schema", "schema": tagger.TAG_SCHEMA}},
        messages=[{"role": "user", "content": user}],
    )
    u = r.usage
    return {"model": r.model, "in": u.input_tokens, "out": u.output_tokens,
            "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
            "sec": round(time.perf_counter() - t0, 2)}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))[:N_CASES]
    report = {"n_cases": N_CASES, "dialogue_turns": DIALOGUE_TURNS, "cases": []}

    for i, row in enumerate(rows, 1):
        cid, text = row["case_id"], row["평가용_제시문구"]
        print(f"\n[{i}/{len(rows)}] {cid}", flush=True)
        c = {"case_id": cid}

        print("  이미지 인식(Vision)...", flush=True)
        c["vision"] = measure_vision(IMG_DIR / f"{cid}.jpg")
        print(f"    in={c['vision']['in']} out={c['vision']['out']}", flush=True)

        print("  검색 임베딩(Upstage)...", flush=True)
        c["embedding"] = measure_embedding(text)
        print(f"    tokens={c['embedding']['tokens']}", flush=True)

        print(f"  확인 질문 생성 x{DIALOGUE_TURNS}...", flush=True)
        c["dialogue"] = measure_dialogue(text, DIALOGUE_TURNS)
        for d in c["dialogue"]:
            print(f"    turn{d['turn']}: in={d['in']} out={d['out']} "
                  f"cache_w={d['cache_write']} cache_r={d['cache_read']}", flush=True)

        print("  오판유형 분류...", flush=True)
        c["tagging"] = measure_tagging(text)
        print(f"    in={c['tagging']['in']} out={c['tagging']['out']} "
              f"cache_w={c['tagging']['cache_write']} cache_r={c['tagging']['cache_read']}", flush=True)

        report["cases"].append(c)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
