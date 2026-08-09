import { useEffect, useRef, useState } from 'react'
import { getQuestion } from '../api.js'
import { logClick, logError, logEvidenceLinkClick } from '../events.js'
import resultIndicator from '../assets/check-flow/official-source-indicator.png'
import resultArrow from '../assets/check-flow/arrow-right.svg'
import questionMascot from '../assets/check-flow/question-mascot.png'
import checkIcon from '../assets/check-flow/check-icon.svg'
import imageIcon from '../assets/check-flow/image-icon.svg'
import documentIcon from '../assets/check-flow/document-icon.svg'
import findingMascot from '../assets/check-flow/finding-mascot.png'
import reviewImageIcon from '../assets/check-flow/review-image-icon.svg'

const SCREEN = 'S3'
const LONG_WAIT_MS = 10000
const LONG_WAIT_MESSAGE = '생각보다 시간이 걸리고 있어요. 정확한 질문을 준비하고 있으니 조금만 기다려 주세요.'

const FLOW_STEPS = ['발견', '탐색', '확인']

const VERDICT_TIERS = {
  confirmed: {
    label: '공식 자료 확인',
    desc: '관련 공식 자료를 찾았어요.',
    className: 'tier-ok',
    title: '공식 자료를 찾았어요',
    subtitle: '원문을 함께 확인해요',
  },
  suspicious: {
    label: '함께 확인',
    desc: '공식 자료와 비교해 볼 내용이 있어요.',
    className: 'tier-warn',
    title: '함께 확인할 점이 있어요',
    subtitle: '공식 자료를 하나씩 살펴봐요',
  },
  unknown: {
    label: '추가 확인',
    desc: '공식 자료에서 같은 내용을 바로 확인하지 못했어요.',
    className: 'tier-unknown',
    title: '공식 자료를 더 찾아봐요',
    subtitle: '확인할 수 있는 단서를 함께 살펴봐요',
  },
}

function verdictTier(evidence) {
  if (evidence?.verdict_hint === 'no_source_found') return 'unknown'
  const hasAttentionSignal = (evidence?.signals || []).some((signal) => signal.severity === 'attention')
  return hasAttentionSignal ? 'suspicious' : 'confirmed'
}

function evidenceSummary(evidence, tier) {
  const attention = (evidence?.signals || []).find((signal) => signal.severity === 'attention')
  if (attention?.label) return attention.label

  const publishers = [...new Set((evidence?.references || []).map((reference) => reference.publisher).filter(Boolean))]
  if (publishers.length > 0) return `${publishers.slice(0, 2).join('·')} 자료를 직접 확인해 보세요.`

  return VERDICT_TIERS[tier].desc
}

function questionReferences(data, evidence) {
  const allReferences = evidence?.references || []
  const byUrl = new Map(allReferences.map((reference) => [reference.url, reference]))
  const urls = data?.evidence_refs || []

  if (urls.length === 0) return allReferences
  return urls.map((url) => byUrl.get(url) || { url, title: url, publisher: '', published_at: '' })
}

function logReferenceClick(reference) {
  let domain = 'unknown'
  try {
    domain = new URL(reference.url).hostname
  } catch {
    // A malformed external URL should never interrupt the check flow.
  }
  logEvidenceLinkClick(SCREEN, domain)
}

function ReferenceLink({ reference, compact = false }) {
  return (
    <a
      className={compact ? 'check-flow__reference check-flow__reference--compact' : 'check-flow__reference'}
      href={reference.url}
      target="_blank"
      rel="noreferrer"
      onClick={() => logReferenceClick(reference)}
    >
      <img src={documentIcon} alt="" aria-hidden="true" />
      <span>
        <strong>{reference.title || reference.url}</strong>
        {(reference.publisher || reference.published_at) && (
          <small>
            {[reference.publisher, reference.published_at].filter(Boolean).join(' · ')}
          </small>
        )}
      </span>
    </a>
  )
}

function FlowProgress({ activeStep, steps = FLOW_STEPS }) {
  return (
    <ol className="check-flow__progress" aria-label={`진행 단계: ${steps[activeStep]}`}>
      {steps.map((label, index) => {
        const complete = index < activeStep
        const active = index === activeStep
        return (
          <li className={`${complete ? 'is-complete' : ''}${active ? ' is-active' : ''}`} key={label}>
            <span className="check-flow__progress-status">{active ? '진행 중' : ''}</span>
            <span className="check-flow__progress-bar" aria-hidden="true" />
            <span>{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

function ResultStage({ evidence, loading, onContinue }) {
  const tier = verdictTier(evidence)
  const copy = VERDICT_TIERS[tier]

  return (
    <section className="check-flow check-flow--result" aria-labelledby="check-result-title">
      <div className="check-flow__result-visual" aria-hidden="true">
        <span />
        <img src={resultIndicator} alt="" />
      </div>
      <div className="check-flow__result-copy">
        <h2 id="check-result-title">{copy.title}</h2>
        <p>{copy.subtitle}</p>
      </div>
      {loading && <p className="check-flow__pending" role="status">질문을 준비하고 있어요.</p>}
      <button className="check-flow__primary-action" type="button" onClick={onContinue}>
        <span>하나씩 확인하기</span>
        <img src={resultArrow} alt="" aria-hidden="true" />
      </button>
    </section>
  )
}

function FindingStage({ evidence, checkData, onContinue }) {
  const [showMessage, setShowMessage] = useState(false)
  const signals = (evidence?.signals || []).filter((signal) => signal.severity === 'attention')

  return (
    <section className="check-flow check-flow--finding" aria-labelledby="check-finding-title">
      <section className="check-flow__notice" aria-label="발견한 확인 포인트">
        <span className="check-flow__notice-icon check-flow__notice-icon--label">
          <img src={resultIndicator} alt="" aria-hidden="true" />
          <span>주의</span>
        </span>
        <div>
          <h2>공식 안내와 비교해 볼 점이 있어요</h2>
          <p>받은 내용을 살펴봤어요</p>
        </div>
      </section>

      <article className="check-flow__finding-card">
        <div className="check-flow__mascot-label">
          <img src={findingMascot} alt="" />
          <span>곁눈이 발견했어요</span>
        </div>
        <h1 id="check-finding-title">이 정보에서 확인할 점을 찾았어요</h1>
        {signals.length > 0 ? (
          <ul className="check-flow__finding-list">
            {signals.map((signal) => <li key={signal.key}>{signal.label}</li>)}
          </ul>
        ) : (
          <p className="check-flow__finding-empty">받은 내용과 공식 안내를 나란히 살펴보면 판단에 도움이 됩니다.</p>
        )}

        {checkData?.extracted_text && (
          <div className="check-flow__review-actions">
            <button type="button" onClick={() => setShowMessage((open) => !open)} aria-expanded={showMessage}>
              <img src={reviewImageIcon} alt="" aria-hidden="true" />
              <span>받은 내용 다시 보기</span>
            </button>
          </div>
        )}
        {showMessage && <p className="check-flow__received-text">{checkData.extracted_text}</p>}
      </article>

      <button className="check-flow__primary-action" type="button" onClick={onContinue}>
        <span>질문 전에 잠깐 보기</span>
        <img src={resultArrow} alt="" aria-hidden="true" />
      </button>
    </section>
  )
}

function SourcesStage({ evidence, onContinue }) {
  const references = evidence?.references || []

  return (
    <section className="check-flow check-flow--sources" aria-labelledby="check-sources-title">
      <section className="check-flow__notice" aria-label="질문 전 확인 안내">
        <span className="check-flow__notice-icon"><img src={checkIcon} alt="" /><span>확인</span></span>
        <div>
          <h2 id="check-sources-title">다음 화면부터 질문을 시작해요</h2>
          <p>질문은 3개예요. 하나씩 천천히 답하면 돼요</p>
        </div>
      </section>

      <article className="check-flow__source-card">
        <header>
          <div>
            <h3>질문 전에 잠깐 살펴봐요</h3>
            <p>아래 자료는 필요한 만큼만 보면 돼요.</p>
          </div>
        </header>

        {references.length > 0 ? (
          <div className="check-flow__reference-list">
            {references.map((reference) => <ReferenceLink key={reference.url} reference={reference} />)}
          </div>
        ) : (
          <p className="check-flow__source-empty">지금은 바로 열 수 있는 공식 자료를 찾지 못했어요. 아래 질문에서 확인 단서를 함께 살펴봐요.</p>
        )}
      </article>

      <button className="check-flow__primary-action" type="button" onClick={onContinue}>
        <span>질문 시작하기</span>
        <img src={resultArrow} alt="" aria-hidden="true" />
      </button>
    </section>
  )
}

function QuestionStage({ checkData, data, evidence, turn, selected, openPanel, onSelect, onTogglePanel, onNext }) {
  const references = questionReferences(data, evidence)
  const questionNumber = data?.turn || turn
  const isFirstQuestion = questionNumber === 1

  return (
    <section className="check-flow check-flow--question" aria-labelledby="check-question-title">
      <section className="check-flow__notice" aria-label="질문 안내" key={questionNumber}>
        <span className="check-flow__notice-icon check-flow__notice-icon--question">
          <span>질문 {questionNumber}</span>
        </span>
        <div>
          <h2>{isFirstQuestion ? '하나씩 답해 볼까요?' : '다음 질문도 함께 볼게요'}</h2>
          <p>받은 내용과 공식 자료를 비교해서 골라주세요</p>
        </div>
      </section>

      <article className="check-flow__question-card">
        <div className="check-flow__mascot-label">
          <img src={questionMascot} alt="" />
          <span>곁눈이 여쭤봐요</span>
        </div>
        <h1 id="check-question-title">{data.question}</h1>
        {data.why && <p className="check-flow__why">{data.why}</p>}

        <div className="check-flow__review-actions">
          {checkData?.extracted_text && (
            <button type="button" onClick={() => onTogglePanel('message')} aria-expanded={openPanel === 'message'}>
              <img src={imageIcon} alt="" aria-hidden="true" />
              <span>받은 내용 다시 보기</span>
            </button>
          )}
          {references.length > 0 && (
            <button type="button" onClick={() => onTogglePanel('sources')} aria-expanded={openPanel === 'sources'}>
              <img src={documentIcon} alt="" aria-hidden="true" />
              <span>공식 안내 다시 보기</span>
            </button>
          )}
        </div>

        {openPanel === 'message' && <p className="check-flow__received-text">{checkData.extracted_text}</p>}
        {openPanel === 'sources' && (
          <div className="check-flow__question-references">
            {references.map((reference) => <ReferenceLink key={reference.url} reference={reference} compact />)}
          </div>
        )}
      </article>

      <div className="check-flow__answers" role="radiogroup" aria-label="질문 답변">
        {data.options?.map((option) => {
          const isSelected = selected === option.id
          return (
            <button
              className={isSelected ? 'is-selected' : ''}
              type="button"
              role="radio"
              aria-checked={isSelected}
              key={option.id}
              onClick={() => onSelect(option.id)}
            >
              <span className="check-flow__radio" aria-hidden="true" />
              <span>{option.label}</span>
              <span className="check-flow__answer-state" aria-hidden="true">{isSelected ? '선택됨' : '선택'}</span>
            </button>
          )
        })}
      </div>

      <button className="check-flow__primary-action" type="button" disabled={!selected} onClick={onNext}>
        <span>{data.is_final ? '함께 확인 마치기' : '다음 질문'}</span>
        <img src={resultArrow} alt="" aria-hidden="true" />
      </button>
    </section>
  )
}

export default function Question({ checkId, checkData, evidence, onDone }) {
  const [turn, setTurn] = useState(1)
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [longWait, setLongWait] = useState(false)
  const [stage, setStage] = useState('result')
  const [openPanel, setOpenPanel] = useState(null)
  const requestIdRef = useRef(0)

  async function load(nextTurn, reply) {
    const myRequestId = ++requestIdRef.current
    setLoading(true)
    setError('')
    setSelected(null)
    setOpenPanel(null)
    setLongWait(false)
    const longWaitTimer = setTimeout(() => {
      if (myRequestId === requestIdRef.current) setLongWait(true)
    }, LONG_WAIT_MS)

    try {
      const result = await getQuestion(checkId, nextTurn, reply)
      if (myRequestId !== requestIdRef.current) return
      setData(result)
    } catch (error) {
      if (myRequestId !== requestIdRef.current) return
      setError(error.message)
      logError(SCREEN, error.code || 'dialogue_fetch_failed')
    } finally {
      clearTimeout(longWaitTimer)
      if (myRequestId === requestIdRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    setTurn(1)
    setStage('result')
    load(1, null)
  }, [checkId])

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [stage, turn])

  function next() {
    if (data?.is_final) {
      logClick(SCREEN, 'finish')
      onDone()
      return
    }

    const nextTurn = turn + 1
    logClick(SCREEN, 'next_turn')
    setTurn(nextTurn)
    load(nextTurn, selected)
  }

  function select(optionId) {
    logClick(SCREEN, 'choice_option')
    setSelected(optionId)
  }

  function togglePanel(panel) {
    setOpenPanel((current) => current === panel ? null : panel)
  }

  if (error) {
    const activeStep = stage === 'sources' ? 1 : stage === 'question' ? 2 : 0
    return (
      <section className="check-flow check-flow--error" aria-live="polite">
        <FlowProgress activeStep={activeStep} />
        <div className="check-flow__error-box">
          <h2>질문을 불러오지 못했어요</h2>
          <p>{error}</p>
        </div>
      </section>
    )
  }

  if (stage === 'result') {
    return <ResultStage evidence={evidence} loading={loading} onContinue={() => { logClick(SCREEN, 'open_finding'); setStage('finding') }} />
  }

  if (stage === 'finding') {
    return <FindingStage evidence={evidence} checkData={checkData} onContinue={() => { logClick(SCREEN, 'open_sources'); setStage('sources') }} />
  }

  if (stage === 'sources') {
    return <SourcesStage evidence={evidence} onContinue={() => { logClick(SCREEN, 'start_questions'); setStage('question') }} />
  }

  if (loading || !data) {
    return (
      <section className="check-flow check-flow--loading" aria-live="polite">
        <FlowProgress activeStep={2} />
        <div className="check-flow__loading-spinner" role="status" />
        <h2>{longWait ? LONG_WAIT_MESSAGE : '다음 질문을 준비하고 있어요'}</h2>
      </section>
    )
  }

  return (
    <QuestionStage
      checkData={checkData}
      data={data}
      evidence={evidence}
      turn={turn}
      selected={selected}
      openPanel={openPanel}
      onSelect={select}
      onTogglePanel={togglePanel}
      onNext={next}
    />
  )
}
