/**
 * 곁눈(Gyeotnun) - S3 확인 결과 배지(확인됨/의심/확인 불가) 3단계 실측 검증
 * 실행: cd tests && node verify_verdict_badge.mjs
 *       E2E_BASE_URL=http://localhost node verify_verdict_badge.mjs   (nginx 프로덕션 빌드 대상, 기본값)
 *
 * 무엇을 검증하는가
 *   실제 corpus_index 대조 결과가 3가지 서로 다른 verdict_hint/signals 조합을
 *   만들어내는 입력 문구 3개를 골라(아래 CASES), '글로 붙여넣기' 경로로 실제 API에
 *   넣고, S3 화면에 뜨는 배지가 매번 다른 tier(class + 라벨 문구)로 정확히
 *   렌더링되는지 브라우저에서 직접 확인한다. mock 을 쓰지 않는다.
 *
 * 문구별로 실제 collect_evidence() 가 만드는 조합(사전 확인 완료):
 *   확인됨   - references 있음 + signals 전부 severity=info (official_source_found 뿐)
 *   의심     - references 있음 + severity=attention 신호 있음 (similar_scam_case)
 *   확인 불가 - references 없음 (verdict_hint=no_source_found)
 */
import { chromium } from 'playwright'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'screenshots')
const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost'

const CASES = [
  {
    tier: 'tier-ok',
    label: '확인됨',
    text: '국민건강보험공단에서 발표한 2025 고령자 통계에 따르면 65세 이상 인구 비율이 20.3%라고 합니다. 관련 내용을 확인하고 싶습니다.',
  },
  {
    tier: 'tier-warn',
    label: '의심',
    text: '복지로 노후준비서비스 안내 페이지입니다. 지원 내용과 문의처를 확인하세요.',
  },
  {
    tier: 'tier-unknown',
    label: '확인 불가',
    text: '농어가목돈마련저축 저축장려금 지급 안내입니다.',
  },
]

const errors = []
const browser = await chromium.launch()
let failed = false

for (const [i, c] of CASES.entries()) {
  // ★ localhost 로 프로덕션 nginx(HTTPS)를 검증할 때는 인증서가 gyeotnun.duckdns.org
  //   앞으로 발급돼 있어 CN 불일치가 난다 - 로컬 스모크 검증이므로 무시한다.
  const page = await browser.newPage({ viewport: { width: 420, height: 900 }, ignoreHTTPSErrors: true })
  page.on('pageerror', (e) => errors.push(`[${c.label}] pageerror: ${e.message}`))
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`[${c.label}] console.error: ${msg.text()}`) })

  await page.goto(BASE_URL + '/', { waitUntil: 'networkidle' })

  const mockFlag = await page.locator('.mock-flag').count()
  if (mockFlag > 0) throw new Error('mock-flag 배너가 떠 있음 - USE_MOCK 이 여전히 true 입니다.')

  await page.getByRole('button', { name: /글로 붙여넣기/ }).click()
  await page.locator('#pasted').fill(c.text)
  await page.getByRole('button', { name: '확인 시작하기' }).click()

  // S2(확인 중)를 거쳐 S3 로 - 배지는 로딩 중에도 떠 있어야 한다(결과 먼저, 질문은 그 다음)
  await page.waitForSelector('.verdict-badge', { timeout: 60000 })
  // 질문까지 완전히 뜬 뒤 스크린샷 (배지+질문 함께 보이는 최종 상태)
  await page.waitForSelector('.ai-block', { timeout: 60000 }).catch(() => {})
  await page.waitForTimeout(300)

  const badge = page.locator('.verdict-badge')
  const classAttr = await badge.getAttribute('class')
  const badgeText = await badge.innerText()
  const summaryText = await page.locator('.verdict-summary').innerText()

  console.log(`\n=== [${i + 1}/3] 기대 tier=${c.tier} 라벨="${c.label}" ===`)
  console.log('  실제 class:', classAttr)
  console.log('  배지 내용:\n   ' + badgeText.replace(/\n/g, '\n   '))
  console.log('  근거 요약(동적):', summaryText)

  const okClass = classAttr?.includes(c.tier)
  const okLabel = badgeText.includes(c.label)
  const noBanned = !/가짜|사기/.test(badgeText)
  const hasIconAndText = /[✅⚠️❓]/.test(badgeText) && badgeText.trim().length > 0

  if (!okClass || !okLabel) {
    failed = true
    console.log(`  ✗ FAIL: tier class 또는 라벨 불일치 (기대 ${c.tier}/${c.label})`)
  } else if (!noBanned) {
    failed = true
    console.log('  ✗ FAIL: 금지어(가짜/사기) 포함')
  } else if (!hasIconAndText) {
    failed = true
    console.log('  ✗ FAIL: 아이콘+문구 병기 확인 안 됨')
  } else {
    console.log('  ✓ PASS')
  }

  const shotPath = path.join(OUT, `badge_${i + 1}_${c.tier}.png`)
  await page.screenshot({ path: shotPath, fullPage: true })
  console.log('  screenshot:', shotPath)

  await page.close()
}

await browser.close()

console.log('\nCONSOLE/PAGE ERRORS:', errors.length ? JSON.stringify(errors, null, 2) : 'none')
if (errors.length || failed) process.exit(1)
console.log('\n모든 tier(확인됨/의심/확인 불가) 정상 렌더링 확인 완료.')
