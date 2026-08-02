/**
 * S1 - 홈: 업로드 + 오늘의 연습
 * 담당: 조희진
 *
 * 시니어 UX 원칙
 *  - 첫 화면에 버튼은 3개 이하. 무엇을 눌러야 할지 고민할 여지를 없앤다.
 *  - '사진 올리기'가 가장 크고 맨 위에 있다. 실제 사용의 90%가 카톡 캡처다.
 *  - 안내 문구는 명령형이 아니라 초대형("~해 보세요")으로 쓴다.
 */
import { useEffect, useRef, useState } from 'react'
import { createCheck } from '../api.js'
import { logClick, logError } from '../events.js'
import { withCode } from '../errorCodes.js'

const SCREEN = 'S1'

// Web Share Target(sw.js)이 공유받은 이미지를 담아 두는 캐시 위치.
// manifest.json 의 share_target.action("/share")과 sw.js 가 같은 이름을 쓴다.
const SHARE_CACHE = 'gyeotnun-share-v1'
const SHARE_KEY = '/__shared-image'

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
        const code = data.error_code || 'SYS-000'
        setFailMessage(withCode(data.message || '처리하지 못했습니다. 글로 직접 입력해 주세요.', code))
        logError(SCREEN, code)
        return
      }
      onStarted(data)
    } catch (e) {
      // ★ e.message 는 api.js 의 handle()/safeFetch() 가 이미 "(오류 코드: XX-000)" 를
      //   덧붙여 준 상태다 - 화면에 별도로 코드를 또 붙이지 않는다.
      setError(e.message)
      logError(SCREEN, e.code || 'SYS-000')
    } finally {
      setBusy(false)
    }
  }

  // ★ 카카오톡 등에서 '공유 → 곁눈'으로 들어온 경우: sw.js 가 이미지를 캐시에 넣고
  //   '/?share=1' 로 리다이렉트해 온다. 여기서 꺼내 S1 업로드 흐름 그대로 이어붙인다.
  //   지원하지 않는 브라우저(caches 없음)나 캐시에 아무것도 없으면 안내만 하고
  //   넘어간다 - 이 경로가 실패해도 '사진 올리기' 버튼은 항상 그대로 동작해야 한다.
  //   ★ 2026-08 실측: 공유 목록에 곁눈이 뜨고 눌러서 열리기까지는 되는데(관문 통과)
  //   OS/브라우저 조합에 따라 실제 파일이 아예 첨부되지 않고 열리는 경우가 있었다
  //   (manifest.json 의 accept 에 확장자 누락이 원인 - 고쳤지만, 조용히 실패하면
  //   사용자는 원인을 알 길이 없으므로 실패 시 안내 문구 + 계측을 남긴다).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('share') !== '1') return
    window.history.replaceState({}, '', window.location.pathname)
    if (!('caches' in window)) return
    ;(async () => {
      try {
        const cache = await caches.open(SHARE_CACHE)
        const res = await cache.match(SHARE_KEY)
        if (!res) {
          logError(SCREEN, 'IN-003')
          setFailMessage(withCode('공유된 사진을 받지 못했습니다. 아래 "사진 올리기"로 다시 시도해 주세요.', 'IN-003'))
          return
        }
        const blob = await res.blob()
        await cache.delete(SHARE_KEY)
        const file = new File([blob], 'shared-image.jpg', { type: blob.type || 'image/jpeg' })
        start({ image: file })
      } catch (e) {
        logError(SCREEN, 'IN-003')
        setFailMessage(withCode('공유된 사진을 받지 못했습니다. 아래 "사진 올리기"로 다시 시도해 주세요.', 'IN-003'))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        <button className="btn" disabled={busy} onClick={() => { logClick(SCREEN, 'photo_upload'); fileRef.current?.click() }}>
          <span aria-hidden="true">📷</span> 사진 올리기
        </button>
      </div>

      <button className="btn secondary" disabled={busy} onClick={() => { logClick(SCREEN, 'paste_text_toggle'); setShowText((v) => !v) }}>
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
            onClick={() => { logClick(SCREEN, 'submit_text'); start({ text }) }}
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
            onClick={() => { logClick(SCREEN, 'retry_as_text'); setFailMessage(''); setShowText(true) }}
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
        <button className="btn secondary" onClick={() => { logClick(SCREEN, 'to_training'); onTraining() }}>
          오늘의 연습 하러 가기
        </button>
      </div>
    </>
  )
}
