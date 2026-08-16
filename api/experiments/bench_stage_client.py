"""단계별 전후 비교용 표준 측정 클라이언트 (2026-08-16, #33)

동시 1·3·5 명으로 두 경로를 잰다. **LLM 은 부르지 않는다**(비용 없이 반복 가능해야
단계마다 전후 비교를 할 수 있다). LLM 을 포함한 전체 여정은 bench_journey_client.py 다.

    텍스트 경로  POST /checks(text) + GET evidence
    사진 경로    POST /checks(image)   ← OCR

격리 컨테이너(127.0.0.1:8010) 전용. bench_workers.sh 가 띄운다.
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
DEVICE = "bench-stage"
IMG = "/home/ubuntu/gyeotnun/api/tests/fixtures/kakao_sample.jpg"
LEVELS = (1, 3, 5)
ROUNDS = 3

TEXT = ("기초연금은 만 65세 이상이면서 소득인정액이 선정기준액 이하인 분께 매달 "
        "지급됩니다. 신청은 주소지 주민센터나 국민연금공단 지사에서 하실 수 있습니다.")
_RAW = open(IMG, "rb").read()


def _text_flow() -> tuple[bool, float]:
    t = time.perf_counter()
    try:
        body = urllib.parse.urlencode({"device_id": DEVICE, "text": TEXT}).encode()
        req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            cid = json.loads(r.read())["check_id"]
        with urllib.request.urlopen(
                f"{BASE}/checks/{cid}/evidence?device_id={DEVICE}", timeout=180) as r:
            r.read()
        return True, time.perf_counter() - t
    except Exception:  # noqa: BLE001
        return False, time.perf_counter() - t


def _image_flow() -> tuple[bool, float]:
    t = time.perf_counter()
    try:
        b = uuid.uuid4().hex
        body = b"".join([
            f"--{b}\r\nContent-Disposition: form-data; name=\"device_id\"\r\n\r\n{DEVICE}\r\n".encode(),
            f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"k.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n".encode(), _RAW, b"\r\n", f"--{b}--\r\n".encode()])
        req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
        with urllib.request.urlopen(req, timeout=300) as r:
            json.loads(r.read())
        return True, time.perf_counter() - t
    except Exception:  # noqa: BLE001
        return False, time.perf_counter() - t


def measure(flow, n: int) -> tuple[list[float], int]:
    lasts, fails = [], 0
    for _ in range(ROUNDS):
        out: list = []
        gate = threading.Barrier(n)
        t0 = time.perf_counter()

        def one() -> None:
            gate.wait()
            ok, _d = flow()
            out.append((time.perf_counter() - t0, ok))

        ths = [threading.Thread(target=one) for _ in range(n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        lasts.append(max(x[0] for x in out))
        fails += sum(1 for x in out if not x[1])
        time.sleep(0.5)
    return lasts, fails


def main() -> None:
    for _ in range(6):        # 워밍업 - 지연 초기화를 털어낸다
        _text_flow()
    for _ in range(3):
        _image_flow()

    for name, flow in (("텍스트(POST+evidence)", _text_flow), ("사진(POST, OCR)", _image_flow)):
        print(f"  {name}")
        print(f"    {'N':>2} | {'마지막 완료 중앙':>16} {'최대':>8} | 실패")
        for n in LEVELS:
            lasts, fails = measure(flow, n)
            print(f"    {n:>2} | {statistics.median(lasts):>15.2f}s {max(lasts):>7.2f}s | {fails}")


if __name__ == "__main__":
    main()
