# 곁눈(Gyeotnun) 평가세트 30건 실측 성능 보고서

데이터: `corpus/곁눈_평가세트_30건.csv` (정상 10 · 사칭 10 · 경계 10)
실행 방식: mock 없이 실제 API(`?mock=0`) — 30건 각각 `POST /checks`(텍스트 입력) → `GET /checks/{id}/evidence` → `POST /checks/{id}/dialogue`(1턴) 순서로 호출. 실제 Claude Vision/Sonnet 호출 + `corpus_index` 실데이터 대조.

## 1. 핵심 지표 요약

| 지표 | 값 | 비고 |
|---|---|---|
| 실행 건수 | 30건 | 실패 0건 |
| 근거 검색 성공률(references≥1) | 27/30 (90%) | |
| 기대판단 일치율 | 10/30 (33%) | 매핑: 정상→needs_check, 사칭→partially_matched, 경계→no_source_found (아래 §2 설명) |
| 단정문 재생성(2단 가드레일) 발생 건 | 4/30 (13%) | 재생성이 1회 이상 발생한 케이스 수 |
| 재생성 발생율(시도 기준) | 9/39 (23%) | 전체 생성 시도(재시도 포함) 39회 중 |
| 폴백(3회 모두 실패) 발생 | 2/30 (7%) | FALLBACK_QUESTION 으로 대체된 케이스 |

### 유형별 상세

| 유형 | 건수 | 근거 검색 성공률 | 기대 verdict_hint | 실제 일치율 | verdict_hint 실제 분포 |
|---|---|---|---|---|---|
| 정상 | 10 | 7/10 (70%) | `needs_check` | 0/10 (0%) | partially_matched=7, no_source_found=3 |
| 사칭 | 10 | 10/10 (100%) | `partially_matched` | 10/10 (100%) | partially_matched=10 |
| 경계 | 10 | 10/10 (100%) | `no_source_found` | 0/10 (0%) | partially_matched=10 |

**주의**: `needs_check` 는 30건 중 단 한 번도 나오지 않았다(§4-2 원인 분석 참고). 그래서 '정상' 유형의 일치율이 정의상 0%가 된다 — 시스템이 틀렸다기보다, 이 평가셋의 문구 스타일에서는 `needs_check` 도달 조건(신호 0건)이 사실상 불가능하기 때문이다.

---

## 2. 기대판단 ↔ verdict_hint 매핑 근거

곁눈의 `verdict_hint` 는 `needs_check | partially_matched | no_source_found` 3값이고, CSV의 `기대판단` 은 `정상 | 의심 | 확인불가` 3값이다. 이름이 다를 뿐 설계 의도가 대응되므로 다음과 같이 매핑해 측정했다:

| CSV 기대판단 | 의미 | 대응하는 verdict_hint | 근거 |
|---|---|---|---|
| 정상 | 공식 서비스, 위험 없음 | `needs_check` | 근거 있음 + 위험 신호 없음 → 낮은 확인 필요도 |
| 의심 | 사기/사칭 패턴 뚜렷 | `partially_matched` | 근거(유사 사례) 있음 + 위험 신호 있음 |
| 확인불가 | 실재하나 모호한 단서 | `no_source_found` | 확정 근거 없음 → '못 찾았다'는 신호 자체가 곁눈의 원칙 |

이 매핑은 이 보고서를 위해 정의한 것이며 시스템 코드에는 없다. 곁눈은 애초에 진위 판정을 하지 않으므로 '정답'이라는 개념 자체가 원칙적으로 없지만, 성능을 측정하려면 어떤 형태로든 대응이 필요해 위와 같이 정했다.

---

## 3. 경계(boundary) 10건 심층 분석 ★

**요청 배경**: 경계 케이스는 '실제 제도명 + 수상한 단서'가 섞인 모호한 사례다. 이걸 시스템이 '의심'으로 단정해 버리면 안 되고 '확인불가'가 나와야 한다.

| case_id | verdict_hint | signals | 단정 여부 |
|---|---|---|---|
| B01 | `partially_matched` | similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B02 | `partially_matched` | source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B03 | `partially_matched` | source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B04 | `partially_matched` | source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B05 | `partially_matched` | similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B06 | `partially_matched` | urgency_pressure, source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B07 | `partially_matched` | source_missing, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B08 | `partially_matched` | similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B09 | `partially_matched` | source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |
| B10 | `partially_matched` | source_missing, similar_scam_case, similar_scam_case | ⚠️ partially_matched (기대: no_source_found) |

**결과: 경계 10건 전부(10/10) `partially_matched` 로 나왔다. 기대(`no_source_found`)와 전부 어긋난다. 10건 전부(10/10)에서 `similar_scam_case` 신호가 발생했다.**

### 단정문(진위 판정 단어) 누출 여부

`validate_question()` 의 금지어 검사는 경계 10건 전부 통과했다 — 최종 질문/이유/보기 문구에 '가짜·사기·확실합니다' 같은 판정 단어는 하나도 새지 않았다(재생성 발생: 1/10건, 사유는 아래 §5 참고). **즉 '단정문'(명시적 판정 발언)은 나오지 않았다.**

다만 `verdict_hint=partially_matched` + `similar_scam_case` 신호 + 실제 사기사례 URL 조합은 사용자에게 사실상 '의심스럽다'는 톤을 강하게 전달한다. 명시적 판정 단어는 없지만, **결과적으로 시스템이 경계 사례를 '의심' 쪽으로 기울여 보여주는 것은 사실**이다 — 질문/이유 문구 자체는 판정하지 않지만, 근거 영역의 신호가 균형을 깨고 있다.

### 근본 원인 (§4-3 에서 자세히)

매칭된 근거 제목을 확인해 보니 **경계 케이스가 자기 자신 또는 형제 경계 케이스와 매칭되고 있었다** — 아래 §4-3 참고. 즉 이 100% 라는 수치는 시스템이 실전에서 얼마나 잘 구분하는지가 아니라, 이 평가셋 고유의 데이터 누수 때문일 가능성이 크다.

---

## 4. 실패 사례

**없음 — 30/30건 모두 API 호출 성공 (500/501 없음, 타임아웃 없음).**

---

## 5. 단정문 차단(2단 가드레일 재생성) 상세

| case_id | 유형 | 재생성 횟수 | 사유 | 폴백 발생 |
|---|---|---|---|---|
| N01 | 정상 | 3 | too_long, too_long, too_long | 예 |
| S07 | 사칭 | 1 | forbidden_word | 아니오 |
| S08 | 사칭 | 2 | too_long, forbidden_word | 아니오 |
| B08 | 경계 | 3 | too_long, too_long, too_long | 예 |

**사유별 집계**: too_long=7, forbidden_word=2

---

## 6. 원인 분석 (지금 고치지 않음 — 진단만)

### 6-1. 기대판단 일치율이 낮은 이유 (33.3%)

- **`needs_check` 가 한 번도 안 나옴**: `search.detect_signals()` 의 `source_missing` 규칙은 본문에 `보건복지부·질병관리청·금융감독원·국민연금·정책브리핑·복지로·식약처·공단` 8개 키워드 중 하나도 없으면 발동한다. 평가셋 문구는 '복지로에서 확인하세요' 처럼 실제 서술형이라 이 정확한 8개 키워드를 그대로 안 쓰는 경우가 많아, 정상적인 공식 안내조차 `source_missing` 신호가 뜨고 `needs_check`(신호 0건 조건) 에 도달하지 못한다.

- **정상 케이스 중 3건(N03/N06/N08)이 `no_source_found`**: 근거 코퍼스(`근거_검증표.csv`, 11건)가 아직 작고 `corpus/public_data`(공공데이터 577건 목표)가 비어 있어, '농어가목돈마련저축' 같은 특정 제도명을 다루는 근거가 아예 없다. README 에 이미 문서화된 한계다.

### 6-2. 경계 10건이 전부 `partially_matched` 인 이유 — 데이터 누수 발견 ★

`services/corpus_index.py` 의 `_scam_cases_from_eval()` 은 **이 평가세트 CSV 자신의 '사칭'/'경계' 20행을 그대로 `SCAM_CASES`(실제 매칭 코퍼스) 에 포함시킨다.** 그 결과 이 CSV로 평가를 돌리면, 각 경계 케이스의 입력 문구가 **평가셋에 있는 자기 자신 또는 형제 케이스와 매칭**되어 `similar_scam_case` 신호가 발생한다.

실측 증거 — B01 케이스가 매칭한 근거 제목 2건:
```
1) "경계 사례 - 서비스는 실재하지만 발송 주체와 단축 링크는 별도 확인 필요"
   → 이건 B01 자신의 정답근거 문구 그대로다 (자기 자신과 매칭)
2) "경계 사례 - 위험 요구는 없지만 개인별 검진 대상 여부는 공식 채널 확인 필요"
   → 이건 B05 의 정답근거 문구다 (형제 케이스와 교차 매칭)
```
즉 지금 측정한 '경계 100% partially_matched' 라는 결과는, 시스템이 실제 운영 환경에서도 이렇게 반응한다는 뜻이 아니라 **이 평가셋으로 측정할 때만 생기는 자기 참조(self-reference) 아티팩트일 가능성이 크다.** 더 근본적으로는, `corpus_index.SCAM_CASES` 가 '평가/테스트 데이터' (이 CSV) 와 '운영 참조 데이터'(재라벨링표의 실제 피싱 사례)를 구분하지 않고 섞어 쓰고 있다는 설계상 문제이기도 하다 — 실제 사용자가 이 평가셋 문구와 우연히 비슷하게 쓰면 운영 중에도 같은 현상이 재현될 수 있다.

### 6-3. 근거 검색 성공률이 유형별로 차이 나는 이유

사칭·경계는 100%인데 정상은 70%다. 사칭/경계가 높은 것도 위와 같은 이유(평가셋 자신이 코퍼스에 포함됨)로 설명된다 — '정상' 행은 애초에 `_scam_cases_from_eval()` 에서 제외되므로 이 누수의 영향을 받지 않고, 진짜 코퍼스 크기(11건)만으로 승부해야 해서 상대적으로 낮게 나온다. 역설적으로 **정상 케이스의 70%가 오히려 더 '진짜' 수치에 가깝다.**

### 6-4. 재생성/폴백이 발생하는 이유

- **`too_long`(7/9, 대부분)**: 시나리오가 여러 조건을 담고 있는 입력(N01, B08 등)에서 Claude가 한 질문에 여러 정보를 담으려다 2문장 제한을 반복해서 못 지켰다. N01/B08 은 3회 재시도 모두 실패해 폴백까지 갔다 — 특정 입력 패턴(정보 밀도가 높은 문장)에서 2문장 제한 준수가 불안정하다는 신호다.

- **`forbidden_word`(2건, S07/S08)**: 둘 다 `question` 이 아니라 **`why` 필드**에서 '사기'/'가짜' 가 검출됐다. 질문 자체는 깨끗했는데 이유 설명에서 판정어가 샜다는 뜻 — 달리 말해 **`why`까지 검사하는 2단 검증 설계가 실제로 유효하게 작동한 사례**이기도 하다 (question 만 검사했다면 이 2건은 그대로 사용자에게 나갔을 것이다).

---

## 7. 결론 요약

- 30건 모두 API 오류 없이 완주(성공률 100%) — 안정성은 확인됨.
- 사칭(의심) 케이스는 기대와 100% 일치 — 스캠 패턴 탐지 자체는 잘 작동한다.
- **경계 케이스의 '확인불가' 재현은 이번 측정 방식으로는 신뢰할 수 없다** — 평가셋 데이터가 매칭 코퍼스에 섞여 들어가 있어 자기참조 오염이 있다. 재측정하려면 평가셋을 코퍼스에서 제외한 상태로 다시 돌려야 진짜 수치를 알 수 있다(이번 작업 범위 밖, 수정하지 않음).
- 명시적 판정 단어('가짜입니다' 등)는 30건 어디에도 새지 않았다 — 2단 가드레일(`validate_question`) 은 견고하게 작동했다. 다만 `verdict_hint`+근거 신호 조합이 주는 '톤'은 경계 케이스에서 완전히 중립적이지 않았다.
- 정상 케이스의 낮은 근거매칭(70%)과 `needs_check` 미발생은 코퍼스 크기(11건)와 신호 키워드 리스트가 원인 — 둘 다 이미 알려진 확장 과제(README TODO)다.

원본 데이터: [`eval_30_raw.json`](eval_30_raw.json)