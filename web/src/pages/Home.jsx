/**
 * S1 - 홈: 확인 시작 + 오늘의 훈련
 * 담당: 조희진
 *
 * 시니어 UX 원칙
 *  - 첫 화면에 버튼은 3개 이하. 무엇을 눌러야 할지 고민할 여지를 없앤다.
 *  - '사진 확인'이 가장 크고 맨 위에 있다. 실제 사용의 90%가 카톡 캡처다.
 *  - 안내 문구는 명령형이 아니라 초대형("~해 보세요")으로 쓴다.
 *
 * ★ 2026-08 Figma 이식(1차): 사진/문자 입력을 "안내 → 선택/입력 → 미리 보고 확인"
 *   3단계 모달로 바꿨다(곁눈(figma)/src/app/screens/home.tsx 의 CaptureGuide/
 *   StepGuide/ModalShell 을 plain CSS 로 옮김, styles.css 의 "S1 홈 - Figma 이식"
 *   절 참고). API 호출(createCheck)·상태 흐름(start)·계측(logClick/logError)·
 *   공유 수신(share=1) 로직은 이식 전과 동일하다.
 *
 * ★ 2026-08 Figma 이식(2차): 위 모달 로직은 그대로 두고, 화면 상단(헤더·히어로
 *   카드·확인 카드 3개·SNS 안내·포인트 배너)과 하단 고정 네비게이션을 새 Figma
 *   화면 그대로 새로 짰다(styles.css "S1 홈 - 신규 레이아웃" 절 참고). 393x852
 *   고정 좌표는 가져오지 않고 Flex 로 재구성했다 - 다른 폰 크기에서도 깨지지
 *   않아야 하기 때문. "링크 확인" 카드는 기존에 UI가 없던 createCheck({link})
 *   경로를 문자 모달과 같은 패턴으로 새로 노출한 것이다(백엔드는 이미 지원).
 *
 * ★ 2026-08 이름 개인화: 헤더의 "OO 님의 곁눈"을 실제로 채우기 위해, 기기에만
 *   저장되는(회원가입 없음) 이름 입력을 추가했다(api.js 의 getDisplayName/
 *   setDisplayName). deviceId() 는 원래 "이름을 받지 않기 위한" 무작위 값이라는
 *   원칙을 그대로 두고, 이름은 완전히 별개의 선택 항목으로 로컬에만 둔다.
 *   서버에는 보내지 않는다. 처음 방문했고 아직 이름/건너뛰기 기록이 없을 때만
 *   한 번 물어보고, 이후엔 헤더 제목을 눌러 언제든 다시 바꿀 수 있게 했다.
 */
import { useEffect, useRef, useState } from 'react'
import { getDisplayName, setDisplayName } from '../api.js'
import { logClick, logError } from '../events.js'
import { withCode } from '../errorCodes.js'
import BottomNav from '../components/BottomNav.jsx'

import envelopeImg from '../assets/home/envelope.png'
import icPhoto from '../assets/home/ic_photo.png'
import icLink from '../assets/home/ic_link.png'
import icSms from '../assets/home/ic_sms.png'
import icPencil from '../assets/home/ic_pencil.svg'
import icBell from '../assets/home/ic_bell.svg'
import icChevron from '../assets/home/ic_chevron.svg'

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

function HomeHeader({ displayName, onEditName, onBell }) {
  return (
    <div className="home-header">
      <div>
        <p className="home-eyebrow">오늘도 스스로 확인하는 시간</p>
        <button
          type="button"
          className="home-title-btn"
          onClick={onEditName}
          aria-label={displayName ? '이름 바꾸기' : '이름 입력하기'}
        >
          <h1 className="home-title">{displayName ? `${displayName} 님의 곁눈` : '나의 곁눈'}</h1>
          <img src={icPencil} width="14" height="14" alt="" aria-hidden="true" className="home-title-edit" />
        </button>
      </div>
      <button type="button" className="home-bell" aria-label="알림" onClick={onBell}>
        <img src={icBell} width="20" height="20" alt="" aria-hidden="true" />
      </button>
    </div>
  )
}

function HeroCard({ onLearn }) {
  return (
    <div className="hero-wrap">
      <section className="hero-card">
        <img src={envelopeImg} className="hero-illust" width="87" height="87" alt="" aria-hidden="true" />
        <div className="hero-copy">
          <h2 className="hero-title">지원금 문자,<br />어디부터 볼까요?</h2>
          <p className="hero-sub">공식 출처와 조건을 함께 찾아봐요.</p>
        </div>
      </section>
      <button type="button" className="hero-cta" onClick={onLearn}>
        <img src={icPencil} width="18" height="18" alt="" aria-hidden="true" />
        <span>오늘의 훈련</span>
        {/* ★ 포인트 시스템 백엔드 없음 - G/120 은 고정값. TODO: 포인트 API 나오면 교체 */}
        <span className="hero-cta-badge">
          <b className="g">G</b><b className="pt">120</b>
        </span>
      </button>
    </div>
  )
}

function ConfirmCard({ icon, title, desc, onClick }) {
  return (
    <button type="button" className="confirm-card" onClick={onClick}>
      <img src={icon} className="confirm-card-icon" alt="" aria-hidden="true" />
      <span className="confirm-card-text">
        <b className="confirm-card-title">{title}</b>
        <span className="confirm-card-desc">{desc}</span>
      </span>
      <span className="confirm-card-arrow" aria-hidden="true">
        <img src={icChevron} width="10" height="10" alt="" />
      </span>
    </button>
  )
}

function ConfirmCluster({ onPhoto, onLink, onText }) {
  return (
    <section className="confirm-cluster" aria-label="확인 방법 고르기">
      <div className="confirm-cards">
        <ConfirmCard icon={icPhoto} title="사진 확인" desc="클릭하여 사진 선택하기" onClick={onPhoto} />
        <ConfirmCard icon={icLink} title="링크 확인" desc="클릭하여 주소 붙여넣기" onClick={onLink} />
        <ConfirmCard icon={icSms} title="문자 확인" desc="클릭하여 내용 입력하기" onClick={onText} />
      </div>
    </section>
  )
}

function PointBanner() {
  return (
    <section className="point-banner" aria-label="최근 포인트 적립 소식">
      {/* ★ 포인트 시스템 백엔드 없음 - 아래 내용 전체가 고정값이다.
          TODO: /points 류 API 가 생기면 실제 최근 적립 내역으로 교체한다. */}
      <span className="point-g-badge" aria-hidden="true">G</span>
      <p className="point-text">
        <b>방금 전</b> · 순자 님이 의심스러운 결제를 멈추고<br />
        280,000원을 지켜 <b className="pt">30 포인트</b>를 받았어요.
      </p>
    </section>
  )
}

export default function Home({ onSubmit, notice, onTraining }) {
  const fileRef = useRef(null)
  const [busy, setBusy] = useState(false)
  // ★ notice: 업로드가 실패해 '확인 중' 화면에서 홈으로 되돌아온 경우, App 이
  //   실패 안내를 들려 보낸다. 홈이 새로 마운트되므로 초기값으로 받아야 한다.
  const [error, setError] = useState(notice?.kind === 'error' ? notice.message : '')
  // status:"failed" 는 네트워크 오류가 아니라 서버가 "처리는 됐지만 못 읽었다"고
  // 알려 준 정상 응답이다(10MB 초과, 사진 인식 실패 등). catch 가 아니라 여기서 구분한다.
  const [failMessage, setFailMessage] = useState(notice?.kind === 'fail' ? notice.message : '')

  // ---- 사진 모달 상태 ----
  const [photoOpen, setPhotoOpen] = useState(false)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [previewFile, setPreviewFile] = useState(null)

  // ---- 문자 모달 상태 ----
  const [textOpen, setTextOpen] = useState(false)
  const [textDraft, setTextDraft] = useState('')
  const [textConfirmed, setTextConfirmed] = useState(null)

  // ---- 링크 모달 상태 (2026-08 Figma 이식 2차에서 신규 추가 - API는 기존 것) ----
  const [linkOpen, setLinkOpen] = useState(false)
  const [linkDraft, setLinkDraft] = useState('')
  const [linkConfirmed, setLinkConfirmed] = useState(null)

  // ---- 하단 네비 "준비 중" 안내 ----
  const [navToast, setNavToast] = useState('')
  const navToastTimer = useRef(null)
  useEffect(() => () => window.clearTimeout(navToastTimer.current), [])

  // ---- 이름 입력 (2026-08, 기기에만 저장 - 회원가입 아님) ----
  const [displayName, setDisplayNameValue] = useState(() => getDisplayName())
  const [nameOpen, setNameOpen] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  useEffect(() => {
    // 처음 방문(이름도 없고, "나중에" 누른 기록도 없을 때)에만 한 번 먼저 물어본다.
    if (!displayName && !localStorage.getItem('gyeotnun_name_skipped')) {
      setNameDraft('')
      setNameOpen(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * ★ 실제 요청은 App 이 보낸다(onSubmit).
   *   이 화면은 요청을 보내자마자 '확인 중' 화면으로 바뀌면서 언마운트되는데,
   *   요청 주인이 여기 있으면 타임아웃 뒤 '다시 시도'·'그만두기'를 붙일 데가
   *   없어진다(이미 사라진 컴포넌트라서). 그래서 요청 소유권만 App 으로 옮겼다.
   */
  function start(payload) {
    setBusy(true)
    setError('')
    setFailMessage('')
    onSubmit(payload)
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

  function openLinkModal() { logClick(SCREEN, 'link_upload_toggle'); setLinkDraft(''); setLinkConfirmed(null); setLinkOpen(true) }
  function closeLinkModal() { logClick(SCREEN, 'link_modal_close'); setLinkOpen(false); setLinkDraft(''); setLinkConfirmed(null) }
  function reviewLink() { logClick(SCREEN, 'link_review'); setLinkConfirmed(linkDraft.trim()) }
  function retryLink() { logClick(SCREEN, 'link_retry'); setLinkDraft(''); setLinkConfirmed(null) }
  function confirmLink() {
    logClick(SCREEN, 'submit_link')
    const value = linkConfirmed
    setLinkOpen(false)
    setLinkDraft('')
    setLinkConfirmed(null)
    start({ link: value })
  }

  function showNavToast(msg) {
    setNavToast(msg)
    window.clearTimeout(navToastTimer.current)
    navToastTimer.current = window.setTimeout(() => setNavToast(''), 2200)
  }
  function handleNavTap(key) {
    logClick(SCREEN, `nav_${key}`)
    if (key === 'home') { window.scrollTo({ top: 0, behavior: 'smooth' }); return }
    if (key === 'learn') { onTraining(); return }
    if (key === 'fab') { openPhotoModal(); return }
    // ★ 성장/내 정보: 아직 화면이 없다 - 새 화면을 만들지 말고 "준비 중" 안내만
    showNavToast('준비 중입니다')
  }
  function handleBell() {
    logClick(SCREEN, 'notification_bell')
    showNavToast('준비 중입니다')
  }

  function openNameModal() {
    logClick(SCREEN, displayName ? 'name_edit_open' : 'name_prompt_open')
    setNameDraft(displayName)
    setNameOpen(true)
  }
  function skipNameModal() {
    logClick(SCREEN, 'name_skip')
    localStorage.setItem('gyeotnun_name_skipped', '1')
    setNameOpen(false)
  }
  function confirmNameModal() {
    logClick(SCREEN, 'name_confirm')
    const saved = setDisplayName(nameDraft)
    setDisplayNameValue(saved)
    localStorage.removeItem('gyeotnun_name_skipped')
    setNameOpen(false)
  }

  return (
    <>
      <HomeHeader displayName={displayName} onEditName={openNameModal} onBell={handleBell} />

      {failMessage && (
        <div className="error-box">
          <p>{failMessage}</p>
          {/* ★ 10MB 초과 · 인식 실패 공통 안내: 문자 직접 입력 경로로 바로 넘겨준다 */}
          <button
            className="btn figma-outline"
            style={{ marginTop: 12 }}
            onClick={() => { logClick(SCREEN, 'retry_as_text'); setFailMessage(''); openTextModal() }}
          >
            <span aria-hidden="true">⌨️</span> 글로 입력하기
          </button>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}

      <HeroCard onLearn={() => { logClick(SCREEN, 'hero_to_training'); onTraining() }} />

      <ConfirmCluster
        onPhoto={busy ? undefined : openPhotoModal}
        onLink={busy ? undefined : openLinkModal}
        onText={busy ? undefined : openTextModal}
      />

      <PointBanner />

      {/* 하단 고정 네비 아래에 콘텐츠가 가리지 않도록 여백 확보 */}
      <div aria-hidden="true" style={{ height: 110 }} />
      {/* ★ 짧은 화면(360x800 등)에서는 포인트 배너 등이 하단 네비 뒤로 일부만
          비치며 글자가 잘려 보이는("깨진" 것처럼 보이는) 문제가 있었다 - 기기별
          여백을 딱 맞추는 대신, 네비 위에 배경색으로 자연스럽게 페이드되는 막을
          깔아 어떤 화면 크기에서도 텍스트가 어중간하게 잘려 보이지 않게 했다. */}
      <div className="bottom-scrim" aria-hidden="true" />
      <BottomNav active="home" onTap={handleNavTap} />
      <div className="nav-toast-wrap" aria-live="polite">
        {navToast && <div className="nav-toast">{navToast}</div>}
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

      {linkOpen && (
        <ModalShell
          label="링크로 내용 확인하기"
          eyebrow="링크로 살펴보기"
          title={linkConfirmed !== null ? '이 주소로 이어갈까요?' : '받은 주소를 붙여넣어 주세요'}
          onClose={closeLinkModal}
          footer={linkConfirmed !== null ? (
            <div className="modal-actions-2">
              <button type="button" className="action-secondary" onClick={retryLink}>
                <span aria-hidden="true">↺</span> 다시 입력
              </button>
              <button type="button" className="action-primary" onClick={confirmLink}>
                <span aria-hidden="true">→</span> 이 주소로
              </button>
            </div>
          ) : (
            <button type="button" className="action-primary" disabled={!linkDraft.trim()} onClick={reviewLink}>
              <span aria-hidden="true">✓</span> 입력한 주소 보기
            </button>
          )}
        >
          {linkConfirmed === null ? (
            <>
              <div className="input-hint">
                <span aria-hidden="true">🔗</span>
                <p style={{ margin: 0 }}>받은 문자나 게시글 속 주소를 그대로 옮겨주세요.</p>
              </div>
              <StepGuide steps={[
                '받은 주소를 길게 눌러 복사해요.',
                '아래 빈칸을 누르고 붙여넣어 주세요.',
                '입력한 주소 보기 버튼을 눌러주세요.',
              ]} />
              <label style={{ display: 'block', marginTop: 18 }}>
                <span style={{ display: 'block', marginBottom: 8, fontSize: 19, fontWeight: 800, color: 'var(--fg-ink-title)' }}>받은 주소</span>
                <textarea
                  className="textarea"
                  style={{ minHeight: 80 }}
                  value={linkDraft}
                  onChange={(e) => setLinkDraft(e.target.value)}
                  placeholder="https:// 로 시작하는 주소를 여기에 붙여넣으세요."
                  inputMode="url"
                />
              </label>
            </>
          ) : (
            <>
              <div className="confirm-box">{linkConfirmed}</div>
              <StepGuide steps={['위에 적힌 주소가 맞는지 살펴보세요.', '처음 받은 주소와 같은지 확인해요.']} />
            </>
          )}
        </ModalShell>
      )}

      {nameOpen && (
        <ModalShell
          label="이름 입력"
          eyebrow="곁눈 사용"
          title={displayName ? '이름을 바꿔볼까요?' : '이름을 알려주시겠어요?'}
          onClose={() => { logClick(SCREEN, 'name_modal_close'); setNameOpen(false) }}
          footer={
            <div className="modal-actions-2">
              {displayName ? (
                <button type="button" className="action-secondary" onClick={() => { logClick(SCREEN, 'name_modal_close'); setNameOpen(false) }}>
                  취소
                </button>
              ) : (
                <button type="button" className="action-secondary" onClick={skipNameModal}>
                  나중에 할게요
                </button>
              )}
              <button type="button" className="action-primary" disabled={!nameDraft.trim()} onClick={confirmNameModal}>
                <span aria-hidden="true">✓</span> 이렇게 부를게요
              </button>
            </div>
          }
        >
          <div className="input-hint">
            <span aria-hidden="true">😊</span>
            <p style={{ margin: 0 }}>이 기기에만 저장돼요. 화면 위 이름을 눌러 언제든 바꿀 수 있어요.</p>
          </div>
          <label style={{ display: 'block', marginTop: 18 }}>
            <span style={{ display: 'block', marginBottom: 8, fontSize: 19, fontWeight: 800, color: 'var(--fg-ink-title)' }}>부를 이름</span>
            <input
              type="text"
              className="name-input"
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              placeholder="예) 순자"
              maxLength={12}
              autoFocus
            />
          </label>
        </ModalShell>
      )}

      <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFileChange} />
    </>
  )
}
