/**
 * 곁눈(Gyeotnun) API 호출 래퍼
 * 담당: 조희진 (프론트) / 계약: 박진영
 *
 * ★ 기본값이 실제 API 다. 백엔드가 실제로 붙었으니 화면에는 진짜 데이터가 떠야 한다.
 *   그래도 개발 편의를 위해 mock 토글은 남겨 둔다.
 *
 * 모드 결정 우선순위 (위가 이긴다)
 *   1) 주소창 쿼리 ?mock=1 / ?mock=0   - 지금 이 탭만 바꿔서 확인하고 싶을 때
 *   2) 환경변수 VITE_USE_MOCK=1        - 이 머신에서 개발할 때 기본을 mock 으로
 *   3) 기본값 = 실제 API (false)
 */

import { withCode } from './errorCodes.js'

const params = new URLSearchParams(window.location.search)
const envDefaultMock = import.meta.env.VITE_USE_MOCK === '1'

export const USE_MOCK = params.has('mock')
  ? params.get('mock') === '1'
  : envDefaultMock

const BASE = '/api/v1'

/** mock 플래그를 붙인 URL 을 만든다. */
function url(path) {
  const sep = path.includes('?') ? '&' : '?'
  return `${BASE}${path}${sep}mock=${USE_MOCK ? 1 : 0}`
}

/** 오류 코드를 실은 Error 를 만든다. 화면(error.message)과 계측(error.code) 양쪽에 다 쓴다. */
function codedError(message, code) {
  const err = new Error(withCode(message, code))
  err.code = code
  return err
}

/**
 * ★★ 요청 제한 시간 (2026-08 추가) ★★
 *   전에는 어떤 요청에도 타임아웃이 없었다. 백엔드가 응답하지 않으면 화면이
 *   영원히 로딩 상태로 남고, 어르신은 고장 난 줄 알고 앱을 닫아 버린다.
 *   이건 "느린 것"이 아니라 "끝나지 않는 것"이라 체감이 전혀 다르다.
 *
 *   값을 30초로 잡은 근거(실측):
 *     사진 1건 = 업로드 + Vision OCR 3.67초 + 근거검색 0.17초 ≈ 12초
 *     질문 생성(LLM) 평균 6.62초, 최대 14.05초
 *   즉 정상 요청도 10초를 넘기는 게 정상이다. 너무 짧게 잡으면 멀쩡한 요청을
 *   끊어 버리므로, 가장 느린 정상 경로(약 14초)의 2배를 여유로 둔다.
 *   nginx proxy_read_timeout 이 120초라 그 안쪽이기도 하다.
 */
export const REQUEST_TIMEOUT_MS = 30000

/** 타임아웃으로 끊긴 요청인지 (화면에서 '다시 시도' 를 띄울지 판단할 때 쓴다) */
export const TIMEOUT_CODE = 'EX-005'
/** 사용자가 직접 취소한 경우 - 오류가 아니므로 화면에 빨간 박스를 띄우지 않는다 */
export const CANCELLED_CODE = 'EX-canceled'

/**
 * fetch 에 제한 시간과 취소를 붙인다.
 *
 * - init.signal 로 화면이 준 취소 신호를 함께 듣는다(로딩 중 '그만두기').
 * - fetch() 자체가 실패하면(오프라인 등) 응답이 아예 없다 - 서버는 이 실패를
 *   볼 수 없으므로(요청이 도달하지 않음) 프론트에서만 EX-004 로 판단한다.
 */
async function safeFetch(input, init = {}) {
  const { signal: externalSignal, ...rest } = init
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; controller.abort() }, REQUEST_TIMEOUT_MS)
  const onExternalAbort = () => controller.abort()
  if (externalSignal) {
    if (externalSignal.aborted) controller.abort()
    else externalSignal.addEventListener('abort', onExternalAbort)
  }

  try {
    return await fetch(input, { ...rest, signal: controller.signal })
  } catch (e) {
    // 취소와 타임아웃은 둘 다 AbortError 로 온다 - 어느 쪽이 먼저였는지로 가른다.
    if (externalSignal?.aborted && !timedOut) throw codedError('', CANCELLED_CODE)
    if (timedOut || e?.name === 'AbortError') {
      throw codedError('시간이 오래 걸리고 있어요. 다시 해보시겠어요?', TIMEOUT_CODE)
    }
    throw codedError('인터넷 연결을 확인해 주세요.', 'EX-004')
  } finally {
    clearTimeout(timer)
    if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort)
  }
}

async function handle(res) {
  if (res.ok) return res.json()
  // ★ 본문은 한 번만 읽을 수 있다. 예전에는 res.json() 이 실패한 뒤 res.text() 를
  //   또 불러서 "body stream already read" 가 나고, 정작 진짜 오류 내용은
  //   사라졌다. 텍스트로 한 번 읽고 그걸 파싱한다.
  const raw = await res.text().catch(() => '')
  let code = ''
  let detail = raw
  try {
    const body = JSON.parse(raw)
    code = body?.detail?.code || ''
    detail = body?.detail?.message || body?.detail || raw
    if (typeof detail !== 'string') detail = JSON.stringify(detail)
  } catch { /* JSON 이 아니면 원문 그대로 쓴다 */ }

  // 501 = 키가 없거나 아직 구현 전. 사용자에게는 부드럽게 안내한다.
  if (res.status === 501) {
    throw codedError(`아직 준비 중인 기능입니다. (${detail})`, code || 'SYS-000')
  }
  throw codedError(detail || `요청에 실패했습니다. (${res.status})`, code || 'SYS-000')
}

async function getJSON(path, opts) {
  return handle(await safeFetch(url(path), opts))
}

async function postJSON(path, body, opts) {
  return handle(
    await safeFetch(url(path), {
      ...opts,
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
    })
  )
}

/** 기기 식별자. 이름·전화번호를 받지 않기 위한 최소 식별값. */
export function deviceId() {
  let id = localStorage.getItem('gyeotnun_device_id')
  if (!id) {
    id = 'dev_' + Math.random().toString(36).slice(2, 12)
    localStorage.setItem('gyeotnun_device_id', id)
  }
  return id
}

/**
 * ★ 2026-08 홈 화면 개인화(Figma "OO 님의 곁눈"): deviceId() 는 위 주석대로
 * 의도적으로 이름을 받지 않는 무작위 값이다 - 그 원칙은 그대로 두고, 화면에
 * 표시할 이름만 "완전히 선택"으로 별도 저장한다. 서버로는 전송하지 않고
 * deviceId() 와 같은 방식(이 기기의 localStorage, 회원가입 없음)으로만 둔다.
 */
const NAME_KEY = 'gyeotnun_display_name'

export function getDisplayName() {
  return localStorage.getItem(NAME_KEY) || ''
}

export function setDisplayName(name) {
  const trimmed = (name || '').trim().slice(0, 12)
  if (trimmed) localStorage.setItem(NAME_KEY, trimmed)
  else localStorage.removeItem(NAME_KEY)
  return trimmed
}

/* ------------------------------------------------------------------ S1 */
/** POST /checks — 이미지/링크/텍스트 업로드 (multipart) */
export async function createCheck({ image, link, text }, opts) {
  const fd = new FormData()
  fd.append('device_id', deviceId())
  if (image) fd.append('image', image)
  if (link) fd.append('link', link)
  if (text) fd.append('text', text)
  return handle(await safeFetch(url('/checks'), { ...opts, method: 'POST', body: fd }))
}

/* ------------------------------------------------------------------ S2 */
/** GET /checks/{id}/evidence — 근거 수집 결과
 *  ★ device_id 를 함께 보낸다: 이 확인 건을 만든 기기만 조회할 수 있다(IDOR 방지). */
export async function getEvidence(checkId, opts) {
  return getJSON(`/checks/${checkId}/evidence?device_id=${encodeURIComponent(deviceId())}`, opts)
}

/* ------------------------------------------------------------------ S3 */
/** POST /checks/{id}/dialogue — 다음 확인 질문 1개
 *  ★ device_id 를 함께 보낸다(소유권 확인). */
export async function getQuestion(checkId, turn, userReply = null, opts) {
  return postJSON(`/checks/${checkId}/dialogue`, { turn, user_reply: userReply, device_id: deviceId() }, opts)
}

/* ------------------------------------------------------------------ S4 */
/** POST /checks/{id}/verdict — 사용자 판단 기록 + 오판유형 태깅
 *  ★ device_id 를 함께 보낸다(소유권 확인). */
export async function submitVerdict(checkId, decision, reasonTags = [], opts) {
  return postJSON(`/checks/${checkId}/verdict`, { decision, reason_tags: reasonTags, device_id: deviceId() }, opts)
}

/* ------------------------------------------------------------------ S5 */
/** GET /training/today — 오늘의 5분 훈련 카드 */
export async function getTodayCard(errorType) {
  return getJSON(`/training/today${errorType ? `?error_type=${errorType}` : ''}`)
}

/** GET /reports/weekly — 주간 리포트 */
export async function getWeeklyReport() {
  return getJSON(`/reports/weekly?device_id=${deviceId()}`)
}

/* --------------------------------------------------------------- 온보딩 */
/** POST /onboarding/diagnosis — 첫 실행 3문항 진단 */
export async function submitDiagnosis(answers) {
  return postJSON('/onboarding/diagnosis', { device_id: deviceId(), answers })
}

/** GET /health */
export async function health() {
  return handle(await safeFetch('/health'))
}
