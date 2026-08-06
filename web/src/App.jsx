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
import { useEffect, useState } from 'react'
import { USE_MOCK } from './api.js'
import { logScreenEnter, logScreenLeave } from './events.js'
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

export default function App() {
  const [screen, setScreen] = useState('home')   // home | checking | judgment | question | decision | training
  const [checkId, setCheckId] = useState(null)
  const [checkData, setCheckData] = useState(null)
  const [evidence, setEvidence] = useState(null)
  // 업로드가 실패해 홈으로 되돌릴 때 들려 보내는 안내(홈이 새로 마운트되므로 prop 으로 넘긴다)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    const code = SCREEN_CODE[screen]
    logScreenEnter(code)
    return () => logScreenLeave(code)
  }, [screen])

  const goHome = () => {
    setScreen('home')
    setCheckId(null)
    setCheckData(null)
    setEvidence(null)
    setNotice(null)
  }

  return (
    <div className="app">
      {/* ★ 2026-08 홈 화면 Figma 이식(2차): S1은 자체 헤더(HomeHeader, 알림 버튼
          포함)를 갖게 돼 이 공용 헤더와 겹친다 - S1에서만 숨긴다. S2~S5는 그대로. */}
      {screen !== 'home' && (
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
          /* ★ 업로드 요청을 보내기 **전에** 확인 중 화면으로 넘긴다. 사진 경로는
               업로드 + OCR 만으로 4~15초가 걸리는데, 예전엔 그 내내 홈 화면이
               그대로 떠 있어 아무 반응이 없는 것처럼 보였다. */
          onSubmitStart={() => {
            setNotice(null)
            setCheckId(null)
            setCheckData(null)
            setEvidence(null)
            setScreen('checking')
          }}
          onStarted={(data) => {
            setCheckData(data)
            setCheckId(data.check_id)
          }}
          onFailed={(n) => { setNotice(n); setScreen('home') }}
          onTraining={() => setScreen('training')}
        />
      )}

      {screen === 'checking' && (
        <Checking
          checkId={checkId}
          checkData={checkData}
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
          onStart={() => setScreen('question')}
        />
      )}

      {screen === 'question' && (
        <Question
          checkId={checkId}
          checkData={checkData}
          evidence={evidence}
          onDone={() => setScreen('decision')}
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
