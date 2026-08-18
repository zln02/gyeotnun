"""재생성이 왜 안 먹히는가 — 조사 전용 (2026-08-17)

실행: docker compose exec -T -e DATABASE_URL=sqlite:////tmp/diag.db api \
          python3 experiments/diag_regeneration.py

★★ 조사만 한다. prompt_chain.py 는 읽기만 하고 한 줄도 고치지 않는다. ★★
★ DATABASE_URL 을 임시 SQLite 로 덮어 돌린다 — 실험이 운영 error_logs 에
  GN-001 을 또 쌓지 않게 하기 위해서다(이 문제 자체가 별도 조사 대상이다).

무엇을 보나
  (a) 3회 시도의 **생성 텍스트 원문**과, 가드레일이 센 문장 수
      ★ 가드레일이 세는 수와 사람이 세는 수가 다른지가 첫 확인이다.
  (b) 3회 출력이 서로 **같은가 다른가**
  (c) 재생성 호출의 **실제 페이로드** — "2문장 이내" 지시가 어디에 실리는가
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import prompt_chain as pc  # noqa: E402
from services import search  # noqa: E402
from services.masking import mask_text  # noqa: E402

CASES = {
    "라이브(근거 4건)": ("[국민건강보험공단] 건강보험료 환급금 128,000원이 미수령 상태입니다. "
                    "오늘까지 신청하지 않으면 소멸됩니다. 아래 주소에서 계좌번호 "
                    "***-***-****** 입력 후 본인확인 바랍니다. 문의 010-****-**** "
                    "https://nhis-refund2026.com"),
    "S08(근거 0건)": "건강보험료 환급 신청 nhis-refund24.com",
}


def human_view(text: str) -> str:
    """사람이 세도록 문장 후보를 그대로 늘어놓는다."""
    parts = [p.strip() for p in pc._SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return "\n".join(f"          [{i + 1}] {p}" for i, p in enumerate(parts))


def run(label: str, text: str) -> None:
    print("=" * 78)
    print(f"■ {label}")
    print("=" * 78)
    masked = mask_text(text).text
    ev = search.collect_evidence(masked)
    print(f"  근거 {len(ev.references)}건 · 신호 {[s['key'] for s in ev.signals]}\n")

    calls: list[dict] = []
    orig = pc._call_claude

    def spy(messages):
        payload, raw = orig(messages)
        calls.append({"messages": messages, "payload": payload, "raw": raw})
        return payload, raw

    pc._call_claude = spy
    pc.reset_guardrail_stats()
    try:
        vq = pc.generate_question(extracted_text=masked, signals=ev.signals,
                                  references=ev.references, history=[])
    finally:
        pc._call_claude = orig

    for i, c in enumerate(calls, 1):
        q = c["payload"].get("question", "")
        n = pc.count_sentences(q)
        print(f"  ── {i}회차  가드레일이 센 문장 수 = {n} (상한 {pc.MAX_SENTENCES})")
        print(f"     question 원문: {q!r}")
        print("     문장 분해 (사람이 셀 것):")
        print(human_view(q))
        print(f"     why: {c['payload'].get('why','')!r}")
        print(f"     보기: {[o.get('label') for o in c['payload'].get('options', [])]}")
        print()

    # (b) 3회가 같은가
    qs = [c["payload"].get("question", "") for c in calls]
    print(f"  (b) 3회 출력이 서로 같은가 → 서로 다른 문장 {len(set(qs))}종 / {len(qs)}회")
    if len(set(qs)) == 1:
        print("      ★ 완전히 같다 = 재생성 요청이 모델에 닿지 않았거나 무시됐다")

    # (c) 재생성 호출 페이로드
    print(f"\n  (c) 호출별 messages 구성 (역할, 길이, '2문장' 포함 여부)")
    for i, c in enumerate(calls, 1):
        print(f"      {i}회차: {len(c['messages'])}개 메시지")
        for m in c["messages"]:
            body = m["content"] if isinstance(m["content"], str) else str(m["content"])
            has = "2문장" in body
            print(f"         role={m['role']:<9} {len(body):>5}자  '2문장' {'포함' if has else '없음'}")
            if m["role"] == "user" and i > 1:
                print(f"            └ 재생성 지시 원문: {body[:160]!r}")

    print(f"\n  system 블록에 '2문장' 이 있는가: ", end="")
    sysblocks = pc._system_blocks()
    txt = json.dumps(sysblocks, ensure_ascii=False)
    print("포함" if "2문장" in txt or "두 문장" in txt else "없음")
    print(f"  최종: 폴백={vq.fallback} · 집계={ {k: v for k, v in pc.guardrail_stats().items() if v} }\n")


if __name__ == "__main__":
    for k, v in CASES.items():
        run(k, v)
