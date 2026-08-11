# 곁눈 (Gyeotnun)

> **판정하지 않습니다. 함께 확인합니다.**
> 팀 **Second Look** (6인) · 해커톤 프로젝트

**배포 주소: <https://gyeotnun.duckdns.org>** — PWA로 설치 가능(Android Chrome:
주소창 메뉴 → "홈 화면에 추가"). 인증서는 Let's Encrypt, 90일마다 자동 갱신.

---

## 1. 무슨 서비스인가

시니어가 카카오톡·유튜브에서 받은 의심스러운 정보를 **사진 한 장 또는 링크**로 올리면,
AI가 **진위를 판정하지 않고** 스스로 확인할 수 있는 **질문을 하나씩** 던져 판단을 돕습니다.
판단이 끝나면 **확인 취약 유형을 태깅**해, 다음 날 **5분 훈련**으로 연결합니다.

### 왜 판정하지 않는가

기존 팩트체크 서비스는 "이건 가짜입니다"라고 알려줍니다. 그런데,

| 판정해 줄 때 생기는 문제 | 곁눈의 선택 |
|---|---|
| 사용자가 판단을 AI에 위임한다 (의존 심화) | 사용자가 직접 확인하게 만든다 |
| 틀린 판정 한 번이면 서비스 신뢰가 무너진다 | 판정하지 않으니 틀릴 것이 없다 |
| 어르신을 '속은 사람'으로 만든다 (자존감 훼손) | 확인한 행동 자체를 칭찬한다 |
| 이번 한 건만 걸러진다 | 다음번엔 스스로 거를 수 있게 된다 |

곁눈의 목표는 **"이번 한 건을 걸러 주는 것"이 아니라 "스스로 거를 수 있게 되는 것"** 입니다.

### 화면 흐름

```
S1 업로드      사진/링크/텍스트를 올린다 (+ 오늘의 연습 입구)
   ↓
S2 확인 중     OCR → 개인정보 마스킹 → 공공데이터 대조 → 검색
   ↓
S3 질문 카드   ★ AI 질문(파란 영역) + 실제 출처 링크(초록 영역)를 시각적으로 분리
   ↓
S4 판단 기록   '진짜/가짜'가 아니라 '내가 어떻게 할지'를 고른다 → 확인 취약 유형 태깅
   ↓
S5 훈련/리포트 5분 훈련 카드 + 주간 리포트(가족 공유)
```

---

## 심사위원 3분 데모

1. 배포 주소 <https://gyeotnun.duckdns.org> 에 접속합니다.
2. 예시 문자(사기 의심 문구)를 입력하거나 카톡 캡처를 올립니다.
3. **확인 질문 카드**가 뜨는지 봅니다 — 진위를 판정하지 않고, 스스로 확인할 질문을 하나씩 줍니다.
4. 외부 API 장애 시 주소 끝에 `?mock=1` 을 붙이면 고정 응답으로 폴백해 데모가 이어집니다.

---

## 검증 결과 (예선 평가 세트 30건)

| 지표 | 결과 |
|---|---|
| 근거 검색 성공률 | 15/18 (83.3%) |
| Top-3 정답 포함 | 13/18 (72.2%) |
| 잘못된 근거 제시 | 0건 |
| 확인불가 정확 처리 | 7/8 |

라벨 정의·재현 절차: [`docs/evaluation/label_reclassification_20260810.md`](docs/evaluation/label_reclassification_20260810.md)

---

## 2. 빠른 시작 (3줄)

```bash
cp .env.example .env                                  # 키는 비워 둬도 된다 (mock 모드로 동작)
cd api && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
cd ../web && npm install && npm run dev               # http://localhost:5173
```

- API 문서(Swagger): <http://localhost:8000/docs>
- 헬스체크: <http://localhost:8000/health>
- **API 키가 하나도 없어도 전체 플로우가 동작합니다.** (아래 mock 사용법 참고)

### Docker 로 한 번에

```bash
cp .env.example .env      # ★ 이 파일이 없으면 compose 가 멈춘다
docker compose up --build # api(127.0.0.1:8000만) + postgres(내부 네트워크 전용)
```

### 배포 (nginx + HTTPS)

로컬 개발용 위 두 명령과 별도로, 배포는 `prod` 프로파일로 nginx·certbot까지 띄운다.
자세한 절차·트러블슈팅은 [`deploy/README.md`](deploy/README.md) 참고.

```bash
cd web && npm run build                      # web/dist 생성 (VITE_USE_MOCK 비워 둘 것)
docker compose --profile prod up -d --build   # api + db + nginx + certbot
```

---

## 새로 클론한 환경에서

검색 대상 문서와 색인은 저장소에 포함하지 않았습니다. 수집한
공공기관 자료 가운데 상당수가 개별 이용 조건 확인이 필요한
상태여서, 확인이 끝나기 전까지 공개 저장소에 재배포하지 않기로
했습니다.

따라서 새로 클론한 환경에서는 근거 검색 결과가 0건으로 나옵니다.
키워드 검색으로 전환되더라도 검색 대상 문서 자체가 없기 때문입니다.
서비스 동작은 배포된 주소에서 확인하실 수 있습니다.

---

## 3. mock 사용법 ★ 가장 먼저 읽을 것

**모든 엔드포인트는 `?mock=1` 을 붙이면 `api/mocks/fixtures.py` 의 고정 응답을 돌려줍니다.**

```bash
curl "http://localhost:8000/api/v1/checks/chk_demo/evidence?mock=1"
curl "http://localhost:8000/api/v1/training/today?mock=1"
curl -X POST "http://localhost:8000/api/v1/checks?mock=1" -F "device_id=demo"
```

프론트는 **기본값이 실제 API(mock OFF)** 입니다 (`web/src/api.js`). 우선순위는
주소창 쿼리 `?mock=1`/`?mock=0` > 환경변수 `VITE_USE_MOCK=1`(`web/.env.example`
참고) > 기본값(false). 개발 중 백엔드 없이 화면만 보고 싶으면 `?mock=1` 을 붙이세요.

**시연 중 외부 API가 죽어도 `?mock=1` 로 즉시 폴백해 데모를 이어갈 수 있습니다.**

mock 이 아닐 때 키가 없으면 **501 + 안내 메시지**를 돌려줍니다(서버가 죽지 않음).

```json
{"detail": {"error": "missing_api_key", "key": "ANTHROPIC_API_KEY",
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요."}}
```

---

## 4. 팀 · 기여

폴더별 담당자·협업 규칙은 [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) 참고.

---

## 5. API 요약표

Base URL: 로컬 `http://localhost:8000/api/v1` · 배포 `https://gyeotnun.duckdns.org/api/v1`
· 모든 엔드포인트가 `?mock=1` 지원

| Method | Path | 설명 | 담당 |
|---|---|---|---|
| `GET` | `/health` | 헬스체크 + 어떤 키가 설정됐는지 | 박진영 |
| `POST` | `/checks` | multipart(image·link·text + device_id) 업로드 → 텍스트 추출 + 마스킹 | 박진 |
| `GET` | `/checks/{id}/evidence` | 공공데이터 대조 + 검색 결과 | 김유리 |
| `POST` | `/checks/{id}/dialogue` | 확인 질문 1개 생성 (판정 억제) | 김태희 |
| `POST` | `/checks/{id}/verdict` | 사용자 판단 기록 + 확인 취약 유형 태깅 | 장지석 |
| `GET` | `/training/today` | 오늘의 5분 훈련 카드 | 장지석 |
| `GET` | `/reports/weekly` | 주간 리포트 | 박진영 |
| `POST` | `/onboarding/diagnosis` | 첫 실행 3문항 진단 | 장지석 |
| `POST` | `/events` | 사용자 행동 이벤트 기록 (fire-and-forget, mock 없음) | 박진영 |
| `GET` | `/events/summary` | 화면별 체류시간·이탈률·클릭수·근거링크 클릭률 집계 | 박진영 |
| `GET` | `/errors/codes` | 오류 코드 전체 정의(단일 소스, mock 없음) | 박진영 |
| `GET` | `/errors/summary` | 최근 오류를 코드별로 집계 | 박진영 |

### 주요 응답 형태

```jsonc
// POST /checks
{"check_id":"chk_demo","extracted_text":"...","masked":true,
 "masked_items":[{"type":"phone","original_hint":"010-****-****","count":1}],
 "detected_domain":"policy","status":"extracted"}

// POST /checks/{id}/dialogue  요청 {"turn":1,"user_reply":null}
{"turn":1,"question":"두 문장 이내 질문","why":"이 질문을 하는 이유",
 "evidence_refs":["https://..."],"options":[{"id":"found","label":"..."}],"is_final":false}
```

전체 스키마: `/docs` (Swagger)

---

## 6. 판정 억제 장치 (서비스 정체성)

`api/services/prompt_chain.py` 에 **2단 안전장치**가 있습니다.

**1단 — `SYSTEM_PROMPT` (사전 억제)**
진위 판정 금지 / "가짜입니다·사기입니다·진짜입니다" 금지 / 한 번에 한 질문 /
근거는 제공된 검색 결과의 실제 링크만, 지어내지 말 것 /
출처를 못 찾으면 "찾지 못했다는 것 자체가 확인 신호" /
사용자의 기존 판단을 비난 금지 / 두 문장 이내 / 쉬운 말

**2단 — `validate_question(text, allowed_refs)` (사후 차단)**
프롬프트는 뚫릴 수 있으므로 코드로 다시 검사합니다.

| 검사 | 동작 |
|---|---|
| 금지어 (`가짜`, `사기`, `진짜입니다`, `확실합니다`, `허위`, `속으신`, …) | `ValidationError(reason="forbidden_word")` → **재생성 신호** |
| 링크 | `allowed_refs`(실제 검색 결과)에 없는 URL은 **제거** (본문에 박힌 URL 포함) |
| 길이 | 2문장 초과 시 `ValidationError(reason="too_long")` |

이 함수는 `api/tests/test_smoke.py` 에서 단위 테스트로 고정되어 있습니다.
**프롬프트를 고칠 때마다 `pytest` 를 돌려 이 테스트가 통과하는지 확인하세요.**

```bash
cd api && python -m pytest tests/ -q
```

---

## 7. 개인정보 · 보안

- `.env` 는 `.gitignore` **최상단**에 등록. 실제 키를 커밋하면 즉시 revoke 하고 팀에 알릴 것.
- **원본 이미지는 처리 후 파기**합니다. 디스크에 쓰지 않고 메모리에서만 다룹니다.
- **DB 에는 마스킹된 텍스트만** 저장합니다 (`checks.masked_text`).
  원본 텍스트 컬럼은 의도적으로 만들지 않았습니다. 추가하지 마세요.
- 전화번호·계좌번호·주민번호·카드번호는 `services/masking.py` 에서 정규식으로 치환됩니다.

```python
mask_text("연락처 010-1234-5678 계좌 123-456-789012")
# → "연락처 010-****-**** 계좌 ***-***-******"
```

- 사용자 식별은 `device_id` 의 **SHA-256 해시**만 사용합니다. 이름·연락처를 받지 않습니다.
- 얼굴 마스킹은 TODO (박진) — Vision face detection + 가우시안 블러 예정.

### 사용자 행동 계측 (2026-08 추가, 8/5 사용성 테스트용)

- 목적: 60대 사용성 테스트에서 화면별 체류시간·이탈률·클릭수·근거 링크 클릭률
  같은 정량 지표를 얻기 위함입니다. `POST /api/v1/events` → `events` 테이블.
- **수집 항목**: 화면 진입/이탈 시각(S1~S5), 버튼 클릭(어떤 버튼을 몇 번),
  화면 진입~첫 클릭 소요시간, 근거 링크 클릭 여부, 오류 발생(OCR 실패·업로드
  실패 등 **오류 유형 코드만** - 오류 메시지 원문은 저장하지 않음).
- **절대 수집하지 않는 것**: 화면에 입력된 내용(붙여넣은 글, 질문 답변의 자유
  서술 등)은 수집하지 않습니다. 버튼 id·화면 이름·시각만 남깁니다.
- `device_id` 는 다른 테이블과 동일하게 **SHA-256 해시**로만 저장합니다.
  `session_id`(브라우저 세션 UUID)는 개인정보가 아니라, 같은 기기를 여러
  참가자가 돌려 쓰는 사용성 테스트 특성상 방문 단위를 구분하기 위한 임의값입니다.
- 계측은 **fire-and-forget**입니다 - 실패해도 화면 흐름을 막지 않고, 응답을
  기다리지 않아 화면 반응 속도에 영향을 주지 않습니다(`web/src/events.js`).
- 집계: `GET /api/v1/events/summary` (화면별 평균 체류시간/이탈률/첫클릭시간,
  버튼별 클릭수, 근거 링크 클릭률, 오류 유형별 건수를 즉시 JSON으로 반환).

---

## 8. DB 스키마 (9테이블)

`api/models/db.py`

| 테이블 | 역할 |
|---|---|
| `users` | 비회원 사용자 (device 해시, 취약 유형, 연속 일수) |
| `checks` | 확인 요청 1건 (**마스킹 텍스트만** 저장) |
| `evidence` | 검색·대조 결과 (verdict_hint, signals, references) |
| `taggings` | 사용자 판단 + 확인 취약 유형 태깅 |
| `training_cards` | 5분 훈련 카드 |
| `corpus` | 공공데이터 문서 (규모는 표 아래 참고) |
| `weekly_reports` | 주간 리포트 스냅샷 |
| `events` | 사용자 행동 계측 (화면 진입/이탈·클릭·오류 - **입력 내용 없음**, device 해시만) |
| `error_logs` | 장애 로그(2026-08) - 코드/화면/device 해시/짧은 진단정보만, **개인정보 없음** |

> **코퍼스 규모**
> - 라이브 인덱스 1,052문서 / 2,012청크 (기획서 평가 기준, 현재 서빙 중인 검색 인덱스)
> - 디스크 재구성본 1,017 / 2,065 는 차기 인덱스 빌드 예정 (현재 검색 미반영)

### 오류 코드 체계 (2026-08 추가, 8/2 보안 멘토링 지시사항)

- 목적: 심사 배점(시스템 오류 대비·복구) 대응 - 모든 오류 응답과 화면에 코드를
  실어 문의 시 식별할 수 있게 한다.
- 단일 소스: `api/services/error_codes.py` (영역별 접두어: 입력 IN·인식 RC·
  마스킹 MK·검색 SR·생성 GN·저장 ST·외부연동 EX·공통 SYS). 프론트는 이 표를
  `GET /api/v1/errors/codes` 로 받아서 쓴다 - 프론트에 따로 복사해 두지 않는다.
- 표 전체(코드/상황/사용자 안내/복구 방법)는 [`docs/error_codes.md`](docs/error_codes.md)
  (`api/tools/gen_error_codes_doc.py` 로 단일 소스에서 자동 생성).
- 장애 로그: 서버가 스스로 인지한 실패는 `error_logs` 테이블에(`services/incident_log.py`,
  DB 쓰기 자체가 실패해도 절대 상위로 예외를 던지지 않는다), 프론트가 신고한 오류는
  기존 `events` 테이블(`event_type=error`, `target`에 오류 코드)에 남는다.
  `GET /api/v1/errors/summary` 로 두 표를 코드 기준으로 합쳐 집계한다.
- **주의**: 코드를 부여하는 작업이지 폴백 동작을 바꾸는 작업이 아니다 - 임베딩
  실패 시 BM25 자동 전환(EX-003), 질문 재생성 실패 시 기본 질문 대체(GN-001),
  태깅 LLM 실패 시 규칙 기반 대체(GN-002) 등 기존 폴백은 그대로 두고 코드+로그만
  추가했다.

---

## 9. 시니어 UX 기준 (프론트 리뷰 체크리스트)

`web/src/styles.css` 에 수치로 박아 두었습니다. PR 리뷰 시 이것부터 확인하세요.

- [ ] 본문 **18px 이상** (현재 19px), 제목 **24px 이상** (현재 27px)
- [ ] 버튼 **min-height 56px 이상** (현재 60px), **폭 80% 이상** (현재 100%)
- [ ] 버튼에 **테두리 3px + 그림자**
- [ ] 명도 대비 **7:1 이상** (WCAG AAA)
- [ ] **단독 화살표·아이콘 버튼 금지** — "다음 →" 처럼 글자를 반드시 병기
- [ ] 얇은 폰트(300) 금지, 최소 500
- [ ] `user-scalable=no` 금지 (확대를 막지 않는다)
- [ ] **S3 화면에서 AI 문장(파란 영역)과 실제 출처(초록 점선 영역)가 시각적으로 분리**되어 있는가 ★

---

## 11. 지금 상태

**동작함 (키 없이)**
- 전 엔드포인트 `?mock=1` 응답 · `validate_question()` 판정 억제 검증 ·
  텍스트 마스킹(전화/계좌/주민/카드) · 규칙 기반 신호 탐지 · 확인 취약 유형 태깅 ·
  샘플 훈련카드 3장 · 프론트 5개 화면 전체 플로우

**동작함 (ANTHROPIC_API_KEY 필요, `?mock=0`)**
- 이미지 인식과 근거 검색은 자체 서버의 로컬 모델로 처리합니다.
  외부 인공지능 서비스는 확인 질문을 생성하는 단계에서만 사용하며,
  이때 전달되는 것은 개인정보가 제거된 문장뿐입니다.

  ```
  이미지 인식   PaddleOCR (자체 서버)
  근거 검색     e5-small-ko-v2 (자체 서버)
  질문 생성     Claude API
  ```
- 근거 검색: `dragonkue/multilingual-e5-small-ko-v2`(384차원) 임베딩 + BM25
  자동 폴백. 평가 세트 실측 근거 검색 성공률 15/18건(83.3%),
  잘못된 근거 제시 0건 (`services/search.py`, `services/corpus_index.py`)
- 질문 생성: Claude(`claude-sonnet-5`)로 실제 호출 + 재생성 루프 + 프롬프트 캐싱
  (`services/prompt_chain.py`)
- 근거 대조: `근거_검증표`/`평가세트`/`사례_재라벨링표` CSV 로컬 인덱스 대조 +
  공공데이터 대상 **임베딩 검색을 채택해 프로덕션 적용**(`services/embeddings.py`,
  `search.match_official_docs_safe`). BM25 단독 대비 정상 근거매칭 7/10→10/10,
  Recall@3 30%→65%, 경계 확인불가 1/10→3/10(정상 오판은 0/10 그대로 유지).
  - **★ 2026-08-04 부터 임베딩은 자체 서버의 로컬 모델로 돈다** —
    `EMBEDDING_PROVIDER = "local"`, `dragonkue/multilingual-e5-small-ko-v2`
    (Apache-2.0, 384차원). 30건 재측정에서 Upstage 대비 Recall@3 0.65 동일,
    근거검색 0.867→0.900 로 오히려 개선, 정상 10건 오판 0/10 유지, 질의
    112ms→141ms. 바꾼 가장 큰 이유는 성능이 아니라 개인정보다 - **사용자
    질의 텍스트가 외부 API 로 나가지 않는다.** 로컬 후보 5종 중 유일하게
    정상/경계 유사도가 분리돼(정상min 0.6820 > 경계max 0.6760) 확신 판정이
    가능했다. 근거는
    [`docs/evaluation/local_embeddings_report.md`](docs/evaluation/local_embeddings_report.md).
  - 롤백 경로는 살려 뒀다: `embeddings.py` 의 `EMBEDDING_PROVIDER` 를
    `"upstage"` 로 되돌리면 Upstage Solar Embedding 경로가 그대로 다시 돈다
    (`_embed_upstage()` 미삭제, `UPSTAGE_API_KEY` 는 그때만 필요).
  - 임베딩을 쓸 수 없을 때(인덱스 파일 없음·모델 로드 실패·질의 3초 타임아웃)는
    로컬 BM25 검색(`services/corpus_index.py`)으로 자동 폴백하며 그 사실을
    로그로 남긴다.
  - RRF 하이브리드 결합(`search.match_official_docs_hybrid`)은 벤치마크 결과
    임베딩 단독보다 나은 지표가 없어 미채택했지만, 코드는 삭제하지 않고 남겨 뒀다.
    비교표는
    [`docs/evaluation/hybrid_search_report.md`](docs/evaluation/hybrid_search_report.md).
- 확인 취약 유형 태깅: Claude 프롬프팅 기반 분류(`services/tagger.py` `tag_error_type_llm`),
  실패 시 규칙 기반으로 자동 폴백
- PWA: 아이콘·Web Share Target·service worker 적용, 설치 조건 실측 통과
- **배포: <https://gyeotnun.duckdns.org> 로 실제 서비스 중.** 자세한 내용은
  아래 [12. 배포 · 인프라](#12-배포--인프라) 참고.

**남은 과제 (담당자별)**

아래는 실제로 아직 안 된 것만 남긴 목록이다. 끝난 항목(공공데이터 수집·변환)은
지웠다 — 결과는 위 [8. DB 스키마](#8-db-스키마-9테이블) 의 코퍼스 규모에 있다.

- 박진: 링크 본문 추출, 얼굴 블러 (`services/masking.py` 는 아직 스텁이고,
  얼굴 마스킹 미적용 사실을 응답에 명시한다)
- 김유리: 네이버 검색 API 연동 — 최신 이슈 보강용 **선택 레이어**다.
  근거 검색 자체는 임베딩 + BM25 로 이미 동작한다(`services/search.py` 4번 경로).
- 김태희: 프롬프트 튜닝(질문 길이 등)
- 장지석: 코퍼스 → 훈련 카드 자동 생성
  (지금은 고정 샘플 3장뿐 —
  [`docs/evaluation/training_card_status.md`](docs/evaluation/training_card_status.md))
- 조희진: iOS 대체 경로 실기기 테스트(Share Target 은 Android Chrome 전용)
- 박진영: 메모리 저장소 → DB 세션 교체, Alembic 마이그레이션

---

## 12. 배포 · 인프라

**주소**: <https://gyeotnun.duckdns.org> (DuckDNS + Let's Encrypt)

```
인터넷 → nginx(80/443, 컨테이너) → api (127.0.0.1 전용, 도커 내부망으로만 붙음)
                                  → db  (호스트 포트 없음, 내부망 전용)
```

- `docker compose --profile prod up -d --build` 로 nginx·certbot 까지 함께 기동한다.
  로컬 개발(`docker compose up`)에는 이 둘이 안 뜬다 — nginx/certbot 은
  `profiles: ["prod"]` 로 분리돼 있다.
- **호스트에 외부로 열린 포트는 80 / 443 / 22 뿐이다.** api(8000)는
  `127.0.0.1:8000` 으로만 바인딩돼 있어 nginx 를 거치지 않고는 접근할 수 없고,
  db는 호스트 포트 자체가 없다(기본 비밀번호를 인터넷에 노출하지 않기 위함).
- 인증서는 `deploy/init-letsencrypt.sh` 로 최초 발급했다(만료: 2026-10-27).
  `certbot` 컨테이너가 12시간마다 자동 갱신을 시도한다(실제 갱신은 만료 30일
  이내에만 일어난다). nginx reload 는 자동이 아니라 crontab 에 매일 새벽 3시
  등록해 뒀다(`deploy/README.md` 참고).
- PWA 설치 조건(manifest·아이콘·service worker·HTTPS)을 Chrome DevTools의
  `Page.getInstallabilityErrors` 로 실측 확인했다(빈 배열 = 조건 충족). Android
  Chrome에서 "홈 화면에 추가"가 뜬다. iOS Safari는 Web Share Target을 지원하지
  않아 '사진 올리기' 버튼 경로가 그 대체 경로다.
- 업로드 크기 한도: nginx `client_max_body_size 11m` (api의 `MAX_UPLOAD_MB=10`
  보다 1MB 여유를 둬서, 10~11MB 구간은 nginx 기본 에러 페이지 대신 앱의 안내
  메시지가 뜨게 했다).
- 자세한 절차·트러블슈팅: [`deploy/README.md`](deploy/README.md)

---

## 알려진 한계

- 기록 조회의 소유자 대조는 화면이 보내는 기기 식별자에 기대고
  있습니다. 서버가 발급하는 인증은 본선 단계에서 적용합니다.
- 확인 기록을 프로세스 메모리에 보관하므로 처리 프로세스가
  하나입니다. 여러 이용자가 동시에 요청하면 순서대로 처리됩니다.
- 생성된 질문이 입력에 없는 내용을 전제하는지는 아직 검사하지
  않습니다.
- 발신자명이 채팅 화면 상단에 있을 때 말풍선 영역 밖으로 판단해
  인식하지 못하는 경우가 있습니다.
