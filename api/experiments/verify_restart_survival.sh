#!/usr/bin/env bash
# 재시작 생존 확인 (2026-08-16, #33 3단계)
#
# 무엇을 증명하나
#   저장소를 프로세스 메모리에서 DB 로 옮겼으니, **컨테이너를 재시작해도 진행 중인
#   확인이 살아 있어야 한다.** 전에는 재시작 즉시 404 였다.
#
# ★★ 운영 컨테이너를 건드리지 않는다 ★★
#   별도 이름·별도 포트(127.0.0.1:8013)·--network bridge(compose 의 db 호스트명이
#   해석조차 안 된다)·DATABASE_URL 은 컨테이너 안 SQLite.
#   docker restart 는 파일시스템을 유지하므로 DB 파일이 그대로 남는다 = 재시작 검증에 맞다.
set -u
NAME=gyeotnun-api-restart
BASE=http://127.0.0.1:8013/api/v1
DEV="restart-check-$$"

docker rm -f $NAME >/dev/null 2>&1
docker run -d --name $NAME --network bridge -p 127.0.0.1:8013:8000 \
  --env-file /home/ubuntu/gyeotnun/.env \
  -e APP_ENV=local -e DATABASE_URL="sqlite:////tmp/restart.db" -e MAX_UPLOAD_MB=10 \
  -e HF_HOME=/app/data/hf_cache -e HOME=/app/data/paddle_home \
  -e PADDLE_PDX_CACHE_HOME=/app/data/paddle_home/.paddlex \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True -e OCR_PROVIDER=local \
  -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e FLAGS_paddle_num_threads=1 \
  -v /home/ubuntu/gyeotnun/api:/app -v /home/ubuntu/gyeotnun/corpus:/corpus:ro \
  gyeotnun-api uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 >/dev/null

wait_up() {
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8013/health" 2>/dev/null || true)
    [ "$code" = "200" ] && return 0
    sleep 3
  done
  echo "  ★ 서버가 뜨지 않았다"; return 1
}

wait_up || { docker rm -f $NAME >/dev/null; exit 1; }
URL=$(docker exec $NAME python3 -c "import sys;sys.path.insert(0,'/app');from models.db import engine;print(engine.url)")
case "$URL" in sqlite*) ;; *) echo "  ★ 중단 - sqlite 가 아니다: $URL"; docker rm -f $NAME >/dev/null; exit 1;; esac

echo "── 재시작 전"
CID=$(curl -s -X POST "$BASE/checks" -F "device_id=$DEV" \
      -F "text=기초연금은 만 65세 이상이면서 소득인정액이 선정기준액 이하인 분께 매달 지급됩니다." \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['check_id'])")
echo "  check_id = $CID"
curl -s "$BASE/checks/$CID/evidence?device_id=$DEV" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('  evidence  hint:',d['verdict_hint'])"
curl -s -X POST "$BASE/checks/$CID/dialogue" -H "Content-Type: application/json" \
  -d "{\"turn\":1,\"device_id\":\"$DEV\"}" \
  | python3 -c "import sys,json;print('  dialogue1 질문:',json.load(sys.stdin)['question'][:44])"

echo "── 컨테이너 재시작"
docker restart $NAME >/dev/null
wait_up || { docker rm -f $NAME >/dev/null; exit 1; }

echo "── 재시작 후 (같은 check_id 로)"
curl -s "$BASE/checks/$CID/evidence?device_id=$DEV" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'detail' in d: print('  ★ 실패:', d['detail'])
else: print('  evidence  hint:', d['verdict_hint'], '(살아 있다)')"
curl -s -X POST "$BASE/checks/$CID/dialogue" -H "Content-Type: application/json" \
  -d "{\"turn\":2,\"user_reply\":\"문자로 받았어요\",\"device_id\":\"$DEV\"}" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
if 'detail' in d: print('  ★ 실패:', d['detail'])
else: print('  dialogue2 질문:', d['question'][:44])"

echo "── 대화 이력이 DB 에 남아 있는가 (재시작을 건너뛴 줄이 없어야 한다)"
docker exec $NAME python3 -c "
import sys; sys.path.insert(0,'/app')
from services import check_store
h = check_store.get('$CID')['history']
print('  이력 %d줄' % len(h))
for line in h: print('   ', line[:66])
"

echo "── ★ 소유자 대조는 재시작 후에도 유효한가 (남의 기기는 여전히 404)"
curl -s -o /dev/null -w "  다른 device_id → HTTP %{http_code}\n" \
  "$BASE/checks/$CID/evidence?device_id=someone-else"

docker rm -f $NAME >/dev/null
echo "정리 완료"
