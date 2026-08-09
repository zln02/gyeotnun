/**
 * 곁눈(Gyeotnun) 화면 흐름 컨트롤러
 * 담당: 조희진
 *
 * S1 업로드 → S2 확인중 → S3 질문(핵심) → S4 판단기록 → S5 훈련/리포트
 *
 * 라우터 라이브러리를 쓰지 않는 이유
 *   시니어는 브라우저 뒤로가기로 흐름이 깨지면 크게 혼란스러워한다.
 *   화면 수가 5개뿐이라 단순 state 전환이 오히려 안전하다.
 */
import { useEffect, useState } from 'react'
import { USE_MOCK } from './api.js'
import { logScreenEnter, logScreenLeave } from './events.js'
import Home from './pages/Home.jsx'
import Checking from './pages/Checking.jsx'
import Question from './pages/Question.jsx'
import Decision from './pages/Decision.jsx'
import Training from './pages/Training.jsx'

// 내부 screen 상태 이름 → 계측용 화면 코드(S1~S5). 화면 흐름이 한 곳(App.jsx)에서만
// 바뀌므로, 진입/이탈 계측도 페이지마다 넣지 않고 여기 한 곳에만 넣는다.
const SCREEN_CODE = { home: 'S1', checking: 'S2', question: 'S3', decision: 'S4', training: 'S5' }

export default function App() {
  const [screen, setScreen] = useState('home')   // home | checking | question | decision | training
  const [checkId, setCheckId] = useState(null)
  const [checkData, setCheckData] = useState(null)
  const [evidence, setEvidence] = useState(null)
  const isCheckFlow = screen === 'question' || screen === 'decision'

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
  }

  return (
    <div className={`app${screen === 'home' ? ' app--home' : ''}${screen === 'training' ? ' app--training' : ''}${isCheckFlow ? ' app--check-flow' : ''}`}>
      {/* ★ 2026-08 홈 화면 Figma 이식(2차): S1은 자체 헤더(HomeHeader, 알림 버튼
          포함)를 갖게 돼 이 공용 헤더와 겹친다 - S1에서만 숨긴다. S2~S5는 그대로. */}
      {screen !== 'home' && screen !== 'training' && !isCheckFlow && (
        <header className="header">
          <h1>곁눈</h1>
          <span className="tagline">함께 확인해요</span>
        </header>
      )}

      {/* 개발/시연 중 어떤 모드인지 항상 보이게 한다 (팀 내부용 표시) */}
      {USE_MOCK && <div className="mock-flag">데모 모드 (mock=1) — 고정 응답으로 동작 중</div>}

      {screen === 'home' && (
        <Home
          onStarted={(data) => {
            setCheckData(data)
            setCheckId(data.check_id)
            setScreen('checking')
          }}
          onTraining={() => setScreen('training')}
        />
      )}

      {screen === 'checking' && (
        <Checking
          checkId={checkId}
          checkData={checkData}
          onReady={(ev) => {
            setEvidence(ev)
            setScreen('question')
          }}
          onError={goHome}
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
