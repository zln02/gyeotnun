/**
 * S4 - 판단 기록
 * 담당: 조희진 (화면) / 장지석 (태깅)
 *
 * ★ 여기서 고르는 것은 '진짜/가짜'가 아니라 '내가 어떻게 할지' 이다.
 *   진위를 고르게 하면 결국 사용자에게 판정을 강요하는 셈이 된다.
 *   곁눈은 행동(따라한다 / 안 한다 / 미룬다 / 물어본다)을 고르게 한다.
 * ★ 결과 문구는 절대 비난하지 않는다. 확인한 행동 자체를 칭찬한다.
 */
import { useState } from 'react'
import { submitVerdict } from '../api.js'

const DECISIONS = [
  { id: 'not_apply', label: '이번엔 따라하지 않을래요', icon: '🙅' },
  { id: 'hold',      label: '조금 더 알아보고 정할게요', icon: '⏸️' },
  { id: 'ask_family',label: '가족에게 한번 물어볼게요', icon: '👨‍👩‍👧' },
  { id: 'apply',     label: '그래도 따라해 보려고요',   icon: '👍' },
]

const ERROR_TYPE_LABEL = {
  title_dependent: '제목만 보고 판단하기 쉬운 글',
  authority_impersonation: '기관 이름이 앞세워진 글',
  number_condition: '숫자와 조건이 빠진 글',
  overgeneralization: '한 가지를 전부로 넓힌 글',
}

export default function Decision({ checkId, onTraining, onHome }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function choose(decision) {
    setBusy(true)
    setError('')
    try {
      setResult(await submitVerdict(checkId, decision))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (result) {
    return (
      <>
        <h2>기록해 두었어요</h2>
        <div className="card">
          <span className="badge">{ERROR_TYPE_LABEL[result.tagged_error_type] || '확인이 필요한 글'}</span>
          <p className="lead" style={{ marginTop: 14 }}>{result.message}</p>
        </div>
        <button className="btn" onClick={onTraining}>오늘의 5분 연습 하러 가기</button>
        <button className="btn secondary" onClick={onHome}>처음으로 돌아가기</button>
      </>
    )
  }

  return (
    <>
      <h2>어떻게 하시겠어요?</h2>
      <p className="sub">
        정답은 없습니다. 지금 마음이 가는 대로 골라 주세요.
        고르신 내용은 다음 연습을 만드는 데만 씁니다.
      </p>

      {error && <div className="error-box">{error}</div>}

      {DECISIONS.map((d) => (
        <button key={d.id} className="btn choice" disabled={busy} onClick={() => choose(d.id)}>
          <span aria-hidden="true">{d.icon}</span> {d.label}
        </button>
      ))}
    </>
  )
}
