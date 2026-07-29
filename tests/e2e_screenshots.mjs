/**
 * 곁눈(Gyeotnun) 실제 API 연동 E2E 스크린샷 검증
 * 실행: cd tests && node e2e_screenshots.mjs
 *       E2E_BASE_URL=http://localhost node e2e_screenshots.mjs   (nginx로 서빙되는 프로덕션 빌드 대상)
 *
 * 무엇을 검증하는가
 *   프론트(mock 기본 OFF)를 실제 api 컨테이너(8000)에 붙인 채로,
 *   브라우저에서 S1(이미지 업로드)→S2(로딩)→S3(질문+근거)→S4(판단+태깅)→S5(훈련)
 *   를 실제로 한 번 관통시킨다. mock=1 을 붙이지 않는다 - 화면에 뜨는 모든 값이
 *   실제 Claude Vision/Sonnet 호출과 corpus_index 대조 결과여야 의미가 있다.
 *   E2E_BASE_URL 로 대상을 바꿀 수 있다 - vite dev 서버든, nginx가 서빙하는
 *   프로덕션 빌드(web/dist)든 같은 스크립트로 검증한다.
 *
 * 사전 조건
 *   - docker compose 로 api(8000)+db 가 떠 있고 ANTHROPIC_API_KEY 가 설정돼 있을 것
 *   - 기본값(E2E_BASE_URL 미지정): web/ 에서 `npm run dev` 로 vite(5173) 가 떠 있을 것
 *   - 프로덕션 검증: `npm run build` 후 `docker compose --profile prod up -d nginx`,
 *     E2E_BASE_URL=http://localhost 로 실행 (mock=1 절대 붙이지 않는다)
 */
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'screenshots')
const KAKAO_IMAGE = path.join(__dirname, '..', 'api', 'tests', 'fixtures', 'kakao_sample.jpg')
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:5173'

const errors = []
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 420, height: 900 } })
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))
page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console.error: ${msg.text()}`) })
page.on('request', (req) => {
  if (req.url().includes('/dialogue')) {
    console.log('>>> dialogue 요청 바디:', req.postData())
  }
})
page.on('response', async (res) => {
  if (res.url().includes('/dialogue')) {
    const body = await res.json().catch(() => null)
    console.log('<<< dialogue 응답:', body && { turn: body.turn, is_final: body.is_final })
  }
})

let shotN = 0
async function shot(name) {
  shotN += 1
  const file = `${String(shotN).padStart(2, '0')}_${name}.png`
  await page.screenshot({ path: path.join(OUT, file), fullPage: true })
  console.log('shot:', file)
}

// ── S1: 홈 (실제 API 모드, mock 파라미터 없음) ──────────────────────────────
await page.goto(BASE_URL + '/', { waitUntil: 'networkidle' })
await shot('home')

const mockFlag = await page.locator('.mock-flag').count()
if (mockFlag > 0) throw new Error('mock-flag 배너가 떠 있음 - USE_MOCK 이 여전히 true 입니다.')

// 카카오톡 캡처 이미지 업로드 → 실제 Claude Vision 호출
const fileInput = page.locator('input[type="file"]')
await fileInput.setInputFiles(KAKAO_IMAGE)
await shot('home_uploading')

// ── S2: 확인 중 (실제 evidence 수집은 mock보다 오래 걸릴 수 있다) ──────────
await page.waitForSelector('.loading', { timeout: 15000 })
await shot('checking')

// ── S3: 질문 (최대 3턴) ──────────────────────────────────────────────────
await page.waitForSelector('.ai-block', { timeout: 60000 })
await shot('question_turn1')

// 근거(초록 영역) 실측: 참조가 있으면 기관명/발행일이, 없으면 안내문이 보여야 한다
const sourceBlockText = await page.locator('.source-block').innerText()
console.log('--- source-block(turn1) ---\n' + sourceBlockText)

for (let loopTurn = 1; loopTurn <= 4; loopTurn++) {
  await page.waitForSelector('.ai-block')
  const progressLabel = await page.locator('.sub').first().innerText()
  const choices = page.locator('button.btn.choice')
  const n = await choices.count()
  if (n === 0) break
  await choices.first().click()
  // 진행 버튼(다음/다 확인했어요) 자체는 choice 가 아닌 유일한 .btn 이다 - 정확히 짚는다
  const submitBtn = page.locator('button.btn:not(.choice):not(.secondary)').last()
  const submitText = (await submitBtn.innerText()).trim()
  const isFinal = submitText.includes('다 확인했어요')
  console.log(`--- loop#${loopTurn} 실제 화면: ${progressLabel} | 버튼: "${submitText}" | isFinal=${isFinal} ---`)
  await shot(`question_loop${loopTurn}_selected`)
  await submitBtn.click()
  if (isFinal) break
  await page.waitForTimeout(300)
}

// ── S4: 판단 기록 ────────────────────────────────────────────────────────
await page.waitForSelector('text=어떻게 하시겠어요?', { timeout: 30000 })
await shot('decision')

await page.getByRole('button', { name: /조금 더 알아보고 정할게요/ }).click()
await page.waitForSelector('text=기록해 두었어요', { timeout: 30000 })
await shot('decision_result')

const resultText = await page.locator('.card').first().innerText()
console.log('--- 판단 기록 결과(LLM 오판유형 태깅) ---\n' + resultText)

// ── S5: 오늘의 5분 훈련 (보너스 - 실제 corpus 기반 카드) ───────────────────
await page.getByRole('button', { name: /오늘의 5분 연습 하러 가기/ }).click()
await page.waitForSelector('text=오늘의 5분 연습', { timeout: 30000 })
await shot('training')

const trainingChoice = page.locator('button.btn.choice').first()
await trainingChoice.click()
await page.getByRole('button', { name: '답 확인하기' }).click()
await page.waitForSelector('text=이번 주 기록', { timeout: 10000 })
await shot('training_report')

await browser.close()

console.log('\nCONSOLE/PAGE ERRORS:', errors.length ? JSON.stringify(errors, null, 2) : 'none')
if (errors.length) process.exit(1)
