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

export default function Question({ checkId, evidence, onDone }) {
  const [turn, setTurn] = useState(1)
  const [data, setData] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  // ★ 실제 API 는 응답이 겹칠 만큼 느릴 수 있다(React.StrictMode 의 개발 중 이펙트
  //   이중 실행도 같은 상황을 만든다). 가장 최근 요청의 응답만 반영하고,
  //   먼저 보낸 요청이 나중에 도착해도 화면을 덮어쓰지 않게 막는다.
  const requestIdRef = useRef(0)

  async function load(nextTurn, reply) {
    const myRequestId = ++requestIdRef.current
    setLoading(true)
    setError('')
    setSelected(null)
    try {
      const result = await getQuestion(checkId, nextTurn, reply)
      if (myRequestId !== requestIdRef.current) return   // 더 최신 요청이 이미 나갔다 - 이 응답은 버린다
      setData(result)
    } catch (e) {
      if (myRequestId !== requestIdRef.current) return
      setError(e.message)
    } finally {
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

  if (loading) return <div className="loading"><div className="spinner" /><p className="lead">질문을 준비하고 있어요</p></div>
  if (error) return <div className="error-box">{error}</div>

  return (
    <>
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
            <a key={r.url} className="source-link" href={r.url} target="_blank" rel="noreferrer">
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
            onClick={() => setSelected(o.id)}
          >
            <span aria-hidden="true">{selected === o.id ? '✅' : '⬜'}</span> {o.label}
          </button>
        ))}
      </div>

      {/* ★ 화살표만 있는 버튼 금지 — '다음' 글자를 반드시 병기 */}
      <button className="btn" disabled={!selected} onClick={next}>
        {data.is_final ? '다 확인했어요' : '다음 →'}
      </button>
    </>
  )
}
