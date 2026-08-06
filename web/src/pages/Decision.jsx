/**
 * S4 - 응답(어떻게 할지 고르기) → 기록
 * 담당: 조희진 (화면) / 장지석 (태깅)
 * Figma node 493:87 "응답" / 509:37 "기록"
 *
 * ★ 여기서 고르는 것은 '진짜/가짜'가 아니라 '내가 어떻게 할지' 이다.
 *   진위를 고르게 하면 결국 사용자에게 판정을 강요하는 셈이 된다.
 *   곁눈은 행동(따라한다 / 안 한다 / 미룬다 / 물어본다)을 고르게 한다.
 * ★ 결과 문구는 절대 비난하지 않는다. 확인한 행동 자체를 칭찬한다.
 *
 * ★ 2026-08 Figma 3차 이식: 글자만 있던 버튼 4개를 그림 카드 2×2 로 바꿨다.
 *   고르는 순간 바로 제출하지 않고 한 번 더 확인 버튼을 두는 이유는,
 *   이 선택이 되돌릴 수 없는 기록이고 카드가 커서 스크롤 중 잘못 눌리기
 *   쉽기 때문이다(Figma 의 카드 우상단 체크 표시가 '고른 상태'를 전제한다).
 */
import { useState } from 'react'
import { submitVerdict } from '../api.js'
import { logClick, logError } from '../events.js'
import icNotApply from '../assets/verify/dec_not_apply.png'
import icHold from '../assets/verify/dec_hold.png'
import icAskFamily from '../assets/verify/dec_ask_family.png'
import icApply from '../assets/verify/dec_apply.png'
import mascot from '../assets/verify/mascot.png'
import recordDone from '../assets/verify/ic_record_done.png'

const SCREEN = 'S4'

const DECISIONS = [
  { id: 'not_apply',  label: '따라하지 않을래요',   image: icNotApply },
  { id: 'hold',       label: '조금 더 알아볼래요',  image: icHold },
  { id: 'ask_family', label: '가족에게 물어볼래요', image: icAskFamily },
  { id: 'apply',      label: '그래도 따라할래요',   image: icApply },
]

const ERROR_TYPE_LABEL = {
  title_dependent: '제목만 보고 판단하기 쉬운 글',
  authority_impersonation: '기관 이름이 앞세워진 글',
  number_condition: '숫자와 조건이 빠진 글',
  overgeneralization: '한 가지를 전부로 넓힌 글',
}

export default function Decision({ checkId, onTraining, onHome }) {
  const [selected, setSelected] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function submit() {
    if (!selected) return
    setBusy(true)
    setError('')
    try {
      setResult(await submitVerdict(checkId, selected))
    } catch (e) {
      setError(e.message)
      logError(SCREEN, e.code || 'verdict_submit_failed')
    } finally {
      setBusy(false)
    }
  }

  /* ---------------------------------------------------------------- 기록 */
  if (result) {
    return (
      <div className="record">
        <img src={recordDone} width="120" height="120" alt="" aria-hidden="true" className="record-hero" />
        <h2 className="record-title">응답을 <span className="accent">기록</span>해 두었어요</h2>
        <div className="record-card">
          <span className="record-badge">
            {ERROR_TYPE_LABEL[result.tagged_error_type] || '확인이 필요한 글'}
          </span>
          <p className="record-message">{result.message}</p>
        </div>
        <button type="button" className="record-btn primary" onClick={() => { logClick(SCREEN, 'to_training'); onTraining() }}>
          오늘의 5분 연습 시작하기
        </button>
        <button type="button" className="record-btn" onClick={() => { logClick(SCREEN, 'to_home'); onHome() }}>
          홈 화면으로 돌아가기
        </button>
      </div>
    )
  }

  /* ---------------------------------------------------------------- 응답 */
  return (
    <div className="respond">
      <div className="respond-head">
        <img src={mascot} width="62" height="62" alt="" aria-hidden="true" className="respond-mascot" />
        <p className="respond-eyebrow">곁눈과 함께 확인한 정보</p>
        <h2 className="respond-title">어떻게 해보고 싶으신가요?</h2>
      </div>

      <div className="respond-sheet">
        <p className="respond-note">
          정답은 없습니다<br />
          응답은 더 좋은 연습을 만들기 위해 활용됩니다
        </p>

        {error && <div className="error-box">{error}</div>}

        <div className="respond-grid" role="radiogroup" aria-label="어떻게 할지 고르기">
          {DECISIONS.map((d) => (
            <button
              key={d.id}
              type="button"
              role="radio"
              aria-checked={selected === d.id}
              disabled={busy}
              className={`respond-card${selected === d.id ? ' selected' : ''}`}
              onClick={() => { logClick(SCREEN, `decision_${d.id}`); setSelected(d.id) }}
            >
              <span className="respond-check" aria-hidden="true" />
              <img src={d.image} alt="" aria-hidden="true" className="respond-card-img" />
              <span className="respond-card-label">{d.label}</span>
            </button>
          ))}
        </div>

        <button type="button" className="verify-cta" disabled={!selected || busy} onClick={submit}>
          {busy ? '기록하는 중이에요' : '이렇게 할래요'}
        </button>
      </div>
    </div>
  )
}
