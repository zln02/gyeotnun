import test from 'node:test'
import assert from 'node:assert/strict'
import { staticDemoResponse } from './staticDemo.js'

test('the complete portfolio flow is served without network calls', async () => {
  const cases = [
    ['/api/v1/checks?mock=1', { method: 'POST' }, 'check_id'],
    ['/api/v1/checks/chk_demo/evidence?mock=1', {}, 'references'],
    ['/api/v1/checks/chk_demo/dialogue?mock=1', { method: 'POST', body: JSON.stringify({ turn: 2 }) }, 'question'],
    ['/api/v1/checks/chk_demo/verdict?mock=1', { method: 'POST' }, 'tagged_error_type'],
    ['/api/v1/training/today?mock=1', {}, 'card_id'],
    ['/api/v1/reports/weekly?mock=1', {}, 'checks_count'],
    ['/api/v1/onboarding/diagnosis?mock=1', { method: 'POST' }, 'user_id'],
  ]
  for (const [path, init, key] of cases) {
    const res = await staticDemoResponse(path, init)
    assert.equal(res.status, 200, path)
    assert.ok((await res.json())[key] !== undefined, `${path}: ${key}`)
  }
})

test('unknown routes are not silently treated as successful', async () => {
  assert.equal((await staticDemoResponse('/api/v1/unknown')).status, 404)
})

test('cancelled requests do not proceed', async () => {
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(staticDemoResponse('/api/v1/checks', { signal: controller.signal }), /Abort/)
})
