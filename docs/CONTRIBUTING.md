# 기여 가이드 — 곁눈 (Gyeotnun)

## 폴더별 담당자

| 담당 | 영역 | 주요 파일 |
|---|---|---|
| **박진** | 인식 · 마스킹 | `api/services/ocr.py`, `api/services/masking.py` |
| **김유리** | 검색 · 공공데이터 대조 | `api/services/search.py` |
| **김태희** | 프롬프트 (판정 억제) | `api/services/prompt_chain.py` |
| **장지석** | 태깅 · RAG · 코퍼스 | `api/services/tagger.py`, `api/services/rag.py`, `corpus/` |
| **조희진** | 프론트 | `web/` 전체 |
| **박진영** | API · DB · 배포 | `api/main.py`, `api/routers/`, `api/models/`, `docker-compose.yml`, `deploy/` |

> 남의 폴더를 고쳐야 하면 먼저 담당자에게 말하세요.
> 단, `api/models/schemas.py`(계약서)는 **바꾸기 전에 반드시 팀 채널 공지**.

## 협업 규칙

1. **매일 push.** 로컬에만 두고 자면 다음 날 합칠 수 없습니다.
2. **`.env` 절대 커밋 금지.** 커밋 전 `git status` 로 확인하는 습관.
3. **브랜치: `feat/{모듈}`** — `feat/ocr`, `feat/search`, `feat/prompt`, `feat/tagger`, `feat/web`, `feat/api`
4. `main` 직접 push 금지. PR → 담당자 1명 확인 → merge.
5. `models/schemas.py` (API 계약) 수정은 **팀 채널 공지 필수.**
6. 커밋 메시지: `feat(ocr): Vision OCR 연동` / `fix(web): 버튼 높이 56px 미달 수정`
7. 막히면 30분 안에 물어보기. 혼자 붙잡고 있는 시간이 가장 비쌉니다.
