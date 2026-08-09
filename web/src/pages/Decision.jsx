import { useEffect, useState } from 'react'
import { submitVerdict } from '../api.js'
import { logClick, logError } from '../events.js'
import surveyMascot from '../assets/check-flow/decision-mascot.svg'
import surveyAvoid from '../assets/check-flow/survey-avoid.png'
import surveyLearnMore from '../assets/check-flow/survey-learn-more.png'
import surveyAskFamily from '../assets/check-flow/survey-ask-family.png'
import surveyFollowAnyway from '../assets/check-flow/survey-follow-anyway.png'
import recordCheck from '../assets/check-flow/record-check.png'

const SCREEN = 'S4'

const DECISIONS = [
  { id: 'not_apply', label: '따라하지 않을래요', image: surveyAvoid },
  { id: 'hold', label: '조금 더 알아볼래요', image: surveyLearnMore },
  { id: 'ask_family', label: '가족에게 물어볼래요', image: surveyAskFamily },
  { id: 'apply', label: '그래도 따라할래요', image: surveyFollowAnyway },
]

const ERROR_TYPE_LABEL = {
  title_dependent: '제목만 보고 판단하기 쉬운 글',
  authority_impersonation: '기관 이름을 닮게 꾸민 글',
  number_condition: '숫자와 조건이 빠진 글',
  overgeneralization: '한 가지를 모두에게 넓힌 글',
}

export default function Decision({ checkId, onTraining, onHome }) {
  const [result, setResult] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [])

  async function choose(decision) {
    setSelected(decision)
    setBusy(true)
    setError('')
    try {
      setResult(await submitVerdict(checkId, decision))
    } catch (error) {
      setError(error.message)
      logError(SCREEN, error.code || 'verdict_submit_failed')
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    const category = ERROR_TYPE_LABEL[result.tagged_error_type] || '확인이 필요한 글'
    return (
      <section className="decision-record" aria-labelledby="decision-record-title">
        <div className="decision-record__visual" aria-hidden="true">
          <span />
          <img src={recordCheck} alt="" />
        </div>
        <h2 id="decision-record-title">응답을 <strong>기록</strong>해 두었어요</h2>
        <article className="decision-record__message">
          <span>{category}</span>
          <p>{result.message}</p>
        </article>
        <div className="decision-record__actions">
          <button type="button" onClick={() => { logClick(SCREEN, 'to_training'); onTraining() }}>오늘의 5분 연습 시작하기</button>
          <button type="button" onClick={() => { logClick(SCREEN, 'to_home'); onHome() }}>홈 화면으로 돌아가기</button>
        </div>
      </section>
    )
  }

  return (
    <section className="decision-flow" aria-labelledby="decision-title">
      <div className="decision-flow__hero">
        <span className="decision-flow__mascot"><img src={surveyMascot} alt="" /></span>
        <p>곁눈과 함께 확인한 정보</p>
        <h2 id="decision-title">어떻게 해보고 싶으신가요?</h2>
      </div>

      <div className="decision-flow__panel">
        <p className="decision-flow__notice">
          <span>정답은 없습니다</span>
          <span>응답은 더 좋은 연습을 만들기 위해 활용됩니다</span>
        </p>

        {error && <div className="error-box">{error}</div>}

        <div className="decision-flow__options" role="radiogroup" aria-label="앞으로 하고 싶은 행동">
          {DECISIONS.map((decision) => {
            const isSelected = selected === decision.id
            return (
              <button
                className={isSelected ? 'is-selected' : ''}
                type="button"
                role="radio"
                aria-checked={isSelected}
                disabled={busy}
                key={decision.id}
                onClick={() => { logClick(SCREEN, `decision_${decision.id}`); choose(decision.id) }}
              >
                <span className="decision-flow__check" aria-hidden="true" />
                <img src={decision.image} alt="" aria-hidden="true" />
                <span>{decision.label}</span>
              </button>
            )
          })}
        </div>
        {busy && <p className="decision-flow__pending" role="status">응답을 기록하고 있어요.</p>}
      </div>
    </section>
  )
}
