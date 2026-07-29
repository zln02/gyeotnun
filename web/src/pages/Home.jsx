/**
 * S1 - 홈: 업로드 + 오늘의 연습
 * 담당: 조희진
 *
 * 시니어 UX 원칙
 *  - 첫 화면에 버튼은 3개 이하. 무엇을 눌러야 할지 고민할 여지를 없앤다.
 *  - '사진 올리기'가 가장 크고 맨 위에 있다. 실제 사용의 90%가 카톡 캡처다.
 *  - 안내 문구는 명령형이 아니라 초대형("~해 보세요")으로 쓴다.
 */
import { useRef, useState } from 'react'
import { createCheck } from '../api.js'

export default function Home({ onStarted, onTraining }) {
  const fileRef = useRef(null)
  const [text, setText] = useState('')
  const [showText, setShowText] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // status:"failed" 는 네트워크 오류가 아니라 서버가 "처리는 됐지만 못 읽었다"고
  // 알려 준 정상 응답이다(10MB 초과, 사진 인식 실패 등). catch 가 아니라 여기서 구분한다.
  const [failMessage, setFailMessage] = useState('')

  async function start(payload) {
    setBusy(true)
    setError('')
    setFailMessage('')
    try {
      const data = await createCheck(payload)
      if (data.status === 'failed') {
        setFailMessage(data.message || '처리하지 못했습니다. 글로 직접 입력해 주세요.')
        return
      }
      onStarted(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h2>받으신 내용,<br />같이 살펴볼까요?</h2>
      <p className="sub">
        진짜인지 가짜인지 대신 정해 드리지 않습니다.
        어디를 확인하면 되는지 하나씩 여쭤볼게요.
      </p>

      <div className="upload-box">
        <p className="lead" style={{ marginBottom: 16 }}>
          카카오톡에서 받은 사진을<br />그대로 올려 주세요
        </p>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files?.[0] && start({ image: e.target.files[0] })}
        />
        {/* ★ 아이콘만 있는 버튼 금지 — 그림과 글자를 항상 함께 */}
        <button className="btn" disabled={busy} onClick={() => fileRef.current?.click()}>
          <span aria-hidden="true">📷</span> 사진 올리기
        </button>
      </div>

      <button className="btn secondary" disabled={busy} onClick={() => setShowText((v) => !v)}>
        <span aria-hidden="true">⌨️</span> 글로 붙여넣기
      </button>

      {showText && (
        <div className="card">
          <label htmlFor="pasted" className="lead" style={{ display: 'block', marginBottom: 10 }}>
            받으신 글을 붙여넣어 주세요
          </label>
          <textarea
            id="pasted"
            className="textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="예) 65세 이상 어르신 전원 매달 40만원 지급..."
          />
          <button
            className="btn"
            style={{ marginTop: 14 }}
            disabled={busy || !text.trim()}
            onClick={() => start({ text })}
          >
            확인 시작하기
          </button>
        </div>
      )}

      {failMessage && (
        <div className="error-box">
          <p>{failMessage}</p>
          {/* ★ 10MB 초과 · 인식 실패 공통 안내: 텍스트 직접 입력 경로로 바로 넘겨준다 */}
          <button
            className="btn secondary"
            style={{ marginTop: 12 }}
            onClick={() => { setFailMessage(''); setShowText(true) }}
          >
            <span aria-hidden="true">⌨️</span> 글로 입력하기
          </button>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}

      <div className="card" style={{ marginTop: 24 }}>
        <span className="badge">오늘의 연습</span>
        <h3 style={{ marginTop: 12 }}>5분이면 끝나요</h3>
        <p className="sub">
          어제 확인하신 내용과 비슷한 문제를 하나 준비했습니다.
        </p>
        <button className="btn secondary" onClick={onTraining}>
          오늘의 연습 하러 가기
        </button>
      </div>
    </>
  )
}
