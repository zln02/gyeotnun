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

## 백엔드 배포 체크리스트 (★ 매 배포 필수)

백엔드(api) 를 다시 띄울 때는 **`docker compose restart api` 를 직접 치지 않는다.**
아래 스크립트가 재시작과 검사를 함께 한다.

```bash
deploy/verify_restart_race.sh        # 코드만 바뀐 경우
deploy/verify_restart_race.sh up     # docker-compose.yml 이 바뀐 경우
```

| 단계 | 검사 | 통과 기준 |
|---|---|---|
| 1 | 새 프로세스에서 기준 `verdict_hint` 계산 | 계산됨 |
| 2 | 재시작 **전** HTTP 응답 | 기준값과 일치 (다르면 지금 도는 프로세스가 이미 망가진 것) |
| 3 | 재시작 → **프리워밍이 도는 동안** 동시 5건 투입 | 5건 전부 HTTP 200 |
| 4 | `verdict_hint` 대조 | 5건 전부 기준값과 일치 |
| 5 | `EX-003`(임베딩 실패)·`EX-006`(폴백률)·`meta tensor` | **증가 0건** |
| 6 | 검사가 만든 `checks` 행 정리 | 삭제됨 (`EX-003` 기록은 지우지 않는다) |

실패하면 0이 아닌 코드로 끝난다. **그때는 배포를 완료로 보지 않는다.**

### ★ 왜 이 단계가 필요한가

2026-08-16 에 임베딩 지연 로더의 경합이 라이브로 나갔다. 프리워밍 스레드와 요청
스레드가 동시에 로더에 들어가 반쯤 만들어진 모델이 남았고, 그 프로세스는 재시작
전까지 **영구히 BM25 로만** 답했다. **터지지 않는 고장**이라 사용자에겐 200 이
나가고 근거 품질만 조용히 떨어졌다.

그래서 기존 게이트 세 개를 전부 통과했다.

| 게이트 | 왜 못 잡았나 |
|---|---|
| `pytest` | 단일 스레드라 경합이 안 일어난다 |
| `render_verdict.mjs` 142건 대조 | 별도 프로세스에서 계산해 서버 상태를 안 본다 |
| 동시성 출력 대조 | 프리워밍이 끝난 뒤 요청을 보내 경합 자체가 없었다 |

실제로 잡은 단서는 두 개였고 둘 다 **사람이 우연히** 본 것이다 — 서버 로그의
`EX-003`, 그리고 "같은 입력인데 재시작 전후 판정이 다르다". 이 스크립트는 그
우연을 절차로 바꾼 것이다.

★ 스크립트 자체가 실패할 때 정말 실패하는지도 확인해 두었다
(`SELFTEST=hint` / `SELFTEST=incident` — 두 판정 분기를 일부러 어긋나게 만든다).
**실패하는 걸 본 적 없는 게이트는 초록불의 의미가 없다.**

★ 운영 DB 를 더럽히지 않는다. 검사가 만든 `checks` 행은 `device_hash` 로 정확히
그 행만 골라 지운다. `EX-003`/`EX-006` 이 늘었다면 그건 **진짜 사고의 진짜 기록**
이므로 지우지 않는다.

---

## 운영 DB 삭제 규칙 (★ 예외 없음, 2026-08-17 확정)

**운영 DB 에서 행을 지우는 일은 `api/tools/delete_rows.py` 로만 한다.**
`psql -c "delete …"` 를 직접 치지 않는다.

```bash
docker compose exec -T api python -m tools.delete_rows \
    --table events --where "device_hash='…' and created_at >= '…'" --expect 17
#   → 백업 → 복원 리허설 → --expect 일치 확인까지 하고 멈춘다
#   → 실제로 지우려면 --yes 를 붙인다
```

| 순서 | 단계 | 끌 수 있나 |
|---|---|---|
| 1 | 대상 전체를 CSV 로 백업 (`api/data/deleted_rows/`) | **불가** |
| 2 | 백업을 임시 테이블에 넣어 **복원 리허설** (행수 + 내용 체크섬) | **불가** |
| 3 | `--expect` 와 실제 건수 일치 확인 | **불가** |
| 4 | `--yes` 가 있을 때만 삭제 | — |

### ★ 행 수와 무관하다

**"작아서 생략"이 2026-08-16 사고의 원인이다.** 1행이든 10만 행이든 같은 절차를 밟는다.
"17행뿐이니까" 로 시작해 262행을 지웠고, 8/01~8/06 관측 데이터 237행이 복구 불가로
사라졌다.

### ★ 지시에 안 적혀 있어도 적용된다

8/15 지시에는 백업 단계가 있었고 실제로 백업·리허설을 했다. 8/16 지시에는 없었고
그래서 안 했다 — **절차가 지시서에 실려 다니면, 지시서가 얇아질 때 절차도 얇아진다.**
이 규칙은 지시서와 무관하게 늘 적용된다.

### ★ 확인을 '출력'하는 것과 '차단'하는 것은 다르다

사고 당시 삭제 직전에 `89219851811ea6df|262` 를 화면에 찍었다. 숫자는 눈앞에 있었는데
같은 명령 안에서 곧바로 DELETE 가 실행됐다. 출력은 사람이 읽어야 작동하고, 그때
아무도 읽지 않았다. **차단만이 절차다.**

경위 전문: [`docs/reports/2026-08-17_사고기록_events_262행_삭제.txt`](../docs/reports/2026-08-17_사고기록_events_262행_삭제.txt)

---

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

### 5. 서버 cron 전체 (등록 완료, `crontab -l` 로 확인)

| 시각(UTC) | 하는 일 | 로그 |
|---|---|---|
| 03:00 | nginx reload (갱신된 인증서 반영) | `deploy/nginx-reload.log` |
| 04:00 | 보관 90일 초과 관측 로그 삭제 (`tools.purge_old_records`) | `deploy/purge.log` |
| 05:00 | **회귀 검사** (`tools.regression_check`) | `deploy/regression.log` |

```
0 5 * * * cd /home/ubuntu/gyeotnun && sudo docker compose exec -T api python -m tools.regression_check >> /home/ubuntu/gyeotnun/deploy/regression.log 2>&1
```

회귀 검사는 정상 오판 기준선(확대 평가셋 / 홀드아웃)과 `SCAM_CASES` 규모를 매일 재고
`tests/test_scam_threshold_regression.py` 3건을 돌린다. 통과/실패만이 아니라 **실측한
숫자 자체**를 남기므로, "언제부터 늘었나"를 로그만 보고 되짚을 수 있다.

```
[regression] 2026-08-15 11:04:59 UTC OK passed=3 failed=0 skipped=0 | SCAM_CASES=51건 / 확대평가셋 정상오판=1/37 / 홀드아웃 정상오판=1/10
```

- 실패 확인: `grep '\[regression\] FAIL' deploy/regression.log`
- ★ **스킵도 실패로 센다.** 코퍼스가 마운트되지 않으면 테스트는 실패가 아니라 스킵이고,
  스킵은 초록불처럼 보인다. 아무것도 검사하지 않은 초록불이 가장 위험하다.
- ★ GitHub Actions 를 쓰지 않는 이유가 그것이다. 검색 코퍼스는 저장소에 없어서
  호스트 러너에서는 이 테스트가 전부 스킵된다. 공개 저장소에 셀프호스트 러너를
  붙이는 것은 보안 사고 경로이기도 하다. 코퍼스가 실제로 있는 이 서버에서 돌린다.
- 운영 DB 에는 쓰지 않는다. pytest 는 `tests/conftest.py` 가 `DATABASE_URL` 을
  임시 SQLite 로 덮어쓴 상태에서 돈다.

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
