/**
 * S5 - 오늘의 5분 훈련 + 학습 완료 + 리워드 + 주간 리포트
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
 *
 * ★ 2026-08 2차 이식(node 196:434 정답/217:1521 오답/196:1406 학습 완료/
 *   272:22 리워드): 4단계를 다 마치면 기존처럼 바로 주간 리포트로 보내지 않고
 *   학습 완료(카테고리별 정답 요약) → 리워드(G적립) 를 먼저 보여주고,
 *   리워드 화면의 "리포트 보러가기"를 눌러야 주간 리포트(getWeeklyReport)로
 *   간다. 카테고리별 "N건" 은 이번 실습 회차의 정답 여부만 반영한다 - 여러
 *   회차를 누적한 카테고리별 이력 API가 없어서다(TODO: 생기면 교체).
 *   정답/오답 시 O·X 버튼 자체가 초록 체크·빨강 경고로 바뀌는 것도 이번에
 *   새로 반영한 디자인이다(전엔 버튼 아래 피드백 문구로만 표시했다).
 */
import { useEffect, useRef, useState } from 'react'
import { getWeeklyReport } from '../api.js'
import { logClick, logError } from '../events.js'
import BottomNav from '../components/BottomNav.jsx'

import icBack from '../assets/training/ic_back.svg'
import icHint from '../assets/training/ic_hint.svg'
import completionPeople from '../assets/training/completion-people.png'
import completionTitleBook from '../assets/training/completion-title-book.png'
import completionOrganizationBuilding from '../assets/training/completion-organization-building.png'
import completionNumberBlocks from '../assets/training/completion-number-blocks.png'
import completionAllPuzzle from '../assets/training/completion-all-puzzle.png'
import rewardCoin from '../assets/training/reward-coin.svg'
import icRewardReport from '../assets/training/ic_reward_report.svg'
import icRewardHome from '../assets/training/ic_reward_home.svg'
import practiceIllustration from '../assets/training/problem-illustration.png'

const SCREEN = 'S5'

// 오늘의 훈련 보상 포인트. 홈 화면 배너("오늘의 훈련 G 120")와 같은 값으로
// 맞춘다 - 실제 포인트 지급 API가 없어 고정값이다(TODO: 생기면 교체).
const REWARD_POINTS = 120

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
    { icon: 'message', label: '문자' },
    { icon: 'time', label: '약 5분' },
    { icon: 'steps', label: '4단계' },
  ],
}

// correct: 이 단계에서 '정답'으로 치는 선택('trust' 믿어요 / 'suspicious' 의심해요).
// 4단계 모두 피싱 사례라 전부 'suspicious' 지만, 향후 "진짜 안전한 문자" 사례가
// 섞일 수 있어 단계별 필드로 둔다.
const PRACTICE_STEPS = [
  {
    categoryLabel: '제목 판단하기',
    focusTip: '제목만 보고 넘겨짚지 않아요',
    highlight: { line: 'title' },
    hint: '제목에 기관 이름이 있어도 진짜라는 뜻은 아니에요.',
    question: '제목만 보고 이 문자를 믿어도 될까요?',
    correct: 'suspicious',
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
    correct: 'suspicious',
    feedback: {
      suspicious: { title: '맞아요. 의심해야 해요.', detail: '낯선 주소로 접속하라고 재촉하는 문자는 조심해요.' },
      trust: { title: '다시 한번 살펴봐요.', detail: '기관 이름은 누구나 문자에 적을 수 있어요.' },
    },
  },
  {
    categoryLabel: '숫자·조건 검토하기',
    focusTip: '서두르게 하는 말은 조심해요',
    highlight: { line: 'body' },
    hint: "'지금 안 하면 취소' 같은 급한 말은 피싱 신호예요.",
    question: '이 문자를 믿어도 될까요?',
    correct: 'suspicious',
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
    correct: 'suspicious',
    feedback: {
      suspicious: { title: '정확해요', detail: '공식 사이트는 이런 낯선 주소를 쓰지 않아요.' },
      trust: { title: '절대 누르지 마세요', detail: 'welfare-giveaway.net 은 정부 공식 도메인이 아니에요.' },
    },
  },
]

// 학습 완료 화면의 카테고리 카드 - PRACTICE_STEPS 와 1:1 순서로 대응한다.
// 카드 문구는 학습 완료 화면(node 196:1406) 원문을 그대로 썼다 - 진행 중
// 화면의 categoryLabel 과 표현이 살짝 다른 건(예: '기관 이름 확인하기' vs
// '기관명 확인하기') Figma 원본 자체가 화면마다 그렇게 되어 있어서다.
const SUMMARY_CARDS = [
  { label: '제목 판단하기', icon: completionTitleBook, iconClass: 'is-title' },
  { label: '기관명 확인하기', icon: completionOrganizationBuilding, iconClass: 'is-organization' },
  { label: '숫자·조건 확인하기', icon: completionNumberBlocks, iconClass: 'is-number' },
  { label: '전체 유형 확인하기', icon: completionAllPuzzle, iconClass: 'is-all' },
]

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
              <span className={`practice-chip__icon practice-chip__icon--${c.icon}`} aria-hidden="true" />
              {c.label}
            </span>
          ))}
        </div>

        <div className="practice-howcard">
          <p className="practice-how-eyebrow">이렇게 배워요</p>
          <ul className="practice-how-list">
            {PRACTICE_STEPS.map((s) => (
              <li key={s.categoryLabel}>
                {s.categoryLabel}
              </li>
            ))}
          </ul>
          <button type="button" className="practice-start-btn" onClick={onStart}>
            <span>학습 시작하기</span>
            <span className="practice-start-reward"><b>G</b> {REWARD_POINTS}</span>
          </button>
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

function TrainingProgress({ index, total }) {
  return (
    <div className="training-practice__progress" aria-label={`${total}단계 중 ${index + 1}단계 진행 중`}>
      {Array.from({ length: total }, (_, stepIndex) => {
        const current = stepIndex === index
        const complete = stepIndex < index

        return (
          <div className="training-practice__progress-item" key={stepIndex}>
            {current ? <span className="training-practice__progress-badge">진행 중</span> : <span className="training-practice__progress-space" aria-hidden="true" />}
            <span className={`training-practice__progress-bar${current || complete ? ' is-complete' : ''}`} />
            <span className={current ? 'is-current' : complete ? 'is-complete' : ''}>{stepIndex + 1}단계</span>
          </div>
        )
      })}
    </div>
  )
}

function TrainingMessage({ highlight, hintOpen, answer }) {
  const isRiskShown = answer === 'trust'
  const isHighlighted = hintOpen || isRiskShown
  const highlightClass = isRiskShown ? 'is-risk' : 'is-hint'
  const emphasisClass = (type) => isHighlighted && (
    highlight.line === type || (type === 'sender' && highlight.line === 'title' && highlight.part === 'sender')
  ) ? highlightClass : ''

  return (
    <p>
      <span className={emphasisClass('sender')}>{MESSAGE.senderTag}</span>{' '}
      <span className={emphasisClass('title')}>{MESSAGE.titleRest.trim()}</span><br />
      <span className={emphasisClass('body')}>{MESSAGE.body}</span><br />
      <span className={emphasisClass('link')}>{MESSAGE.link}</span>
    </p>
  )
}

function PracticeStep({ index, total, step, answer, hintOpen, onToggleHint, onPick, onPrev, onNext, onQuit }) {
  const isLast = index === total - 1
  const picked = answer != null
  const feedback = picked ? step.feedback[answer] : null
  const isCorrect = answer === step.correct

  return (
    <section className="training-practice" aria-labelledby="training-practice-title" key={index}>
      <div className="training-practice__content">
        <header className="training-practice__header">
          <button type="button" onClick={onPrev} aria-label="이전 단계"><img src={icBack} width="20" height="20" alt="" aria-hidden="true" /></button>
          <p>오늘의 5분 연습</p>
          <button type="button" onClick={onQuit}>학습 그만하기</button>
        </header>

        <TrainingProgress index={index} total={total} />

        <section className="training-practice__topic">
          <span className="training-practice__illustration" aria-hidden="true"><img src={practiceIllustration} alt="" /></span>
          <div>
            <h1 id="training-practice-title">{step.categoryLabel}</h1>
            <p>{step.focusTip}</p>
          </div>
        </section>

        <article className="training-practice__message">
          <div className="training-practice__message-meta"><span>받은 문자</span><b>SMS</b></div>
          <TrainingMessage highlight={step.highlight} hintOpen={hintOpen} answer={answer} />
          <button type="button" className={hintOpen ? 'is-open' : ''} onClick={onToggleHint}>
            <img src={icHint} width="18" height="18" alt="" aria-hidden="true" />
            {hintOpen ? '힌트 닫기' : '살짝 알려주세요'}
          </button>
          {hintOpen && <div className="training-practice__hint">{step.hint}</div>}
        </article>

        <section className="training-practice__question" aria-labelledby="training-question-title">
          <h2 id="training-question-title">{step.question}</h2>
          <div className="training-practice__answers">
            <button className={answer === 'trust' ? 'is-wrong' : ''} type="button" aria-pressed={answer === 'trust'} onClick={() => onPick('trust')}><span aria-hidden="true">○</span>믿어요</button>
            <button className={answer === 'suspicious' ? 'is-correct' : ''} type="button" aria-pressed={answer === 'suspicious'} onClick={() => onPick('suspicious')}><span aria-hidden="true">×</span>의심해요</button>
          </div>
        </section>

        {feedback && (
          <section className={`training-practice__feedback ${isCorrect ? 'is-correct' : 'is-wrong'}`} role="status" aria-live="polite">
            <strong>{feedback.title}</strong>
            <p>{feedback.detail}</p>
          </section>
        )}

        <button className="training-practice__next" type="button" disabled={!picked} onClick={onNext}>
          {isLast ? '학습 마치기' : '다음 단계'} <span aria-hidden="true">›</span>
        </button>
      </div>
    </section>
  )
}

function CompleteScreen({ answers, report, onConfirm }) {
  const correctCount = PRACTICE_STEPS.filter((s, i) => answers[i] === s.correct).length

  return (
    <div className="practice-complete">
      <p style={{ textAlign: 'center', margin: '0 0 14px' }}>
        <span className="practice-complete-badge">학습 완료</span>
      </p>
      <h2 className="practice-complete-title">오늘도 수고하셨어요!</h2>
      <p className="practice-complete-sub">내가 고른 답을 한눈에 다시 살펴보세요.</p>

      <img className="practice-complete-hero" src={completionPeople} alt="" aria-hidden="true" />

      <div className="practice-complete-stats">
        <div className="practice-complete-stat">
          <b>{correctCount}/{PRACTICE_STEPS.length}</b>
          <span>오늘 정답</span>
        </div>
        <div className="practice-complete-stat">
          <b>{report ? report.training_completed : '-'}</b>
          <span>연습 완료</span>
        </div>
        <div className="practice-complete-stat">
          <b>{report ? report.streak_days : '-'}</b>
          <span>연속 일수</span>
        </div>
      </div>

      <div className="practice-complete-grid">
        {SUMMARY_CARDS.map((card, i) => (
          <div className="practice-complete-card" key={card.label}>
            <p className="practice-complete-card-label">{card.label}</p>
            <div className="practice-complete-card-row">
              <p className="practice-complete-card-count">{answers[i] === PRACTICE_STEPS[i].correct ? 1 : 0}<em>건</em></p>
              <img className={card.iconClass} src={card.icon} alt="" aria-hidden="true" />
            </div>
          </div>
        ))}
      </div>

      <button type="button" className="practice-complete-cta" onClick={onConfirm}>확인 했어요</button>
    </div>
  )
}

function RewardScreen({ onReport, onHome }) {
  return (
    <div className="practice-reward">
      <span className="practice-reward-badge">리워드 적립</span>
      <img className="practice-reward-coin" src={rewardCoin} alt="" aria-hidden="true" />
      <div className="practice-reward-body">
        <p className="practice-reward-label">오늘의 훈련 보상</p>
        <h2 className="practice-reward-title">G {REWARD_POINTS} 적립 완료</h2>
        <p className="practice-reward-sub">내일도 5분 연습으로 이어가 볼까요?</p>
      </div>
      <div className="practice-reward-actions">
        <button type="button" className="practice-reward-btn primary" onClick={onReport}>
          <img src={icRewardReport} width="20" height="11" alt="" aria-hidden="true" />
          리포트 보러가기
        </button>
        <button type="button" className="practice-reward-btn" onClick={onHome}>
          <img src={icRewardHome} width="20" height="20" alt="" aria-hidden="true" />
          홈으로 돌아가기
        </button>
      </div>
    </div>
  )
}

export default function Training({ onHome }) {
  // mode: 연습 시작 안내 → 4단계 O/X 실습 → 학습 완료 → 리워드 → (선택)주간 리포트
  const [mode, setMode] = useState('intro')
  const [stepIndex, setStepIndex] = useState(0)
  const [answers, setAnswers] = useState({})
  const [hintOpen, setHintOpen] = useState(false)

  const [report, setReport] = useState(null)
  const [reportError, setReportError] = useState('')

  const [toast, setToast] = useState('')
  const toastTimer = useRef(null)
  useEffect(() => () => window.clearTimeout(toastTimer.current), [])

  // 학습 완료 화면의 '연습 완료/연속 일수' 통계에 실제 API 값을 쓰려고 이
  // 시점에 미리 불러온다. 리워드 화면을 거쳐 '리포트 보러가기'로 다시 갈 때
  // 재요청하지 않도록 이미 있으면 건너뛴다.
  useEffect(() => {
    if (mode !== 'complete' && mode !== 'report') return
    if (report || reportError) return
    ;(async () => {
      try {
        setReport(await getWeeklyReport())
      } catch (e) {
        setReportError(e.message)
        logError(SCREEN, e.code || 'weekly_report_fetch_failed')
      }
    })()
  }, [mode, report, reportError])

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
    setHintOpen(false)
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
    setHintOpen(false)
  }

  function goNextStep() {
    const isLast = stepIndex === PRACTICE_STEPS.length - 1
    logClick(SCREEN, isLast ? 'practice_finish' : 'practice_next')
    if (isLast) { setMode('complete'); return }
    setStepIndex((i) => i + 1)
    setHintOpen(false)
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

  if (mode === 'complete') {
    return (
      <CompleteScreen
        answers={answers}
        report={report}
        onConfirm={() => { logClick(SCREEN, 'complete_confirm'); setMode('reward') }}
      />
    )
  }

  if (mode === 'reward') {
    return (
      <RewardScreen
        onReport={() => { logClick(SCREEN, 'reward_to_report'); setMode('report') }}
        onHome={() => { logClick(SCREEN, 'reward_to_home'); onHome() }}
      />
    )
  }

  // ---- mode === 'report' : 리워드 화면의 '리포트 보러가기'를 눌렀을 때만 오는
  //      주간 리포트(기존 그대로) ----
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
