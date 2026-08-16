#!/usr/bin/env bash
# 3단계 측정용 — 격리된 Postgres + 격리된 api (2026-08-16, #33)
#
# 왜 별도 스크립트인가
#   3단계부터는 요청마다 DB 왕복이 생긴다. SQLite 로 재면 운영(Postgres)과 다른 값이
#   나온다. 그래서 **버리는 Postgres 를 따로 띄워** 같은 엔진으로 잰다.
#
# ★★ 운영을 건드리지 않는다 ★★
#   전용 네트워크 · 전용 컨테이너 이름 · 127.0.0.1:8010 · 측정 후 전부 삭제.
#   운영 db 컨테이너와는 네트워크가 달라 서로 보이지도 않는다.
#
# 실행:  bash api/experiments/bench_with_postgres.sh <워커수>
#        BENCH_CLIENT=... 로 클라이언트를 바꿀 수 있다(기본: bench_stage_client.py)
set -u
N="${1:-1}"
NET=gyeotnun-bench-net
PG=gyeotnun-bench-pg
API=gyeotnun-bench-api
CLIENT="${BENCH_CLIENT:-/home/ubuntu/gyeotnun/api/experiments/bench_stage_client.py}"

cleanup() {
  docker rm -f $API $PG >/dev/null 2>&1
  docker network rm $NET >/dev/null 2>&1
}
cleanup
docker network create $NET >/dev/null

docker run -d --name $PG --network $NET \
  -e POSTGRES_USER=gyeotnun -e POSTGRES_PASSWORD=gyeotnun -e POSTGRES_DB=gyeotnun \
  postgres:16-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec $PG pg_isready -U gyeotnun >/dev/null 2>&1 && break
  sleep 2
done

docker run -d --name $API --network $NET -p 127.0.0.1:8010:8000 \
  --env-file /home/ubuntu/gyeotnun/.env \
  -e APP_ENV=local \
  -e DATABASE_URL="postgresql+psycopg2://gyeotnun:gyeotnun@$PG:5432/gyeotnun" \
  -e MAX_UPLOAD_MB=10 -e HF_HOME=/app/data/hf_cache -e HOME=/app/data/paddle_home \
  -e PADDLE_PDX_CACHE_HOME=/app/data/paddle_home/.paddlex \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True -e OCR_PROVIDER=local \
  -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 \
  -e FLAGS_paddle_num_threads=1 ${EXTRA_ENV:-} \
  -v /home/ubuntu/gyeotnun/api:/app -v /home/ubuntu/gyeotnun/corpus:/corpus:ro \
  gyeotnun-api uvicorn main:app --host 0.0.0.0 --port 8000 --workers "$N" >/dev/null

for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8010/health 2>/dev/null)" = "200" ] && break
  sleep 3
done

# ★ 운영 DB 로 새지 않는지 확인. 격리 pg 호스트명이 아니면 즉시 중단.
URL=$(docker exec $API python3 -c "import sys;sys.path.insert(0,'/app');from models.db import engine;print(engine.url)")
case "$URL" in *"@$PG:5432"*) ;; *) echo "  ★ 중단 - 격리 DB 가 아니다: $URL"; cleanup; exit 1;; esac
echo "  격리 DB 확인: $PG (운영 db 와 네트워크 분리)"

for _ in $(seq 1 40); do
  ok=$(docker logs $API 2>&1 | grep -c "prewarm.*준비 완료")
  [ "$ok" -ge $((2 * N)) ] && break
  sleep 5
done
echo "  워커 $N — prewarm $ok 줄 · 메모리 $(docker stats --no-stream --format '{{.MemUsage}}' $API)"

python3 "$CLIENT"

# ★★ 측정이 오염되지 않았는지 스스로 검사한다 (2026-08-16) ★★
#   임베딩 로더 경합으로 검색이 BM25 로 폴백하면 **더 빨라진다.** 그걸 모르고
#   "개선됐다"고 적으면 거짓 보고가 된다. 실제로 한 번 당했다.
FALLBACKS=$(docker logs $API 2>&1 | grep -c "임베딩 검색 실패" || true)
META=$(docker logs $API 2>&1 | grep -c "meta tensor" || true)
if [ "$FALLBACKS" != "0" ] || [ "$META" != "0" ]; then
  echo "  ★★ 측정 무효 - 임베딩이 폴백했다 (임베딩실패 $FALLBACKS · meta tensor $META)"
  echo "     이 수치는 BM25 전용 경로라 실제보다 빠르다. 쓰지 말 것."
else
  echo "  ✓ 임베딩 폴백 0건 - 측정 유효"
fi

echo "  --- 저장된 행수 ---"
docker exec $PG psql -U gyeotnun -d gyeotnun -t -c \
  "select 'checks', count(*) from checks union all select 'taggings', count(*) from taggings;" \
  | sed 's/^ */    /' | grep -v '^ *$'
cleanup
echo "정리 완료"
