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

// ★ fetch() 자체가 실패하면(오프라인 등) 응답이 아예 없다 - 서버는 이 실패를
//   볼 수 없으므로(요청이 도달하지 않음) 프론트에서만 EX-004 로 판단한다.
async function safeFetch(input, init) {
  try {
    return await fetch(input, init)
  } catch {
    throw codedError('인터넷 연결을 확인해 주세요.', 'EX-004')
  }
}

async function handle(res) {
  if (res.ok) return res.json()
  let code = ''
  let detail = ''

  // Response 본문은 한 번만 읽을 수 있으므로, 텍스트를 먼저 읽고 JSON 여부를 판별한다.
  const rawBody = await res.text()
  try {
    const body = JSON.parse(rawBody)
    code = body?.detail?.code || ''
    detail = body?.detail?.message || body?.detail || JSON.stringify(body)
  } catch {
    detail = rawBody
  }
  // 501 = 키가 없거나 아직 구현 전. 사용자에게는 부드럽게 안내한다.
  if (res.status === 501) {
    throw codedError(`아직 준비 중인 기능입니다. (${detail})`, code || 'SYS-000')
  }
  throw codedError(detail || `요청에 실패했습니다. (${res.status})`, code || 'SYS-000')
}

async function getJSON(path) {
  return handle(await safeFetch(url(path)))
}

async function postJSON(path, body) {
  return handle(
    await safeFetch(url(path), {
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
export async function createCheck({ image, link, text }) {
  const fd = new FormData()
  fd.append('device_id', deviceId())
  if (image) fd.append('image', image)
  if (link) fd.append('link', link)
  if (text) fd.append('text', text)
  return handle(await safeFetch(url('/checks'), { method: 'POST', body: fd }))
}

/* ------------------------------------------------------------------ S2 */
/** GET /checks/{id}/evidence — 근거 수집 결과 */
export async function getEvidence(checkId) {
  return getJSON(`/checks/${checkId}/evidence`)
}

/* ------------------------------------------------------------------ S3 */
/** POST /checks/{id}/dialogue — 다음 확인 질문 1개 */
export async function getQuestion(checkId, turn, userReply = null) {
  return postJSON(`/checks/${checkId}/dialogue`, { turn, user_reply: userReply })
}

/* ------------------------------------------------------------------ S4 */
/** POST /checks/{id}/verdict — 사용자 판단 기록 + 오판유형 태깅 */
export async function submitVerdict(checkId, decision, reasonTags = []) {
  return postJSON(`/checks/${checkId}/verdict`, { decision, reason_tags: reasonTags })
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
