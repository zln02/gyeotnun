/**
 * S2.5 - 판단 (확인 결과 요약)
 * 담당: 조희진
 * Figma node 340:459 "판단"
 *
 * ★ 왜 화면이 하나 늘었나
 *   이전에는 이 내용이 S3 질문 화면 맨 위에 배지(VerdictBadge)로 얹혀 있었다.
 *   그러다 보니 "결과"와 "첫 질문"이 한 화면에 같이 떠서, 시니어가 결과를
 *   읽기도 전에 질문에 답하려다 혼란스러워하는 게 반복 관찰됐다.
 *   Figma 3차 개편에서 결과를 독립 화면으로 떼어냈고, 그대로 따랐다.
 *
 * ★★ 하지 않은 것 두 가지 (의도적) ★★
 *   1) Figma 에는 제목 아래에 '제목 의존형'·'과잉 일반화형' 같은 오판유형
 *      태그가 붙어 있다. 오판유형은 사용자가 행동을 고른 뒤(S4) 서버가
 *      태깅하는 값이라 이 시점에 존재하지 않는다 → 대신 실제로 검출된
 *      신호를 태그로 보여준다(verdict.js 의 riskTags). 없으면 비운다.
 *   2) Figma 하단의 "오늘 1,248명이 함께 확인했어요" 는 넣지 않았다.
 *      그런 집계를 주는 API 가 없고, 숫자를 지어내면 곁눈이 하지 않기로 한
 *      짓이 된다(docs/evaluation/judgment_basis.md 의 표시 정직성 원칙).
 */
import { verdictTier, evidenceSummary, riskTags } from '../verdict.js'
import { logClick } from '../events.js'
import warnHero from '../assets/verify/warn_hero.png'
import okHero from '../assets/verify/ic_record_done.png'
import arrowRight from '../assets/verify/ic_arrow_right_white.svg'

const SCREEN = 'S3'   // 계측 화면 코드는 기존 S3(질문 흐름)에 붙여 둔다 - 흐름상 같은 단계다

/**
 * Figma 원본은 '확인 필요'(빨강) 상태 하나만 그려져 있다. 그런데 실제 서버는
 * 세 가지 결과를 낸다. 못 찾았거나 관련 자료를 찾은 경우까지 빨간 경고를
 * 띄우면 사실과 다른 겁을 주게 되므로, 같은 레이아웃에 색과 문구만 바꿔
 * 나머지 두 상태를 만들었다.
 */
const TIERS = {
  suspicious: {
    hero: warnHero,
    heroClass: 'warn',
    lead: '확인이 ', accent: '필요', tail: '한 문자에요',
    ctaClass: 'warn',
  },
  unknown: {
    hero: warnHero,
    heroClass: 'hold',
    lead: '공식 자료에서 ', accent: '찾지 못', tail: '했어요',
    ctaClass: 'hold',
  },
  confirmed: {
    hero: okHero,
    heroClass: 'ok',
    lead: '관련 자료를 ', accent: '찾았', tail: '어요',
    ctaClass: 'ok',
  },
}

export default function Judgment({ evidence, onStart }) {
  const tier = verdictTier(evidence)
  const t = TIERS[tier]
  const tags = riskTags(evidence)

  return (
    <div className="judgment">
      <div className={`judgment-hero ${t.heroClass}`}>
        <span className="judgment-hero-ring" aria-hidden="true" />
        <img src={t.hero} width="98" height="98" alt="" aria-hidden="true" className="judgment-hero-img" />
      </div>

      <h2 className="judgment-title">
        {t.lead}<span className={`accent ${t.heroClass}`}>{t.accent}</span>{t.tail}
      </h2>

      <p className="judgment-sub">{evidenceSummary(evidence, tier)}</p>

      {tags.length > 0 && (
        <ul className="judgment-tags" aria-label="글에서 확인된 표현">
          {tags.map((name) => <li key={name} className="judgment-tag">{name}</li>)}
        </ul>
      )}

      <button
        type="button"
        className={`judgment-cta ${t.ctaClass}`}
        onClick={() => { logClick(SCREEN, 'start_verify'); onStart() }}
      >
        <span>하나씩 확인하기</span>
        <img src={arrowRight} width="21" height="21" alt="" aria-hidden="true" />
      </button>
    </div>
  )
}
