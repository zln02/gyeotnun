/**
 * 곁눈(Gyeotnun) 사용자 행동 계측
 * 담당: 조희진
 *
 * 8/5 60대 사용성 테스트에서 정량 데이터(화면별 체류시간·이탈률·클릭수·근거링크
 * 클릭률)를 얻기 위해 추가한다. 서버: api/routers/events.py 참고.
 *
 * ★★ 지켜야 할 원칙 ★★
 * 1) 개인정보: 화면에 입력된 내용(붙여넣은 글, 질문 답변 자유 서술 등)은 절대
 *    보내지 않는다. 버튼 id·화면 이름·오류 유형처럼 미리 정해진 짧은 값만 보낸다.
 * 2) fire-and-forget: 절대 await 하지 않는다. 실패해도 조용히 무시하고 화면
 *    흐름을 막지 않는다. 이 파일의 함수는 전부 반환값이 없다(Promise 를 밖으로
 *    노출하지 않는다) - 호출하는 쪽에서 실수로 await 하지 못하게 막는 설계다.
 * 3) 응답을 기다리지 않으므로 화면 반응 속도에 영향이 없다.
 */
import { deviceId } from './api.js'

const EVENTS_URL = '/api/v1/events'

// SPA 가 한 번 로드될 때마다 새로 발급 - 같은 기기를 여러 참가자가 돌려 쓰는
// 사용성 테스트 특성상, 이게 없으면 서로 다른 방문이 하나로 뒤섞여 체류시간·
// 이탈지점 집계가 틀어진다(개인정보는 아니다 - 방문 세션을 구분하는 임의값일 뿐).
const SESSION_ID = (crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`)

// 페이지를 벗어날 때(탭 닫기 등) 마지막 화면 이탈을 최대한 남기기 위해 기억해 둔다.
let _currentScreen = null

function send(event) {
  // ★ 여기서 절대 throw 하지 않는다 - 계측 코드의 예외가 화면을 깨뜨리면 안 된다.
  try {
    const body = JSON.stringify({
      device_id: deviceId(),
      session_id: SESSION_ID,
      ts: new Date().toISOString(),
      ...event,
    })
    fetch(EVENTS_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,   // 페이지 전환 중에도 요청이 살아남을 확률을 높인다
    }).catch(() => {})    // 실패해도 조용히 무시 - fire-and-forget
  } catch {
    // JSON 직렬화 실패 등 - 계측은 서비스 흐름에 영향을 주지 않는다
  }
}

/** 화면 진입 기록. S1~S5 스크린 코드를 넘긴다. */
export function logScreenEnter(screen) {
  _currentScreen = screen
  send({ event_type: 'screen_enter', screen })
}

/** 화면 이탈 기록. 보통 다음 화면 진입 직전에 자동으로 호출된다(App.jsx). */
export function logScreenLeave(screen) {
  if (_currentScreen === screen) _currentScreen = null
  send({ event_type: 'screen_leave', screen })
}

/** 버튼 클릭. target 은 버튼을 식별하는 짧은 코드만 - 버튼 라벨 원문을 그대로 쓰지 않는다. */
export function logClick(screen, target) {
  send({ event_type: 'click', screen, target })
}

/** 근거(실제 자료) 링크 클릭 - '공식 출처 확인률' 지표의 원천. */
export function logEvidenceLinkClick(screen, target) {
  send({ event_type: 'evidence_link_click', screen, target })
}

/** 오류 발생(OCR 실패, 업로드 실패, API 오류 등). target 은 오류 유형 코드만. */
export function logError(screen, target) {
  send({ event_type: 'error', screen, target })
}

// ── 탭을 닫거나 백그라운드로 전환할 때도 마지막 화면 이탈을 남긴다 ──────────
// fetch(keepalive) 는 언로드 시점에 유실될 수 있어, 이 마지막 한 건만 더 안정적인
// sendBeacon 으로 보낸다. (주의: 잠깐 다른 탭을 봤다가 돌아오는 경우도 이 이벤트가
// 한 번 나가지만, 화면 자체는 안 바뀌므로 App.jsx 의 재진입 로그와 짝이 맞지 않을
// 수 있다 - 완벽한 정밀도보다 '진짜 이탈'을 놓치지 않는 쪽을 택했다.)
function flushOnExit() {
  if (!_currentScreen) return
  try {
    const body = JSON.stringify({
      device_id: deviceId(),
      session_id: SESSION_ID,
      ts: new Date().toISOString(),
      event_type: 'screen_leave',
      screen: _currentScreen,
      target: 'page_exit',
    })
    navigator.sendBeacon?.(EVENTS_URL, new Blob([body], { type: 'application/json' }))
  } catch {
    // 무시 - 마지막 이탈 기록 실패는 감수한다
  }
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushOnExit()
})
window.addEventListener('pagehide', flushOnExit)
