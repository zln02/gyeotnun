"""
match_scam_cases() 의 min_score 를 실제로 적용하면 무엇이 바뀌는가 - 사전 진단 (2026-08-08)
실행: docker compose exec api python3 experiments/diag_scam_min_score.py

배경
  2026-08-05 판정축 변경(어휘 합산 → 수법 카테고리 일치) 때 min_score 인자가
  코드에서 빠졌다. 지금은 '수법 카테고리 1개 + 키워드 1개' 만 겹치면 하한선 없이
  근거로 승격된다. 실제 사례: B07(대출 이미지)이 단어 '은행' 하나로 C09(금융위
  카드뉴스)에, 단어 '직원' 하나로 C12(경찰청 투자리딩방)에 매칭됐다.
  → docs/reports/2026-08-08_은행명질문_금융위근거_원인조사.txt

이 스크립트는 **코드를 고치지 않고** 같은 점수 계산을 재현해, 하한선을 적용하면
어떤 매칭이 사라지는지만 미리 잰다. 절대조건이 깨지면 적용하지 않는다.
  ★ 정상 10건 오판 0건 유지
  ★ 사칭 10건 위험신호 검출 10/10 유지
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index as ci  # noqa: E402
from services.scam_taxonomy import detect_categories  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
HOLDOUT_CSV = Path("/app/tests/fixtures/holdout/holdout_normal_5.csv")
OUT = Path("/app/data/diag_scam_min_score.json")

# 실사용 SMS 11건 - 원본은 리포에 없어 재구성본을 쓴다(docs/evaluation/mismatch_baemin_nia.md
# 와 동일한 취지). 적용 전/후 **같은 문장**으로 비교하므로 델타 비교에는 문제가 없다.
REAL_SMS = [
    ("R01", "[배달의민족] 고객님께 3,000원 할인쿠폰이 도착했어요. 앱에서 확인하세요."),
    ("R02", "[쿠팡] 주문하신 상품이 오늘 도착 예정입니다. 배송 조회는 앱에서 가능합니다."),
    ("R03", "[토스] 김철수님께 50,000원을 보냈습니다. 잔액을 확인해 주세요."),
    ("R04", "[스타벅스] 별 3개가 적립되었습니다. 다음 방문 때 사용하실 수 있어요."),
    ("R05", "[신한카드] 3월 이용대금 명세서가 발행되었습니다. 청구금액을 확인하세요."),
    ("R06", "[넷플릭스] 이번 달 이용요금 결제가 완료되었습니다. 이용 내역 안내드립니다."),
    ("R07", "[GS25] 포인트 2,000점이 적립되었습니다. 유효기간 안에 사용해 주세요."),
    ("R08", "[올리브영] 봄맞이 세일 최대 50% 할인 진행 중입니다. 매장에서 만나요."),
    ("R09", "[SKT] 이번 달 통신요금은 45,800원입니다. 자동이체 예정일을 확인하세요."),
    ("R10", "[카카오톡] 친구가 선물을 보냈어요. 선물함에서 확인해 보세요."),
    ("R11", "[안내] 어르신 디지털 기기 이용 교육 프로그램 참여자를 모집합니다. 이용 안내를 확인하세요."),
]

THRESHOLDS = [0.0, 3.0, 4.0, 5.0, 6.0]


def score_candidates(text: str):
    """match_scam_cases() 의 채점 로직을 그대로 재현한다(코드 수정 없이 관찰만).

    반환: [(수법일치수, 어휘점수, 매칭단어, case), ...] 정렬된 전체 후보
    """
    kws = [k for k in ci.extract_keywords(text) if k not in ci.STOPWORDS]
    if not kws:
        return []
    text_cats = detect_categories(text)
    if not text_cats:
        return []
    scored = []
    for case in ci.SCAM_CASES:
        case_cats = ci._case_categories(case.id)
        if not case_cats:
            continue
        shared = text_cats & case_cats
        if not shared:
            continue
        matched = ci._dedup_morph_variants([k for k in kws if k in case._blob])
        if not matched:
            continue
        lexical = sum(ci._keyword_weight(k) for k in matched)
        scored.append((len(shared), lexical, matched, case))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return scored


def survivors(scored, min_score: float, limit: int = 2):
    """어휘 점수 하한선을 적용했을 때 살아남는 매칭(상위 limit)."""
    kept = [s for s in scored if s[1] >= min_score]
    return kept[:limit]


def run_set(name: str, rows: list) -> list:
    print("=" * 78)
    print(f"{name}  ({len(rows)}건)")
    print("=" * 78)
    print(f"{'ID':<6}{'유형':<6}{'현재매칭(수법/어휘/단어)':<58}{'5.0 적용시'}")
    print("-" * 78)
    out = []
    for cid, typ, text in rows:
        scored = score_candidates(text)
        now = scored[:2]
        after = survivors(scored, 5.0)
        now_s = " ".join(f"{c.id}({n},{lx:.2f},{'+'.join(m)})" for n, lx, m, c in now) or "-"
        after_s = " ".join(c.id for _, _, _, c in after) or "-"
        mark = "  ← 사라짐" if now and not after else ("  ← 일부" if len(after) < len(now) else "")
        print(f"{cid:<6}{typ:<6}{now_s:<58}{after_s}{mark}")
        out.append({
            "id": cid, "유형": typ,
            "now": [{"case": c.id, "shared": n, "lexical": round(lx, 2), "words": m} for n, lx, m, c in now],
            "after_5": [c.id for _, _, _, c in after],
            "all_lexicals": sorted([round(lx, 2) for _, lx, _, _ in scored], reverse=True)[:5],
        })
    return out


def main() -> None:
    erows = [(r["case_id"], r.get("유형", ""), r["평가용_제시문구"])
             for r in csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig"))]
    hrows = [(r["case_id"], "홀드아웃", r["평가용_제시문구"])
             for r in csv.DictReader(HOLDOUT_CSV.open(encoding="utf-8-sig"))]
    rrows = [(cid, "실사용", t) for cid, t in REAL_SMS]
    b07 = [("B07img", "OCR", "은행 직원이 정부지원 대출상품을설명하고지점방문상담을권")]

    res_e = run_set("SET1 평가셋 30건", erows)
    print()
    res_h = run_set("SET2 홀드아웃 5건", hrows)
    print()
    res_r = run_set("SET3 실사용 SMS 11건(재구성)", rrows)
    print()
    res_b = run_set("SET4 B07 실제 OCR 출력", b07)

    # ---- 임계값별 매칭 건수 분포
    print()
    print("=" * 78)
    print("임계값별 '사기사례 매칭이 있는 건수' (평가셋 30건)")
    print("=" * 78)
    scored_all = {cid: (typ, score_candidates(t)) for cid, typ, t in erows}
    print(f"{'임계값':<8}{'정상':<8}{'사칭':<8}{'경계':<8}")
    for th in THRESHOLDS:
        cnt = {"정상": 0, "사칭": 0, "경계": 0}
        for cid, (typ, sc) in scored_all.items():
            if survivors(sc, th):
                cnt[typ] = cnt.get(typ, 0) + 1
        print(f"{th:<8}{cnt['정상']:<8}{cnt['사칭']:<8}{cnt['경계']:<8}")

    # ---- 사칭 10건의 최고 어휘점수(하한선을 어디까지 올릴 수 있나)
    print()
    print("사칭 10건의 최고 어휘점수 (이 값 아래로 하한선을 잡아야 검출이 유지된다)")
    tops = []
    for cid, (typ, sc) in scored_all.items():
        if typ != "사칭":
            continue
        top = max((lx for _, lx, _, _ in sc), default=0.0)
        tops.append((cid, top))
    for cid, top in sorted(tops, key=lambda x: x[1]):
        print(f"  {cid}  {top:.2f}")
    live = [t for _, t in tops if t > 0]
    print(f"  → 사칭 중 최저 최고점: {min(live):.2f}" if live else "  → 매칭 없음")

    OUT.write_text(json.dumps(
        {"eval": res_e, "holdout": res_h, "real_sms": res_r, "b07": res_b},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
