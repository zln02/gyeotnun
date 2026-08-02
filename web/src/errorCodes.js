/**
 * 오류 코드 - 단일 소스는 서버(api/services/error_codes.py)에 있다.
 * 담당: 조희진 / 8/2 보안 멘토링 지시사항
 *
 * 대부분의 오류는 서버 응답에 이미 사람이 읽을 문구(message)가 실려 온다 -
 * 그 경우 프론트는 코드만 덧붙이면 된다(withCode). 서버 응답을 아예 받지 못하는
 * 순수 클라이언트 오류(네트워크 끊김 EX-004, 공유 실패 IN-003)만 이 표를
 * 앱 시작 시 한 번 받아와 문구를 채우는 데 쓴다 - 같은 문구를 프론트에 따로
 * 하드코딩하면 그 순간 "단일 소스" 원칙이 깨지기 때문이다.
 */
let _cache = null
let _fetchPromise = null

export async function loadErrorCodes() {
  if (_cache) return _cache
  if (!_fetchPromise) {
    _fetchPromise = fetch('/api/v1/errors/codes')
      .then((r) => (r.ok ? r.json() : []))
      .then((list) => { _cache = Array.isArray(list) ? list : []; return _cache })
      .catch(() => { _cache = []; return _cache })
  }
  return _fetchPromise
}

/** 클라이언트 전용 코드(IN-003/EX-004 등)의 안내 문구를 표에서 찾는다. */
export function errorMessageFor(code) {
  const found = (_cache || []).find((c) => c.code === code)
  return found?.user_message || ''
}

/** 화면에 오류 코드를 덧붙인다 - 문의 시 이 코드를 읽어 주면 된다. */
export function withCode(message, code) {
  if (!code) return message
  return `${message}${message ? ' ' : ''}(오류 코드: ${code})`
}
