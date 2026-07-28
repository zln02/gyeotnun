/**
 * S5 - 오늘의 5분 훈련 + 주간 리포트
 * 담당: 조희진 (화면) / 장지석 (카드 내용)
 *
 * ★ 리포트에 '몇 번 속았는지'를 쓰지 않는다. '몇 번 확인했는지'를 쓴다.
 *   가족과 공유되는 화면이므로, 어르신이 부끄러워지는 순간 서비스는 삭제된다.
 */
import { useEffect, useState } from 'react'
import { getTodayCard, getWeeklyReport } from '../api.js'

const ERROR_TYPE_LABEL = {
  title_dependent: '제목만 보고 판단',
  authority_impersonation: '기관 이름 앞세우기',
  number_condition: '숫자·조건 빠짐',
  overgeneralization: '한 가지를 전부로',
}

export default function Training({ onHome }) {
  const [card, setCard] = useState(null)
  const [report, setReport] = useState(null)
  const [picked, setPicked] = useState(null)
  const [showAnswer, setShowAnswer] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    ;(async () => {
      try {
        const [c, r] = await Promise.all([getTodayCard(), getWeeklyReport()])
        setCard(c)
        setReport(r)
      } catch (e) {
        setError(e.message)
      }
    })()
  }, [])

  if (error) return (<><div className="error-box">{error}</div><button className="btn" onClick={onHome}>처음으로</button></>)
  if (!card) return <div className="loading"><div className="spinner" /><p className="lead">연습 문제를 가져오고 있어요</p></div>

  const correct = picked === card.answer
  const maxTrend = Math.max(1, ...Object.values(report?.error_type_trend || { a: 1 }))

  return (
    <>
      <h2>오늘의 5분 연습</h2>
      <span className="badge">{ERROR_TYPE_LABEL[card.target_error_type]}</span>

      <div className="card" style={{ marginTop: 14 }}>
        <p className="lead" style={{ whiteSpace: 'pre-line' }}>{card.content}</p>
      </div>

      {card.items.map((it) => (
        <button
          key={it.id}
          className={`btn choice ${picked === it.id ? 'selected' : ''}`}
          disabled={showAnswer}
          onClick={() => setPicked(it.id)}
        >
          <span aria-hidden="true">{picked === it.id ? '✅' : '⬜'}</span> {it.label}
        </button>
      ))}

      {!showAnswer ? (
        <button className="btn" disabled={!picked} onClick={() => setShowAnswer(true)}>
          답 확인하기
        </button>
      ) : (
        <div className="card">
          <h3>{correct ? '잘 찾으셨습니다' : '거의 다 오셨어요'}</h3>
          <p>{card.explanation}</p>
        </div>
      )}

      {report && (
        <div className="card" style={{ marginTop: 26 }}>
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
      )}

      <button className="btn secondary" onClick={onHome}>처음으로 돌아가기</button>
    </>
  )
}
