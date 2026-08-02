/**
 * S2 - 확인 중 (로딩)
 * 담당: 조희진
 *
 * 로딩 화면에서도 '판정 중'이라고 쓰지 않는다.
 *  (X) "진위를 판별하고 있습니다"  → 판정 서비스로 오해된다
 *  (O) "어디를 확인하면 좋을지 찾고 있어요"
 * 무엇을 하고 있는지 단계로 보여 주면 기다림 체감이 크게 줄어든다.
 *
 * ★ 2026-08 Figma 이식: 한 줄씩 바뀌던 문구를 "체크리스트가 하나씩 켜지는"
 *   형태로 바꿨다(곁눈(figma) 신규 내보내기 node 95:901 참고, styles.css의
 *   "S2 확인 중 - Figma 이식" 절). 문구 자체(STEPS)는 기존 그대로 두고,
 *   보여주는 방식만 Figma 패턴을 따랐다 - Figma 원본 3단계 문구는 이 프로젝트에서
 *   이미 자리잡은 4단계 문구와 달라 덮어쓰지 않았다. API 호출(getEvidence)·
 *   최소 노출 시간(2초)·장기 대기 안내·오류 처리 로직은 그대로다.
 */
import { useEffect, useState } from 'react'
import { getEvidence } from '../api.js'
import { logClick, logError } from '../events.js'
import mascotImg from '../assets/checking/mascot.png'
import checkIcon from '../assets/checking/check.svg'

const SCREEN = 'S2'

const STEPS = [
  '올려 주신 내용을 읽고 있어요',
  '개인정보를 가리고 있어요',
  '공식 자료와 맞춰 보고 있어요',
  '여쭤볼 것을 정리하고 있어요',
]

const STEP_INTERVAL_MS = 1300

// 실제 API(공공데이터 대조 + Claude 호출)는 mock 과 달리 몇 초씩 걸릴 수 있다.
// 이 시간을 넘기면 "아직 하고 있어요" 문구로 바꿔 화면이 멈춘 게 아니라는 걸 알려 준다.
const LONG_WAIT_MS = 10000
const LONG_WAIT_MESSAGE = '생각보다 시간이 걸리고 있어요. 실제 자료를 자세히 살펴보는 중입니다. 조금만 더 기다려 주세요.'

export default function Checking({ checkId, checkData, onReady, onError }) {
  const [step, setStep] = useState(0)
  const [error, setError] = useState('')
  const [longWait, setLongWait] = useState(false)

  useEffect(() => {
    setStep(0)
    setLongWait(false)
    // 마지막 단계에 닿으면 멈춘다 - 끝까지 다 확인했다는 느낌을 주고 계속
    // 순환하며 불안하게 만들지 않는다(실제 완료는 아래 getEvidence 가 결정).
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), STEP_INTERVAL_MS)
    const longWaitTimer = setTimeout(() => setLongWait(true), LONG_WAIT_MS)
    let cancelled = false
    ;(async () => {
      try {
        const ev = await getEvidence(checkId)
        // 최소 2초는 보여 준다 — 너무 빨리 넘어가면 "제대로 본 게 맞나" 불안해한다
        setTimeout(() => { if (!cancelled) onReady(ev) }, 2000)
      } catch (e) {
        if (!cancelled) { setError(e.message); logError(SCREEN, e.code || 'evidence_fetch_failed') }
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
    <div className="checking2" role="status" aria-live="polite">
      <div className="checking2-icon-wrap">
        <span className="checking2-glow" aria-hidden="true" />
        <img src={mascotImg} width="80" height="80" alt="" aria-hidden="true" className="checking2-icon" />
      </div>
      <h2 className="checking2-title"><span className="brand">곁눈</span>이 살펴보고 있어요</h2>
      <p className="checking2-sub">{longWait ? LONG_WAIT_MESSAGE : '잠시만 기다려 주세요'}</p>

      <ul className="checking2-steps">
        {STEPS.map((label, i) => (
          <li key={label} className={i <= step ? 'done' : 'pending'}>
            <span className="checking2-step-badge" aria-hidden="true">
              <img src={checkIcon} width="15" height="11" alt="" />
            </span>
            <span className="checking2-step-text">{label}</span>
          </li>
        ))}
      </ul>

      <div className="checking2-progress">
        <div className="checking2-progress-fill" style={{ width: `${((step + 1) / STEPS.length) * 100}%` }} />
      </div>

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
