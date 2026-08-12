#!/usr/bin/env bash
#
# 프론트 배포 — web/dist 를 web/live 로 옮긴다.
#
# ■ 왜 이 스크립트가 있나
#   전에는 nginx 가 web/dist 를 직접 바인드 마운트했다. 그래서 `npm run build` 를
#   돌리는 순간 라이브가 바뀌었다 - 확인용 빌드도 배포가 됐다.
#   2026-08-11 01:22 에 문법 확인용으로 돌린 `vite build --base ./` 가 백업 없이
#   그대로 라이브에 나간 사고가 있었다.
#   → 2026-08-12 부터 nginx 는 web/live 를 본다. 빌드는 dist 로만 나가고,
#     배포는 이 스크립트를 명시적으로 실행할 때만 일어난다.
#
#       npm run build       -> web/dist   (라이브 영향 없음)
#       deploy/publish.sh   -> web/live   (여기서 비로소 배포)
#
# ■ 하는 일
#   1. 현재 live 를 타임스탬프 붙여 백업
#   2. dist 에 index.html 과 assets 가 있는지 확인 (빈 디렉터리를 배포하지 않는다)
#   3. live 로 복사
#   4. HTTP 200 확인. 실패하면 백업에서 자동 복구하고 0 이 아닌 코드로 끝난다
#
# ■ 금지
#   ★ rm -rf 를 쓰지 않는다. 어느 경로에도. 복사로만 한다.
#     디렉터리를 지우면 nginx 바인드 마운트가 끊겨 사이트가 500 이 된다
#     (실제로 겪은 사고다. 복구에 force-recreate 가 필요했다).
#   ★ 그래서 live 의 옛 파일을 지우지 않는다. 해시가 붙은 자산은 파일명이 매번
#     달라지므로 덮어쓰기만으로 새 빌드가 온전히 반영된다. 남는 옛 자산은
#     롤오버 중인 브라우저 캐시에 오히려 도움이 되고, 필요하면 사람이 따로 정리한다.
#
# 사용법:  deploy/publish.sh [확인할URL]
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$REPO/web/dist"
LIVE="$REPO/web/live"
BACKUP_ROOT="$REPO/deploy/live_backups"
URL="${1:-https://gyeotnun.duckdns.org/}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$BACKUP_ROOT/live_$STAMP"

say() { printf '%s\n' "$*"; }
fail() { printf '[중단] %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 2. 먼저 검증
# 백업보다 먼저 본다. 배포할 게 성립하지 않으면 아무것도 건드리지 않고 끝낸다.
[ -d "$DIST" ] || fail "빌드 결과가 없다: $DIST  (먼저 'cd web && npm run build')"
[ -s "$DIST/index.html" ] || fail "index.html 이 없거나 비었다: $DIST/index.html"
[ -d "$DIST/assets" ] || fail "assets 디렉터리가 없다: $DIST/assets"

ASSET_COUNT="$(find "$DIST/assets" -type f | wc -l | tr -d ' ')"
[ "$ASSET_COUNT" -gt 0 ] || fail "assets 가 비어 있다. 빌드가 실패한 것으로 본다."

# index.html 이 실제로 자산을 참조하는지까지 본다(빈 껍데기 배포 방지).
grep -q 'assets/' "$DIST/index.html" || fail "index.html 이 assets 를 참조하지 않는다."

say "[1/4] 검증 통과 — index.html + assets 파일 ${ASSET_COUNT}개"

# ---------------------------------------------------------------- 1. 백업
mkdir -p "$BACKUP_ROOT"
if [ -d "$LIVE" ] && [ -n "$(ls -A "$LIVE" 2>/dev/null)" ]; then
    mkdir -p "$BACKUP"
    cp -a "$LIVE/." "$BACKUP/"
    say "[2/4] 백업 생성 — $BACKUP"
else
    mkdir -p "$LIVE"
    BACKUP=""
    say "[2/4] live 가 비어 있어 백업을 건너뛴다 (첫 배포)"
fi

# ---------------------------------------------------------------- 3. 복사
# ★ 지우지 않고 덮어쓴다. 디렉터리를 지우면 바인드 마운트가 끊긴다.
cp -a "$DIST/." "$LIVE/"
say "[3/4] 복사 완료 — dist -> live"

# ---------------------------------------------------------------- 4. 확인
sleep 1
# ★ curl 이 실패하면 %{http_code} 로 "000" 을 찍고 종료코드도 0 이 아니다.
#   `|| echo 000` 을 붙이면 "000000" 처럼 두 번 찍히므로 || true 로 받는다.
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL" || true)"
CODE="${CODE:-000}"

ASSET_PATH="$(curl -s --max-time 15 "$URL" | grep -o 'assets/index-[^"]*\.js' | head -1 || true)"
ASSET_CODE=000
if [ -n "$ASSET_PATH" ]; then
    ASSET_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "${URL%/}/$ASSET_PATH" || true)"
    ASSET_CODE="${ASSET_CODE:-000}"
fi

if [ "$CODE" = "200" ] && [ "$ASSET_CODE" = "200" ]; then
    say "[4/4] 확인 완료 — / HTTP $CODE · $ASSET_PATH HTTP $ASSET_CODE"
    say ""
    say "배포 성공. 되돌리려면:"
    say "  cp -a ${BACKUP:-<백업없음>}/. $LIVE/"
    exit 0
fi

# ---- 실패: 백업에서 자동 복구
say "[4/4] 확인 실패 — / HTTP $CODE · asset HTTP $ASSET_CODE"
if [ -n "$BACKUP" ] && [ -d "$BACKUP" ]; then
    cp -a "$BACKUP/." "$LIVE/"
    sleep 1
    RECODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL" || true)"
    RECODE="${RECODE:-000}"
    say "[복구] 백업 복원 완료 — 현재 HTTP $RECODE  (백업: $BACKUP)"
else
    say "[복구] 백업이 없어 자동 복구를 하지 못했다. 수동 확인이 필요하다."
fi
exit 1
