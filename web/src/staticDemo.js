/**
 * GitHub Pages 전용, 서버 없는 포트폴리오 데모.
 * 응답은 api/mocks/fixtures.py에서 내보낸 고정 합성 사례다.
 * 사용자 입력을 분석하거나 서버로 보내지 않는다.
 */
import fixtures from './staticDemoFixtures.js'

export const STATIC_DEMO = import.meta.env?.VITE_STATIC_DEMO === '1'

export function staticDemoResponse(input, init = {}) {
  if (init.signal?.aborted) {
    return Promise.reject(new DOMException('Aborted', 'AbortError'))
  }
  const { pathname } = new URL(input, globalThis.location?.origin || 'https://zln02.github.io')
  const method = (init.method || 'GET').toUpperCase()
  const prefix = '/api/v1'
  let body

  if (pathname === `${prefix}/checks` && method === 'POST') body = fixtures.CHECK_CREATE
  else if (/^\/api\/v1\/checks\/[^/]+\/evidence$/.test(pathname) && method === 'GET') body = fixtures.EVIDENCE
  else if (/^\/api\/v1\/checks\/[^/]+\/dialogue$/.test(pathname) && method === 'POST') {
    const turn = Number(JSON.parse(init.body || '{}').turn) || 1
    body = fixtures.DIALOGUE_TURNS[String(Math.min(Math.max(turn, 1), 3))]
  }
  else if (/^\/api\/v1\/checks\/[^/]+\/verdict$/.test(pathname) && method === 'POST') body = fixtures.VERDICT
  else if (pathname === `${prefix}/training/today` && method === 'GET') body = fixtures.TRAINING_TODAY
  else if (pathname === `${prefix}/reports/weekly` && method === 'GET') body = fixtures.WEEKLY_REPORT
  else if (pathname === `${prefix}/onboarding/diagnosis` && method === 'POST') body = fixtures.ONBOARDING_DIAGNOSIS
  else if (pathname === '/health') body = { status: 'demo' }

  return Promise.resolve(new Response(
    JSON.stringify(body ?? { detail: { code: 'DEMO-404', message: '데모에 없는 화면입니다.' } }),
    { status: body ? 200 : 404, headers: { 'Content-Type': 'application/json' } },
  ))
}
