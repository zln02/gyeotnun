/**
 * 곁눈(Gyeotnun) 기획서 삽입용 스크린샷
 * 실행: cd tests && node demo_screenshots.mjs
 *
 * e2e_screenshots.mjs 와 달리 이건 "검증용"이 아니라 "제출용"이다. 그래서
 *  - 실제 모바일에 가까운 뷰포트(390x844, iPhone 12/13 급)와 2x 배율로 찍는다
 *  - 전체 흐름이 아니라 핵심 4장(S1/S3/S4/S5)만 고른다
 *  - 저장 위치도 tests/screenshots/(검증용)와 분리해 docs/demo/ 에 둔다
 *
 * 대상은 실제 배포 도메인(HTTPS) 기본값이다. 다른 대상을 쓰려면 E2E_BASE_URL.
 */
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, '..', 'docs', 'demo')
const KAKAO_IMAGE = path.join(__dirname, '..', 'api', 'tests', 'fixtures', 'kakao_sample.jpg')
const BASE_URL = process.env.E2E_BASE_URL || 'https://gyeotnun.duckdns.org'

const browser = await chromium.launch()
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
})

async function shot(name) {
  await page.screenshot({ path: path.join(OUT, name), fullPage: true })
  console.log('saved:', name)
}

// S1 - 홈 (업로드 전, 실제 화면)
await page.goto(BASE_URL + '/', { waitUntil: 'networkidle' })
if (await page.locator('.mock-flag').count() > 0) {
  throw new Error('mock-flag 배너가 떠 있음 - 실제 데이터가 아닙니다.')
}
await shot('01_home.png')

// 카카오톡 캡처 이미지 업로드 → 실제 Claude Vision 호출
await page.locator('input[type="file"]').setInputFiles(KAKAO_IMAGE)
await page.waitForSelector('.loading', { timeout: 15000 })
await page.waitForSelector('.ai-block', { timeout: 60000 })

// S3 - 질문 카드(근거 렌더링까지 포함된 첫 턴)
await shot('02_question.png')

// 3턴 답하고 S4로 이동
for (let i = 0; i < 4; i++) {
  const choices = page.locator('button.btn.choice')
  if ((await choices.count()) === 0) break
  await choices.first().click()
  const submitBtn = page.locator('button.btn:not(.choice):not(.secondary)').last()
  const isFinal = (await submitBtn.innerText()).includes('다 확인했어요')
  await submitBtn.click()
  if (isFinal) break
  await page.waitForSelector('.ai-block')
}

// S4 - 판단 기록 결과 (LLM 오판유형 태깅 포함)
await page.waitForSelector('text=어떻게 하시겠어요?', { timeout: 30000 })
await page.getByRole('button', { name: /조금 더 알아보고 정할게요/ }).click()
await page.waitForSelector('text=기록해 두었어요', { timeout: 30000 })
await shot('03_decision_result.png')

// S5 - 오늘의 5분 훈련 + 주간 리포트
await page.getByRole('button', { name: /오늘의 5분 연습 하러 가기/ }).click()
await page.waitForSelector('text=오늘의 5분 연습', { timeout: 30000 })
const trainingChoice = page.locator('button.btn.choice').first()
await trainingChoice.click()
await page.getByRole('button', { name: '답 확인하기' }).click()
await page.waitForSelector('text=이번 주 기록', { timeout: 10000 })
await shot('04_training.png')

await browser.close()
console.log('완료:', OUT)
