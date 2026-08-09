# 훈련 카드 현황 — 지금 무엇이 되고 무엇이 안 되는가 (2026-08-05)

코드를 새로 만들지 않고 현재 상태만 기술한다.
확인 대상: `api/routers/training.py` · `api/services/rag.py` ·
`api/models/schemas.py` · `corpus/training_cards/sample_cards.json` ·
`web/src/pages/Training.jsx` · `web/src/api.js`

---

## 0. 한 줄 요약

**훈련 카드 기능은 "고정 샘플 3장을 유형으로 골라 주는 것"까지만 동작한다.**
사용자가 방금 놓친 것을 복습시키는 흐름은 없다. 그리고 화면은 현재
이 API 를 **호출조차 하지 않는다.**

---

## 1. 고정 샘플 3장의 실제 내용

`corpus/training_cards/sample_cards.json` — 카드 3장이 전부다.

| card_id | target_error_type | source_url |
|---|---|---|
| `card_demo_001` | `number_condition` | https://basicpension.mohw.go.kr/ |
| `card_demo_002` | `authority_impersonation` | https://www.mohw.go.kr/ |
| `card_demo_003` | `overgeneralization` | https://health.kdca.go.kr/ |

오판 유형은 4종인데(`number_condition`, `authority_impersonation`,
`overgeneralization`, `title_dependent`) 카드는 3장이라
**`title_dependent` 에 대응하는 카드가 없다.** 이 유형의 사용자는
`?error_type=title_dependent` 를 넘겨도 1번 카드(조건 누락)를 받는다.

1번 카드 전문:

```
다음 두 문장을 읽고, 조건이 빠져 있는 문장을 골라 주세요.

(가) 65세 이상이면 누구나 매달 40만원을 받습니다.
(나) 65세 이상 중 소득인정액이 기준액 이하인 분이 기초연금을 받습니다.

보기 a) (가) 65세 이상이면 누구나
     b) (나) 소득인정액이 기준액 이하인 분
정답 a
해설 (가)에는 '누구나'라는 말만 있고 소득 조건이 없습니다.
     '누구나·전원·무조건' 같은 말이 보이면 빠진 조건이 없는지 한 번 더 살펴보세요.
```

카드 JSON 의 키: `card_id, target_error_type, content, items, answer,
explanation, estimated_sec, source_doc_key, source_url`

---

## 2. target_error_type 이 어떻게 쓰이는가

**카드 3장 중 하나를 고르는 문자열 일치, 그것뿐이다.**

```python
# api/services/rag.py:41
def pick_today_card(error_type):
    cards = load_sample_cards()
    if not cards:
        return None
    if error_type:
        for c in cards:
            if c.get("target_error_type") == error_type:
                return c
    return cards[0]        # 일치하는 게 없으면 무조건 첫 장
```

- 쿼리 파라미터 `?error_type=` 로 클라이언트가 넘겨 주는 값이다.
- 일치하는 카드가 없으면 **조용히 첫 카드**로 떨어진다. 사용자는 자기
  취약 유형과 무관한 카드를 받고도 그 사실을 알 수 없다.
- 오판 유형은 `/checks/{id}/verdict` 가 태깅하지만 **서버에 저장되지
  않는다** — 응답으로 돌려줄 뿐이다(`_MEMORY_STORE` 는 읽기만 한다).
  따라서 이 값을 유지하는 책임은 전적으로 클라이언트에 있다.

### 이력 기반 카드 생성은 미구현

```python
# api/services/rag.py:53
def generate_card_from_corpus(doc, target_error_type):
    """TODO(장지석): 공공데이터 원문 1건 → 훈련카드 1장 변환."""
    ...
    raise NotImplementedError("generate_card_from_corpus 미구현. sample_cards.json 을 사용하세요.")
```

---

## 3. "즉시 복습"은 동작하는가 — **아니다**

기획서 2.2 예선 범위에 있는 항목이지만, 현재 구현으로는 성립하지 않는다.

| 즉시 복습에 필요한 것 | 현재 상태 |
|---|---|
| 사용자가 놓친 질문을 식별 | 오판 유형만 태깅. 질문 자체는 보관 안 됨 |
| 그 결과를 저장 | **저장 안 됨.** `record_verdict` 는 응답만 돌려준다 |
| 저장된 것으로 카드 생성 | **미구현** (`NotImplementedError`) |
| 방금 본 문자를 다시 보여주기 | 없음 |

동작하는 것은 **"오판 유형 문자열을 넘기면 그 유형 태그가 붙은 고정
카드를 돌려주는 것"** 까지다. 이것을 즉시 복습이라고 부르려면
"방금 틀린 그 건"과 카드 사이에 연결이 있어야 하는데, 그 연결이 없다.

> 기획서에 "즉시 복습"이라고 적혀 있다면 **현재 구현을 정확히 기술하지
> 않는다.** "취약 유형별 연습 카드 제공"이 맞는 서술이다.

---

## 4. 화면은 이 API 를 호출하지 않는다 ★

`web/src/pages/Training.jsx` 는 `/training/today` 를 부르지 않는다.
실습 내용이 파일 안 `PRACTICE_STEPS` 상수에 **하드코딩**돼 있다.

```
web/src/api.js:139   getTrainingCard()  ← 정의는 있음
web/src/            사용처 검색 결과      ← 0건
```

Training.jsx 상단 주석에도 그렇게 적혀 있다:

> *"포인트 배너(G/120)와 같은 이유로, 실습 내용은 PRACTICE_STEPS 에 고정값으로"*

즉 **서버의 훈련 카드 3장과 화면에 보이는 실습은 별개의 데이터**다.
서버 카드를 고쳐도 화면은 바뀌지 않는다.

### 이번에 고친 것 / 못 고친 것

| | 상태 |
|---|---|
| `TrainingCardResponse.source_url` 추가 | **완료** |
| mock 픽스처에도 동일 필드 추가 | **완료** |
| API 응답에 실제로 나오는지 | **확인됨** (실응답·mock 양쪽 `https://basicpension.mohw.go.kr/`) |
| 화면에 링크 노출 · 클릭 확인 | **못 함 — 붙일 화면이 없다** |

화면 연결을 하려면 Training.jsx 가 `PRACTICE_STEPS` 대신 API 를 쓰도록
바꿔야 하는데, 이 파일은 지금 UI 세션이 재설계 중이고 실습 흐름 전체를
새 구조로 옮긴 상태다. **제품 결정에 해당하므로 임의로 바꾸지 않았다.**

선택지는 두 가지다.
1. 화면을 API 기반으로 되돌린다 (UI 세션과 조율 필요)
2. `PRACTICE_STEPS` 각 항목에도 근거 URL 을 넣어 하드코딩 흐름 안에서
   근거를 노출한다 (서버 카드와 이원화는 유지)

---

## 5. 기획서 2.4 "관통 흐름 검증"이 실제로 검증한 것

### ★ 훈련 관련 자동 테스트는 **한 건도 없다**

`api/tests/` 전수 확인 결과:

```
tests/test_guardrail_adversarial.py
tests/test_llm_generation.py
tests/test_ocr_vision.py
tests/test_search_fallback.py
tests/test_smoke.py
```

`training` 이라는 문자열을 포함한 테스트는 없다. `card` 가 걸리는 두 건은
**신용카드 번호 마스킹** 테스트로 훈련 카드와 무관하다
(`test_smoke.py:142 test_mask_rrn_and_card`).

즉 `/training/today`, `pick_today_card()`, `error_type` 분기,
카드 없을 때의 `ST-002` 폴백 — **어느 것도 테스트로 보증되지 않는다.**

### 그래서 "관통 흐름 검증"이 무엇을 검증했는지는 **리포에서 확인할 수 없다**

기획서 2.4 가 가리키는 검증이 무엇이었는지는 코드로 역추적이 불가능하다.
자동화된 흔적이 남아 있지 않기 때문이다. 가능한 해석은 두 가지다.

1. 수동 시연(데모)으로 화면 흐름을 훑은 것 — 이 경우 재현·회귀 확인이 안 된다
2. 다른 산출물(별도 문서·영상)에 근거가 있는 것 — 리포 밖이라 확인 못 함

**확인 못 함으로 기록한다.** 추측으로 채우지 않는다.

다만 코드 사실만으로도 말할 수 있는 것이 하나 있다. 화면이
`/training/today` 를 호출하지 않으므로(§4), **"확인 → 오판 태깅 →
그 유형의 복습이 사용자에게 도달한다"** 는 경로는 현재 코드상 연결돼
있지 않다. 무엇을 검증했든 이 구간은 아니다.

---

## 6. 정리 — 기획서에서 고쳐야 할 표현

| 기획서 표현(추정) | 실제 |
|---|---|
| 즉시 복습 | 취약 유형 문자열로 고정 카드 3장 중 1장 선택 |
| 오답 기반 학습 | 오답을 저장하지 않는다 |
| 관통 흐름 검증 | API 규격 검증. 화면은 이 API 를 쓰지 않는다 |

기획서 원본이 리포에 없어 **실제 문구는 확인하지 못했다.**
위 표는 지시서에 인용된 항목명(2.2 즉시 복습, 2.4 관통 흐름 검증)에
대응하는 구현 현황이다. 기획서 문구를 주시면 그 문장 단위로 대조하겠다.
