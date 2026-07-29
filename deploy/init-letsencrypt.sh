#!/usr/bin/env bash
# 곁눈(Gyeotnun) - Let's Encrypt 인증서 최초 발급
#
# ★ 반드시 DNS(gyeotnun.duckdns.org → 이 서버의 공인 IP)가 실제로 전파된 뒤에만
#   실행한다. 전파 전에 실행하면 HTTP-01 검증이 실패하고, 실패가 반복되면
#   Let's Encrypt Rate Limit(같은 도메인 1주일에 5회)에 걸려 한동안 재시도가 막힌다.
#
# 실행: cd /home/ubuntu/gyeotnun && bash deploy/init-letsencrypt.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DOMAIN="gyeotnun.duckdns.org"
EMAIL="${CERTBOT_EMAIL:-}"   # 만료 알림 받을 이메일. 비워 두면 이메일 없이 발급한다.

if [ -z "$EMAIL" ]; then
  EMAIL_ARGS="--register-unsafely-without-email"
else
  EMAIL_ARGS="--email $EMAIL --no-eff-email"
fi

echo "1) DNS 확인 - $DOMAIN 이 이 서버의 공인 IP를 가리키는지 먼저 확인하세요."
echo "   조회 결과:"
dig +short "$DOMAIN" @8.8.8.8 || true
echo "   이 서버의 공인 IP: $(curl -s -4 ifconfig.me || echo '확인 실패')"
read -r -p "   위 둘이 같습니까? 같으면 Enter, 다르면 Ctrl+C 로 중단하세요 ... " _

echo "2) nginx 를 HTTP 설정으로 기동 (이미 떠 있으면 그대로 사용)"
mkdir -p deploy/nginx
cp deploy/nginx/http.conf deploy/nginx/active.conf
sudo docker compose --profile prod up -d nginx

# ★ certbot 서비스는 docker-compose.yml 에서 entrypoint 를 12시간 주기 renew 루프로
#   고정해 뒀다(자동 갱신용). `docker compose run <service> <command>` 는 기본적으로
#   command 만 덮어쓰고 entrypoint 는 그대로 두므로, --entrypoint 로 명시적으로
#   되돌리지 않으면 우리가 넘긴 "certonly ..." 인자가 무시되고 renew 루프가 그대로
#   실행되어 버린다(실제로 한 번 이렇게 걸려서 무한 대기에 빠진 적이 있다).
echo "3) certbot dry-run (실제 발급 전에 검증만 먼저 해 본다 - 실패해도 rate limit에 안 걸린다)"
sudo docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -n --agree-tos --dry-run -d "$DOMAIN" $EMAIL_ARGS < /dev/null

read -r -p "   dry-run 이 성공했습니까? 실제 발급을 진행하려면 Enter, 아니면 Ctrl+C ... " _

echo "4) 실제 인증서 발급"
sudo docker compose run --rm --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -n --agree-tos -d "$DOMAIN" $EMAIL_ARGS < /dev/null

echo "5) HTTPS 설정으로 교체하고 nginx reload"
cp deploy/nginx/https.conf deploy/nginx/active.conf
sudo docker compose --profile prod exec nginx nginx -s reload

echo
echo "완료. https://$DOMAIN 에서 확인하세요."
echo "자동 갱신: docker-compose.yml 의 certbot 서비스가 12시간마다 'certbot renew' 를 실행합니다."
echo "  단, renew 이후 nginx 는 자동으로 reload 되지 않으니, crontab 에 아래를 등록해 두세요:"
echo '  0 3 * * * cd '"$(pwd)"' && docker compose --profile prod exec nginx nginx -s reload'
