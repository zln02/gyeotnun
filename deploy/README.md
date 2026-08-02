# 곁눈(Gyeotnun) 배포 가이드

담당: 박진영 (API·DB·배포)

## 로컬 개발 vs 배포

| | 로컬 개발 | 배포(이 문서) |
|---|---|---|
| 프론트 | `vite dev`(5173), USE_MOCK 기본 실제 API | `vite build` → nginx 정적 서빙 |
| 백엔드 접근 | vite 프록시가 `/api` → `localhost:8000` | nginx가 `/api` → `api:8000` |
| DB 포트 | 노출 안 함(내부 네트워크만) | 동일 |
| 실행 | `docker compose up -d --build` | `docker compose --profile prod up -d --build` |

`nginx`/`certbot` 서비스는 `prod` 프로파일에만 속해 있어 평소 `docker compose up`
에는 뜨지 않는다. 로컬 개발엔 필요 없기 때문이다.

## 배포 절차

### 1. 프론트 프로덕션 빌드

```bash
cd web && npm run build     # web/dist/ 생성. nginx 가 이 폴더를 그대로 서빙한다
```

`VITE_USE_MOCK` 을 설정하지 않은 채(기본값) 빌드해야 한다 - 그래야 실제 API를 쓴다.
`web/.env` 파일이 있다면 `VITE_USE_MOCK` 이 비어 있는지 반드시 확인할 것.

### 2. nginx 로 HTTP 우선 기동

```bash
cp deploy/nginx/http.conf deploy/nginx/active.conf   # 최초 1회
docker compose --profile prod up -d --build
```

이 시점에서 `http://<서버 IP>/` 로 접속되면 정상이다. HTTPS는 아직 없다.

### 3. DNS 확인 후 인증서 발급

`gyeotnun.duckdns.org` 가 이 서버의 공인 IP를 실제로 가리켜야 한다(DuckDNS 콘솔에서
등록/갱신). 아래로 확인:

```bash
dig +short gyeotnun.duckdns.org @8.8.8.8   # 이 서버의 공인 IP와 같아야 한다
```

같다면:

```bash
bash deploy/init-letsencrypt.sh
```

dry-run → 실제 발급 → `active.conf` 를 `https.conf` 로 교체 → nginx reload 까지
자동으로 진행한다(중간에 확인 프롬프트 있음).

★ DNS가 안 맞는 상태로 실행하면 Let's Encrypt 검증이 실패한다. 반복 실패 시
Rate Limit(동일 도메인 1주일 5회)에 걸리니 dry-run 이 성공한 뒤에만 실제 발급으로
넘어갈 것.

### 4. 인증서 자동 갱신

`certbot` 서비스가 12시간마다 `certbot renew` 를 시도한다(만료 30일 이내에만 실제
갱신). 갱신 후 nginx 가 새 인증서를 읽으려면 reload 가 필요한데, 이건 자동화돼 있지
않아 crontab 에 등록해 뒀다(`crontab -l` 로 확인 가능, **등록 완료**):

```
0 3 * * * cd /home/ubuntu/gyeotnun && sudo docker compose --profile prod exec nginx nginx -s reload >> /home/ubuntu/gyeotnun/deploy/nginx-reload.log 2>&1
```

★ `sudo` 가 붙어 있다. 이 서버에서는 `ubuntu` 계정이 `docker` 그룹에 속해 있어도
(과거 로그인 세션 기준) 매 cron 실행마다 그룹 재적용이 보장되지 않아, 확실하게
동작하는 `sudo`(NOPASSWD 설정됨) 를 그대로 썼다. 로그는
`deploy/nginx-reload.log` 에 쌓인다(.gitignore 대상).

## 파일 구조

```
deploy/
  nginx/
    http.conf         HTTP 전용 설정 (인증서 발급 전 단계, 커밋됨)
    https.conf         HTTPS 설정 (인증서 발급 후, 커밋됨)
    active.conf         실제 컨테이너에 마운트되는 파일. http.conf 또는 https.conf 를
                         복사해서 만든다. .gitignore 대상 - 서버 로컬 산출물이라 커밋 안 함.
  certbot/
    www/                 ACME HTTP-01 챌린지 webroot (.gitignore, 인증서 발급 때만 사용)
    conf/                Let's Encrypt 인증서·개인키 저장소 (.gitignore, 절대 커밋 금지)
  init-letsencrypt.sh    최초 인증서 발급 자동화 스크립트
```

## 트러블슈팅

- **502 Bad Gateway**: `api` 컨테이너가 안 떠 있거나 재시작 중. `docker compose ps` 확인.
- **`GET /` 가 500(rewrite or internal redirection cycle)**: `web/dist` 를
  `rm -rf dist && npm run build` 처럼 **디렉터리째 삭제 후 재생성**하면, 이미 떠
  있는 nginx 컨테이너의 바인드 마운트가 옛 디렉터리(inode)를 붙들고 있어 새
  디렉터리를 못 본다(컨테이너 안에서 `/usr/share/nginx/html` 이 빈 폴더로
  보임). `npm run build` 만 다시 돌리는 건 안전하다(Vite 가 `dist` 를 지우지
  않고 안의 파일만 정리·교체한다) - 문제는 오직 `rm -rf dist` 로 디렉터리
  자체를 지웠을 때만 생긴다. 이미 걸렸다면
  `docker compose --profile prod up -d --force-recreate nginx` 로 마운트를
  다시 맺어야 한다(`restart`/`up -d`만으로는 재마운트가 안 될 수 있다).
- **413 Request Entity Too Large**: nginx 의 `client_max_body_size` 는 11MB로
  일부러 앱의 10MB 제한보다 1MB 여유를 뒀다(앱이 먼저 친절한 안내를 보여주게 하려고).
  11MB를 넘는 진짜 대용량 업로드만 nginx 선에서 막힌다.
- **PWA 설치(홈 화면에 추가)가 안 뜬다**: Android Chrome 기준 manifest + service
  worker + 아이콘 + **HTTPS(또는 localhost)** 가 모두 있어야 설치 프롬프트가 뜬다.
  HTTP로 IP 접속 중이면 `window.isSecureContext` 가 `false`라 서비스워커 등록 자체가
  브라우저에서 막힌다 - 이 항목만은 인증서 발급 전엔 검증할 수 없다.
- **DB 접속하고 싶을 때**: 포트를 안 열어 뒀으므로 `docker compose exec db psql -U
  gyeotnun` 로 컨테이너 안에서 접속한다.
