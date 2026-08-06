/**
 * 확인 결과(evidence) → 화면 표시용 판정 정리
 * 담당: 조희진
 *
 * ★ 원래 Question.jsx 안에만 있던 로직인데, 2026-08 Figma 3차 이식에서
 *   '판단' 화면(S2.5)이 따로 생기면서 두 화면이 같은 판정을 써야 해졌다.
 *   두 곳에 복사하면 반드시 한쪽만 고쳐지므로 여기로 뺀다.
 *
 * ★★ 표시 정직성 원칙 (docs/evaluation/judgment_basis.md) ★★
 *   서버는 임베딩 유사도로 '관련 문서를 찾을' 뿐, 찾은 문서와 이 글의 내용을
 *   대조하지 않는다. 그러므로 "확인했다"/"다르다"고 쓰지 않는다.
 *   찾은 것까지만 말하고 판단은 사용자에게 넘긴다.
 */

/**
 * verdict_hint 하나만 그대로 쓰지 않는 이유
 *   search.py 의 official_source_found / contact_in_image 신호는 severity="info"
 *   (문제 신호 아님)라서, 공식 자료를 찾았을 뿐인데도 partially_matched 가 찍히는
 *   경우가 있다. severity="attention" 이 실제로 있을 때만 '의심'으로 올린다.
 */
export function verdictTier(evidence) {
  if (evidence?.verdict_hint === 'no_source_found') return 'unknown'
  const hasAttentionSignal = (evidence?.signals || []).some((s) => s.severity === 'attention')
  return hasAttentionSignal ? 'suspicious' : 'confirmed'
}

// 위험 표현 신호 → 사용자에게 보여줄 짧은 이름.
// ★ 서버 search.py 의 SIGNAL_RULES 키와 1:1 이다. 없는 키는 표시하지 않는다
//   (지어낸 이름을 붙이지 않기 위해 일부러 폴백을 두지 않았다).
export const RISK_PHRASE_NAME = {
  urgency_pressure: '서두르게 만드는 표현',
  condition_omitted: '조건이 빠졌을 수 있는 표현',
}

/**
 * '판단' 화면 상단 태그(회색 알약) 목록.
 *
 * ★★ Figma 원본은 여기에 '제목 의존형'·'과잉 일반화형' 같은 오판유형(ErrorType)을
 *   달아 두었다. 그런데 오판유형은 서버가 **사용자가 행동을 고른 뒤**(S4 verdict,
 *   tagger.py) 태깅한다 - 이 화면(질문 시작 전) 시점에는 존재하지 않는 값이다.
 *   없는 값을 그럴듯하게 지어내면 곁눈이 하지 않기로 한 짓이 되므로,
 *   같은 자리에 **실제로 검출된 신호**를 대신 넣는다. 검출된 게 없으면 비운다.
 */
export function riskTags(evidence) {
  const names = (evidence?.signals || [])
    .filter((s) => s.severity === 'attention' && RISK_PHRASE_NAME[s.key])
    .map((s) => RISK_PHRASE_NAME[s.key])
  return [...new Set(names)].slice(0, 2)
}

/**
 * 배지/제목 아래 한 줄 근거 요약 - 실제 references/signals 에서만 뽑는다.
 */
export function evidenceSummary(evidence, tier) {
  const refs = evidence?.references || []
  const publishers = [...new Set(refs.map((r) => r.publisher).filter(Boolean))].slice(0, 2).join('·')

  if (tier === 'unknown') {
    // ★ 참고자료가 남아 있는데 "찾지 못했습니다"라고 하면 화면과 어긋난다
    //   (아래 목록에는 링크가 그대로 보이기 때문). 유사도가 임계값에 못 미쳐
    //   '유보'된 상태이지 아무것도 못 찾은 상태가 아니다 - 갈라서 말한다.
    return refs.length > 0
      ? '비슷한 자료는 찾았지만, 같은 안내인지는 확인하지 못했습니다.'
      : '공식 자료에서 같은 이름의 공고나 안내를 찾지 못했습니다.'
  }

  if (tier === 'suspicious') {
    // ★ similar_scam_case 신호의 원문 label 은 "...사기 수법과 비슷합니다"처럼
    //   금지어를 담고 있다. 괄호 안 실제 상세정보는 살리고 표현만 순화한다.
    const scamSignal = (evidence?.signals || []).find((s) => s.key === 'similar_scam_case')
    if (scamSignal) {
      const detail = scamSignal.label.match(/\(([^)]+)\)/)?.[1]
      return detail
        ? `이전에 확인된 사례와 비슷한 점이 있어요 (${detail}).`
        : '이전에 확인된 사례와 비슷한 점이 있어요.'
    }
    const names = riskTags(evidence)
    if (names.length > 0) {
      return publishers
        ? `글에 ${names.join('·')}이 있어요. ${publishers} 자료를 직접 확인해 보세요.`
        : `글에 ${names.join('·')}이 있어요. 한 번 더 확인해 보세요.`
    }
    return '확인할 점이 남아 있어요.'
  }

  return publishers
    ? `${publishers}의 관련 자료를 찾았어요. 직접 확인해 보세요.`
    : '공식 자료에서 관련 안내를 찾았어요. 직접 확인해 보세요.'
}
