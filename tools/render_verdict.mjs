// verdict.js 를 실제로 돌려 '화면 출력'을 전수로 뽑는다 (2026-08-13)
//
// 사용:
//   docker compose exec api python3 experiments/dump_screen_payloads.py before
//   docker cp gyeotnun-api:/app/data/screen_before.json /tmp/
//   node tools/render_verdict.mjs /tmp/screen_before.json /tmp/render_before.json
//
// ★ 왜 필요한가: tier 만 바뀌는 변경은 파이썬으로 재현해 잴 수 있지만,
//   '사실 한 줄'·인용·링크까지 바뀌는 변경은 verdict.js 를 실제로 돌려야
//   확인된다. 8/13 블록 구조 변경에서 경보문 링크가 조용히 사라진 적이 있다.
import { readFileSync, writeFileSync } from 'node:fs'
import { judgmentState } from '../web/src/verdict.js'

const rows = JSON.parse(readFileSync(process.argv[2], 'utf-8'))
const out = rows.map((r) => {
  const s = judgmentState(r.evidence, r.checkData)
  return {
    id: r.id, 유형: r.유형, 기대판단: r.기대판단, 위험행동: r.위험행동,
    tier: s.tier,
    title: `${s.lead}${s.accent}${s.tail}`,
    fact: s.fact || '', factUrl: s.factUrl || '',
    factQuote: s.factQuote || '',
    risk: s.risk ? `${s.risk.quote} | ${s.risk.fact} | ${s.risk.action}` : '',
    // ③ 주소 블록 (2026-08-15). 여기 빠뜨리면 주소 줄이 조용히 바뀌어도 못 잡는다
    //   - 8/13 에 경보문 링크가 그렇게 사라진 적이 있다.
    link: s.link ? `${s.link.fact} | ${s.link.publicNote}` : '',
  }
})
writeFileSync(process.argv[3], JSON.stringify(out, null, 1))
console.log(`${out.length}건 렌더 → ${process.argv[3]}`)
