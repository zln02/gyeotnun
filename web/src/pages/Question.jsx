/**
 * S3 - 질문 카드  ★ 곁눈의 핵심 화면
 * 담당: 조희진 (화면) / 김태희 (질문 내용)
 *
 * ★★ 이 화면의 설계 원칙 ★★
 * 1) AI가 만든 문장과 실제 출처를 **시각적으로 완전히 분리**한다.
 *    - AI 질문  : 파란 배경 + 왼쪽 굵은 세로선 + "곁눈이 여쭤봐요" 라벨
 *    - 실제 출처: 초록 점선 테두리 + "실제 자료" 라벨 + 누를 수 있는 링크 버튼
 *    섞어 놓으면 사용자는 링크까지 AI가 지어낸 것으로 의심하거나,
 *    반대로 AI 문장을 공식 발표로 오해한다. 둘 다 신뢰를 무너뜨린다.
 * 2) 한 화면에 질문은 하나만.
 * 3) 답변은 타이핑 없이 버튼으로. 시니어에게 자유 입력은 큰 장벽이다.
 * 4) '다음' 버튼에 화살표만 쓰지 않고 글자를 함께 쓴다.
 */
import { useEffect, useRef, useState } from 'react'
import { getQuestion } from '../api.js'
import { logClick, logError, logEvidenceLinkClick } from '../events.js'

const SCREEN = 'S3'

// 실제 API 는 질문 검증(2단 가드레일)이 재시도되면 턴마다 몇 초~10여 초씩 걸릴 수
// 있다(Checking.jsx 의 S2 화면과 같은 이유). S2 에는 이 안내가 있었는데 S3 의
// 턴 전환 로딩에는 없어서, 느린 턴에서 화면이 멈춘 것처럼 보여 사용자가 다시
// 시도하다 이탈하는 사례가 실제로 있었다(2026-08-01 실사용 로그에서 확인) - 같은
// 패턴을 S3 에도 그대로 적용한다.
const LONG_WAIT_MS = 10000
const LONG_WAIT_MESSAGE = '생각보다 시간이 걸리고 있어요. 더 정확한 질문을 만들고 있습니다. 조금만 더 기다려 주세요.'

/**
 * 확인 결과 배지 (S3 상단, 질문보다 먼저 보여준다)
 * ★ verdict_hint 하나만 그대로 옮기지 않는다. search.py 의 official_source_found /
 *   contact_in_image 신호는 severity="info"(문제 신호 아님)라서, 공식 자료를 찾았을
 *   뿐인데도 partially_matched 가 찍히는 경우가 있다. severity="attention" 신호가
 *   실제로 있을 때만 '의심'으로 올리고, 그 외엔 verdict_hint 의 no_source_found 여부로
 *   '확인 불가' 를 가른다 - verdict_hint 와 signals 를 함께 봐야 정확하다.
 */
const VERDICT_TIERS = {
  confirmed: {
    label: '확인됨',
    icon: '✅',
    desc: '공식 자료에서 확인됐습니다.',
    className: 'tier-ok',
  },
  suspicious: {
    label: '의심',
    icon: '⚠️',
    desc: '확인할 점이 남아 있습니다.',
    className: 'tier-warn',
  },
  unknown: {
    label: '확인 불가',
    icon: '❓',
    desc: '공식 자료에서 확인하지 못했습니다.',
    className: 'tier-unknown',
  },
}

function verdictTier(evidence) {
  if (evidence?.verdict_hint === 'no_source_found') return 'unknown'
  const hasAttentionSignal = (evidence?.signals || []).some((s) => s.severity === 'attention')
  return hasAttentionSignal ? 'suspicious' : 'confirmed'
}

// 배지 아래 한 줄 근거 요약 - 실제 references/signals 에서만 뽑는다(지어내지 않는다)
function evidenceSummary(evidence, tier) {
  const refs = evidence?.references || []
  if (tier === 'unknown') {
    return '공식 자료에서 같은 이름의 공고나 안내를 찾지 못했습니다.'
  }
  const publishers = [...new Set(refs.map((r) => r.publisher).filter(Boolean))].slice(0, 2).join('·')
  if (tier === 'suspicious') {
    // ★ similar_scam_case 신호의 원문 label 은 "...사기 수법과 비슷합니다"처럼
    //   금지어를 그대로 담고 있다. 괄호 안 실제 상세정보(특징/오판유형)는 그대로 살리고
    //   표현만 순화한다 - 데이터를 지어내지 않으면서 단정적 단어만 피한다.
    const scamSignal = (evidence?.signals || []).find((s) => s.key === 'similar_scam_case')
    if (scamSignal) {
      const detail = scamSignal.label.match(/\(([^)]+)\)/)?.[1]
      return detail
        ? `이전에 확인된 사례와 비슷한 점이 있습니다 (${detail}).`
        : '이전에 확인된 사례와 비슷한 점이 있습니다.'
    }
    return publishers ? `${publishers} 자료와 다른 점이 있어 확인이 필요합니다.` : '확인할 점이 남아 있습니다.'
  }
  return publishers ? `${publishers}에서 같은 내용을 확인했습니다.` : '공식 자료에서 같은 내용을 확인했습니다.'
}

function VerdictBadge({ evidence }) {
  const tier = verdictTier(evidence)
  const t = VERDICT_TIERS[tier]
  return (
    <div className={`verdict-badge ${t.className}`}>
      <div className="verdict-head">
        <span className="verdict-icon" aria-hidden="true">{t.icon}</span>
        <span className="verdict-label">{t.label}</span>
      </div>
      <p className="verdict-desc">{t.desc}</p>
      <p className="verdict-summary">{evidenceSummary(evidence, tier)}</p>
    </div>
  )
}

export default function Question({ checkId, evidence, onDone }) {
  const [turn, setTurn] = useState(1)
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [longWait, setLongWait] = useState(false)
  // ★ 실제 API 는 응답이 겹칠 만큼 느릴 수 있다(React.StrictMode 의 개발 중 이펙트
  //   이중 실행도 같은 상황을 만든다). 가장 최근 요청의 응답만 반영하고,
  //   먼저 보낸 요청이 나중에 도착해도 화면을 덮어쓰지 않게 막는다.
  const requestIdRef = useRef(0)

  async function load(nextTurn, reply) {
    const myRequestId = ++requestIdRef.current
    setLoading(true)
    setError('')
    setSelected(null)
    setLongWait(false)
    const longWaitTimer = setTimeout(() => {
      if (myRequestId === requestIdRef.current) setLongWait(true)
    }, LONG_WAIT_MS)
    try {
      const result = await getQuestion(checkId, nextTurn, reply)
      if (myRequestId !== requestIdRef.current) return   // 더 최신 요청이 이미 나갔다 - 이 응답은 버린다
      setData(result)
    } catch (e) {
      if (myRequestId !== requestIdRef.current) return
      setError(e.message)
      logError(SCREEN, e.code || 'dialogue_fetch_failed')
    } finally {
      clearTimeout(longWaitTimer)
      if (myRequestId === requestIdRef.current) setLoading(false)
    }
  }

  useEffect(() => { load(1, null) }, [checkId])

  function next() {
    if (data?.is_final) return onDone()
    const n = turn + 1
    setTurn(n)
    load(n, selected)
  }

  // 질문에 딸린 출처 URL → evidence.references 의 상세 정보(기관명·자료명·발행일)와 연결
  const refs = (data?.evidence_refs || []).map((u) => {
    const found = evidence?.references?.find((r) => r.url === u)
    return found || { url: u, title: u, publisher: '', published_at: '' }
  })

  // ★ 결과(배지)를 먼저, 질문은 그 다음 - 로딩/에러 중에도 배지는 계속 보여준다
  if (loading) {
    return (
      <>
        {evidence && <VerdictBadge evidence={evidence} />}
        <div className="loading">
          <div className="spinner" role="status" aria-live="polite" />
          <p className="lead">{longWait ? LONG_WAIT_MESSAGE : '질문을 준비하고 있어요'}</p>
        </div>
      </>
    )
  }
  if (error) {
    return (
      <>
        {evidence && <VerdictBadge evidence={evidence} />}
        <div className="error-box">{error}</div>
      </>
    )
  }

  return (
    <>
      {evidence && <VerdictBadge evidence={evidence} />}
      <div className="progress" aria-label={`3단계 중 ${turn}단계`}>
        {[1, 2, 3].map((i) => <span key={i} className={i <= turn ? 'on' : ''} />)}
      </div>
      <p className="sub" style={{ marginBottom: 14 }}>{turn}번째 질문 (모두 3개)</p>

      {/* ========== ① AI가 만든 문장 영역 (파란색) ========== */}
      <div className="ai-block">
        <span className="ai-label">🤖 곁눈이 여쭤봐요</span>
        <p className="ai-question">{data.question}</p>
        {data.why && <p className="ai-why">{data.why}</p>}
      </div>

      {/* ========== ② 실제 출처 영역 (초록색, 점선) ==========
          여기 있는 링크는 AI가 지어낸 것이 아니라 검색으로 확보한 실제 주소다.
          서버의 validate_question() 이 허용 목록 밖의 링크를 미리 제거한다. */}
      <div className="source-block">
        <span className="source-label">🔗 실제 자료 (직접 눌러 확인)</span>
        {refs.length > 0 ? (
          refs.map((r) => (
            <a
              key={r.url}
              className="source-link"
              href={r.url}
              target="_blank"
              rel="noreferrer"
              onClick={() => {
                // ★ '공식 출처 확인률' 지표의 원천 - URL 원문 대신 도메인만 남긴다
                //   (URL 은 공개된 정부 자료 링크라 개인정보는 아니지만, target 길이
                //   제한도 있고 도메인만으로 충분히 분석 가능하다).
                let domain = 'unknown'
                try { domain = new URL(r.url).hostname } catch { /* noop */ }
                logEvidenceLinkClick(SCREEN, domain)
              }}
            >
              <span aria-hidden="true">📄</span>
              <span>
                {r.title}
                {(r.publisher || r.published_at) && (
                  <>
                    <br />
                    <small>
                      {r.publisher}
                      {r.publisher && r.published_at && ' · '}
                      {r.published_at}
                    </small>
                  </>
                )}
              </span>
            </a>
          ))
        ) : (
          <p className="source-empty">
            공식 자료에서 같은 내용을 찾지 못했습니다.
            찾지 못했다는 것 자체가 한 번 더 확인해 볼 신호입니다.
          </p>
        )}
      </div>

      {/* ========== ③ 답변 보기 ========== */}
      <div style={{ marginTop: 24 }}>
        {data.options?.map((o) => (
          <button
            key={o.id}
            className={`btn choice ${selected === o.id ? 'selected' : ''}`}
            onClick={() => { logClick(SCREEN, 'choice_option'); setSelected(o.id) }}
          >
            <span aria-hidden="true">{selected === o.id ? '✅' : '⬜'}</span> {o.label}
          </button>
        ))}
      </div>

      {/* ★ 화살표만 있는 버튼 금지 — '다음' 글자를 반드시 병기 */}
      <button className="btn" disabled={!selected} onClick={() => { logClick(SCREEN, data.is_final ? 'finish' : 'next_turn'); next() }}>
        {data.is_final ? '다 확인했어요' : '다음 →'}
      </button>
    </>
  )
}
