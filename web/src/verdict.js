/**
 * 확인 결과(evidence) → '판단' 화면에 띄울 상태 한 벌
 * 담당: 조희진
 *
 * ★★ 왜 5단계인가 (2026-08 리뷰 반영 → 2026-08-13 act 추가) ★★
 *   전에는 화면이 하나뿐이라, 빨간 경고 + "확인이 필요한 문자예요" 가
 *   **정상 안내문에도 그대로 나갔다**. 공식 자료를 잘 찾은 경우까지 빨간
 *   경고를 띄우는 건 명백한 오작동이다(놀라게 하는 쪽으로 틀리는 것도 틀린 것이다).
 *   레이아웃은 그대로 두고 색·제목·'사실 한 줄'만 바뀌는 단계로 나눈다.
 *
 *     danger 빨강  지금 멈추세요             ← 계좌·카드번호가 실제로 검출됨
 *     warn   빨강  확인이 필요한 문자예요       ← 주의 신호가 검출됨 (의심 프레임)
 *     act    주황  잠깐, ○○ 전에 확인해 보세요  ← 위험행동만이 유일한 근거 (행동 프레임)
 *     hold   주황  공식 자료를 못 찾았어요
 *     ok     초록  공식 자료를 찾았어요
 *
 *   빨강은 위 두 개에서만 쓴다.
 *   ★ act 는 2026-08-13 에 늘었다. 위험행동만으로 올라간 글에 의심 프레임
 *     ("확인이 필요한 문자예요")을 재사용하면 "이 글이 수상하다"는 뜻이 되는데,
 *     서버가 실제로 관찰한 것은 "이 글이 무엇을 요구한다"뿐이다. 자세한 이유는
 *     아래 RISK_ACTION_TITLE 주석 참고.
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

/** 위험행동 유형 → 행동 프레임 제목. (2026-08-13)
 *
 * ★★ 왜 제목을 따로 두는가 ★★
 *   위험행동만으로 경고가 되는 글에 "확인이 필요한 문자예요"(의심 프레임)를 그대로
 *   쓰면 안 된다. 그건 "이 글이 수상하다"는 뜻으로 읽히는데, 서버가 실제로 관찰한
 *   것은 "이 글이 무엇을 요구한다"뿐이다. **정상 문자를 의심으로 표시하지 않는다**는
 *   절대 조건과 충돌한다(R10 쿠팡 광고 · R11 카드사 당첨이 그런 글이다).
 *   그래서 tier 'act' 를 따로 두고 색·그림도 경고(빨강)가 아닌 주황을 쓴다.
 */
const RISK_ACTION_TITLE = {
  계좌이체: ['잠깐, 보내기 전에 ', '확인', '해 보세요'],
  앱설치: ['잠깐, 설치하기 전에 ', '확인', '해 보세요'],
  인증번호: ['잠깐, 인증하기 전에 ', '확인', '해 보세요'],
  개인정보요구: ['잠깐, 보내기 전에 ', '확인', '해 보세요'],
}

/**
 * ② '사실 블록' - **항상** 만든다. (2026-08-13 구조 변경)
 *
 * ★★ 왜 분리했나 ★★
 *   전에는 ②가 "먼저 걸리는 신호가 이긴다"는 구조여서, 위험행동이 붙는 순간
 *   경보문 원문 링크가 화면에서 사라졌다(S12·S16·S18·S22·S28·H27).
 *   위험행동과 경보문은 **경쟁하는 정보가 아니라 서로 다른 자리**다.
 *     ① 위험행동 블록 - 이 글이 무엇을 하라고 하는가 + 그 앞에 무엇을 할 것인가
 *     ② 사실 블록     - 우리가 무엇을 찾았는가(또는 못 찾았는가)
 *   각자 자기 자리에 들어간다.
 */
/**
 * ③ '주소 블록' - 문자 속 주소가 최종적으로 어디로 가는지. (2026-08-15)
 *
 * ★★ 사실만 말한다. 판정하지 않는다. ★★
 *   서버(url_expand.py)가 HEAD 로 펼친 최종 도메인을 그대로 옮긴다.
 *   설계·실측: docs/evaluation/URL펼치기_설계_2026-08-15.md
 *
 * ★ go.kr / or.kr 일 때만 한 줄을 더한다.
 *   그 접미사는 **등록 자격이 정부·공공기관으로 제한**돼 있어서, "공공기관
 *   주소다"가 판정이 아니라 등록 제도에서 나오는 사실이 된다. 누구나 살 수 있는
 *   .com 과 다르다(사칭 S03 gov24-refund-event.com · S08 nhis-refund24.com 이
 *   전부 .com 이었다).
 *
 * ★★ 그 외 도메인에는 아무 말도 하지 않는다 ★★
 *   실측에서 kt.com · coupang.com · play.google.com 이 **전부 정상 문자**였다.
 *   "공공기관 주소가 아닙니다"를 띄우면 그 셋이 전부 의심을 받는다 -
 *   '정상 문자를 의심으로 표시하지 않는다'는 절대 조건 위반이다.
 *   ★ "안전합니다" 도 쓰지 않는다. 공공 도메인이라는 것이 안전을 뜻하지 않는다.
 *
 * ★ 펼쳐지지 않았으면(시작 == 최종) 서버가 신호 자체를 안 보낸다. 실패해도
 *   안 보낸다(EX-007, 침묵). 그러면 이 줄은 화면에 없다 - 없는 것은 없는 것이다.
 */
/**
 * ③-2 '기관 주소 대조' - 문자가 말하는 기관의 공식 주소와 받은 주소를 나란히. (2026-08-16)
 *
 * ★★ 판정하지 않는다. 두 주소를 나란히 놓는 것 자체가 사실이고, 비교는 어르신이 한다. ★★
 *   "가짜입니다"·"사칭입니다"·"위험합니다" 를 쓰지 않는다(validate_question 금지어와
 *   같은 기준). 서버(org_domain.py)가 이미 판정 문구 없이 값만 내려준다.
 *
 * ★ 발동이 아주 좁다. 표(corpus/기관_공식도메인_2026-08-15.csv)에 있는 기관 이름이
 *   본문에 있고 + 본문에 URL 이 있고 + 도메인이 다를 때만이다. 표에 없는 기관
 *   (지자체 전부 포함)·URL 없는 문자·도메인 일치는 전부 **침묵**한다.
 *   실측(2026-08-15): 확대 112건 중 2건(S03·S08, 둘 다 사칭)만 걸리고 정상은 0건.
 *
 * ★ "안전합니다" 는 여기서도 금지다. 그래서 **일치하면 아무 줄도 나오지 않는다** -
 *   일치가 안전을 뜻하지 않기 때문이다.
 */
function orgBlock(signals) {
  const s = signals.find(
    (x) => x.key === 'org_domain_mismatch' && x.detail && x.official_domain && x.received_domain,
  )
  if (!s) return null
  return {
    official: `${s.detail}의 공식 주소는 ${s.official_domain}입니다`,
    received: `받으신 주소는 ${s.received_domain}입니다`,
  }
}

function linkBlock(signals) {
  const s = signals.find((x) => x.key === 'url_expanded' && x.detail)
  if (!s) return null
  return {
    fact: `받으신 주소는 최종적으로 ${s.detail} 로 연결됩니다`,
    // 공공기관 접미사일 때만 채운다. 아니면 빈 문자열 = 화면에 줄이 없다.
    publicNote: s.public_domain ? '정부·공공기관 주소(go.kr)로 연결됩니다' : '',
  }
}

/**
 * ②-보조 '근거 유보 한 줄' - 참고자료는 붙었는데 같은 안내인지 확인하지 못했을 때. (2026-08-16 제안)
 *
 * ★ 2026-08-17 채택 — Judgment.jsx 가 이 값을 화면에 그린다.
 *
 * ★ 왜 필요한가 (실측 2026-08-16)
 *   factBlock 은 한 줄만 고른다. 그래서 의심 신호(similar_scam_case·경보문)가 있으면
 *   그쪽이 이기고 "같은 안내인지는 확인하지 못했어요" 가 **사라진다.**
 *     S25 (유사도 0.6295) 사실 한 줄 = "같은 안내인지는 확인하지 못했어요…"  ← 붙는다
 *     S01 (유사도 0.6644) 사실 한 줄 = "이전에 확인된 사례와 비슷한 문장이 있어요"  ← 빠진다
 *     라이브(0.6539)      같음                                                  ← 빠진다
 *   ★ 하필 **사칭 건**에서 빠진다. 참고자료 목록에는 다른 제도의 공식 문서가 그대로
 *     보이는데, 그게 같은 안내인지 확인하지 못했다는 말만 없어진다.
 *
 * ★ 조건은 기존 branch 와 **같은 것**을 쓴다(근거 있음 + 확신 매칭 아님).
 *   임계값을 새로 만들지 않는다 - 서버가 이미 그 판단을 verdict_hint 로 내려보낸다.
 */
function factNoteFor(evidence, refs, fact) {
  if (!refs.length) return ''
  if (evidence?.verdict_hint === 'needs_check') return ''   // 확신 근거면 유보하지 않는다
  if ((fact || '').includes('확인하지 못했')) return ''      // 이미 사실 한 줄이 말하고 있다
  return '아래 참고자료가 같은 안내인지는 확인하지 못했어요'
}

function factBlock(evidence, signals, refs) {
  const alert = signals.find((s) => s.key === 'official_alert_matched')
  if (alert) {
    // ★ 경보문은 제목과 원문 링크를 함께 보여준다 - 어르신이 그 원문을 직접
    //   읽는 것이 이 블록의 목적이다(2026-08-12 S22 조치).
    return {
      fact: '받으신 내용과 비슷한 사례를 알리는 공식 안내가 있어요',
      factTitle: refs[0]?.title || '',
      factUrl: refs[0]?.url || '',
    }
  }
  // ★ similar_scam_case 의 원문 label 은 "...사기 수법과 비슷합니다" 처럼 단정적
  //   금지어를 담고 있다. 뜻은 살리고 표현만 순화한다.
  const scam = signals.find((s) => s.severity === 'attention' && s.key === 'similar_scam_case')
  if (scam) return { fact: '이전에 확인된 사례와 비슷한 문장이 있어요' }

  const other = signals.find(
    (s) => s.severity === 'attention' && ATTENTION_KEYS.includes(s.key)
      && s.key !== 'similar_scam_case' && s.key !== 'official_alert_matched',
  )
  if (other) return { fact: firstSentence(other.label) }

  // ★ verdict_hint 를 우선한다 - refs 가 있어도 초록(찾았어요)으로 올리지 않는다.
  //   (표시 임계값 우회 방지, 2026-08-06) refs 유무로 '문구만' 나눈다.
  if (evidence?.verdict_hint !== 'needs_check') {
    if (refs.length > 0) {
      let host = ''
      try { host = refs[0]?.url ? new URL(refs[0].url).hostname.replace(/^www\./, '') : '' } catch { /* noop */ }
      return {
        fact: host ? `같은 안내인지는 확인하지 못했어요 · 원문 ${host}` : '같은 안내인지는 확인하지 못했어요',
        factUrl: refs[0]?.url || '',
      }
    }
    return { fact: '공식 자료를 못 찾았어요 · 기관 대표번호로 확인해 보세요' }
  }

  // 확신할 만한 공식 근거를 찾았다. (내용이 같은지까지는 확인하지 않았으므로
  // "맞습니다"라고 쓰지 않는다.)
  let host = ''
  try { host = refs[0]?.url ? new URL(refs[0].url).hostname.replace(/^www\./, '') : '' } catch { /* noop */ }
  return {
    fact: host ? `원문 보기 → ${host}` : '아래에서 원문을 직접 확인해 보세요',
    factUrl: refs[0]?.url || '',
  }
}

/**
 * 화면에 필요한 것 전부를 한 번에 계산한다.
 * @param evidence  GET /checks/{id}/evidence 응답
 * @param checkData POST /checks 응답 (masked_items 가 여기 있다)
 *
 * 반환 - 두 블록이 따로 나간다(2026-08-13)
 *   risk  ① 위험행동 블록 {quote, fact, action} 또는 null
 *   fact / factTitle / factUrl  ② 사실 블록 (항상 있다)
 *   link  ③ 주소 블록 {fact, publicNote} 또는 null (2026-08-15, tier 영향 없음)
 *   org   ③-2 기관 주소 대조 {official, received} 또는 null (2026-08-16, tier 영향 없음)
 *   factNote  ②-보조 근거 유보 한 줄 (2026-08-17 채택 · 화면에 그린다)
 */
export function judgmentState(evidence, checkData) {
  const signals = evidence?.signals || []
  const refs = evidence?.references || []
  const maskedItems = checkData?.masked_items || []

  // ── ① 위험행동 블록. tier 와 무관하게, 검출됐으면 항상 만든다.
  //    ★ quote 는 서버가 마스킹된 텍스트에서만 뽑은 원문 구절이다. 받으신 문장을
  //      눈으로 직접 대조하게 하는 것이 이 블록의 핵심이다 - 유형 라벨이 만에 하나
  //      어긋나도 사용자는 실제 문장을 본다.
  const riskSig = signals.find((s) => s.key === 'risk_action_requested' && RISK_ACTION_TEXT[s.detail])
  const risk = riskSig
    ? {
      detail: riskSig.detail,
      quote: riskSig.quote || '',
      fact: RISK_ACTION_TEXT[riskSig.detail][0],
      action: RISK_ACTION_TEXT[riskSig.detail][1],
    }
    : null

  // ── ② 사실 블록. 항상 만든다.
  const facts = factBlock(evidence, signals, refs)
  const factNote = factNoteFor(evidence, refs, facts.fact)

  // ── ③ 주소 블록. 서버가 펼치기에 성공했을 때만 있다. tier 에 영향을 주지 않는다.
  const link = linkBlock(signals)
  // ── ③-2 기관 주소 대조. 매핑표 기관 + URL + 도메인 불일치일 때만. tier 영향 없음.
  const org = orgBlock(signals)

  // ── 단계와 제목
  //    ① 계좌·카드번호가 실제로 검출됐다 → 가장 강한 경고.
  //       masking.py 의 정규식이 문맥까지 보고 잡아낸 '진짜 숫자'라 신뢰도가 높다.
  const money = maskedItems.find((m) => m.type === 'account' || m.type === 'card')
  if (money) {
    return {
      tier: 'danger',
      lead: '지금 ', accent: '멈추세요', tail: '',
      risk,
      link,
      org,
      factNote,
      ...facts,
      fact: MASKED_LABEL[money.type] || '금융 정보가 적혀 있어요',
      factTitle: '', factUrl: '',
    }
  }

  // ② 의심 프레임 - 위험행동 말고 다른 주의 신호가 있다.
  //    ★ 그 신호들(사기사례 유사·경보문 매칭·조건 생략·서두름)은 글 자체에서 관찰된
  //      의심 근거라 "확인이 필요한 문자예요"가 정당하다.
  const attention = signals.find((s) => s.severity === 'attention' && ATTENTION_KEYS.includes(s.key))
  if (attention) {
    return {
      tier: 'warn',
      lead: '확인이 ', accent: '필요', tail: '한 문자예요',
      risk,
      link,
      org,
      factNote,
      ...facts,
    }
  }

  // ③ 행동 프레임 - 위험행동만이 유일한 근거다.
  //    ★ 의심 프레임을 재사용하지 않는다(위 RISK_ACTION_TITLE 주석 참고).
  //    ★ severity 를 본다. 서버 스위치 RISK_ACTION_RAISES_TIER 가 꺼져 있으면
  //      info 로 오고, 그때는 단계를 올리지 않는다 - 스위치가 화면까지 관통한다.
  if (risk && riskSig.severity === 'attention') {
    const [lead, accent, tail] = RISK_ACTION_TITLE[risk.detail]
    return { tier: 'act', lead, accent, tail, risk, link, org, factNote, ...facts }
  }

  // ★★ 초록은 '허용 목록' 방식이다 (2026-08-12) ★★
  //   전에는 배제 방식이었다 - ②의 신호 목록에 걸리면 초록에서 내리고, 안 걸리면
  //   초록으로 갔다. 이러면 **목록에 없는 신호가 새로 생기는 순간 뚫린다.**
  //   그래서 조건을 뒤집는다: **needs_check(확신 매칭)일 때만 초록으로 올린다.**
  //   배제 목록은 빠뜨리면 뚫리지만, 허용 목록은 빠뜨리면 주황으로 안전하게 떨어진다.
  if (evidence?.verdict_hint !== 'needs_check') {
    return {
      tier: 'hold',
      lead: refs.length > 0 ? '같은 안내인지 ' : '공식 자료를 ',
      accent: refs.length > 0 ? '확인하지 못했' : '못 찾았',
      tail: '어요',
      risk,
      link,
      org,
      factNote,
      ...facts,
    }
  }

  // ④ 확신할 만한 공식 근거를 찾았다.
  return {
    tier: 'ok',
    lead: '공식 자료를 ', accent: '찾았', tail: '어요',
    risk,
    link,
    ...facts,
  }
}
