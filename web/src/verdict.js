/**
 * 확인 결과(evidence) → '판단' 화면에 띄울 상태 한 벌
 * 담당: 조희진
 *
 * ★★ 왜 4단계인가 (2026-08 리뷰 반영) ★★
 *   전에는 화면이 하나뿐이라, 빨간 경고 + "확인이 필요한 문자예요" 가
 *   **정상 안내문에도 그대로 나갔다**. 공식 자료를 잘 찾은 경우까지 빨간
 *   경고를 띄우는 건 명백한 오작동이다(놀라게 하는 쪽으로 틀리는 것도 틀린 것이다).
 *   레이아웃은 그대로 두고 색·제목·'사실 한 줄'만 바뀌는 4단계로 나눈다.
 *
 *     빨강  지금 멈추세요        ← 계좌·카드번호가 실제로 검출됨
 *     빨강  확인이 필요한 문자예요  ← 주의 신호가 검출됨
 *     주황  공식 자료를 못 찾았어요
 *     초록  공식 자료를 찾았어요
 *
 *   빨강은 위 두 개에서만 쓴다.
 *
 * ★★ 표시 정직성 원칙 (docs/evaluation/judgment_basis.md) ★★
 *   서버는 임베딩 유사도로 '관련 문서를 찾을' 뿐, 찾은 문서와 이 글의 내용을
 *   대조하지 않는다. 그러므로 "확인했다"/"내용이 다르다"고 쓰지 않는다.
 *   '사실 한 줄'도 **실제로 검출한 것만** 적는다 - 검출하지 않은 것을
 *   그럴듯하게 적으면 그게 바로 곁눈이 막으려는 짓이다.
 */

/** 서버가 실제로 내려주는 주의(attention) 신호 키. search.py SIGNAL_RULES 와 1:1. */
const ATTENTION_KEYS = ['similar_scam_case', 'urgency_pressure', 'condition_omitted']

/** 마스킹 유형 → 사람이 읽는 이름. masking.py 가 실제로 숫자를 찾아낸 것만 들어온다. */
const MASKED_LABEL = {
  account: '계좌번호가 적혀 있어요',
  card: '카드번호가 적혀 있어요',
  rrn: '주민등록번호가 적혀 있어요',
}

/** 신호 label 의 첫 문장만 뽑는다(서버 문구가 두 문장짜리라 화면엔 길다). */
function firstSentence(label) {
  const s = (label || '').split(/(?<=[.!?])\s/)[0].trim()
  return s.replace(/입니다\.?$/, '이에요').replace(/습니다\.?$/, '어요')
}

/**
 * 화면에 필요한 것 전부를 한 번에 계산한다.
 * @param evidence  GET /checks/{id}/evidence 응답
 * @param checkData POST /checks 응답 (masked_items 가 여기 있다)
 */
export function judgmentState(evidence, checkData) {
  const signals = evidence?.signals || []
  const refs = evidence?.references || []
  const maskedItems = checkData?.masked_items || []

  // ① 계좌·카드번호가 실제로 검출됐다 → 가장 강한 경고.
  //    masking.py 의 정규식이 문맥까지 보고 잡아낸 '진짜 숫자'라 신뢰도가 높다.
  const money = maskedItems.find((m) => m.type === 'account' || m.type === 'card')
  if (money) {
    return {
      tier: 'danger',
      lead: '지금 ', accent: '멈추세요', tail: '',
      fact: MASKED_LABEL[money.type] || '금융 정보가 적혀 있어요',
    }
  }

  // ② 주의 신호가 있다 → 확인 필요.
  const attention = signals.find((s) => s.severity === 'attention' && ATTENTION_KEYS.includes(s.key))
  if (attention) {
    // ★ similar_scam_case 의 원문 label 은 "...사기 수법과 비슷합니다" 처럼 단정적
    //   금지어를 담고 있다. 뜻은 살리고 표현만 순화한다.
    const fact = attention.key === 'similar_scam_case'
      ? '이전에 확인된 사례와 비슷한 문장이 있어요'
      : firstSentence(attention.label)
    return {
      tier: 'warn',
      lead: '확인이 ', accent: '필요', tail: '한 문자예요',
      fact,
    }
  }

  // ③ 공식 자료를 못 찾았다.
  if (evidence?.verdict_hint === 'no_source_found' && refs.length === 0) {
    return {
      tier: 'hold',
      lead: '공식 자료를 ', accent: '못 찾았', tail: '어요',
      fact: '기관 대표번호로 확인해 보세요',
    }
  }

  // ④ 관련 자료를 찾았다. '사실 한 줄'은 실제로 찾은 문서의 도메인을 그대로 보여준다.
  //    (내용이 같은지까지는 확인하지 않았으므로 "맞습니다"라고 쓰지 않는다.)
  let host = ''
  try { host = refs[0]?.url ? new URL(refs[0].url).hostname.replace(/^www\./, '') : '' } catch { /* noop */ }
  return {
    tier: 'ok',
    lead: '공식 자료를 ', accent: '찾았', tail: '어요',
    fact: host ? `원문 보기 → ${host}` : '아래에서 원문을 직접 확인해 보세요',
    factUrl: refs[0]?.url || '',
  }
}
