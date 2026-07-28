/**
 * Report - 주간 리포트
 * 담당: 조희진 (백엔드 계약: 장지석)
 *
 * "몇 번 틀렸다"가 아니라 "몇 번 확인했다"를 강조하는 화면.
 *
 * TODO(조희진)
 *   [ ] 오판유형 분포 막대 그래프 (라이브러리 없이 CSS로)
 *   [ ] 가족 공유 버튼 (카톡 공유 / 이미지 저장)
 *   [ ] 지난주 대비 변화 표시
 */
import { useEffect, useState } from 'react'
import { getWeeklyReport } from '../api.js'

export default function Report() {
  const [report, setReport] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const r = await getWeeklyReport()
        if (alive) setReport(r)
      } catch (err) {
        if (alive) setError('리포트를 불러오지 못했습니다.')
        console.error(err)
      }
    })()
    return () => { alive = false }
  }, [])

  if (error) return <div className="card notice">{error}</div>
  if (!report) return <p className="muted">리포트를 준비하고 있습니다…</p>

  const max = Math.max(1, ...report.error_type_counts.map((e) => e.count))

  return (
    <div>
      <h2>주간 리포트</h2>
      <p className="muted">{report.week_start} ~ {report.week_end}</p>

      <div className="card question">
        <p style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>
          이번 주 {report.checks_count}번 확인하셨습니다
        </p>
        <p className="muted" style={{ marginBottom: 0 }}>
          훈련 {report.trainings_completed}회 완료
        </p>
      </div>

      <div className="card">
        <p style={{ marginTop: 0, fontWeight: 700 }}>살펴본 지점</p>
        {report.error_type_counts.map((e) => (
          <div key={e.error_type} style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 17 }}>{e.label} · {e.count}회</div>
            <div style={{ background: 'var(--bg)', borderRadius: 6, height: 14 }}>
              <div
                style={{
                  width: `${(e.count / max) * 100}%`,
                  background: 'var(--green)',
                  height: '100%',
                  borderRadius: 6,
                }}
              />
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <p style={{ margin: 0 }}>{report.summary}</p>
      </div>
    </div>
  )
}
