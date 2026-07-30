# corpus - 곁눈 근거 데이터

담당: 장지석 (코퍼스·RAG), 김유리 (검색 대조)

## 무엇이 들어가는가

| 폴더 | 내용 | 쓰는 곳 |
|---|---|---|
| `public_data/gyeotnun_data/` | 공공데이터 1,017건(records_merged.jsonl) - 996건은 OFFICIAL_DOCS, 21건(짧은 사기 경보문)은 SCAM_CASES로 분리 적재 | `services/corpus_index.py` OFFICIAL_DOCS/OFFICIAL_CHUNKS + SCAM_CASES |
| `training_cards/` | 매일 5분 훈련 카드 | `services/rag.py` → `GET /training/today` |

★ **1,017건이 그대로 OFFICIAL_DOCS에 다 들어가지는 않는다.** `data_type`이
`warning_case`/`press_release`이면서 본문이 200자 이하인 21건(피싱안심SOS 예·경보 등,
개별 사건을 짧게 알리는 경보문)은 SCAM_CASES(재라벨링표 30건 + 이 21건 = 51건,
`origin="public_data_warning"`으로 구분)로 옮겨진다 - "공식 자료를 찾았습니다"로
안내하기보다 "유사 사기 사례"로 다루는 게 더 정확하기 때문이다. 나머지 996건은
OFFICIAL_DOCS에 남는다. 자세한 이유와 실측 근거는 `api/services/corpus_index.py`의
`_SCAM_PATTERN_DATA_TYPES`/`_SCAM_PATTERN_MAX_CHARS` 주석과
[`docs/evaluation/eval_30_report.md`](../docs/evaluation/eval_30_report.md) §9~13 참고.

## public_data/gyeotnun_data — 공공데이터 1,017건 (★ 이 파일은 별도 전달, git에 커밋하지 않음)

데이터팀이 2026-07-30 전달한 배치. 아래 4개 파일이 `corpus/public_data/gyeotnun_data/`에
들어 있어야 코드가 동작한다 — **git에는 없다.** `.gitignore`의 `corpus/public_data/*` 규칙에
그대로 걸려 자동으로 제외된다(용량 6.4MB, 아래 "커밋 여부 판단" 참고). 팀 공유 드라이브로
받아서 이 경로에 그대로 풀어 넣을 것.

| 파일 | 내용 |
|---|---|
| `records_merged.jsonl` | 원본 문서 1,017건(1줄 1건). `id, domain, data_type, title, content, source_name, source_agency, source_url, published_at, collected_at, original_id, risk_types, trust_cues, attachment_urls, license, content_hash` 필드 |
| `chunks_merged.jsonl` | 데이터팀이 전달한 원본 청크(2,065건, 999/1,017 문서만 커버) — 참고용으로 남겨 두되, 실제 검색 인덱스는 `corpus_index.py`가 `records_merged.jsonl`을 **직접 재청킹**해서 만든다(1,017건 전체 커버, §재청킹 참고) |
| `records_merged.csv` | 사람이 눈으로 확인하기 위한 CSV 사본 |
| `expansion_summary.json` / `expansion_report.md` | 수집 요약(출처별/도메인별 건수) |

출처 구성: 한국사회보장정보원 복지서비스정보 367 · 질병관리청 국가건강정보포털 164 ·
NIA 2025 디지털정보격차 실태조사 297 · 경찰청 보이스피싱 현황 10 ·
KISA 피싱·사칭 관련 보도자료 133 · 피싱안심SOS 예경보/보도자료 46 = 1,017건.
domain 필드는 `public_support`(367) / `digital_literacy`(297) / `finance`(189) / `health`(164)
4종이다.

### 커밋 여부 판단(요청에 따른 기록)

`records_merged.jsonl`·`chunks_merged.jsonl` 각 3.2MB, 합쳐서 6.4MB — **git에 커밋하지
않는다.** 이유:
1. 용량 문제는 예전 577건 계획 때부터 이미 정책으로 정해져 있었다(`.gitignore`의
   `corpus/public_data/*` 규칙, 이번 배치가 도착하기 전부터 존재). 새 데이터라고
   예외를 둘 이유가 없다 — 정책 일관성이 더 중요하다.
2. 원본은 정부 공공포털(복지로/질병관리청/NIA/경찰청/KISA)에서 수집한 2차 자료라
   재수집·재전달이 가능하다 — 사용자가 직접 만든, 유실되면 복구 불가능한 콘텐츠가 아니다.
3. 리포지토리를 가볍게 유지해 clone/CI 속도에 영향을 주지 않는다.

대신 무결성은 README의 SHA-256 해시로 검증 가능하고, 이 문서에 "별도 전달"임을 명시해
새로 합류하는 사람이 파일이 안 보인다고 당황하지 않게 한다.

### 재청킹 (`corpus_index.py`가 기동 시 직접 수행)

전달받은 `chunks_merged.jsonl`은 999/1,017 문서만 커버한다(너무 짧은 경보문 18건이
청크 생성 기준에서 빠짐 — 전달 문서의 README 참고). 이 청크 파일을 그대로 쓰지 않고,
`records_merged.jsonl`(1,017건 전체)을 원본으로 직접 재청킹해서 1,017건 전체를
검색 대상으로 커버한다. 청크 크기는 기존과 비슷한 수준(평균 585자대)으로 맞췄고,
`title/source_agency/source_url/published_at/domain/data_type` 메타데이터를 청크에
그대로 들고 다닌다. 구현: `api/services/corpus_index.py`의 `_rechunk_official_docs()`.

## training_cards

- `sample_cards.json` 에 유형별 샘플 3건이 들어 있다. 형식을 그대로 따라 늘려 나간다.
- 카드 지문은 반드시 `public_data` 원문에서 파생시킨다.
  '있을 법한 가짜뉴스'를 창작해 넣지 않는다 — 훈련 자체가 허구가 된다.
- 변형은 결정적 규칙으로만: 조건절 삭제 / 숫자 변경 / 기관명 삭제 / 제목만 남기기.

## 진행 체크리스트

- [x] 공공데이터 수집 및 JSON 변환 — 577건 → 1,017건으로 확장 완료(2026-07-30)
- [x] `url` 누락 건 정리 — 로더가 http(s) 아닌 `source_url` 행을 자동 제외
- [x] 도메인 라벨링 — `public_support/digital_literacy/finance/health` 4종
- [ ] 유형별 훈련카드 각 10장 (총 40장) 확보
