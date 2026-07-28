# 곁눈 (Gyeotnun)

> **판정하지 않습니다. 함께 확인합니다.**
> 팀 **Second Look** (6인) · 해커톤 프로젝트

---

## 1. 무슨 서비스인가

시니어가 카카오톡·유튜브에서 받은 의심스러운 정보를 **사진 한 장 또는 링크**로 올리면,
AI가 **진위를 판정하지 않고** 스스로 확인할 수 있는 **질문을 하나씩** 던져 판단을 돕습니다.
판단이 끝나면 **오판유형을 태깅**해, 다음 날 **5분 훈련**으로 연결합니다.

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
S4 판단 기록   '진짜/가짜'가 아니라 '내가 어떻게 할지'를 고른다 → 오판유형 태깅
   ↓
S5 훈련/리포트 5분 훈련 카드 + 주간 리포트(가족 공유)
```

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
docker compose up --build # api(8000) + postgres(5432)
```

---

## 3. mock 사용법 ★ 가장 먼저 읽을 것

**모든 엔드포인트는 `?mock=1` 을 붙이면 `api/mocks/fixtures.py` 의 고정 응답을 돌려줍니다.**

```bash
curl "http://localhost:8000/api/v1/checks/chk_demo/evidence?mock=1"
curl "http://localhost:8000/api/v1/training/today?mock=1"
curl -X POST "http://localhost:8000/api/v1/checks?mock=1" -F "device_id=demo"
```

프론트는 **기본값이 mock ON** 입니다 (`web/src/api.js`).
실제 백엔드에 붙이려면 주소창에 `?mock=0` 을 붙이거나 `api.js` 의 `USE_MOCK` 을 바꾸세요.

왜 이렇게 했는가
1. 프론트(조희진)가 백엔드 완성을 기다리지 않고 화면을 끝까지 만들 수 있다.
2. API 키 발급이 늦거나 한도가 막혀도 개발이 멈추지 않는다.
3. **시연 중 외부 API가 죽어도 데모는 끝까지 돌아간다.** (가장 중요)

mock 이 아닐 때 키가 없으면 **501 + 안내 메시지**를 돌려줍니다(서버가 죽지 않음).

```json
{"detail": {"error": "missing_api_key", "key": "ANTHROPIC_API_KEY",
            "hint": "지금 바로 확인하려면 같은 요청에 ?mock=1 을 붙이세요."}}
```

---

## 4. 폴더별 담당자

| 담당 | 영역 | 주요 파일 |
|---|---|---|
| **박진** | 인식 · 마스킹 | `api/services/ocr.py`, `api/services/masking.py` |
| **김유리** | 검색 · 공공데이터 대조 | `api/services/search.py` |
| **김태희** | 프롬프트 (판정 억제) | `api/services/prompt_chain.py` |
| **장지석** | 태깅 · RAG · 코퍼스 | `api/services/tagger.py`, `api/services/rag.py`, `corpus/` |
| **조희진** | 프론트 | `web/` 전체 |
| **박진영** | API · DB · 배포 | `api/main.py`, `api/routers/`, `api/models/`, `docker-compose.yml` |

> 남의 폴더를 고쳐야 하면 먼저 담당자에게 말하세요.
> 단, `api/models/schemas.py`(계약서)는 **바꾸기 전에 반드시 팀 채널 공지**.

---

## 5. API 요약표

Base URL: `http://localhost:8000/api/v1` · 모든 엔드포인트가 `?mock=1` 지원

| Method | Path | 설명 | 담당 |
|---|---|---|---|
| `GET` | `/health` | 헬스체크 + 어떤 키가 설정됐는지 | 박진영 |
| `POST` | `/checks` | multipart(image·link·text + device_id) 업로드 → 텍스트 추출 + 마스킹 | 박진 |
| `GET` | `/checks/{id}/evidence` | 공공데이터 대조 + 검색 결과 | 김유리 |
| `POST` | `/checks/{id}/dialogue` | 확인 질문 1개 생성 (판정 억제) | 김태희 |
| `POST` | `/checks/{id}/verdict` | 사용자 판단 기록 + 오판유형 태깅 | 장지석 |
| `GET` | `/training/today` | 오늘의 5분 훈련 카드 | 장지석 |
| `GET` | `/reports/weekly` | 주간 리포트 | 박진영 |
| `POST` | `/onboarding/diagnosis` | 첫 실행 3문항 진단 | 장지석 |

### 주요 응답 형태

```jsonc
// POST /checks
{"check_id":"chk_demo","extracted_text":"...","masked":true,
 "masked_items":[{"type":"phone","original_hint":"010-****-****","count":1}],
 "detected_domain":"policy","status":"extracted"}

// GET /checks/{id}/evidence   ★ verdict_hint 에 true/false 는 없다
{"check_id":"chk_demo","verdict_hint":"partially_matched",   // needs_check | partially_matched | no_source_found
 "signals":[{"key":"number_mismatch","label":"...","severity":"attention"}],
 "references":[{"title":"...","url":"https://...","publisher":"보건복지부","source_type":"gov"}]}

// POST /checks/{id}/dialogue  요청 {"turn":1,"user_reply":null}
{"turn":1,"question":"두 문장 이내 질문","why":"이 질문을 하는 이유",
 "evidence_refs":["https://..."],"options":[{"id":"found","label":"..."}],"is_final":false}

// POST /checks/{id}/verdict   요청 {"decision":"hold","reason_tags":[]}
// decision: apply | not_apply | hold | ask_family
{"check_id":"chk_demo","tagged_error_type":"number_condition","confidence":0.82,"message":"..."}
// tagged_error_type: title_dependent | authority_impersonation | number_condition | overgeneralization

// GET /training/today
{"card_id":"...","target_error_type":"number_condition","content":"...",
 "items":[{"id":"a","label":"..."}],"answer":"a","explanation":"...","estimated_sec":300}

// GET /reports/weekly
{"week":"2026-W30","checks_count":4,"training_completed":5,
 "error_type_trend":{"number_condition":2},"streak_days":5,"message":"..."}
```

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

---

## 8. DB 스키마 (7테이블)

`api/models/db.py`

| 테이블 | 역할 |
|---|---|
| `users` | 비회원 사용자 (device 해시, 취약 유형, 연속 일수) |
| `checks` | 확인 요청 1건 (**마스킹 텍스트만** 저장) |
| `evidence` | 검색·대조 결과 (verdict_hint, signals, references) |
| `taggings` | 사용자 판단 + 오판유형 태깅 |
| `training_cards` | 5분 훈련 카드 |
| `corpus` | 공공데이터 577건 |
| `weekly_reports` | 주간 리포트 스냅샷 |

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

## 10. 협업 규칙

1. **매일 push.** 로컬에만 두고 자면 다음 날 합칠 수 없습니다.
2. **`.env` 절대 커밋 금지.** 커밋 전 `git status` 로 확인하는 습관.
3. **브랜치: `feat/{모듈}`** — `feat/ocr`, `feat/search`, `feat/prompt`, `feat/tagger`, `feat/web`, `feat/api`
4. `main` 직접 push 금지. PR → 담당자 1명 확인 → merge.
5. `models/schemas.py` (API 계약) 수정은 **팀 채널 공지 필수.**
6. 커밋 메시지: `feat(ocr): Vision OCR 연동` / `fix(web): 버튼 높이 56px 미달 수정`
7. 막히면 30분 안에 물어보기. 혼자 붙잡고 있는 시간이 가장 비쌉니다.

---

## 11. 지금 상태 (스켈레톤)

**동작함 (키 없이)**
- 전 엔드포인트 `?mock=1` 응답 · `validate_question()` 판정 억제 검증 ·
  텍스트 마스킹(전화/계좌/주민/카드) · 규칙 기반 신호 탐지 · 오판유형 태깅 ·
  샘플 훈련카드 3장 · 프론트 5개 화면 전체 플로우

**TODO (담당자별)**
- 박진: Vision OCR 연동, 링크 본문 추출, 얼굴 블러
- 김유리: 네이버 검색 API 연동, 코퍼스 임베딩 검색
- 김태희: Claude API 호출 + 재생성 루프 (`generate_question`)
- 장지석: 공공데이터 577건 수집·변환, 코퍼스→훈련카드 자동 생성
- 조희진: PWA Share Target 활성화, 아이콘, 실기기 테스트
- 박진영: 메모리 저장소 → DB 세션 교체, Alembic, 배포
