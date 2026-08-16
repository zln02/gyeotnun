"""동시 접속 측정 — 로컬 API 로만 쏜다 (2026-08-16, #33)

실행(호스트에서):
    python3 api/experiments/exp_concurrency.py

★ 라이브 URL(https://gyeotnun.duckdns.org)로 쏘지 않는다. 127.0.0.1:8000 만 본다.
  같은 프로세스이긴 하나, 공개 경로를 부하로 때리지 않는다는 지시를 지킨다.

★ 운영 DB 를 건드리지 않는다는 근거
  routers/checks.py 는 DB 세션을 쓰지 않고 _MEMORY_STORE(파이썬 dict)에만 담는다
  (2026-08-14 감사 [4-8] 교정 1 에서 실측 확인: 라이브 5건 후에도 checks 0행).
  단 폴백·실패 경로를 타면 error_logs 에는 남을 수 있으므로, 이 스크립트를 돌리기
  전후로 error_logs 행수를 직접 세어 보고한다.

무엇을 재는가
  '확인 1건' = POST /checks → GET /checks/{id}/evidence 전체 흐름.
  동시 N 명이 같은 순간에 이 흐름을 시작한다. N = 1 · 2 · 3 · 5.
  라운드마다 N 개 스레드를 동시에 풀고, 각 요청의 벽시계 시간과 상태코드를 적는다.

★ 두 가지 본문을 따로 잰다
  A(주소 없음)  로컬 CPU(임베딩 추론)만 타는 경로
  B(주소 있음)  url_expand 가 외부로 HEAD 를 보내는 경로
  두 값이 갈리면 병목이 CPU 인지 외부 대기인지가 드러난다.
"""
from __future__ import annotations

import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
DEVICE = "loadtest-local"
TIMEOUT = 60

TEXTS = {
    "A(주소 없음)": (
        "기초연금은 만 65세 이상이면서 소득인정액이 선정기준액 이하인 분께 매달 "
        "지급됩니다. 신청은 주소지 주민센터나 국민연금공단 지사에서 하실 수 있습니다."
    ),
    "B(주소 있음)": (
        "[Web발신][전남광주 통합특별시청 청년정책과] 2026년 청년 천원복비 지원사업 "
        "신청 - 중개보수 최대 30만원 지원 ☞ https://m.site.naver.com/2dNkw"
    ),
}
LEVELS = [1, 2, 3, 5]
ROUNDS = 5


def _post_check(text: str) -> tuple[float, int, str | None]:
    body = urllib.parse.urlencode({"device_id": DEVICE, "text": text}).encode()
    req = urllib.request.Request(f"{BASE}/checks", data=body, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read())
            return time.perf_counter() - t0, r.status, data.get("check_id")
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code, None
    except Exception:  # noqa: BLE001
        return time.perf_counter() - t0, -1, None


def _get_evidence(check_id: str) -> tuple[float, int]:
    url = f"{BASE}/checks/{check_id}/evidence?device_id={DEVICE}"
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            r.read()
            return time.perf_counter() - t0, r.status
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, e.code
    except Exception:  # noqa: BLE001
        return time.perf_counter() - t0, -1


def one_flow(text: str, out: list, idx: int, gate: threading.Barrier) -> None:
    gate.wait()                      # ★ N 개가 정말 같은 순간에 출발하도록 맞춘다
    t_all = time.perf_counter()
    t_c, s_c, cid = _post_check(text)
    if cid is None:
        out.append({"i": idx, "create": t_c, "evidence": None,
                    "total": time.perf_counter() - t_all, "status": (s_c, None)})
        return
    t_e, s_e = _get_evidence(cid)
    out.append({"i": idx, "create": t_c, "evidence": t_e,
                "total": time.perf_counter() - t_all, "status": (s_c, s_e)})


def run_level(text: str, n: int) -> list[dict]:
    rows: list[dict] = []
    for _ in range(ROUNDS):
        out: list[dict] = []
        gate = threading.Barrier(n)
        ths = [threading.Thread(target=one_flow, args=(text, out, i, gate)) for i in range(n)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        rows.extend(out)
        time.sleep(1.0)              # 라운드 사이 숨 고르기 (라이브 사용자 배려)
    return rows


def main() -> None:
    print("워밍업 1건 …", flush=True)
    _t, _s, cid = _post_check(TEXTS["A(주소 없음)"])
    if cid:
        _get_evidence(cid)

    for name, text in TEXTS.items():
        print(f"\n■ 본문 {name}   (라운드 {ROUNDS}회 × 동시 N)")
        print(f"  {'N':>2}  {'건수':>4} {'실패':>4} | "
              f"{'전체 중앙':>9} {'전체 최대':>9} | {'create 중앙':>11} {'evidence 중앙':>13}")
        for n in LEVELS:
            rows = run_level(text, n)
            fail = [r for r in rows if r["status"] != (200, 200)]
            tot = sorted(r["total"] for r in rows)
            cre = [r["create"] for r in rows]
            evi = [r["evidence"] for r in rows if r["evidence"] is not None]
            print(f"  {n:>2}  {len(rows):>4} {len(fail):>4} | "
                  f"{statistics.median(tot):>8.2f}s {max(tot):>8.2f}s | "
                  f"{statistics.median(cre):>10.2f}s {statistics.median(evi):>12.2f}s")
            if fail:
                print(f"       ★ 실패 상태코드: {[r['status'] for r in fail]}")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
