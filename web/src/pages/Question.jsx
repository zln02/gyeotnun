/**
 * S3 - 확인 흐름 (발견 → 탐색 → 확인)  ★ 곁눈의 핵심 화면
 * 담당: 조희진 (화면) / 김태희 (질문 내용)
 * Figma node 428:312(발견) / 483:191(탐색) / 428:568(확인)
 *
 * ★★ 2026-08 Figma 3차 개편: 한 화면에 다 넣던 것을 3단계로 쪼갰다 ★★
 *   이전 화면은 [AI 질문 + 실제 출처 목록 + 답변 보기]가 한 화면에 세로로
 *   쌓여 있었다. 시니어 사용성 테스트에서 스크롤 중간의 출처 링크를 그냥
 *   지나쳐 버리고 바로 답변 버튼부터 누르는 일이 잦았다(공식 출처 확인률이
 *   낮게 나온 원인). Figma 가 이를 세 화면으로 나눴고, 그대로 따랐다.
 *     발견 - 무엇을 봤는지만 읽는다 (답변 버튼 없음)
 *     탐색 - 공식 자료를 열어 본다 (여기서만 링크가 보인다)
 *     확인 - 그제서야 답을 고른다
 *   한 화면에 할 일 하나. 이게 이 개편의 전부다.
 *
 * ★ 유지되는 설계 원칙
 *   1) AI가 만든 문장과 실제 출처를 시각적으로 완전히 분리한다.
 *   2) 한 화면에 질문은 하나만.
 *   3) 답변은 타이핑 없이 버튼으로.
 *   4) '다음' 버튼에 화살표만 쓰지 않고 글자를 함께 쓴다.
 */
import { useEffect, useRef, useState } from 'react'
import { getQuestion, TIMEOUT_CODE, CANCELLED_CODE } from '../api.js'
import { logClick, logError, logEvidenceLinkClick } from '../events.js'
import VerifyProgress from '../components/VerifyProgress.jsx'
import mascot from '../assets/verify/mascot.png'
import icImage from '../assets/verify/ic_image.svg'
import icPhoto from '../assets/verify/ic_photo.svg'
import icDoc from '../assets/verify/ic_doc.svg'
import icDocWhite from '../assets/verify/ic_doc_white.svg'
import icLink from '../assets/verify/ic_link.svg'
import icArrowNext from '../assets/verify/ic_arrow_next.svg'

const SCREEN = 'S3'

// 실제 API 는 질문 검증(2단 가드레일)이 재시도되면 턴마다 몇 초~10여 초씩 걸릴 수
// 있다. 이 시간을 넘기면 화면이 멈춘 게 아니라는 걸 알려 준다(2026-08-01 실사용
// 로그에서 느린 턴에 사용자가 다시 시도하다 이탈한 사례가 확인됐다).
const LONG_WAIT_MS = 10000
const LONG_WAIT_MESSAGE = '생각보다 시간이 걸리고 있어요. 더 정확한 질문을 만들고 있습니다. 조금만 더 기다려 주세요.'

/** 바닥에서 올라오는 '다시 보기' 시트 - 화면을 떠나지 않고 원문을 확인시킨다. */
function Sheet({ title, onClose, children }) {
  return (
    <div className="verify-sheet-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="verify-sheet">
        <div className="verify-sheet-head">
          <h3>{title}</h3>
          <button type="button" className="verify-sheet-close" onClick={onClose}>닫기</button>
        </div>
        <div className="verify-sheet-body">{children}</div>
      </div>
    </div>
  )
}

/** 공식 자료 카드 1건 (탐색 단계 / '안내문 다시 보기' 시트 공용) */
function ReferenceCard({ reference, onOpen }) {
  return (
    <div className="verify-ref">
      <div className="verify-ref-head">
        <span className="verify-ref-badge" aria-hidden="true">
          <img src={icDocWhite} width="15" height="15" alt="" />
        </span>
        <div className="verify-ref-title">
          <p className="verify-ref-name">{reference.title}</p>
          {/* ★ Figma 의 '공식 안내 요약'(본문 3줄 요약) 자리다. 서버 Reference 스키마에는
              요약 필드가 없어(models/schemas.py) 지어내지 않고, 실제로 가진 값인
              발행기관·발행일만 적는다. 요약이 필요하면 백엔드 계약부터 늘려야 한다. */}
          {(reference.publisher || reference.published_at) && (
            <p className="verify-ref-meta">
              {reference.publisher}
              {reference.publisher && reference.published_at && ' · '}
              {reference.published_at}
            </p>
          )}
        </div>
      </div>
      <a
        className="verify-ref-link"
        href={reference.url}
        target="_blank"
        rel="noreferrer"
        onClick={() => onOpen(reference.url)}
      >
        <img src={icLink} width="19" height="19" alt="" aria-hidden="true" />
        <span>공식 안내 보러가기</span>
      </a>
    </div>
  )
}

export default function Question({ checkId, checkData, evidence, photoUrl, onDone, onCancel }) {
  const [turn, setTurn] = useState(1)
  const [phase, setPhase] = useState('find')        // find | explore | confirm
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)   // { message, code }
  const [longWait, setLongWait] = useState(false)
  const [sheet, setSheet] = useState(null)          // 'text' | 'refs' | null
  // ★ 실제 API 는 응답이 겹칠 만큼 느릴 수 있다(React.StrictMode 의 이펙트 이중
  //   실행도 같은 상황을 만든다). 가장 최근 요청의 응답만 반영한다.
  const requestIdRef = useRef(0)
  const abortRef = useRef(null)
  // 시간 초과 뒤 '다시 시도' 를 누르면 같은 턴을 그대로 다시 요청한다.
  const lastArgsRef = useRef({ turn: 1, reply: null })

  async function load(nextTurn, reply) {
    const myRequestId = ++requestIdRef.current
    lastArgsRef.current = { turn: nextTurn, reply }
    setLoading(true)
    setError(null)
    setSelected(null)
    setLongWait(false)
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    const longWaitTimer = setTimeout(() => {
      if (myRequestId === requestIdRef.current) setLongWait(true)
    }, LONG_WAIT_MS)
    try {
      const result = await getQuestion(checkId, nextTurn, reply, { signal: controller.signal })
      if (myRequestId !== requestIdRef.current) return   // 더 최신 요청이 나갔다 - 버린다
      setData(result)
    } catch (e) {
      if (myRequestId !== requestIdRef.current) return
      if (e.code === CANCELLED_CODE) return              // 사용자가 그만뒀다
      setError({ message: e.message, code: e.code })
      logError(SCREEN, e.code || 'dialogue_fetch_failed')
    } finally {
      clearTimeout(longWaitTimer)
      if (myRequestId === requestIdRef.current) setLoading(false)
    }
  }

  // 화면을 벗어날 때 진행 중인 요청을 끊는다(응답이 늦게 와서 되살아나지 않게).
  useEffect(() => () => abortRef.current?.abort(), [])

  function cancel() {
    logClick(SCREEN, 'cancel_waiting')
    abortRef.current?.abort()
    onCancel?.()
  }

  useEffect(() => { load(1, null) }, [checkId])

  // 질문에 딸린 출처 URL → evidence.references 의 상세 정보와 연결.
  // ★ 질문이 출처를 지정하지 않은 턴에는 evidence 전체 목록으로 떨어진다 -
  //   '탐색' 단계는 보여줄 자료가 있어야 의미가 있기 때문.
  const refsFromQuestion = (data?.evidence_refs || [])
    .map((u) => evidence?.references?.find((r) => r.url === u))
    .filter(Boolean)
  const refs = (refsFromQuestion.length > 0 ? refsFromQuestion : (evidence?.references || [])).slice(0, 3)

  function openRef(url) {
    // ★ '공식 출처 확인률' 지표의 원천 - URL 원문 대신 도메인만 남긴다.
    let domain = 'unknown'
    try { domain = new URL(url).hostname } catch { /* noop */ }
    logEvidenceLinkClick(SCREEN, domain)
  }

  function goExplore() { logClick(SCREEN, 'to_explore'); setPhase('explore') }
  function goConfirm() { logClick(SCREEN, 'to_confirm'); setPhase('confirm') }

  function next() {
    if (data?.is_final) return onDone()
    const n = turn + 1
    setTurn(n)
    setPhase('find')
    load(n, selected)
  }

  if (loading) {
    return (
      <div className="verify">
        <VerifyProgress current="find" />
        <div className="wait" role="status" aria-live="polite">
          <div className="wait-icon-wrap">
            <span className="wait-glow" aria-hidden="true" />
            <img src={mascot} width="80" height="80" alt="" aria-hidden="true" className="wait-icon" />
          </div>
          <p className="wait-text">{longWait ? LONG_WAIT_MESSAGE : '질문을 준비하고 있어요'}</p>
          {/* 기다리는 중에도 빠져나갈 길을 남긴다 */}
          <button type="button" className="checking2-cancel" onClick={cancel}>그만두기</button>
        </div>
      </div>
    )
  }

  if (error) {
    const timedOut = error.code === TIMEOUT_CODE
    return (
      <div className="verify">
        <VerifyProgress current="find" />
        <div className="checking-fail" role="alert">
          <img src={mascot} width="72" height="72" alt="" aria-hidden="true" className="checking-fail-icon" />
          <h2 className="checking-fail-title">
            {timedOut ? '시간이 오래 걸리고 있어요.\n다시 해보시겠어요?' : '질문을 준비하지 못했어요'}
          </h2>
          {timedOut
            ? <p className="checking-fail-code">({error.code})</p>
            : <p className="checking-fail-msg">{error.message}</p>}
          <button
            type="button"
            className="verify-cta"
            onClick={() => { logClick(SCREEN, 'retry_after_timeout'); load(lastArgsRef.current.turn, lastArgsRef.current.reply) }}
          >
            다시 시도하기
          </button>
          <button type="button" className="checking-fail-quit" onClick={cancel}>그만두고 처음으로</button>
        </div>
      </div>
    )
  }

  return (
    <div className="verify">
      <VerifyProgress current={phase} />
      <p className="verify-turn">{turn}번째 확인 (모두 3개)</p>

      {/* ================= ① 발견 - 무엇을 봤는지만 읽는다 ================= */}
      {phase === 'find' && (
        <>
          <section className="verify-find">
            <img src={mascot} width="62" height="62" alt="" aria-hidden="true" className="verify-find-mascot" />
            <p className="verify-find-question">{data.question}</p>
            {data.why && <p className="verify-find-why">{data.why}</p>}
            {checkData?.extracted_text && (
              <button type="button" className="verify-recall" onClick={() => { logClick(SCREEN, 'recall_text'); setSheet('text') }}>
                <img src={icImage} width="18" height="18" alt="" aria-hidden="true" />
                <span>문자를 다시 보고싶어요</span>
              </button>
            )}
          </section>
          <button type="button" className="verify-cta" onClick={goExplore}>공식 안내 확인하기</button>
        </>
      )}

      {/* ================= ② 탐색 - 공식 자료를 열어 본다 ================= */}
      {phase === 'explore' && (
        <>
          <section className="verify-explore">
            {refs.length > 0 ? (
              refs.map((r) => <ReferenceCard key={r.url} reference={r} onOpen={openRef} />)
            ) : (
              <p className="verify-empty">
                공식 자료에서 같은 내용을 찾지 못했습니다.
                찾지 못했다는 것 자체가 한 번 더 확인해 볼 신호입니다.
              </p>
            )}
          </section>
          <button type="button" className="verify-cta" onClick={goConfirm}>
            {refs.length > 0 ? '안내 내용을 확인했어요' : '다음으로 넘어갈게요'}
          </button>
        </>
      )}

      {/* ================= ③ 확인 - 그제서야 답을 고른다 ================= */}
      {phase === 'confirm' && (
        <>
          <section className="verify-confirm">
            <span className="verify-confirm-chip">
              <img src={mascot} width="27" height="27" alt="" aria-hidden="true" />
              곁눈이 여쭤봐요
            </span>
            <p className="verify-confirm-question">{data.question}</p>
            {/* ★ '사진 다시 보기'는 사용자가 방금 고른 그 사진이다. 이 탭 메모리에만
                있고(App.jsx 의 photoUrl) 서버로 다시 보내지 않는다. 서버가 원본을
                파기한다는 약속(masking.discard_original)은 서버 보관에 대한 것이라
                자기 사진을 자기 화면에서 다시 보는 것과 어긋나지 않는다.
                글로 붙여넣어 사진이 없는 경우에는 마스킹된 글을 대신 보여준다. */}
            {photoUrl ? (
              <button type="button" className="verify-recall in-card" onClick={() => { logClick(SCREEN, 'recall_photo'); setSheet('photo') }}>
                <img src={icPhoto} width="20" height="20" alt="" aria-hidden="true" />
                <span>사진 다시 보기</span>
              </button>
            ) : checkData?.extracted_text && (
              <button type="button" className="verify-recall in-card" onClick={() => { logClick(SCREEN, 'recall_text'); setSheet('text') }}>
                <img src={icImage} width="20" height="20" alt="" aria-hidden="true" />
                <span>문자 다시 보기</span>
              </button>
            )}
            {refs.length > 0 && (
              <button type="button" className="verify-recall in-card" onClick={() => { logClick(SCREEN, 'recall_refs'); setSheet('refs') }}>
                <img src={icDoc} width="19" height="19" alt="" aria-hidden="true" />
                <span>안내문 다시 보기</span>
              </button>
            )}
          </section>

          <div className="verify-options" role="radiogroup" aria-label="답변 고르기">
            {data.options?.map((o) => (
              <button
                key={o.id}
                type="button"
                role="radio"
                aria-checked={selected === o.id}
                className={`verify-option${selected === o.id ? ' selected' : ''}`}
                onClick={() => { logClick(SCREEN, 'choice_option'); setSelected(o.id) }}
              >
                <span className="verify-radio" aria-hidden="true" />
                <span>{o.label}</span>
              </button>
            ))}
          </div>

          {/* ★ 화살표만 있는 버튼 금지 — '다음' 글자를 반드시 병기 */}
          <button
            type="button"
            className="verify-cta"
            disabled={!selected}
            onClick={() => { logClick(SCREEN, data.is_final ? 'finish' : 'next_turn'); next() }}
          >
            <span>{data.is_final ? '다 확인했어요' : '다음'}</span>
            {!data.is_final && <img src={icArrowNext} width="23" height="23" alt="" aria-hidden="true" />}
          </button>
        </>
      )}

      {sheet === 'photo' && (
        <Sheet title="올려 주신 사진" onClose={() => setSheet(null)}>
          <img src={photoUrl} alt="올려 주신 사진" className="verify-sheet-photo" />
          <p className="verify-sheet-note">
            이 사진은 이 기기에만 있습니다. 확인이 끝나면 사라집니다.
          </p>
        </Sheet>
      )}
      {sheet === 'text' && (
        <Sheet title="올려 주신 문자" onClose={() => setSheet(null)}>
          <p className="verify-sheet-text">{checkData.extracted_text}</p>
          <p className="verify-sheet-note">전화번호·계좌번호 같은 개인정보는 가려 둔 상태입니다.</p>
        </Sheet>
      )}
      {sheet === 'refs' && (
        <Sheet title="공식 안내" onClose={() => setSheet(null)}>
          {refs.map((r) => <ReferenceCard key={r.url} reference={r} onOpen={openRef} />)}
        </Sheet>
      )}
    </div>
  )
}
