/**
 * 곁눈(Gyeotnun) 화면 흐름 컨트롤러
 * 담당: 조희진
 *
 * S1 업로드 → S2 확인중 → S2.5 판단 → S3 확인(발견·탐색·확인) → S4 응답/기록 → S5 훈련
 *
 * 라우터 라이브러리를 쓰지 않는 이유
 *   시니어는 브라우저 뒤로가기로 흐름이 깨지면 크게 혼란스러워한다.
 *   화면 수가 적어 단순 state 전환이 오히려 안전하다.
 */
import { useEffect, useRef, useState } from 'react'
import { USE_MOCK, createCheck, CANCELLED_CODE } from './api.js'
import { downscaleImage } from './imageResize.js'
import { logScreenEnter, logScreenLeave, logError } from './events.js'
import { withCode } from './errorCodes.js'
import Home from './pages/Home.jsx'
import Checking from './pages/Checking.jsx'
import Judgment from './pages/Judgment.jsx'
import Question from './pages/Question.jsx'
import Decision from './pages/Decision.jsx'
import Training from './pages/Training.jsx'

// 내부 screen 상태 이름 → 계측용 화면 코드(S1~S5). 화면 흐름이 한 곳(App.jsx)에서만
// 바뀌므로, 진입/이탈 계측도 페이지마다 넣지 않고 여기 한 곳에만 넣는다.
// ★ judgment 는 S3(확인 흐름)의 첫 화면으로 묶는다 - 계측 스키마(_SCREENS)가
//   S1~S5 로 고정돼 있어 새 코드를 넣으려면 백엔드 계약부터 바꿔야 한다.
const SCREEN_CODE = { home: 'S1', checking: 'S2', judgment: 'S3', question: 'S3', decision: 'S4', training: 'S5' }

/**
 * ★ Figma 대조(2026-08): 확인 흐름 프레임(확인중·판단·발견·탐색·확인·응답·기록)
 *   에는 "곁눈 / 함께 확인해요" 공용 헤더가 없다. 화면 전체를 카드 하나로 쓰는
 *   구성이라 헤더가 붙으면 세로 여백이 밀려 Figma 와 눈에 띄게 어긋난다.
 *   좌우 여백도 18px → 22.5px(Figma Container px)로 맞춘다.
 */
const FLOW_SCREENS = new Set(['checking', 'judgment', 'question', 'decision'])

export default function App() {
  const [screen, setScreen] = useState('home')   // home | checking | judgment | question | decision | training
  const [checkId, setCheckId] = useState(null)
  const [checkData, setCheckData] = useState(null)
  const [evidence, setEvidence] = useState(null)
  // 업로드가 실패해 홈으로 되돌릴 때 들려 보내는 안내(홈이 새로 마운트되므로 prop 으로 넘긴다)
  const [notice, setNotice] = useState(null)
  /**
   * ★ 확인 화면의 '사진 다시 보기'용 - 사용자가 방금 고른 그 사진.
   *   서버로 다시 보내지 않고, 저장하지도 않는다. 이 탭의 메모리에만 있고
   *   홈으로 돌아가거나 새로고침하면 사라진다(objectURL 은 아래에서 회수).
   *   서버는 여전히 원본을 파기한다(masking.discard_original) - S2 에서
   *   사용자에게 고지한 약속은 서버 보관에 대한 것이고, 자기가 방금 고른
   *   사진을 자기 화면에서 다시 보는 것은 그 약속과 무관하다.
   */
  const [photoUrl, setPhotoUrl] = useState(null)
  /**
   * ★★ 확인 요청을 App 이 직접 보내는 이유 (2026-08 타임아웃 작업) ★★
   *   요청은 Home 에서 보내고 화면은 바로 '확인 중'으로 넘겼더니, 요청 주인인
   *   Home 이 이미 언마운트된 뒤라 타임아웃이 나도 '다시 시도'를 붙일 데가
   *   없었다. 요청 소유권을 흐름 컨트롤러인 여기로 올려서, 확인 중 화면이
   *   취소·재시도를 그대로 조작할 수 있게 한다.
   */
  const [submitError, setSubmitError] = useState(null)
  const abortRef = useRef(null)
  const payloadRef = useRef(null)

  useEffect(() => {
    const code = SCREEN_CODE[screen]
    logScreenEnter(code)
    return () => logScreenLeave(code)
  }, [screen])

  /**
   * ★ 2026-08-15: 화면이 바뀌면 맨 위로 올린다.
   *   S3(질문)은 스크롤이 길다. 거기서 아래까지 내려간 채 S4(응답)로 넘어가면
   *   새 화면이 중간부터 보인다 - 제목을 못 보고 선택지부터 마주치게 된다.
   *   behavior 를 'auto' 로 둔 것은 의도적이다. 화면이 바뀌는 순간에 부드럽게
   *   흘러내리면 '뭐가 움직이는지' 알기 어렵다.
   *   (feat/web-ui-update 는 이걸 Decision 안에만 넣었는데, 같은 문제가
   *    모든 전환에 있으므로 흐름을 쥔 여기에 한 번만 둔다.)
   */
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'auto' }) }, [screen])

  // 탭을 닫거나 컴포넌트가 사라질 때 마지막 objectURL 을 반드시 회수한다.
  useEffect(() => () => { if (photoUrl) URL.revokeObjectURL(photoUrl) }, [photoUrl])

  const replacePhoto = (file) => {
    setPhotoUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return file ? URL.createObjectURL(file) : null
    })
  }

  const goHome = () => {
    abortRef.current?.abort()      // 진행 중인 요청이 있으면 확실히 끊는다
    abortRef.current = null
    setSubmitError(null)
    setScreen('home')
    setCheckId(null)
    setCheckData(null)
    setEvidence(null)
    setNotice(null)
    replacePhoto(null)
  }

  /** 확인 1건을 보낸다. 화면은 요청 전에 먼저 넘어간다(대기 구간을 로딩이 덮도록). */
  async function runCheck(payload) {
    payloadRef.current = payload
    setNotice(null)
    setSubmitError(null)
    setCheckId(null)
    setCheckData(null)
    setEvidence(null)
    // 사용자가 방금 고른 원본 사진을 이 탭 메모리에만 붙들어 둔다
    // ('사진 다시 보기'용). 서버로 다시 보내지 않는다.
    replacePhoto(payload?.image || null)
    setScreen('checking')

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    try {
      // 사진은 올리기 전에 긴 변 1280px 로 줄인다. 인식률에는 영향이 없고
      // (Vision 은 이미지 크기에 거의 무관하다) 업로드 시간만 줄어든다.
      const body = payload.image
        ? { ...payload, image: await downscaleImage(payload.image) }
        : payload
      if (controller.signal.aborted) return
      const data = await createCheck(body, { signal: controller.signal })
      if (controller.signal.aborted) return
      if (data.status === 'failed') {
        // 네트워크 오류가 아니라 서버가 "처리는 됐지만 못 읽었다"고 알려 준
        // 정상 응답이다(10MB 초과, 인식 실패 등) - 홈으로 돌려보내 안내한다.
        const code = data.error_code || 'SYS-000'
        logError('S1', code)
        setNotice({ kind: 'fail', message: withCode(data.message || '처리하지 못했습니다. 글로 직접 입력해 주세요.', code) })
        setScreen('home')
        return
      }
      setCheckData(data)
      setCheckId(data.check_id)
    } catch (e) {
      if (e.code === CANCELLED_CODE) return    // 사용자가 그만뒀다 - goHome 이 처리했다
      logError('S1', e.code || 'SYS-000')
      // ★ 홈으로 튕겨내지 않는다. 확인 중 화면에 그대로 두고 '다시 시도'를 준다 -
      //   사진을 다시 고르게 만드는 건 어르신에게 큰 부담이다.
      setSubmitError({ message: e.message, code: e.code })
    }
  }

  const isFlow = FLOW_SCREENS.has(screen)

  return (
    <div className={`app${isFlow ? ' flow' : ''}`}>
      {/* ★ S1은 자체 헤더(HomeHeader)를 가져 이 공용 헤더와 겹치므로 숨긴다.
          확인 흐름(FLOW_SCREENS)도 Figma 원본에 헤더가 없어 숨긴다. 남는 건 S5. */}
      {screen !== 'home' && !isFlow && (
        <header className="header">
          <h1>곁눈</h1>
          <span className="tagline">함께 확인해요</span>
        </header>
      )}

      {/* 개발/시연 중 어떤 모드인지 항상 보이게 한다 (팀 내부용 표시) */}
      {USE_MOCK && <div className="mock-flag">데모 모드 (mock=1) — 고정 응답으로 동작 중</div>}

      {screen === 'home' && (
        <Home
          notice={notice}
          /* 요청은 App 이 보낸다(runCheck). 화면은 요청 전에 '확인 중'으로 넘어가
             업로드+OCR 대기(실측 4~15초)를 로딩 표시가 덮는다. */
          onSubmit={runCheck}
          onTraining={() => setScreen('training')}
        />
      )}

      {screen === 'checking' && (
        <Checking
          checkId={checkId}
          checkData={checkData}
          submitError={submitError}
          onRetrySubmit={() => runCheck(payloadRef.current)}
          onCancel={goHome}
          onReady={(ev) => {
            setEvidence(ev)
            setScreen('judgment')
          }}
          onError={goHome}
        />
      )}

      {screen === 'judgment' && (
        <Judgment
          evidence={evidence}
          checkData={checkData}
          onStart={() => setScreen('question')}
        />
      )}

      {screen === 'question' && (
        <Question
          checkId={checkId}
          checkData={checkData}
          evidence={evidence}
          photoUrl={photoUrl}
          onDone={() => setScreen('decision')}
          onCancel={goHome}
        />
      )}

      {screen === 'decision' && (
        <Decision
          checkId={checkId}
          onTraining={() => setScreen('training')}
          onHome={goHome}
        />
      )}

      {screen === 'training' && <Training onHome={goHome} />}
    </div>
  )
}
