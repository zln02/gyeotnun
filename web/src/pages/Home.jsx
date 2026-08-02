/**
 * S1 - 홈: 업로드 + 오늘의 연습
 * 담당: 조희진
 *
 * 시니어 UX 원칙
 *  - 첫 화면에 버튼은 3개 이하. 무엇을 눌러야 할지 고민할 여지를 없앤다.
 *  - '사진으로 확인하기'가 가장 크고 맨 위에 있다. 실제 사용의 90%가 카톡 캡처다.
 *  - 안내 문구는 명령형이 아니라 초대형("~해 보세요")으로 쓴다.
 *
 * ★ 2026-08 Figma 이식: 사진/문자 입력을 "안내 → 선택/입력 → 미리 보고 확인" 3단계
 *   모달로 바꿨다(곁눈(figma)/src/app/screens/home.tsx 의 CaptureGuide/StepGuide/
 *   ModalShell 을 plain CSS 로 옮김, styles.css 의 "S1 홈 - Figma 이식" 절 참고).
 *   API 호출(createCheck)·상태 흐름(start)·계측(logClick/logError)·공유 수신
 *   (share=1) 로직은 이식 전과 동일하다 - 바뀐 건 입력을 받는 화면 구조뿐이다.
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

function StepGuide({ steps }) {
  return (
    <ol className="step-guide" aria-label="이용 순서 안내">
      {steps.map((step, i) => (
        <li key={step}>
          <span className="step-badge" aria-hidden="true">{i + 1}</span>
          <p className="step-text">{step}</p>
        </li>
      ))}
    </ol>
  )
}

function CaptureGuide() {
  return (
    <figure className="capture-guide" aria-label="화면 사진 찍는 방법">
      <div className="img-wrap">
        <picture>
          <source srcSet="/capture-guide.webp" type="image/webp" />
          <img
            src="/capture-guide.png"
            width="290"
            height="142"
            alt="음량 낮추기 버튼과 측면 버튼 위치를 표시한 휴대폰 그림"
            decoding="async"
          />
        </picture>
      </div>
      <figcaption>오른쪽의 두 버튼을 함께 눌러요.</figcaption>
    </figure>
  )
}

/** 모달 공용 뼈대 - 배경을 눌러도, X 버튼을 눌러도 onClose 가 불린다. */
function ModalShell({ label, eyebrow, title, onClose, children, footer }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="modal-shell"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div style={{ minWidth: 0 }}>
            <p className="modal-eyebrow">{eyebrow}</p>
            <h2 className="modal-title">{title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="닫기" className="modal-close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        <div className="modal-footer">{footer}</div>
      </section>
    </div>
  )
}

export default function Home({ onStarted, onTraining }) {
  const fileRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  // status:"failed" 는 네트워크 오류가 아니라 서버가 "처리는 됐지만 못 읽었다"고
  // 알려 준 정상 응답이다(10MB 초과, 사진 인식 실패 등). catch 가 아니라 여기서 구분한다.
  const [failMessage, setFailMessage] = useState('')

  // ---- 사진 모달 상태 ----
  const [photoOpen, setPhotoOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [previewFile, setPreviewFile] = useState(null)

  // ---- 문자 모달 상태 ----
  const [textOpen, setTextOpen] = useState(false)
  const [textDraft, setTextDraft] = useState('')
  const [textConfirmed, setTextConfirmed] = useState(null)

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
  //   넘어간다 - 이 경로가 실패해도 '사진으로 확인하기' 버튼은 항상 그대로 동작해야 한다.
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
          setFailMessage(withCode('공유된 사진을 받지 못했습니다. 아래 "사진으로 확인하기"로 다시 시도해 주세요.', 'IN-003'))
          return
        }
        const blob = await res.blob()
        await cache.delete(SHARE_KEY)
        const file = new File([blob], 'shared-image.jpg', { type: blob.type || 'image/jpeg' })
        start({ image: file })
      } catch (e) {
        logError(SCREEN, 'IN-003')
        setFailMessage(withCode('공유된 사진을 받지 못했습니다. 아래 "사진으로 확인하기"로 다시 시도해 주세요.', 'IN-003'))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 모달을 벗어날 때(닫기/성공 제출) 미리보기 objectURL 을 반드시 정리한다.
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  function resetPhotoPreview() {
    setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return null })
    setPreviewFile(null)
    if (fileRef.current) fileRef.current.value = ''
  }
  function openPhotoModal() { logClick(SCREEN, 'photo_upload'); setPhotoOpen(true) }
  function closePhotoModal() { logClick(SCREEN, 'photo_modal_close'); setPhotoOpen(false); resetPhotoPreview() }
  function pickPhoto() { fileRef.current?.click() }
  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setPreviewUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(file) })
    setPreviewFile(file)
  }
  function retryPhoto() { logClick(SCREEN, 'photo_retry'); resetPhotoPreview() }
  function confirmPhoto() {
    logClick(SCREEN, 'photo_confirm')
    const file = previewFile
    setPhotoOpen(false)
    resetPhotoPreview()
    start({ image: file })
  }

  function openTextModal() { logClick(SCREEN, 'paste_text_toggle'); setTextDraft(''); setTextConfirmed(null); setTextOpen(true) }
  function closeTextModal() { logClick(SCREEN, 'text_modal_close'); setTextOpen(false); setTextDraft(''); setTextConfirmed(null) }
  function reviewText() { logClick(SCREEN, 'text_review'); setTextConfirmed(textDraft.trim()) }
  function retryText() { logClick(SCREEN, 'text_retry'); setTextDraft(''); setTextConfirmed(null) }
  function confirmText() {
    logClick(SCREEN, 'submit_text')
    const value = textConfirmed
    setTextOpen(false)
    setTextDraft('')
    setTextConfirmed(null)
    start({ text: value })
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
        {/* ★ 아이콘만 있는 버튼 금지 — 그림과 글자를 항상 함께 */}
        <button className="btn" disabled={busy} onClick={openPhotoModal}>
          <span aria-hidden="true">📷</span> 사진으로 확인하기
        </button>
      </div>

      <button className="btn secondary" disabled={busy} onClick={openTextModal}>
        <span aria-hidden="true">⌨️</span> 글로 확인하기
      </button>

      {failMessage && (
        <div className="error-box">
          <p>{failMessage}</p>
          {/* ★ 10MB 초과 · 인식 실패 공통 안내: 문자 직접 입력 경로로 바로 넘겨준다 */}
          <button
            className="btn secondary"
            style={{ marginTop: 12 }}
            onClick={() => { logClick(SCREEN, 'retry_as_text'); setFailMessage(''); openTextModal() }}
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

      {photoOpen && (
        <ModalShell
          label="사진으로 내용 확인하기"
          eyebrow={previewUrl ? '사진 살펴보기' : '사진으로 살펴보기'}
          title={previewUrl ? '이 사진으로 이어갈까요?' : '화면 사진을 찍어주세요'}
          onClose={closePhotoModal}
          footer={previewUrl ? (
            <div className="modal-actions-2">
              <button type="button" className="action-secondary" onClick={retryPhoto}>
                <span aria-hidden="true">↺</span> 다시 고르기
              </button>
              <button type="button" className="action-primary" onClick={confirmPhoto}>
                <span aria-hidden="true">✓</span> 네, 맞아요
              </button>
            </div>
          ) : (
            <button type="button" className="action-primary" onClick={pickPhoto}>
              <span aria-hidden="true">🖼️</span> 사진 선택하기
            </button>
          )}
        >
          {!previewUrl ? (
            <>
              <CaptureGuide />
              <StepGuide steps={[
                '"찰칵" 소리가 나면 화면 사진이 저장돼요.',
                '아래 사진 선택하기 버튼을 눌러 방금 찍은 사진을 골라요.',
              ]} />
            </>
          ) : (
            <>
              <div className="photo-preview">
                <img src={previewUrl} alt="선택한 화면 사진 미리보기" />
              </div>
              <StepGuide steps={['카카오톡 화면 사진이 맞나요?', '살펴볼 내용이 맞나요?']} />
            </>
          )}
        </ModalShell>
      )}

      {textOpen && (
        <ModalShell
          label="문자로 내용 확인하기"
          eyebrow="문자로 살펴보기"
          title={textConfirmed !== null ? '이 내용으로 이어갈까요?' : '받은 문자를 붙여넣어 주세요'}
          onClose={closeTextModal}
          footer={textConfirmed !== null ? (
            <div className="modal-actions-2">
              <button type="button" className="action-secondary" onClick={retryText}>
                <span aria-hidden="true">↺</span> 다시 입력
              </button>
              <button type="button" className="action-primary" onClick={confirmText}>
                <span aria-hidden="true">→</span> 이 내용으로
              </button>
            </div>
          ) : (
            <button type="button" className="action-primary" disabled={!textDraft.trim()} onClick={reviewText}>
              <span aria-hidden="true">✓</span> 입력한 내용 보기
            </button>
          )}
        >
          {textConfirmed === null ? (
            <>
              <div className="input-hint">
                <span aria-hidden="true">💬</span>
                <p style={{ margin: 0 }}>받은 문자 내용을 그대로 옮겨주세요.</p>
              </div>
              <StepGuide steps={[
                '받은 문자를 길게 눌러 전체 내용을 복사해요.',
                '아래 빈칸을 누르고 붙여넣어 주세요.',
                '입력한 내용 보기 버튼을 눌러주세요.',
              ]} />
              <label style={{ display: 'block', marginTop: 18 }}>
                <span style={{ display: 'block', marginBottom: 8, fontSize: 19, fontWeight: 800, color: 'var(--fg-ink-title)' }}>받은 문자</span>
                <textarea
                  className="textarea"
                  value={textDraft}
                  onChange={(e) => setTextDraft(e.target.value)}
                  placeholder="받은 문자 내용을 여기에 붙여넣으세요."
                />
              </label>
            </>
          ) : (
            <>
              <div className="confirm-box">{textConfirmed}</div>
              <StepGuide steps={['위에 적힌 내용을 천천히 읽어보세요.', '처음 받은 문자와 같은지 살펴보세요.']} />
            </>
          )}
        </ModalShell>
      )}

      <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFileChange} />
    </>
  )
}
