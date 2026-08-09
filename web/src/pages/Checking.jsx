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
 *   형태로 바꿨다(node 95:901 참고). 문구 자체(STEPS)는 기존 그대로 두고
 *   보여주는 방식만 Figma 패턴을 따랐다.
 *
 * ★★ 2026-08 타임아웃 ★★
 *   이 화면은 두 요청을 덮는다 - 확인 생성(POST /checks, App 이 소유)과
 *   근거 수집(GET /evidence, 여기서 소유). 둘 중 어느 쪽이 늦어도 사용자
 *   입장에선 "안 끝나는 화면"이라, 실패 안내와 다시 시도를 한 곳에서 처리한다.
 *   기다리는 중에도 언제든 그만둘 수 있어야 한다 - 갇힌 느낌이 이탈을 만든다.
 */
import { useEffect, useRef, useState } from 'react'
import { getEvidence, TIMEOUT_CODE, CANCELLED_CODE } from '../api.js'
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

// ★★ 2026-08 실측으로 걷어낸 것 ★★
//   전에는 evidence 응답을 받은 뒤 **무조건 2000ms 를 더 기다렸다**. "너무 빨리
//   넘어가면 제대로 본 게 맞나 불안해한다"는 이유였는데, 이제 이 화면은 업로드가
//   시작되기 전부터 떠 있다(App.runCheck 가 요청 전에 넘긴다). 사진 경로는 이미
//   수 초간 이 화면에 머물기 때문에 덧붙일 이유가 사라졌다.
//   대신 '붙여넣은 글' 경로처럼 정말 순식간(evidence 실측 약 170ms)에 끝나는
//   경우에만 최소 노출 시간을 둔다. 기준점도 응답 시각이 아니라 **화면 진입 시각**이다.
const MIN_VISIBLE_MS = 900

export default function Checking({ checkId, checkData, submitError, onRetrySubmit, onCancel, onReady, onError }) {
  const [step, setStep] = useState(0)
  const [evidenceError, setEvidenceError] = useState(null)
  const [longWait, setLongWait] = useState(false)
  const [attempt, setAttempt] = useState(0)      // '다시 시도' 를 누를 때마다 올린다
  const enteredAtRef = useRef(Date.now())
  const abortRef = useRef(null)

  // 확인 생성(App) 이든 근거 수집(여기) 이든, 사용자에겐 같은 실패다.
  const failure = submitError || evidenceError

  // 단계 표시는 checkId 가 아직 없어도(= 업로드·OCR 중) 곧바로 돈다.
  // 이 구간이 실제로 가장 길기 때문에 여기서부터 덮어야 의미가 있다.
  useEffect(() => {
    if (failure) return            // 실패 화면에서는 진행 표시를 멈춘다
    enteredAtRef.current = Date.now()
    setStep(0)
    setLongWait(false)
    // 마지막 단계에 닿으면 멈춘다 - 끝까지 다 확인했다는 느낌을 주고 계속
    // 순환하며 불안하게 만들지 않는다(실제 완료는 아래 getEvidence 가 결정).
    const t = setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), STEP_INTERVAL_MS)
    const longWaitTimer = setTimeout(() => setLongWait(true), LONG_WAIT_MS)
    return () => { clearInterval(t); clearTimeout(longWaitTimer) }
  }, [attempt, failure])

  useEffect(() => {
    // 업로드가 끝나야 check_id 가 생긴다. 그전에는 기다리기만 한다.
    if (!checkId || submitError) return
    let cancelled = false
    let timer
    const controller = new AbortController()
    abortRef.current = controller
    ;(async () => {
      try {
        const ev = await getEvidence(checkId, { signal: controller.signal })
        if (cancelled) return
        const remaining = Math.max(0, MIN_VISIBLE_MS - (Date.now() - enteredAtRef.current))
        timer = setTimeout(() => { if (!cancelled) onReady(ev) }, remaining)
      } catch (e) {
        if (cancelled || e.code === CANCELLED_CODE) return
        setEvidenceError({ message: e.message, code: e.code })
        logError(SCREEN, e.code || 'evidence_fetch_failed')
      }
    })()
    return () => { cancelled = true; clearTimeout(timer); controller.abort() }
  }, [checkId, submitError, attempt])

  function retry() {
    logClick(SCREEN, 'retry_after_timeout')
    if (submitError) {
      onRetrySubmit()              // 확인 생성부터 다시 (사진을 다시 고를 필요 없다)
    } else {
      setEvidenceError(null)
      setAttempt((a) => a + 1)
    }
  }

  function cancel() {
    logClick(SCREEN, 'cancel_waiting')
    abortRef.current?.abort()
    onCancel()
  }

  /* -------------------------------------------------- 실패(대부분 시간 초과) */
  if (failure) {
    const timedOut = failure.code === TIMEOUT_CODE
    return (
      <div className="checking-fail" role="alert">
        <img src={mascotImg} width="72" height="72" alt="" aria-hidden="true" className="checking-fail-icon" />
        <h2 className="checking-fail-title">
          {timedOut ? '시간이 오래 걸리고 있어요.\n다시 해보시겠어요?' : '확인하지 못했어요'}
        </h2>
        {!timedOut && <p className="checking-fail-msg">{failure.message}</p>}
        {timedOut && <p className="checking-fail-code">({failure.code})</p>}

        <button type="button" className="verify-cta" onClick={retry}>다시 시도하기</button>
        <button type="button" className="checking-fail-quit" onClick={() => { logClick(SCREEN, 'quit_after_fail'); onError() }}>
          그만두고 처음으로
        </button>
      </div>
    )
  }

  /* -------------------------------------------------------------- 확인 중 */
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

      {/* ★ 기다리는 중에도 언제든 그만둘 수 있어야 한다. 빠져나갈 길이 없는
          화면은 그 자체로 불안을 만든다(어르신은 '닫기'를 못 찾으면 앱을 끈다). */}
      <button type="button" className="checking2-cancel" onClick={cancel}>그만두기</button>
    </div>
  )
}
