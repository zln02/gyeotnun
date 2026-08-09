/**
 * 확인 흐름 3단계 진행 표시 (발견 → 탐색 → 확인)
 * Figma node 428:329(발견) / 483:196(탐색) / 428:585(확인)
 *
 * ★ 기존 S3 는 점 3개짜리 무의미한 진행바(`.progress`)를 썼다. 시니어 대상
 *   사용성 테스트에서 "점이 몇 개 남았는지"보다 "지금 무슨 단계인지"를
 *   알고 싶어 한다는 게 반복 관찰돼, Figma 가 단계에 이름을 붙였다.
 *   여기서는 그 이름(발견/탐색/확인)을 그대로 쓴다.
 *
 * ★ 아이콘을 상태별 파일로 나눈 이유: <img> 는 currentColor 를 상속하지 않아
 *   CSS 로 색을 바꿀 수 없다. Figma 가 상태별로 다른 색 아이콘을 내보내므로
 *   그대로 3벌씩 둔다(색만 다르고 path 는 동일).
 */
import findDone from '../assets/verify/step_find_done.svg'
import findActive from '../assets/verify/step_find_active.svg'
import findPending from '../assets/verify/step_find_pending.svg'
import exploreDone from '../assets/verify/step_explore_done.svg'
import exploreActive from '../assets/verify/step_explore_active.svg'
import explorePending from '../assets/verify/step_explore_pending.svg'
import confirmDone from '../assets/verify/step_confirm_done.svg'
import confirmActive from '../assets/verify/step_confirm_active.svg'
import confirmPending from '../assets/verify/step_confirm_pending.svg'
import arrowOn from '../assets/verify/step_arrow.svg'
import arrowOff from '../assets/verify/step_arrow_pending.svg'

export const VERIFY_STEPS = ['find', 'explore', 'confirm']

const STEP_META = {
  find:    { label: '발견', icon: { done: findDone,    active: findActive,    pending: findPending } },
  explore: { label: '탐색', icon: { done: exploreDone, active: exploreActive, pending: explorePending } },
  confirm: { label: '확인', icon: { done: confirmDone, active: confirmActive, pending: confirmPending } },
}

export default function VerifyProgress({ current }) {
  const currentIndex = Math.max(0, VERIFY_STEPS.indexOf(current))

  return (
    <ol
      className="verify-progress"
      aria-label={`확인 3단계 중 ${currentIndex + 1}단계 (${STEP_META[VERIFY_STEPS[currentIndex]].label})`}
    >
      {VERIFY_STEPS.map((key, i) => {
        const state = i < currentIndex ? 'done' : i === currentIndex ? 'active' : 'pending'
        const meta = STEP_META[key]
        return (
          <li key={key} className="verify-progress-item">
            <span className={`verify-step ${state}`} aria-current={state === 'active' ? 'step' : undefined}>
              <img src={meta.icon[state]} width="16" height="16" alt="" aria-hidden="true" />
              <span className="verify-step-label">{meta.label}</span>
              {/* 색만으로 상태를 구분하지 않는다 - 화면 낭독기에는 글자로도 알린다 */}
              <span className="sr-only">
                {state === 'done' ? ' 완료' : state === 'active' ? ' 진행 중' : ' 남음'}
              </span>
            </span>
            {i < VERIFY_STEPS.length - 1 && (
              <img
                className="verify-step-arrow"
                src={i < currentIndex ? arrowOn : arrowOff}
                width="13"
                height="13"
                alt=""
                aria-hidden="true"
              />
            )}
          </li>
        )
      })}
    </ol>
  )
}
