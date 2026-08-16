#!/usr/bin/env bash
# 워커 수·스레드 수별 처리량 측정 (2026-08-16, #33)
#
# 실행:  bash api/experiments/bench_workers.sh <워커수>
#        EXTRA_ENV="-e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 \
#                   -e OPENBLAS_NUM_THREADS=1 -e FLAGS_paddle_num_threads=1" \
#          bash api/experiments/bench_workers.sh 4
#
# ★★ 운영 컨테이너(gyeotnun-api)를 건드리지 않는다 ★★
#   - 별도 이름·별도 포트(127.0.0.1:8010)로 같은 이미지를 새로 띄운다
#   - --network bridge 라 compose 네트워크의 db 호스트명이 애초에 해석되지 않는다
#   - DATABASE_URL 을 sqlite 로 덮고, **sqlite 가 아니면 즉시 중단**한다
#   - 측정이 끝나면 컨테이너를 지운다
set -u
N="$1"; NAME=gyeotnun-api-bench
docker rm -f $NAME >/dev/null 2>&1
docker run -d --name $NAME --network bridge -p 127.0.0.1:8010:8000 \
  --env-file /home/ubuntu/gyeotnun/.env \
  -e APP_ENV=local -e DATABASE_URL="sqlite:////tmp/bench.db" -e MAX_UPLOAD_MB=10 \
  -e HF_HOME=/app/data/hf_cache -e HOME=/app/data/paddle_home \
  -e PADDLE_PDX_CACHE_HOME=/app/data/paddle_home/.paddlex \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True -e OCR_PROVIDER=local ${EXTRA_ENV:-} \
  -v /home/ubuntu/gyeotnun/api:/app -v /home/ubuntu/gyeotnun/corpus:/corpus:ro \
  gyeotnun-api uvicorn main:app --host 0.0.0.0 --port 8000 --workers "$N" >/dev/null
URL=$(sleep 25; docker exec $NAME python3 -c "import sys;sys.path.insert(0,'/app');from models.db import engine;print(engine.url)" 2>/dev/null)
case "$URL" in sqlite*) ;; *) echo "  ★ 중단 — DATABASE_URL 이 sqlite 가 아니다: $URL"; docker rm -f $NAME >/dev/null; exit 1;; esac
for i in $(seq 1 40); do ok=$(docker logs $NAME 2>&1 | grep -c "prewarm.*준비 완료"); [ "$ok" -ge $((2*N)) ] && break; sleep 5; done
sleep 5
echo "  워커 $N — prewarm $ok 줄 · 메모리 $(docker stats --no-stream --format '{{.MemUsage}}' $NAME)"
python3 "${BENCH_CLIENT:-/home/ubuntu/gyeotnun/api/experiments/_bench_ocr_client.py}"
docker rm -f $NAME >/dev/null
