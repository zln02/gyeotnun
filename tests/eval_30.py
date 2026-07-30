"""
곁눈(Gyeotnun) - 평가세트 30건 실제 API 성능 측정
실행: python3 tests/eval_30.py   (저장소 루트에서)

corpus/곁눈_평가세트_30건.csv 의 '평가용_제시문구' 30건을 실제 텍스트
입력으로 POST /checks(mock=0) 에 넣고, evidence + dialogue(1턴) 를
순서대로 호출한다. mock 없이 실제 corpus_index 대조 + 실제 Claude
호출을 그대로 탄다.

★ 이 스크립트는 측정만 한다. 시스템 코드를 고치지 않는다.

가드레일(재생성)·토큰 사용량 통계는 HTTP 응답에 안 실려 있어서, api 컨테이너의
로그를 케이스별 시간창(timestamp window)으로 상관시켜 뽑아낸다 - 코드 수정 없이
측정하기 위한 방법이다. prompt_chain.py 가 재생성마다
"[guardrail] blocked attempt=X/Y reason=Z detail=..." 를, 호출마다
"[llm] model=... in=... cache_write=... cache_read=... out=..." 를 남기므로,
각 케이스의 dialogue 호출 시작~끝 사이에 찍힌 줄만 그 케이스 것으로 센다(케이스를
순차 실행하므로 시간창이 겹치지 않는다). 응답 시간은 dialogue 호출 자체만 별도로
재서(dialogue_elapsed_sec) evidence 수집(코퍼스 검색, LLM 미사용) 시간과 섞이지
않게 했다.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "corpus" / "곁눈_평가세트_30건.csv"
OUT_DIR = ROOT / "docs" / "evaluation"
BASE = "http://localhost:8000/api/v1"


def curl_json(args: list[str]) -> dict:
    out = subprocess.run(["curl", "-s", "--max-time", "90"] + args, capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"_curl_error": True, "_raw": out.stdout, "_stderr": out.stderr}


def create_check(text: str) -> dict:
    return curl_json(["-X", "POST", f"{BASE}/checks?mock=0", "-F", "device_id=eval30", "-F", f"text={text}"])


def get_evidence(check_id: str) -> dict:
    return curl_json([f"{BASE}/checks/{check_id}/evidence?mock=0"])


def get_dialogue(check_id: str) -> dict:
    body = json.dumps({"turn": 1, "user_reply": None})
    return curl_json(
        ["-X", "POST", f"{BASE}/checks/{check_id}/dialogue?mock=0",
         "-H", "Content-Type: application/json", "-d", body]
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건입니다."

    results = []
    print(f"=== {len(rows)}건 순차 실행 시작 (mock=0, 실제 API) ===\n")

    for i, row in enumerate(rows, 1):
        case_id = row["case_id"]
        text = row["평가용_제시문구"]
        t0 = now_utc()
        print(f"[{i:>2}/30] {case_id} ({row['유형']}) 실행 중...", end=" ", flush=True)

        record = {
            "case_id": case_id,
            "유형": row["유형"],
            "기대판단": row["기대판단"],
            "입력채널": row["입력채널"],
            "제시문구": text,
            "t_start": t0.isoformat(),
        }

        try:
            check = create_check(text)
            if check.get("_curl_error") or "check_id" not in check:
                record.update(실패=True, 실패사유=f"checks 생성 실패: {check}")
                results.append(record)
                print("FAIL(checks)")
                continue
            if check.get("status") == "failed":
                record.update(실패=True, 실패사유=f"OCR/추출 실패: {check.get('message')}")
                results.append(record)
                print("FAIL(status=failed)")
                continue

            check_id = check["check_id"]
            evidence = get_evidence(check_id)
            t_dialogue_start = now_utc()
            dialogue = get_dialogue(check_id)
            t_dialogue_end = now_utc()
            t1 = t_dialogue_end

            record.update(
                실패=False,
                check_id=check_id,
                masked=check.get("masked"),
                verdict_hint=evidence.get("verdict_hint"),
                references=evidence.get("references", []),
                references_count=len(evidence.get("references", [])),
                signals=[s.get("key") for s in evidence.get("signals", [])],
                question=dialogue.get("question"),
                why=dialogue.get("why"),
                dialogue_evidence_refs_count=len(dialogue.get("evidence_refs", [])),
                is_final=dialogue.get("is_final"),
                t_dialogue_start=t_dialogue_start.isoformat(),
                t_dialogue_end=t_dialogue_end.isoformat(),
                dialogue_elapsed_sec=round((t_dialogue_end - t_dialogue_start).total_seconds(), 3),
                t_end=t1.isoformat(),
            )
            results.append(record)
            print(f"OK (verdict={evidence.get('verdict_hint')}, refs={len(evidence.get('references', []))})")

        except Exception as e:  # noqa: BLE001
            record.update(실패=True, 실패사유=f"예외: {e}")
            results.append(record)
            print(f"FAIL(예외: {e})")

        time.sleep(0.5)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUT_DIR / "eval_30_raw.json"
    raw_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 결과 저장: {raw_path}")

    # ---- 서버 로그에서 가드레일 재생성 이벤트를 케이스별 시간창으로 상관시킨다
    print("서버 로그에서 가드레일 이벤트 수집 중...")
    log_proc = subprocess.run(
        ["sudo", "docker", "logs", "--timestamps", "gyeotnun-api"],
        capture_output=True, text=True,
    )
    log_lines = (log_proc.stdout + log_proc.stderr).splitlines()

    # docker --timestamps 는 나노초(9자리)를 찍는데 Python strptime %f 는 6자리(마이크로초)
    # 까지만 받는다. 앞 6자리만 잘라서 파싱한다(케이스 구간 상관에는 마이크로초 정밀도로 충분).
    ts_re = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d+)Z\s+(.*)$")
    blocked_re = re.compile(r"\[guardrail\] blocked attempt=(\d+)/(\d+) reason=(\w+) detail=(.*)")
    fallback_re = re.compile(r"\[guardrail\] fallback used")
    # prompt_chain._call_claude() 가 호출마다 남기는 토큰 사용량 로그 - 재생성 포함 전체 시도를 합산한다.
    llm_re = re.compile(r"\[llm\] model=(\S+) in=(\d+) cache_write=(\d+) cache_read=(\d+) out=(\d+)")

    parsed_logs = []
    for line in log_lines:
        m = ts_re.match(line)
        if not m:
            continue
        try:
            frac = (m.group(2) + "000000")[:6]
            ts = datetime.strptime(f"{m.group(1)}.{frac}Z", "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        parsed_logs.append((ts, m.group(3)))

    for record in results:
        if record.get("실패"):
            continue
        t0 = datetime.fromisoformat(record["t_start"])
        t1 = datetime.fromisoformat(record["t_end"])
        window = [msg for ts, msg in parsed_logs if t0 <= ts <= t1]

        regenerations = []
        fell_back = False
        llm_calls = []
        for msg in window:
            bm = blocked_re.search(msg)
            if bm:
                regenerations.append({"attempt": bm.group(1), "reason": bm.group(3), "detail": bm.group(4)})
            if fallback_re.search(msg):
                fell_back = True
            lm = llm_re.search(msg)
            if lm:
                llm_calls.append({
                    "model": lm.group(1),
                    "in": int(lm.group(2)),
                    "cache_write": int(lm.group(3)),
                    "cache_read": int(lm.group(4)),
                    "out": int(lm.group(5)),
                })

        record["재생성_횟수"] = len(regenerations)
        record["재생성_사유"] = regenerations
        record["폴백_발생"] = fell_back
        # ★ 재생성 포함 이 케이스에서 실제로 발생한 모든 Claude 호출의 토큰 합계 -
        #   '토큰 비용'은 재생성까지 포함해야 실제 과금액에 가깝다.
        record["llm_호출_횟수"] = len(llm_calls)
        record["llm_input_tokens_합"] = sum(c["in"] for c in llm_calls)
        record["llm_cache_write_tokens_합"] = sum(c["cache_write"] for c in llm_calls)
        record["llm_cache_read_tokens_합"] = sum(c["cache_read"] for c in llm_calls)
        record["llm_output_tokens_합"] = sum(c["out"] for c in llm_calls)

    raw_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"가드레일 정보 포함해 재저장: {raw_path}")
    print("\n완료.")


if __name__ == "__main__":
    main()
