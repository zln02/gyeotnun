/**
 * S5 - 오늘의 5분 훈련 + 주간 리포트
 * 담당: 조희진 (화면) / 장지석 (카드 내용)
 *
 * ★ 리포트에 '몇 번 속았는지'를 쓰지 않는다. '몇 번 확인했는지'를 쓴다.
 *   가족과 공유되는 화면이므로, 어르신이 부끄러워지는 순간 서비스는 삭제된다.
 *
 * ★ 2026-08 Figma 이식: 기존의 단일 카드(문항 하나+객관식) 형태를, 하나의
 *   실제 사례 문자를 4단계(제목 판단/기관 이름/숫자·조건/전체)로 나눠 짚어보는
 *   O·X 실습으로 바꿨다(연습 시작 안내 화면 + 진행 중 화면, node 144:846 /
 *   151:1656). 오늘의 훈련 카드 API(getTodayCard)는 이 4단계 구조(문구별
 *   강조 위치·단계별 힌트)를 표현하지 못해 이번 이식에서는 쓰지 않는다 -
 *   포인트 배너(G/120)와 같은 이유로, 실습 내용은 PRACTICE_STEPS 에 고정값으로
 *   둔다. TODO: 여러 단계짜리 연습 컨텐츠를 주는 API가 생기면 교체한다.
 *   주간 리포트(getWeeklyReport)는 기존 그대로 실습을 마친 뒤에 보여준다.
 */
import { useEffect, useRef, useState } from 'react'
import { getWeeklyReport } from '../api.js'
import { logClick, logError } from '../events.js'
import BottomNav from '../components/BottomNav.jsx'

import icBack from '../assets/training/ic_back.svg'
import icHomeQuit from '../assets/training/ic_home_quit.svg'
import icHint from '../assets/training/ic_hint.svg'
import icNext from '../assets/training/ic_next.svg'

const SCREEN = 'S5'

// 이번 실습이 다루는 문자 - 실제 사례를 각색한 고정 예시(연습1: 122:9 /
// 곁눈 화면 옮기는중(복사): 151:1656 에서 실측).
const MESSAGE = {
  senderTag: '[복지부알림]',
  titleRest: ' 효도지원금 100만원 지급 안내.',
  body: '이번 달 말까지 신청하지 않으면 취소됩니다.',
  link: 'http://welfare-giveaway.net/apply',
}

const PRACTICE_META = {
  topicLine1: '효도지원금 100만원 문자',
  topicLine2: '함께 확인해요',
  chips: [
    { icon: '📨', label: '문자' },
    { icon: '⏱', label: '약 5분' },
    { icon: '📍', label: '4단계' },
  ],
}

const PRACTICE_STEPS = [
  {
    categoryLabel: '제목 판단하기',
    focusTip: '제목만 보고 넘겨짚지 않아요',
    highlight: { line: 'title' },
    hint: '제목에 기관 이름이 있어도 진짜라는 뜻은 아니에요.',
    question: '제목만 보고 이 문자를 믿어도 될까요?',
    feedback: {
      suspicious: { title: '잘 고르셨어요', detail: '제목만으로는 확인할 수 없어요. 발신 기관과 링크도 함께 봐야 해요.' },
      trust: { title: '다시 한 번 볼까요?', detail: '제목만 보고 판단하기엔 일러요. 발신 기관과 링크도 함께 확인해요.' },
    },
  },
  {
    categoryLabel: '기관 이름 확인하기',
    focusTip: '이름만 보고 진짜 기관이라 믿지 않아요',
    highlight: { line: 'title', part: 'sender' },
    hint: '발신 이름은 누구나 자유롭게 적을 수 있어요.',
    question: "'복지부'라는 이름이 붙어 있으면 진짜 정부 문자일까요?",
    feedback: {
      suspicious: { title: '맞아요', detail: '발신 이름만으로는 진짜 기관인지 확인할 수 없어요.' },
      trust: { title: '다시 한 번 볼까요?', detail: "'복지부' 같은 이름은 누구나 써넣을 수 있어요. 이름만으로는 확인이 안 돼요." },
    },
  },
  {
    categoryLabel: '숫자·조건 검토하기',
    focusTip: '서두르게 하는 말은 조심해요',
    highlight: { line: 'body' },
    hint: "'지금 안 하면 취소' 같은 급한 말은 피싱 신호예요.",
    question: '이 문자를 믿어도 될까요?',
    feedback: {
      suspicious: { title: '잘 골랐어요', detail: '지원금을 미끼로 급한 신청과 낯선 주소 접속을 요구하고 있어요.' },
      trust: { title: '의심해 봐야 해요', detail: '지원금을 미끼로 급한 신청과 낯선 주소 접속을 요구하고 있어요.' },
    },
  },
  {
    categoryLabel: '전부 알아보기',
    focusTip: '낯선 주소는 눌러보지 않아요',
    highlight: { line: 'link' },
    hint: '공식 기관은 이런 낯선 주소를 쓰지 않아요. 정부24·복지로 같은 공식 도메인인지 확인해요.',
    question: '이 주소로 들어가도 될까요?',
    feedback: {
      suspicious: { title: '정확해요', detail: '공식 사이트는 이런 낯선 주소를 쓰지 않아요.' },
      trust: { title: '절대 누르지 마세요', detail: 'welfare-giveaway.net 은 정부 공식 도메인이 아니에요.' },
    },
  },
]

function MessageBody({ highlight }) {
  const senderHighlighted = highlight.line === 'title' && highlight.part === 'sender'
  const titleHighlighted = highlight.line === 'title' && !highlight.part

  let titleNode
  if (senderHighlighted) {
    titleNode = <><span className="practice-highlight-warn">{MESSAGE.senderTag}</span>{MESSAGE.titleRest}</>
  } else if (titleHighlighted) {
    titleNode = <span className="practice-highlight-warn">{MESSAGE.senderTag}{MESSAGE.titleRest}</span>
  } else {
    titleNode = <>{MESSAGE.senderTag}{MESSAGE.titleRest}</>
  }

  return (
    <p className="practice-message-body">
      {titleNode}
      {'\n'}
      {highlight.line === 'body' ? <span className="practice-highlight-warn">{MESSAGE.body}</span> : MESSAGE.body}
      {'\n'}
      {highlight.line === 'link' ? <span className="practice-highlight-link">{MESSAGE.link}</span> : MESSAGE.link}
    </p>
  )
}

function PracticeIntro({ onStart, onNavTap, toast }) {
  return (
    <>
      <section className="practice-hero" aria-label="오늘의 5분 연습 안내">
        <p style={{ textAlign: 'center', margin: '0 0 8px' }}>
          <span className="practice-badge">오늘의 5분 연습</span>
        </p>
        <h2 className="practice-title">
          {PRACTICE_META.topicLine1}<br />{PRACTICE_META.topicLine2}
        </h2>
        <div className="practice-chips" aria-hidden="true">
          {PRACTICE_META.chips.map((c) => (
            <span className="practice-chip" key={c.label}>
              <span aria-hidden="true">{c.icon}</span>{c.label}
            </span>
          ))}
        </div>

        <div className="practice-howcard">
          <p className="practice-how-eyebrow">이렇게 배워요</p>
          <ol className="practice-how-list">
            {PRACTICE_STEPS.map((s, i) => (
              <li key={s.categoryLabel}>
                <span className="practice-how-num" aria-hidden="true">{i + 1}</span>
                {s.categoryLabel}
              </li>
            ))}
          </ol>
          <button type="button" className="practice-start-btn" onClick={onStart}>학습 시작하기</button>
        </div>

        <p className="practice-quit-note">언제든 그만할 수 있어요</p>
      </section>

      <div aria-hidden="true" style={{ height: 110 }} />
      <div className="bottom-scrim" aria-hidden="true" />
      <BottomNav active="learn" onTap={onNavTap} />
      <div className="nav-toast-wrap" aria-live="polite">
        {toast && <div className="nav-toast">{toast}</div>}
      </div>
    </>
  )
}

function PracticeStep({ index, total, step, answer, hintOpen, onToggleHint, onPick, onPrev, onNext, onQuit }) {
  const isLast = index === total - 1
  const picked = answer != null
  const feedback = picked ? step.feedback[answer] : null

  return (
    <>
      <div className="practice-header">
        <button type="button" className="practice-back-btn" onClick={onPrev} aria-label="이전 단계">
          <img src={icBack} width="20" height="20" alt="" aria-hidden="true" />
        </button>
        <button type="button" className="practice-quit-btn" onClick={onQuit}>
          <img src={icHomeQuit} width="16" height="16" alt="" aria-hidden="true" />
          이제 그만하고 싶어요
        </button>
      </div>

      <div className="practice-progress" aria-label={`4단계 중 ${index + 1}단계`}>
        {PRACTICE_STEPS.map((s, i) => (
          <div key={s.categoryLabel} className={`practice-progress-seg${i < index ? ' done' : i === index ? ' current' : ''}`}>
            {i === index ? (
              <span className="practice-progress-tag">진행 중</span>
            ) : (
              <span className="practice-progress-tag" style={{ visibility: 'hidden' }}>진행 중</span>
            )}
            <span className="practice-progress-bar" />
            <span className="practice-progress-label">{i + 1}단계</span>
          </div>
        ))}
      </div>

      <div className="practice-focus-card">
        <span className="practice-focus-num" aria-hidden="true">{index + 1}</span>
        <div>
          <p className="practice-focus-step">{index + 1}단계</p>
          <p className="practice-focus-tip">{step.focusTip}</p>
        </div>
      </div>

      <div className="practice-message-card">
        <div className="practice-message-head">
          <span>받은 문자</span>
          <span className="practice-message-tag">SMS</span>
        </div>
        <MessageBody highlight={step.highlight} />
      </div>

      <button type="button" className="practice-hint-toggle" onClick={onToggleHint}>
        <img src={icHint} width="18" height="18" alt="" aria-hidden="true" />
        {hintOpen ? '힌트 닫기' : '힌트 보기'}
      </button>
      {hintOpen && <p className="practice-hint-box">{step.hint}</p>}

      <h3 className="practice-question">{step.question}</h3>
      <div className="practice-answers">
        <button
          type="button"
          className={`practice-answer believe${answer === 'trust' ? ' selected' : ''}`}
          onClick={() => onPick('trust')}
          aria-pressed={answer === 'trust'}
        >
          <span className="glyph" aria-hidden="true">O</span>
          <span className="label">믿어요</span>
        </button>
        <button
          type="button"
          className={`practice-answer doubt${answer === 'suspicious' ? ' selected' : ''}`}
          onClick={() => onPick('suspicious')}
          aria-pressed={answer === 'suspicious'}
        >
          <span className="glyph" aria-hidden="true">X</span>
          <span className="label">의심해요</span>
        </button>
      </div>

      {feedback && (
        <div className={`practice-feedback ${answer === 'suspicious' ? 'good' : 'retry'}`} role="status" aria-live="polite">
          <b>{feedback.title}</b>
          {feedback.detail}
        </div>
      )}

      <button type="button" className="practice-next-btn" disabled={!picked} onClick={onNext}>
        {isLast ? '학습 마치기' : '다음 단계'}
        <img src={icNext} width="18" height="18" alt="" aria-hidden="true" style={picked ? { filter: 'brightness(0) invert(1)' } : undefined} />
      </button>
    </>
  )
}

export default function Training({ onHome }) {
  // mode: 연습 시작 안내 → 4단계 O/X 실습 → (실습을 마친 뒤) 주간 리포트
  const [mode, setMode] = useState('intro')
  const [stepIndex, setStepIndex] = useState(0)
  const [answers, setAnswers] = useState({})
  const [hintOpen, setHintOpen] = useState(true)

  const [report, setReport] = useState(null)
  const [reportError, setReportError] = useState('')

  const [toast, setToast] = useState('')
  const toastTimer = useRef(null)
  useEffect(() => () => window.clearTimeout(toastTimer.current), [])

  useEffect(() => {
    if (mode !== 'report') return
    ;(async () => {
      try {
        setReport(await getWeeklyReport())
      } catch (e) {
        setReportError(e.message)
        logError(SCREEN, e.code || 'weekly_report_fetch_failed')
      }
    })()
  }, [mode])

  function showToast(msg) {
    setToast(msg)
    window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(''), 2200)
  }

  function handleNavTap(key) {
    logClick(SCREEN, `nav_${key}`)
    if (key === 'home') { onHome(); return }
    if (key === 'learn') { window.scrollTo({ top: 0, behavior: 'smooth' }); return }
    // ★ '바로 확인'은 홈의 사진 모달을 여는 동작이라 이 화면에는 그 모달이
    //   없다 - 가장 가까운 정답은 홈으로 보내는 것이다(성장·내 정보처럼
    //   "준비 중"이라고 하면, 실제로는 되는 기능을 안 된다고 말하는 셈이라 안 된다).
    if (key === 'fab') { onHome(); return }
    showToast('준비 중입니다')
  }

  function startPractice() {
    logClick(SCREEN, 'practice_start')
    setStepIndex(0)
    setAnswers({})
    setHintOpen(true)
    setMode('practice')
  }

  function pickAnswer(choice) {
    logClick(SCREEN, `practice_answer_${choice}`)
    setAnswers((prev) => ({ ...prev, [stepIndex]: choice }))
  }

  function goPrevStep() {
    logClick(SCREEN, 'practice_prev')
    if (stepIndex === 0) { setMode('intro'); return }
    setStepIndex((i) => i - 1)
    setHintOpen(true)
  }

  function goNextStep() {
    const isLast = stepIndex === PRACTICE_STEPS.length - 1
    logClick(SCREEN, isLast ? 'practice_finish' : 'practice_next')
    if (isLast) { setMode('report'); return }
    setStepIndex((i) => i + 1)
    setHintOpen(true)
  }

  function quitPractice() {
    logClick(SCREEN, 'practice_quit')
    onHome()
  }

  if (mode === 'intro') {
    return <PracticeIntro onStart={startPractice} onNavTap={handleNavTap} toast={toast} />
  }

  if (mode === 'practice') {
    return (
      <PracticeStep
        index={stepIndex}
        total={PRACTICE_STEPS.length}
        step={PRACTICE_STEPS[stepIndex]}
        answer={answers[stepIndex]}
        hintOpen={hintOpen}
        onToggleHint={() => { logClick(SCREEN, 'practice_hint_toggle'); setHintOpen((v) => !v) }}
        onPick={pickAnswer}
        onPrev={goPrevStep}
        onNext={goNextStep}
        onQuit={quitPractice}
      />
    )
  }

  // ---- mode === 'report' : 실습을 마친 뒤 주간 리포트(기존 그대로) ----
  if (reportError) {
    return (
      <>
        <div className="error-box">{reportError}</div>
        <button className="btn" onClick={() => { logClick(SCREEN, 'to_home'); onHome() }}>처음으로</button>
      </>
    )
  }
  if (!report) {
    return <div className="loading"><div className="spinner" /><p className="lead">이번 주 기록을 가져오고 있어요</p></div>
  }

  const ERROR_TYPE_LABEL = {
    title_dependent: '제목만 보고 판단',
    authority_impersonation: '기관 이름 앞세우기',
    number_condition: '숫자·조건 빠짐',
    overgeneralization: '한 가지를 전부로',
  }
  const maxTrend = Math.max(1, ...Object.values(report.error_type_trend || { a: 1 }))

  return (
    <>
      <h2>오늘의 5분 연습을 마쳤어요</h2>
      <div className="card">
        <h3>이번 주 기록 ({report.week})</h3>
        <div className="stat-row">
          <div className="stat"><span className="num">{report.checks_count}</span><span className="cap">직접 확인</span></div>
          <div className="stat"><span className="num">{report.training_completed}</span><span className="cap">연습 완료</span></div>
          <div className="stat"><span className="num">{report.streak_days}</span><span className="cap">연속 일수</span></div>
        </div>

        {Object.entries(report.error_type_trend || {}).map(([k, v]) => (
          <div className="trend-row" key={k}>
            <span style={{ width: 150 }}>{ERROR_TYPE_LABEL[k] || k}</span>
            <span className="trend-bar" style={{ width: `${(v / maxTrend) * 100}px` }} />
            <span>{v}건</span>
          </div>
        ))}

        <p className="lead" style={{ marginTop: 16 }}>{report.message}</p>
      </div>

      <button className="btn secondary" onClick={() => { logClick(SCREEN, 'to_home'); onHome() }}>처음으로 돌아가기</button>
    </>
  )
}
