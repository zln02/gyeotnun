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
 *   학습 완료(카테고리별 정답 요약) → 마무리 화면을 먼저 보여주고, 그 화면의
 *   "리포트 보러가기"를 눌러야 주간 리포트(getWeeklyReport)로 간다.
 *   (Figma 의 '리워드(G적립)' 화면이었으나 2026-08-15 에 포인트 표시를 걷어냈다 -
 *    적립되는 곳이 없다. 아래 RewardScreen 주석 참고.) 카테고리별 "N건" 은 이번 실습 회차의 정답 여부만 반영한다 - 여러
 *   회차를 누적한 카테고리별 이력 API가 없어서다(TODO: 생기면 교체).
 *   정답/오답 시 O·X 버튼 자체가 초록 체크·빨강 경고로 바뀌는 것도 이번에
 *   새로 반영한 디자인이다(전엔 버튼 아래 피드백 문구로만 표시했다).
 */
import { useEffect, useRef, useState } from 'react'
import { getWeeklyReport } from '../api.js'
import { logClick, logError } from '../events.js'
import BottomNav from '../components/BottomNav.jsx'

import waitMascot from '../assets/checking/mascot.png'
import icBack from '../assets/training/ic_back.svg'
import icHomeQuit from '../assets/training/ic_home_quit.svg'
import icHint from '../assets/training/ic_hint.svg'
import icNext from '../assets/training/ic_next.svg'
import icAnsIdleBelieve from '../assets/training/ic_ans_idle_believe.svg'
import icAnsIdleDoubt from '../assets/training/ic_ans_idle_doubt.svg'
import icAnsCorrect from '../assets/training/ic_ans_correct.svg'
import icAnsWrong from '../assets/training/ic_ans_wrong.svg'
import icFeedbackCorrect from '../assets/training/ic_feedback_correct.svg'
import icFeedbackWrong from '../assets/training/ic_feedback_wrong.svg'
import completeHero from '../assets/training/complete_hero.png'
import completeIcTitle from '../assets/training/complete_ic_title.png'
import completeIcOrg from '../assets/training/complete_ic_org.png'
import completeIcNumber from '../assets/training/complete_ic_number.png'
import completeIcAll from '../assets/training/complete_ic_all.png'
import icRewardReport from '../assets/training/ic_reward_report.svg'
import icRewardHome from '../assets/training/ic_reward_home.svg'

const SCREEN = 'S5'

// ★★ 2026-08-15: REWARD_POINTS(120) 를 지웠다 ★★
//   포인트를 세는 곳이 서버에도 이 기기에도 없다. 적립되지 않는 보상을
//   "적립 완료"라고 알리는 건 지어낸 성과다. 이 화면이 실제로 알릴 수 있는
//   사실은 하나뿐이다 - 오늘 훈련을 끝냈다는 것. 그것만 적는다.
//   포인트 지급 API 가 생기면 그때 실제 값으로 되살린다.

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
  { label: '제목 판단하기', icon: completeIcTitle },
  { label: '기관명 확인하기', icon: completeIcOrg },
  { label: '숫자·조건 확인하기', icon: completeIcNumber },
  { label: '전체 유형 확인하기', icon: completeIcAll },
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

function AnswerButton({ choice, step, answer, onPick }) {
  const isBelieve = choice === 'trust'
  const state = answer == null ? 'idle' : answer === choice ? (choice === step.correct ? 'correct' : 'wrong') : 'idle'
  const icon = state === 'correct' ? icAnsCorrect : state === 'wrong' ? icAnsWrong : (isBelieve ? icAnsIdleBelieve : icAnsIdleDoubt)

  return (
    <button
      type="button"
      className={`practice-answer ${isBelieve ? 'believe' : 'doubt'}${state !== 'idle' ? ` ${state}` : ''}`}
      onClick={() => onPick(choice)}
      aria-pressed={answer === choice}
    >
      <span className="practice-answer-icon" aria-hidden="true">
        <img src={icon} width="23" height="23" alt="" />
      </span>
      <span className="label">{isBelieve ? '믿어요' : '의심해요'}</span>
    </button>
  )
}

function PracticeStep({ index, total, step, answer, hintOpen, onToggleHint, onPick, onPrev, onNext, onQuit }) {
  const isLast = index === total - 1
  const picked = answer != null
  const feedback = picked ? step.feedback[answer] : null
  const isCorrect = answer === step.correct

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
            <span className={`practice-progress-tag${i === index ? ' visible' : ''}`}>진행 중</span>
            <span className="practice-progress-bar" />
            <span className="practice-progress-label">{i + 1}단계</span>
          </div>
        ))}
      </div>

      {/* ★ key={index}로 매 단계 다시 마운트시켜 CSS 등장 애니메이션(practiceFadeIn)이
          단계가 바뀔 때마다 새로 걸리게 한다 - 이전엔 React 가 내용만 갈아끼워서
          클릭한 순간 다음 문항이 뚝 튀어나오듯 바뀌었다("매끄럽지 않다"는 지적). */}
      <div className="practice-step-body" key={index}>
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
          <AnswerButton choice="trust" step={step} answer={answer} onPick={onPick} />
          <AnswerButton choice="suspicious" step={step} answer={answer} onPick={onPick} />
        </div>

        {feedback && (
          <div className={`practice-feedback ${isCorrect ? 'correct' : 'wrong'}`} role="status" aria-live="polite">
            <img className="practice-feedback-icon" src={isCorrect ? icFeedbackCorrect : icFeedbackWrong} width="20" height="20" alt="" aria-hidden="true" />
            <div>
              <b>{feedback.title}</b>
              <p className="detail">{feedback.detail}</p>
            </div>
          </div>
        )}

        <button type="button" className="practice-next-btn" disabled={!picked} onClick={onNext}>
          {isLast ? '학습 마치기' : '다음 단계'}
          <img src={icNext} width="18" height="18" alt="" aria-hidden="true" style={picked ? { filter: 'brightness(0) invert(1)' } : undefined} />
        </button>
      </div>
    </>
  )
}

function CompleteScreen({ firstAnswers, report, onConfirm }) {
  // ★ 2026-08-09: 기록은 **첫 시도** 기준이다. 아래 firstAnswers 주석 참고.
  //   고쳐서 맞힌 것을 처음부터 맞힌 것으로 적으면 훈련 진단이 무의미해진다.
  const total = PRACTICE_STEPS.length
  const correctCount = PRACTICE_STEPS.filter((s, i) => firstAnswers[i] === s.correct).length
  const fixedCount = total - correctCount

  return (
    <div className="practice-complete">
      <p style={{ textAlign: 'center', margin: '0 0 14px' }}>
        <span className="practice-complete-badge">학습 완료</span>
      </p>
      <h2 className="practice-complete-title">학습을 잘 마쳤어요!</h2>
      <p className="practice-complete-sub">
        {total}문제 중 {correctCount}개를 처음에 맞히셨어요.
        {fixedCount > 0 && ' 나머지는 다시 보면서 바로잡으셨어요.'}
      </p>

      <img className="practice-complete-hero" src={completeHero} alt="" aria-hidden="true" />

      <div className="practice-complete-stats">
        <div className="practice-complete-stat">
          <b>{correctCount}/{total}</b>
          <span>처음에 맞힘</span>
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
              <p className="practice-complete-card-count">{firstAnswers[i] === PRACTICE_STEPS[i].correct ? 1 : 0}<em>건</em></p>
              <img src={card.icon} width="44" height="44" alt="" aria-hidden="true" />
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
      {/* 동전 그림도 함께 뺐다 - 포인트가 없는데 화폐 그림을 두면 글자를 고쳐도
          "뭔가 받았다"로 읽힌다. 그림 하나가 문장 하나만큼 말을 한다. */}
      <span className="practice-reward-badge">훈련 완료</span>
      <div className="practice-reward-body">
        <p className="practice-reward-label">오늘의 훈련</p>
        <h2 className="practice-reward-title">오늘 훈련을 마쳤어요</h2>
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
  // answers: 지금 화면에 표시되는 선택(바꾸면 덮어쓴다). 피드백 표시용.
  const [answers, setAnswers] = useState({})
  // ★ firstAnswers: 각 단계에서 **처음 고른** 답. 한 번 정해지면 덮어쓰지 않는다.
  //   학습 완료 화면의 기록은 반드시 이 값으로 센다.
  //   왜 나누는가: 답을 바꿔 볼 수 있게 두는 것은 학습에 필요하지만(틀린 이유를
  //   읽고 다시 고르는 게 이 연습의 핵심이다), 그렇게 고친 결과를 "처음부터
  //   맞혔다"로 기록하면 훈련 진단이 거짓이 된다. 2026-08 알파테스트 지적 사항.
  //   포인트는 종전대로 완주 기준으로 그대로 지급한다 - 기록만 사실대로 적는다.
  const [firstAnswers, setFirstAnswers] = useState({})
  const [hintOpen, setHintOpen] = useState(true)

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
    setFirstAnswers({})
    setHintOpen(true)
    setMode('practice')
  }

  function pickAnswer(choice) {
    const isRetry = firstAnswers[stepIndex] != null
    logClick(SCREEN, `practice_answer_${choice}${isRetry ? '_retry' : ''}`)
    setAnswers((prev) => ({ ...prev, [stepIndex]: choice }))
    // 첫 선택만 기록한다. 이미 값이 있으면 그대로 둔다(다시 골라도 덮이지 않는다).
    setFirstAnswers((prev) => (prev[stepIndex] != null ? prev : { ...prev, [stepIndex]: choice }))
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
    if (isLast) { setMode('complete'); return }
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

  if (mode === 'complete') {
    return (
      <CompleteScreen
        firstAnswers={firstAnswers}
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
    return (
      <div className="wait" role="status" aria-live="polite">
        <div className="wait-icon-wrap">
          <span className="wait-glow" aria-hidden="true" />
          <img src={waitMascot} width="80" height="80" alt="" aria-hidden="true" className="wait-icon" />
        </div>
        <p className="wait-text">이번 주 기록을 가져오고 있어요</p>
      </div>
    )
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
