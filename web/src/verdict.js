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

/** 서버가 실제로 내려주는 주의(attention) 신호 키. search.py SIGNAL_RULES 와 1:1.
 *
 * ★ 2026-08-12 추가: official_alert_matched
 *   근거로 붙은 공식 문서가 '사기 경보문'일 때 서버가 붙인다.
 *   전에는 경보문이 OFFICIAL_DOCS 에 있다는 이유로 official_source_found(info)만
 *   붙어, KISA 사칭 문자에 "KISA 사칭 스미싱 주의" 경보문을 찾아 놓고도 화면에는
 *   초록 "공식 자료를 찾았어요"가 나갔다(S22). 찾은 건 맞는데 뜻이 정반대로 갔다.
 *   ★ 이 목록에 넣어야 경고(warn)로 올라간다. 초록에서 내려가는 것은 ③의 허용
 *     방식 덕에 자동이지만, 그것만으로는 주황에 머문다(실측 확인).
 */
const ATTENTION_KEYS = [
  'similar_scam_case',
  'urgency_pressure',
  'condition_omitted',
  'official_alert_matched',
]

/** 위험행동 유형 → 화면 문구. 서버 signal.detail 로 분기한다.
 *
 * ★ 2026-08-13 추가. 전에는 R11(KB국민카드 당첨 + KB Pay 앱 설치)에 경고가 뜨는데
 *   이유가 similar_scam_case 라 "이전에 확인된 사례와 비슷한 문장이 있어요"가 나갔다.
 *   실제로 검출한 것은 "앱 설치를 요구한다" 다. **경고는 옳고 이유가 틀렸다.**
 *   이 머리말이 못 박은 원칙("사실 한 줄은 실제로 검출한 것만 적는다") 위반이었다.
 *
 * ★ "…내용이 있어요" 로 쓰고 "…문자예요" 로 쓰지 않는다.
 *   후자는 글 전체를 규정한다. R10(쿠팡 광고 + 본인인증)·R11 처럼 정상 문자에
 *   위험행동이 부수적으로 붙은 경우 과하게 읽힌다. 앞은 '부분'을 가리킨다.
 * ★ '사기'·'가짜' 를 쓰지 않는다(validate_question 금지어와 같은 기준).
 *   '찾았어요' 도 쓰지 않는다(초록 문구와 겹쳐 S22 를 재생산한다).
 */
const RISK_ACTION_TEXT = {
  계좌이체: ['돈을 보내라는 내용이 있어요.', '보내기 전에 기관 대표번호로 확인해 보세요'],
  앱설치: ['앱을 설치하라는 내용이 있어요.', '설치 전에 공식 앱스토어에서 직접 찾아보세요'],
  인증번호: ['본인인증을 하라는 내용이 있어요.', '문자 속 링크 말고 기관 앱에서 해 보세요'],
  개인정보요구: ['개인정보를 보내라는 내용이 있어요.', '보내기 전에 기관 대표번호로 확인해 보세요'],
}

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
    // ★★ 경고의 '이유'를 바로잡는다 (2026-08-13) ★★
    //   이 글이 무엇을 요구하는지 서버가 실제로 검출했다면, 그것을 이유로 쓴다.
    //   ★ tier 는 바꾸지 않는다. 여기는 이미 warn 인 자리이고, 이 분기가 하는 일은
    //     "왜 경고인지"를 실제 검출한 것으로 교체하는 것뿐이다. 그래서 정상 오판이
    //     원리적으로 늘지 않는다(서버 스위치 RISK_ACTION_RAISES_TIER=false 와 짝).
    //   ★ 근거가 된 원문 구절을 그대로 인용한다 - 유형 라벨이 만에 하나 어긋나도
    //     사용자는 실제 문장을 본다. 눈으로 대조할 수 있어야 한다.
    const risk = signals.find((s) => s.key === 'risk_action_requested' && RISK_ACTION_TEXT[s.detail])
    if (risk) {
      const [fact, action] = RISK_ACTION_TEXT[risk.detail]
      return {
        tier: 'warn',
        lead: '확인이 ', accent: '필요', tail: '한 문자예요',
        fact: `${fact} ${action}`,
        factQuote: risk.quote || '',
      }
    }
    // ★ official_alert_matched 는 공식 경보문을 실제로 찾은 경우다. 어르신이 그
    //   원문을 직접 읽는 것이 이 화면의 목적이므로, 문구를 링크로 걸어 크게 보여
    //   준다(factUrl 이 있으면 Judgment.jsx 가 <a> 로 렌더링한다).
    //   ★ "사기"·"가짜" 를 쓰지 않는다 - validate_question 금지어와 같은 기준이다.
    //     찾은 것은 '비슷한 사례를 알리는 안내'이지 이 글에 대한 판정이 아니다.
    //   ★ "찾았어요" 도 쓰지 않는다. 초록(④)의 "공식 자료를 찾았어요" 와 같은
    //     표현이라 S22 에서 사용자를 오도한 그 문구가 된다.
    if (attention.key === 'official_alert_matched') {
      return {
        tier: 'warn',
        lead: '확인이 ', accent: '필요', tail: '한 문자예요',
        fact: '받으신 내용과 비슷한 사례를 알리는 공식 안내가 있어요',
        factUrl: refs[0]?.url || '',
      }
    }
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

  // ③ 백엔드가 '확신할 공식 근거 없음'(no_source_found)을 줬다.
  //    ★ verdict_hint 를 우선한다 - refs 가 있어도 초록(찾았어요)으로 올리지 않는다.
  //      (표시 임계값 우회 방지, 2026-08-06) 예전에는 refs.length===0 일 때만 여기로
  //      왔고, no_source_found 인데 refs 가 있으면 ④ 초록으로 떨어져 "찾았습니다"가
  //      나갔다(배민 문자 → NIA 문서 오매칭). refs 유무로 '문구만' 나눈다.
  if (evidence?.verdict_hint === 'no_source_found') {
    if (refs.length > 0) {
      let host = ''
      try { host = refs[0]?.url ? new URL(refs[0].url).hostname.replace(/^www\./, '') : '' } catch { /* noop */ }
      return {
        tier: 'hold',
        lead: '비슷한 자료는 ', accent: '찾았', tail: '지만',
        fact: host ? `같은 안내인지는 확인하지 못했어요 · 원문 ${host}` : '같은 안내인지는 확인하지 못했어요',
        factUrl: refs[0]?.url || '',
      }
    }
    return {
      tier: 'hold',
      lead: '공식 자료를 ', accent: '못 찾았', tail: '어요',
      fact: '기관 대표번호로 확인해 보세요',
    }
  }

  // ★★ 초록은 '허용 목록' 방식이다 (2026-08-12) ★★
  //   전에는 배제 방식이었다 - ②의 신호 목록에 걸리면 초록에서 내리고, 안 걸리면
  //   초록으로 갔다. 이러면 **목록에 없는 신호가 새로 생기는 순간 뚫린다.**
  //   partially_matched 는 ③(no_source_found)을 그냥 지나가므로 ②가 유일한
  //   방어선이었다. 서버에 attention 신호를 하나 추가하면서 위 ATTENTION_KEYS 에
  //   넣는 것을 잊으면, 그 글이 초록 "공식 자료를 찾았어요"로 나간다.
  //   (8/8 에 유사도 0.6207 이 초록으로 나간 사고가 같은 종류였다.)
  //
  //   그래서 조건을 뒤집는다: **needs_check(확신 매칭)일 때만 초록으로 올린다.**
  //   배제 목록은 빠뜨리면 뚫리지만, 허용 목록은 빠뜨리면 주황으로 안전하게 떨어진다.
  //
  //   ★ 채택 시점 기준 동작 변화는 0건이다(평가셋 112 + 홀드아웃 30 전수 대조).
  //     지금은 needs_check 가 곧 확신 매칭이라 결과가 같다 - 이 변경은 그 등식이
  //     깨질 때를 대비한 것이지, 오늘 무엇을 고치려는 게 아니다.
  if (evidence?.verdict_hint !== 'needs_check') {
    return {
      tier: 'hold',
      lead: '같은 안내인지 ', accent: '확인하지 못했', tail: '어요',
      fact: '기관 대표번호로 확인해 보세요',
    }
  }

  // ④ 확신할 만한 공식 근거를 찾았다. '사실 한 줄'은 실제로 찾은 문서의 도메인을
  //    그대로 보여준다. (내용이 같은지까지는 확인하지 않았으므로 "맞습니다"라고 쓰지 않는다.)
  let host = ''
  try { host = refs[0]?.url ? new URL(refs[0].url).hostname.replace(/^www\./, '') : '' } catch { /* noop */ }
  return {
    tier: 'ok',
    lead: '공식 자료를 ', accent: '찾았', tail: '어요',
    fact: host ? `원문 보기 → ${host}` : '아래에서 원문을 직접 확인해 보세요',
    factUrl: refs[0]?.url || '',
  }
}
