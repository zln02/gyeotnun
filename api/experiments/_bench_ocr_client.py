"""워커 수별 OCR 처리량 클라이언트 (exp_concurrency 의 보조). 격리 포트 8010 전용."""
import json, threading, time, urllib.request, uuid
BASE = "http://127.0.0.1:8010/api/v1"
raw = open("/home/ubuntu/gyeotnun/api/tests/fixtures/kakao_sample.jpg", "rb").read()

def post():
    b = uuid.uuid4().hex
    body = b"".join([
        f"--{b}\r\nContent-Disposition: form-data; name=\"device_id\"\r\n\r\nbench\r\n".encode(),
        f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"k.jpg\"\r\n"
        f"Content-Type: image/jpeg\r\n\r\n".encode(), raw, b"\r\n", f"--{b}--\r\n".encode()])
    req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            json.loads(r.read()); return r.status
    except Exception as e:
        return type(e).__name__

# ★ 워밍업을 넉넉히 돌려 "워커마다 첫 요청이 느리다"는 설명을 배제한다.
#   PREWARM=1 이라 기동 시 워커마다 모델을 이미 올리지만, 그 뒤의 지연 초기화까지
#   확실히 털어내기 위해 순차 12건을 먼저 보낸다(라운드로빈이라 워커마다 최소 3건).
for _ in range(12): post()
# 단독 1건(순차 5회)을 먼저 잰다 - 스레드 제한이 '혼자 쓸 때'를 느리게 하는지 본다.
seq = []
for _ in range(5):
    t = time.perf_counter(); post(); seq.append(time.perf_counter() - t)
seq.sort()
print(f"    단독 1건 순차 5회  중앙 {seq[2]:.2f}s  최소 {seq[0]:.2f}s  최대 {seq[-1]:.2f}s")

out = []; gate = threading.Barrier(5); t0 = time.perf_counter()
def f():
    gate.wait(); s = post(); out.append((time.perf_counter() - t0, s))
ths = [threading.Thread(target=f) for _ in range(5)]
for t in ths: t.start()
for t in ths: t.join()
done = sorted(x[0] for x in out); bad = [x for x in out if x[1] != 200]
print(f"    동시 5건 완료시각 {[f'{d:.2f}' for d in done]}  마지막 {done[-1]:.2f}s  실패 {len(bad)}")
