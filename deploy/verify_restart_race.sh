#!/usr/bin/env bash
#
# 백엔드 배포 — 재시작 + 재시작 직후 경합 검사 (2026-08-16 신설, #33)
#
#   사용:  deploy/verify_restart_race.sh          # 코드만 바뀐 경우 (restart)
#          deploy/verify_restart_race.sh up       # compose 파일이 바뀐 경우 (up -d)
#
# ★★ 왜 이 스크립트가 있나 ★★
#   2026-08-16 에 임베딩 모델 지연 로더의 경합이 라이브로 나갔다. 프리워밍 스레드와
#   요청 스레드가 동시에 로더에 들어가 반쯤 만들어진 모델이 전역에 남았고, 그
#   프로세스는 재시작 전까지 **영구히 BM25 로만** 답했다.
#
#   무서운 점은 터지지 않는다는 것이다. 폴백이 있어 사용자에겐 200 이 나가고 근거
#   품질만 조용히 떨어진다. 그래서 게이트 세 개를 전부 통과했다:
#     - pytest 는 단일 스레드다
#     - render_verdict 142건 대조는 별도 프로세스에서 계산한다
#     - 동시성 대조는 프리워밍이 끝난 뒤 요청을 보내 경합 자체가 안 일어났다
#
#   실제로 잡은 단서는 두 개뿐이었고 둘 다 사람이 우연히 본 것이었다.
#     (1) 서버 로그의 경합 오류(EX-003)
#     (2) 같은 입력인데 재시작 전후 verdict_hint 가 다르다
#   **그 우연을 절차로 만든다.** 이 스크립트가 그 두 가지를 매 배포마다 검사한다.
#
# ■ 하는 일
#   1) 기준값을 **새 프로세스**에서 계산한다 (경합의 영향을 받지 않는 값)
#   2) 재시작 전 HTTP 응답도 기록한다 (지금 도는 프로세스가 이미 망가졌는지 본다)
#   3) api 를 재시작하고, **프리워밍이 도는 동안** 요청 5건을 일부러 동시 투입한다
#   4) EX-003 증가 0건인지 확인
#   5) 5건의 verdict_hint 가 기준값과 일치하는지 확인
#   6) 검사가 만든 checks 행을 지운다 (운영 DB 에 흔적을 남기지 않는다)
#
# ■ ★ 운영 DB 를 더럽히지 않는다
#   이 검사는 실제 운영 API 를 쓰므로 checks 행이 생긴다. 끝나면 device_hash 로
#   **정확히 이 검사가 만든 행만** 지운다. 다른 행은 건드리지 않는다.
#   ★ EX-003 이 늘었다면 그건 진짜 사고의 진짜 기록이므로 **지우지 않는다.**
set -u

MODE="${1:-restart}"
# ★ 자기시험 모드. 이 검사가 **실패할 때 정말 실패하는지**를 확인하기 위한 것이다.
#   실패하는 걸 본 적 없는 게이트는 초록불의 의미가 없다 - 이번 누출이 게이트 세 개를
#   통과한 이유가 정확히 그것이었다.
#     SELFTEST=hint      기준 판정을 일부러 어긋나게 만든다 (판정 불일치 분기)
#     SELFTEST=incident  EX-003 기준치를 1 낮춰 증가한 것처럼 만든다 (경합 오류 분기)
#   ★ 둘 다 스크립트 안에서만 값을 바꾼다. 운영 동작·DB 에 아무 영향이 없고,
#     재시작도 하지 않는다.
SELFTEST="${SELFTEST:-}"
BASE="${GYEOTNUN_API:-http://127.0.0.1:8000}"
DEV="deploy-smoke"
PROBE="기초연금은 만 65세 이상이면서 소득인정액이 선정기준액 이하인 분께 매달 지급됩니다."
CONCURRENCY=5
FAILED=0

say()  { printf '%s\n' "$*"; }
fail() { printf '  ★★ %s\n' "$*"; FAILED=$((FAILED + 1)); }

psql_t() { docker compose exec -T db psql -U gyeotnun -d gyeotnun -t -A -c "$1" 2>/dev/null | tr -d '[:space:]'; }

flow() {   # POST /checks -> GET evidence. "HTTP상태 hint" 한 줄을 출력한다.
  local cid code body hint
  body=$(mktemp)
  cid=$(curl -s -X POST "$BASE/api/v1/checks" -F "device_id=$DEV" -F "text=$PROBE" \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('check_id',''))" 2>/dev/null)
  if [ -z "$cid" ]; then rm -f "$body"; say "000 -"; return; fi
  code=$(curl -s -o "$body" -w "%{http_code}" "$BASE/api/v1/checks/$cid/evidence?device_id=$DEV")
  hint=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('verdict_hint','-'))" \
         "$body" 2>/dev/null || echo "-")
  rm -f "$body"
  say "$code $hint"
}

wait_health() {
  local i
  for i in $(seq 1 60); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null)" = "200" ] && return 0
    sleep 1
  done
  return 1
}

# ────────────────────────────────────────────── 1. 기준값 (새 프로세스)
say "[1/6] 기준값 계산 — 새 프로세스에서 (경합 영향 없음)"
REF_HINT=$(docker compose exec -T api python3 -c "
import sys; sys.path.insert(0,'/app')
from services import search
print(search.collect_evidence('''$PROBE''').verdict_hint)
" 2>/dev/null | tail -1 | tr -d '[:space:]')
if [ -z "$REF_HINT" ]; then
  fail "기준값을 계산하지 못했다. api 컨테이너가 떠 있는지 확인할 것."
  exit 1
fi
say "      기준 verdict_hint = $REF_HINT"
if [ "$SELFTEST" = "hint" ]; then
  REF_HINT="__selftest_불가능한값__"
  say "      [자기시험] 기준값을 일부러 어긋나게 바꿨다 → 아래 판정 검사가 반드시 실패해야 한다"
fi

# ────────────────────────────────────────────── 2. 재시작 전 상태
say "[2/6] 재시작 전 HTTP 응답 확인"
BEFORE=$(flow)
BEFORE_HINT=${BEFORE#* }
say "      재시작 전 = $BEFORE_HINT"
if [ "$BEFORE_HINT" != "$REF_HINT" ]; then
  fail "★ 지금 도는 프로세스가 이미 기준값과 다르다 ($BEFORE_HINT != $REF_HINT)."
  say  "         재시작 전부터 경합에 당해 있었다는 뜻이다. 재시작 후 결과를 특히 볼 것."
fi

EX003_BEFORE=$(psql_t "select count(*) from error_logs where code='EX-003';")
EX006_BEFORE=$(psql_t "select count(*) from error_logs where code='EX-006';")
if [ "$SELFTEST" = "incident" ]; then
  EX003_BEFORE=$((EX003_BEFORE - 1))
  say "      [자기시험] EX-003 기준치를 1 낮췄다 → 아래 경합 오류 검사가 반드시 실패해야 한다"
fi
say "      EX-003 ${EX003_BEFORE}건 · EX-006 ${EX006_BEFORE}건 (재시작 전)"

# ────────────────────────────────────────────── 3. 재시작 + 경합 투입
say "[3/6] api $MODE 후, 프리워밍이 도는 동안 동시 ${CONCURRENCY}건 투입"
if [ -n "$SELFTEST" ]; then
  say "      [자기시험] 재시작은 건너뛴다 (판정 분기만 확인한다)"
elif [ "$MODE" = "up" ]; then
  docker compose up -d api >/dev/null 2>&1
else
  docker compose restart api >/dev/null 2>&1
fi
if ! wait_health; then
  fail "재시작 후 서버가 뜨지 않았다."
  exit 1
fi
# ★ 여기서 프리워밍을 기다리지 않는다. 기다리면 경합이 일어나지 않아 검사가 무의미해진다.

TMP=$(mktemp -d)
for i in $(seq 1 "$CONCURRENCY"); do
  ( flow > "$TMP/r$i" ) &
done
wait

# ────────────────────────────────────────────── 4. 결과 판정
say "[4/6] 응답 확인"
for i in $(seq 1 "$CONCURRENCY"); do
  line=$(cat "$TMP/r$i")
  code=${line%% *}; hint=${line#* }
  say "      $i: HTTP $code · hint=$hint"
  [ "$code" = "200" ] || fail "요청 $i 이 실패했다 (HTTP $code)"
  [ "$hint" = "$REF_HINT" ] || fail "요청 $i 의 판정이 기준과 다르다 ($hint != $REF_HINT)"
done
rm -rf "$TMP"

# ────────────────────────────────────────────── 5. 경합 오류
say "[5/6] 경합 오류 확인"
sleep 2
EX003_AFTER=$(psql_t "select count(*) from error_logs where code='EX-003';")
EX006_AFTER=$(psql_t "select count(*) from error_logs where code='EX-006';")
D3=$((EX003_AFTER - EX003_BEFORE))
D6=$((EX006_AFTER - EX006_BEFORE))
say "      EX-003 증가 ${D3}건 · EX-006 증가 ${D6}건"
[ "$D3" -eq 0 ] || fail "EX-003(임베딩 실패)이 ${D3}건 늘었다 — 로더 경합이다."
[ "$D6" -eq 0 ] || fail "EX-006(검색 폴백률)이 ${D6}건 늘었다 — 폴백이 반복되고 있다."
META=$(docker compose logs api --since 3m 2>&1 | grep -c "meta tensor")
say "      meta tensor 오류 ${META}건"
[ "$META" -eq 0 ] || fail "meta tensor 오류가 ${META}건 있다 — 모델 로드가 깨졌다."

# ────────────────────────────────────────────── 6. 뒷정리
say "[6/6] 검사가 만든 행 정리"
HASH=$(python3 -c "import hashlib;print(hashlib.sha256('$DEV'.encode()).hexdigest())")
# ★ device_hash 로 정확히 이 검사가 만든 checks 행만 지운다. 다른 행은 건드리지 않는다.
DEL=$(psql_t "with d as (delete from checks where device_hash='$HASH' returning 1) select count(*) from d;")
say "      checks ${DEL}행 삭제 (device_hash=${HASH:0:12}…)"
say "      ★ EX-003/EX-006 행은 지우지 않는다 — 진짜 사고의 진짜 기록이다."

say ""
if [ "$FAILED" -eq 0 ]; then
  say "✓ 재시작 직후 경합 검사 통과 (${CONCURRENCY}건 전부 200 · 판정 일치 · 경합 오류 0)"
  exit 0
fi
say "✗ 검사 실패 ${FAILED}건 — 배포를 완료로 보지 말 것."
say "  되돌리기: 직전 커밋으로 되돌린 뒤 docker compose restart api"
say "  진단: docker compose logs api | grep -E '임베딩 검색 실패|meta tensor'"
exit 1
