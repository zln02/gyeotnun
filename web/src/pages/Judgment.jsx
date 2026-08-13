/**
 * S2.5 - 판단 (확인 결과 요약)
 * 담당: 조희진
 * Figma node 340:459 "판단"
 *
 * ★ 왜 화면이 하나 늘었나
 *   이전에는 이 내용이 S3 질문 화면 맨 위에 배지(VerdictBadge)로 얹혀 있었다.
 *   결과와 첫 질문이 한 화면에 같이 떠서, 결과를 읽기도 전에 답하려다
 *   혼란스러워하는 게 반복 관찰됐다. Figma 3차 개편에서 독립 화면이 됐다.
 *
 * ★ 상태는 4개다 (verdict.js 참고)
 *   Figma 원본에는 빨간 경고 한 벌만 그려져 있는데, 그대로 두면 공식 자료를
 *   잘 찾은 정상 안내문에도 빨간 경고가 나간다. 레이아웃·구성은 그대로 두고
 *   색·제목·'사실 한 줄'만 상태별로 바꾼다.
 *
 * ★★ Figma 에 있지만 넣지 않은 것 ★★
 *   하단 "오늘 1,248명이 함께 확인했어요" - 그런 집계를 주는 API 가 없다.
 *   숫자를 지어내면 곁눈이 막으려는 짓을 곁눈이 하는 셈이 된다.
 *   (events 테이블에 세션 기록은 있으니, 집계 엔드포인트가 생기면 켤 수 있다.)
 */
import { judgmentState } from '../verdict.js'
import { logClick, logEvidenceLinkClick } from '../events.js'
import warnHero from '../assets/verify/warn_hero.png'
import holdHero from '../assets/verify/warn_hero_orange.png'
import okHero from '../assets/verify/ic_record_done.png'
import arrowRight from '../assets/verify/ic_arrow_right_white.svg'

const SCREEN = 'S3'   // 계측 코드는 기존 S3(확인 흐름)에 묶는다 - 흐름상 같은 단계다

// ★ act(행동 프레임)는 경고 그림을 쓰지 않는다 (2026-08-13).
//   위험행동만으로 올라간 글에 빨간 경고 그림을 띄우면, 문구를 아무리 고쳐도
//   그림이 "이 글은 수상하다"고 말한다 - 정상 문자를 의심으로 표시하지 않는다는
//   절대 조건과 충돌한다. 주황(hold) 그림을 함께 쓴다.
const HERO = { danger: warnHero, warn: warnHero, act: holdHero, hold: holdHero, ok: okHero }

export default function Judgment({ evidence, checkData, onStart }) {
  const s = judgmentState(evidence, checkData)

  return (
    <div className="judgment">
      <div className={`judgment-hero ${s.tier}`}>
        <span className="judgment-hero-ring" aria-hidden="true" />
        {/* 크기는 styles.css 가 갈래별로 다시 잡는다(경고 118 / 그 외 111).
            여기 값은 로딩 중 레이아웃이 튀지 않게 하는 기준치일 뿐이다. */}
        <img src={HERO[s.tier]} width="111" height="111" alt="" aria-hidden="true" className="judgment-hero-img" />
      </div>

      <h2 className="judgment-title">
        {s.lead}<span className={`accent ${s.tier}`}>{s.accent}</span>{s.tail}
      </h2>

      {/* ── ① 위험행동 블록 (2026-08-13). 검출됐을 때만 나온다.
          ★ 인용 구절이 먼저다. 받으신 문장을 눈으로 직접 대조하는 것이 목적이라
            읽히는 것이 먼저다 - 유형 판단이 만에 하나 어긋나도 실제 문장은 보인다.
          ★ 서버가 이미 마스킹된 텍스트에서만 뽑는다(전화번호·계좌가 실릴 수 없다).
            구절을 못 뽑으면 서버가 빈 값을 주고, 그때는 인용 없이 문구만 나간다.
          ★ ②사실 블록과 경쟁하지 않는다. 서로 다른 자리다 -
            ①은 "이 글이 무엇을 하라고 하는가", ②는 "우리가 무엇을 찾았는가". */}
      {s.risk ? (
        <div className={`judgment-risk ${s.tier}`}>
          {s.risk.quote ? (
            <p className="judgment-risk-quote">{`“${s.risk.quote}”`}</p>
          ) : null}
          <p className="judgment-risk-fact">{s.risk.fact}</p>
          <p className="judgment-risk-action">{s.risk.action}</p>
        </div>
      ) : null}

      {/* ★ '사실 한 줄' - 무엇을 보고 이렇게 판단했는지 여기서 바로 알려 준다.
          전에는 "비슷한 점이 있어요"까지만 있고 무엇이 비슷한지는 다음 화면에
          가야 알 수 있었는데, 어르신이 정작 알고 싶어 하는 게 그거였다. */}
      {s.factUrl ? (
        <a
          className={`judgment-fact link ${s.tier}`}
          href={s.factUrl}
          target="_blank"
          rel="noreferrer"
          onClick={() => {
            let domain = 'unknown'
            try { domain = new URL(s.factUrl).hostname } catch { /* noop */ }
            logEvidenceLinkClick(SCREEN, domain)
          }}
        >
          {s.fact}
          {/* ★ 경보문 제목을 링크 안에 함께 보여준다 (2026-08-13).
              어르신이 그 원문을 직접 읽는 것이 이 블록의 목적이다. */}
          {s.factTitle ? <span className="judgment-fact-title">{s.factTitle}</span> : null}
        </a>
      ) : (
        <p className={`judgment-fact ${s.tier}`}>{s.fact}</p>
      )}

      <button
        type="button"
        className={`judgment-cta ${s.tier}`}
        onClick={() => { logClick(SCREEN, `start_verify_${s.tier}`); onStart() }}
      >
        <span>하나씩 확인하기</span>
        <img src={arrowRight} width="21" height="21" alt="" aria-hidden="true" />
      </button>
    </div>
  )
}
