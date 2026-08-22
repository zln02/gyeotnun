# docs/ — 무엇이 어디에 있나

곁눈의 기록은 **시간순이 아니라 주제순**으로 읽는 것이 빠르다. 이 한 장이 색인이다.

> **5분만 있다면** — 아래 다섯 개만 보면 이 저장소가 어떻게 일했는지 알 수 있다.
>
> | 보고 싶은 것 | 파일 |
> |---|---|
> | 측정하고 **채택하지 않은** 판단 | [`evaluation/hybrid_search_report.md`](evaluation/hybrid_search_report.md) |
> | 제출 문서를 **스스로 반박한** 기록 | [`evaluation/제출후_자체대조_2026-08-11.md`](evaluation/제출후_자체대조_2026-08-11.md) |
> | 운영 데이터를 **지운 사고** | [`reports/2026-08-17_사고기록_events_262행_삭제.txt`](reports/2026-08-17_사고기록_events_262행_삭제.txt) |
> | 아직 **못 고친 것** | [`evaluation/본체결함_발견대장.md`](evaluation/본체결함_발견대장.md) |
> | 숫자가 **어디서 나왔나** | [`evaluation/measurement_provenance.md`](evaluation/measurement_provenance.md) |

폴더는 셋이다.

| 폴더 | 무엇 | 형식 |
|---|---|---|
| `evaluation/` | 결정·측정·미결 대장 | `.md` (표·근거 중심) |
| `reports/` | 그날 사람에게 보고한 내용 | `.txt` (고정폭 평문 — [규칙](reports/README.md)) |
| `security/` | 보안 점검·하드닝 | `.md` |

같은 사건이 `evaluation/` 과 `reports/` 양쪽에 있는 경우가 있다. **`evaluation/` 이
결론이고 `reports/` 가 그날의 과정**이다. 결론만 필요하면 `evaluation/` 을 본다.

---

## 1. 결정 기록 — 무엇을 채택했고, 무엇을 채택하지 않았나

★ 이 저장소에서 **채택보다 기각이 더 중요한 기록**이다. 재 보고 안 쓴 판단이
재 보지 않고 쓴 판단보다 많다.

### 채택한 것

| 결정 | 문서 |
|---|---|
| 검색은 **임베딩 단독** (BM25 는 폴백 전용) | [`evaluation/hybrid_search_report.md`](evaluation/hybrid_search_report.md) |
| 임베딩을 **로컬 모델**로 전환 (외부 전송 제거) | [`evaluation/local_embeddings_report.md`](evaluation/local_embeddings_report.md) |
| 사기사례 하한선 `min_score = 5.0` **유지** | [`evaluation/하한선_결정_2026-08-13.md`](evaluation/하한선_결정_2026-08-13.md) |
| 위험행동 신호 4유형 + 문맥조건 | [`evaluation/위험행동_신호_결정_2026-08-13.md`](evaluation/위험행동_신호_결정_2026-08-13.md) |
| 문자 속 주소 펼치기(HEAD) — 요청 흐름 유지 | [`evaluation/URL펼치기_설계_2026-08-15.md`](evaluation/URL펼치기_설계_2026-08-15.md) |
| 기관 공식 도메인 대조 (tier 불변·회색 표시) | [`evaluation/기관도메인_매핑_조사_2026-08-15.md`](evaluation/기관도메인_매핑_조사_2026-08-15.md) |
| 판단 행동 로그 표 설계 | [`판단행동로그_설계_2026-08-20.md`](판단행동로그_설계_2026-08-20.md) |
| 코퍼스 포함 기준 | [`evaluation/corpus_scope_criteria.md`](evaluation/corpus_scope_criteria.md) |

### ★ 재 보고 채택하지 않은 것

| 기각한 안 | 왜 | 문서 |
|---|---|---|
| **하이브리드(RRF) 검색** | 30건에서 임베딩 단독보다 나은 지점이 **하나도 없었다**. 경계 케이스는 오히려 가장 나빴다 | [`evaluation/hybrid_search_report.md`](evaluation/hybrid_search_report.md) |
| **질의 재작성 3종** | 셋 다 개선 없음 → 프로덕션 무변경 | [`reports/2026-08-09_질의재작성_RRF_실험.md`](reports/2026-08-09_질의재작성_RRF_실험.md) |
| **경보문 이설** | 8/5 에 실측으로 기각한 오판 문제가 다시 나타남 | [`evaluation/경보문_이설_시뮬레이션_2026-08-12.md`](evaluation/경보문_이설_시뮬레이션_2026-08-12.md) |
| **PaddleOCR 로컬 전환** (당시) | 정확도는 좋았으나 이번 범위에서는 채택 안 함 | [`evaluation/paddleocr_retest.md`](evaluation/paddleocr_retest.md) · [`evaluation/paddleocr_ocr_switch.md`](evaluation/paddleocr_ocr_switch.md) |
| **다크모드 전처리 분기** | 가설 기각 — 분기 불필요 | [`evaluation/ocr_comparison.md`](evaluation/ocr_comparison.md) §4-4 |
| **실험 DB 가드 2안** (sitecustomize · incident_log 개입) | 운영 서버가 sqlite 로 뜰 위험 / **진짜 사고 기록이 조용히 사라질 위험** | [`reports/2026-08-18_문장세기_수정_실험가드_NIA링크.txt`](reports/2026-08-18_문장세기_수정_실험가드_NIA링크.txt) §2-6 |
| **NIA·survey_report 검색 제외** | 실물 확인 결과 원인이 다른 경로였다 → 사람이 승인 취소 | [`reports/2026-08-19_NIA_실물확인.txt`](reports/2026-08-19_NIA_실물확인.txt) |

> 기각의 원칙은 두 줄이다.
> **"평가셋과 홀드아웃 양쪽에서 재고, 한쪽만 좋아지면 채택하지 않는다."**
> **"개선이 없으면 없다고 보고한다. 조건을 바꿔 맞추지 않는다."**

---

## 2. 실험 기록 — 어떻게 쟀나

| 주제 | 문서 |
|---|---|
| **숫자의 출처** — 어떤 수치가 어느 실행에서 나왔나 | [`evaluation/measurement_provenance.md`](evaluation/measurement_provenance.md) |
| 예선 30건 정식 재측정 (4지표) | [`evaluation/prelim_final_20260810.md`](evaluation/prelim_final_20260810.md) |
| 확대 평가셋 112건 기준선 | [`evaluation/기준선_확대평가셋_2026-08-11.md`](evaluation/기준선_확대평가셋_2026-08-11.md) |
| 홀드아웃 30건 (검색 코퍼스에 넣지 않음) | [`evaluation/holdout_normal.md`](evaluation/holdout_normal.md) |
| 임계값 하한선 점수분포·손익표 | [`evaluation/하한선_점수분포_손익표_2026-08-13.md`](evaluation/하한선_점수분포_손익표_2026-08-13.md) |
| 폴백률 상시 관측(EX-006) 설계 | [`evaluation/검색폴백_관측_2026-08-13.md`](evaluation/검색폴백_관측_2026-08-13.md) |
| 동시 접속 0→4단계 (단계마다 측정→배포) | [`reports/2026-08-16_동시접속_0단계_1단계.txt`](reports/2026-08-16_동시접속_0단계_1단계.txt) → [`2단계`](reports/2026-08-16_동시접속_2단계.txt) → [`3단계`](reports/2026-08-16_동시접속_3단계.txt) → [`4단계`](reports/2026-08-16_동시접속_4단계.txt) |
| API 원가 분해 | [`evaluation/cost_analysis.md`](evaluation/cost_analysis.md) |
| 마스킹 재현율 | [`reports/2026-08-09_마스킹_재현율_측정.txt`](reports/2026-08-09_마스킹_재현율_측정.txt) |
| OCR 후보 비교 | [`evaluation/ocr_comparison.md`](evaluation/ocr_comparison.md) |
| 화면 판정 근거 분해 | [`evaluation/judgment_basis.md`](evaluation/judgment_basis.md) |
| 근거_검증표 경로 전수 조사 | [`reports/2026-08-19_하한선_전수조사_근거검증표.txt`](reports/2026-08-19_하한선_전수조사_근거검증표.txt) |

---

## 3. 사고 기록 — 무엇을 망가뜨렸나

> ★ **이 항목은 완화해서 쓰지 않는다.** 사고 기록을 부드럽게 고치는 순간
> 기록으로서의 가치가 사라진다.

| 사고 | 무슨 일 | 문서 |
|---|---|---|
| **운영 DB 262행 삭제** (2026-08-16) | "17행만 지우면 된다"로 시작해 **262행을 지웠고 복구하지 못했다.** 세는 SQL 에는 시간 조건이 있었고 지우는 SQL 에는 없었다. 삭제 직전 `262` 라는 숫자를 화면에 찍었는데도 아무것도 막지 못했다 — **확인을 '출력'하는 것과 '차단'하는 것은 다르다.** 지시자가 백업 절차를 빼고 지시한 것도 함께 기록했다 | [`reports/2026-08-17_사고기록_events_262행_삭제.txt`](reports/2026-08-17_사고기록_events_262행_삭제.txt) |

**그 뒤에 만든 것**: [`api/tools/delete_rows.py`](../api/tools/delete_rows.py) —
백업 → 복원 리허설 → `--expect` 일치 → 삭제. 넷 다 끌 수 없고 행 수와 무관하다.
규칙은 [`deploy/README.md`](../deploy/README.md) "운영 DB 삭제 규칙"에 있다.

### 사고는 아니지만 같은 성격의 자기 발견

> ★ **사고(3절)와 자기 발견(여기)의 구분 기준**
> — *실제 피해가 발생했는가*. 되돌릴 수 없는 손실(데이터 소실 등)이나 사용자에게
> 잘못된 결과가 나간 것이 사고다. 이 아래는 **위험이 드러났지만 피해로 이어지지
> 않은 것**이다. 기준을 느슨하게 하면 사고 기록의 무게가 사라지고, 빡빡하게 하면
> 위험 신호가 묻힌다. 그래서 둘 다 남기되 칸을 나눈다.
>
> ★ 아래 둘은 **서로 다른 사건**이다. 배포 스크립트를 도달 불가 URL 로 돌려
> "실패해야 할 검사가 실제로 실패하는가"를 시험한 것(`7d9f5df`)과,
> 보안 스캔이 없는 취약점을 걸었던 오탐은 방향이 반대다 — 전자는 검사를 시험한
> 것이고 후자는 검사가 틀린 것이다. 같은 칸에 넣지 않는다.

| 무엇 | 문서 |
|---|---|
| 임베딩 지연 로드 경합 → **조용한 BM25 폴백**(같은 입력, 다른 판정) | [`reports/2026-08-16_동시접속_2단계.txt`](reports/2026-08-16_동시접속_2단계.txt) |
| 외부 LLM 크레딧 소진으로 **8시간 폴백 100%** 인데 아무도 몰랐다 | [`reports/2026-08-09_운영_LLM폴백_상태점검.txt`](reports/2026-08-09_운영_LLM폴백_상태점검.txt) |
| 타인 기록 조회(IDOR) 실증 | [`reports/2026-08-06_식별자교체_타인기록조회_실증.txt`](reports/2026-08-06_식별자교체_타인기록조회_실증.txt) |
| **보안 스캔 오탐** — `/docs` 노출 경고가 SPA 폴백 200 때문이었다 | [`security/review_2026-08.md`](security/review_2026-08.md) §52 |
| **지표 오인용** — 신호 기준 값을 화면 기준으로 적어 회귀로 오인했다 | [`reports/2026-08-21_정상오판_두정의_재측정.txt`](reports/2026-08-21_정상오판_두정의_재측정.txt) |
| **운영 컨테이너 재시작** — 뒷정리 명령의 `kill 1` 이 PID 1(운영 uvicorn)을 죽였다 | [`reports/2026-08-22_컨테이너재시작_기록.txt`](reports/2026-08-22_컨테이너재시작_기록.txt) |
| 표시 경로로 임계값 우회 차단 | [`reports/2026-08-06_표시경로_임계값우회_차단.txt`](reports/2026-08-06_표시경로_임계값우회_차단.txt) |

---

## 4. 정정 이력 — 우리가 먼저 틀렸다고 말한 것

> 심사위원이 먼저 찾으면 감점이지만, 우리가 먼저 말하면 점검 능력의 증거가 된다.
> ★ **저장소를 문서에 맞추지 않고, 문서를 실측에 맞췄다.**

| 무엇을 정정했나 | 문서 |
|---|---|
| **제출 기획서 ↔ 저장소 대조 3건** — 마스킹 재현율 분모(156 → 실제 90), 90일 삭제 대상, 팀 역할 표기 | [`evaluation/제출후_자체대조_2026-08-11.md`](evaluation/제출후_자체대조_2026-08-11.md) |
| **NIA 근거가 붙는 원인** — 두 번 틀린 진단을 두 번 정정 | [`evaluation/NIA점유_수집경로_2026-08-12.md`](evaluation/NIA점유_수집경로_2026-08-12.md) · [`reports/2026-08-19_NIA_실물확인.txt`](reports/2026-08-19_NIA_실물확인.txt) |
| **라벨 재분류** — 성공률 상승분이 전부 라벨 정정에서 왔음을 명시 | [`evaluation/label_reclassification_20260810.md`](evaluation/label_reclassification_20260810.md) |
| **IDF 척도이동** — "이설을 권하지 않는다"는 결론을 철회 | [`evaluation/IDF척도이동_A안_2026-08-12.md`](evaluation/IDF척도이동_A안_2026-08-12.md) |
| **전체 감사 실측판** — 감사 초안의 미실측 항목을 재측정해 교체 | [`reports/2026-08-14_전체감사_실측판.txt`](reports/2026-08-14_전체감사_실측판.txt) |
| **OCR 재측정** — 유리한 수치를 유지하지 않고 재현 실패를 공개 | [`reports/2026-08-06_PaddleOCR_재측정.txt`](reports/2026-08-06_PaddleOCR_재측정.txt) |
| **역할 표기 검토** | [`reports/2026-08-15_역할표기_fsc검토.md`](reports/2026-08-15_역할표기_fsc검토.md) |

---

## 5. 미해결 대장 — 아직 못 고친 것

**[`evaluation/본체결함_발견대장.md`](evaluation/본체결함_발견대장.md)** 한 파일이다.
결함 자체보다 **결함이 생기는 유형**을 먼저 적는다.

| 유형 | 내용 |
|---|---|
| **L1** | 새 방식을 넣을 때 옛 방식을 끄지 않으면, 옛 방식이 조용히 오답을 만든다 (근거_검증표 경로가 약 20일간 살아 있었다) |
| **L2** | 컨테이너 안 경로에 쓴 파일은 기본적으로 사라진다 (같은 실수를 하루 만에 반복했다) |
| **L3** | 임계값이 없는 경로 6종 — **방어선이 무엇인지** 적어 둔다. "없다고 착각하고 어휘만 늘리면 그때 뚫린다" |
| **L4** | 실행 시점에 달라지는 값을 문서에 고정하지 않는다 (README 의 테스트 수가 하루 만에 어긋났다) |

미결 항목은 대장의 `M` 절에 있다. 해결된 것도 지우지 않고 **해결 표시만** 남긴다 —
지우면 "무엇을 겪었는지"가 사라진다.

**로컬 우회 금지**: 실험 파일에서 본체 결함을 우회했다면 우회 코드만 남기지 않고
이 대장에 올린다. 2026-08-05 의 우회가 12일 뒤 라이브 사고가 된 경로다
([`CONTRIBUTING.md`](CONTRIBUTING.md)).

---

## 6. 보안 · 개인정보

| 주제 | 문서 |
|---|---|
| 보안 점검 종합 | [`security/review_2026-08.md`](security/review_2026-08.md) |
| 최종 하드닝 | [`security/final_hardening_2026-08-06.md`](security/final_hardening_2026-08-06.md) |
| IDOR 실증 시험 | [`security/idor_live_test_2026-08-06.md`](security/idor_live_test_2026-08-06.md) |
| 취약점 스캔 | [`security/vulnerability_scan.md`](security/vulnerability_scan.md) |
| 오류 코드 체계 | [`error_codes.md`](error_codes.md) |

`security/internal/` 은 **공개 대상이 아니다** — 백업 SQL·감사 원자료가 들어 있어
커밋에 포함하지 않는다.

---

## 7. 기여자용

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — 작업 규칙 (로컬 우회 금지 · 임계값 취급 · 배포 절차)
- [`../CLAUDE.md`](../CLAUDE.md) — 새 세션 온보딩 (한 장)
- [`reports/README.md`](reports/README.md) — 보고 `.txt` 작성 규칙
