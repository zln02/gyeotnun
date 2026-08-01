/**
 * S2 - 확인 중 (로딩)
 * 담당: 조희진
 *
 * 로딩 화면에서도 '판정 중'이라고 쓰지 않는다.
 *  (X) "진위를 판별하고 있습니다"  → 판정 서비스로 오해된다
 *  (O) "어디를 확인하면 좋을지 찾고 있어요"
 * 무엇을 하고 있는지 단계로 보여 주면 기다림 체감이 크게 줄어든다.
 */
import { useEffect, useState } from 'react'
import { getEvidence } from '../api.js'
import { logClick, logError } from '../events.js'

const SCREEN = 'S2'

const STEPS = [
  '올려 주신 내용을 읽고 있어요',
  '개인정보를 가리고 있어요',
  '공식 자료와 맞춰 보고 있어요',
  '여쭤볼 것을 정리하고 있어요',
]

// 실제 API(공공데이터 대조 + Claude 호출)는 mock 과 달리 몇 초씩 걸릴 수 있다.
// 이 시간을 넘기면 STEPS 순환 대신 "아직 하고 있어요" 문구로 바꿔
// 화면이 멈춘 게 아니라는 걸 알려 준다.
const LONG_WAIT_MS = 10000
const LONG_WAIT_MESSAGE = '생각보다 시간이 걸리고 있어요. 실제 자료를 자세히 살펴보는 중입니다. 조금만 더 기다려 주세요.'

export default function Checking({ checkId, checkData, onReady, onError }) {
  const [step, setStep] = useState(0)
  const [error, setError] = useState('')
  const [longWait, setLongWait] = useState(false)

  useEffect(() => {
    setLongWait(false)
    const t = setInterval(() => setStep((s) => (s + 1) % STEPS.length), 900)
    const longWaitTimer = setTimeout(() => setLongWait(true), LONG_WAIT_MS)
    let cancelled = false
    ;(async () => {
      try {
        const ev = await getEvidence(checkId)
        // 최소 2초는 보여 준다 — 너무 빨리 넘어가면 "제대로 본 게 맞나" 불안해한다
        setTimeout(() => { if (!cancelled) onReady(ev) }, 2000)
      } catch (e) {
        if (!cancelled) { setError(e.message); logError(SCREEN, 'evidence_fetch_failed') }
      }
    })()
    return () => { cancelled = true; clearInterval(t); clearTimeout(longWaitTimer) }
  }, [checkId])

  if (error) {
    return (
      <>
        <div className="error-box">{error}</div>
        <button className="btn" onClick={() => { logClick(SCREEN, 'to_home_from_error'); onError() }}>처음으로 돌아가기</button>
      </>
    )
  }

  return (
    <div className="loading">
      <div className="spinner" role="status" aria-live="polite" />
      <h2>확인하고 있어요</h2>
      <p className="lead">{longWait ? LONG_WAIT_MESSAGE : STEPS[step]}</p>

      {checkData?.masked && (
        <div className="signal" style={{ textAlign: 'left', marginTop: 24 }}>
          <span aria-hidden="true">🔒</span>
          <span>
            사진 속 전화번호와 계좌번호는 가려 두었습니다.
            원본 사진은 확인이 끝나면 지워집니다.
          </span>
        </div>
      )}
    </div>
  )
}
