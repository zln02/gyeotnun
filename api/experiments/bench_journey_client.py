"""0단계 — 사용자 전체 여정 측정 (2026-08-16, #33)

    POST /checks  →  GET /checks/{id}/evidence  →  POST /checks/{id}/dialogue

★ LLM(Claude) 실호출을 포함한다. 비용이 든다 - 승인된 호출 수 안에서만 돈다.
  아래 LLM_BUDGET 이 상한이고, 넘으면 스스로 멈춘다.

★ 확인 대상: 질문 생성(prompt_chain.generate_question)이 **이벤트 루프를 막는가**.
  routers/dialogue.py 의 next_question 은 async def 인데, 그 안에서
  anthropic.Anthropic(동기 클라이언트)를 부른다. 막는다면 동시 3명의 dialogue
  완료 시각이 계단으로 벌어진다(= LLM 시간 × 3). 안 막는다면 거의 나란히 끝난다.

★ 격리 컨테이너(127.0.0.1:8010) 전용. bench_workers.sh 가 띄운다.
  운영 컨테이너로는 쏘지 않는다.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8010/api/v1"
DEVICE = "bench-journey"
IMG = "/home/ubuntu/gyeotnun/api/tests/fixtures/kakao_sample.jpg"

TEXT = ("기초연금은 만 65세 이상이면서 소득인정액이 선정기준액 이하인 분께 매달 "
        "지급됩니다. 신청은 주소지 주민센터나 국민연금공단 지사에서 하실 수 있습니다.")

LLM_BUDGET = 15          # ★ 승인된 상한. 넘으면 멈춘다.
_llm_calls = 0
_budget_lock = threading.Lock()


def _take_budget() -> bool:
    global _llm_calls
    with _budget_lock:
        if _llm_calls >= LLM_BUDGET:
            return False
        _llm_calls += 1
        return True


def post_text() -> tuple[float, str | None]:
    body = urllib.parse.urlencode({"device_id": DEVICE, "text": TEXT}).encode()
    req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST")
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as r:
        return time.perf_counter() - t, json.loads(r.read()).get("check_id")


def post_image() -> tuple[float, str | None]:
    raw = open(IMG, "rb").read()
    b = uuid.uuid4().hex
    body = b"".join([
        f"--{b}\r\nContent-Disposition: form-data; name=\"device_id\"\r\n\r\n{DEVICE}\r\n".encode(),
        f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"k.jpg\"\r\n"
        f"Content-Type: image/jpeg\r\n\r\n".encode(), raw, b"\r\n", f"--{b}--\r\n".encode()])
    req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        return time.perf_counter() - t, json.loads(r.read()).get("check_id")


def get_evidence(cid: str) -> float:
    t = time.perf_counter()
    with urllib.request.urlopen(f"{BASE}/checks/{cid}/evidence?device_id={DEVICE}", timeout=180) as r:
        r.read()
    return time.perf_counter() - t


def post_dialogue(cid: str) -> tuple[float, bool]:
    """질문 생성 1턴. 반환 (소요, 폴백여부)."""
    payload = json.dumps({"turn": 1, "device_id": DEVICE}).encode()
    req = urllib.request.Request(f"{BASE}/checks/{cid}/dialogue", data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    t = time.perf_counter()
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    # 폴백(GN-001)이면 LLM 을 실제로 안 탄 것이다 - 수치 해석이 달라지므로 표시한다.
    return time.perf_counter() - t, "확인" in (d.get("why") or "") and not d.get("options")


def journey(kind: str, t_zero: float, out: list) -> None:
    if not _take_budget():
        out.append({"skipped": True})
        return
    s = time.perf_counter() - t_zero
    _tc, cid = (post_image() if kind == "image" else post_text())
    a = time.perf_counter() - t_zero
    get_evidence(cid)
    b = time.perf_counter() - t_zero
    t_d, _fb = post_dialogue(cid)
    c = time.perf_counter() - t_zero
    out.append({"start": s, "afterPost": a, "afterEvidence": b, "afterDialogue": c,
                "dialogue": t_d, "skipped": False})


def run(kind: str, n: int, rounds: int, label: str) -> None:
    print(f"\n■ {label} — {kind} POST · 동시 {n}명 × {rounds}회")
    print(f"   {'라운드':>5} {'#':>2} {'POST끝':>8} {'evidence끝':>11} {'dialogue끝':>11} {'dialogue소요':>12}")
    dial, total = [], []
    for r in range(rounds):
        out: list = []
        ths = [threading.Thread(target=journey, args=(kind, time.perf_counter(), out))
               for _ in range(n)]
        t0 = time.perf_counter()
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        rows = [x for x in out if not x.get("skipped")]
        if len(rows) < len(out):
            print("   ★ LLM 호출 예산 소진 - 여기서 멈춘다")
        for i, x in enumerate(sorted(rows, key=lambda z: z["afterDialogue"])):
            print(f"   {r + 1:>5} {i:>2} {x['afterPost']:>7.2f}s {x['afterEvidence']:>10.2f}s "
                  f"{x['afterDialogue']:>10.2f}s {x['dialogue']:>11.2f}s")
            dial.append(x["dialogue"])
            total.append(x["afterDialogue"])
        time.sleep(1.0)
    if dial:
        print(f"   → dialogue 소요 중앙 {statistics.median(dial):.2f}s · "
              f"전체 여정 최대 {max(total):.2f}s")


if __name__ == "__main__":
    print("워밍업(모델 + LLM 1건) …", flush=True)
    _t, cid = post_text()
    get_evidence(cid)
    _take_budget()
    post_dialogue(cid)

    run("text", 1, 3, "0-A 텍스트 여정 · 단독")
    run("text", 3, 2, "0-B 텍스트 여정 · 동시 3명")
    run("image", 3, 1, "0-C 사진 여정 · 동시 3명")
    print(f"\nLLM 실호출 {_llm_calls}건 (상한 {LLM_BUDGET})")
