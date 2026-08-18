"""실험 3(a) — 도메인 분류 혼동표 (2026-08-12)
실행: docker compose exec api python3 experiments/exp_domain_confusion.py

★ 조사만 한다. detect_domain() 을 고치지 않는다.

■ 정답 도메인을 사람이 붙인 기준
  "이 문자가 말하는 주제에 **대조할 공식 원문이 존재하는가**"를 가르는 축으로 잡았다.
    policy      공공지원 제도·행정 (복지로·정부24 등)          원문 있음
    health      건강·질병 정보 (국립암센터·정신건강센터)        원문 있음
    finance     금융 제도·감독·금융상품 (주택연금·금감원·대출)  원문 일부 있음
    commercial  기업 마케팅·거래 (카드사·통신사·분양·쇼핑)      ★ 원문 없음
  사칭·경계는 '사칭당한 주제'로 라벨을 붙였다(사기라는 사실이 아니라 무엇을 사칭했는가).
  시스템 출력을 보고 정한 게 아니라 문구만 읽고 정했다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
from services.ocr import detect_domain  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")

TRUTH: dict[str, str] = {}
TRUTH.update({f"N{i:02d}": "policy" for i in range(1, 11)})          # 기존 정상 = 복지로
TRUTH.update({c: "policy" for c in
              ["N11", "N12", "N14", "N15", "N17", "N18", "N19", "N21", "N22", "N29"]})
TRUTH["N24"] = "finance"                                             # 주택담보노후연금보증
TRUTH.update({c: "health" for c in
              ["N33", "N34", "N35", "N36", "N37", "N38", "N39", "N40"]})
# 실사용 — 지자체·공공 일자리센터 vs 기업
TRUTH.update({c: "policy" for c in ["R01", "R02", "R03", "R04", "R05", "R06"]})
TRUTH.update({c: "commercial" for c in ["R07", "R08", "R09", "R10", "R11"]})
# 사칭 (사칭당한 주제 기준)
TRUTH.update({c: "policy" for c in
              ["S01", "S03", "S04", "S05", "S07", "S08", "S09", "S11", "S14", "S15",
               "S16", "S17", "S22", "S24", "S25", "S27", "S30", "S31", "S32", "S37",
               "S38", "S39"]})
TRUTH.update({c: "finance" for c in
              ["S12", "S13", "S19", "S20", "S28", "S29", "S33", "S34", "S36"]})
TRUTH.update({c: "commercial" for c in ["S18", "S21", "S23", "S26", "S35", "S40"]})
# 경계
TRUTH.update({c: "policy" for c in
              ["B01", "B02", "B04", "B06", "B08", "B09", "B10", "B11", "B12", "B13",
               "B14", "B15", "B17", "B18", "B19", "B20", "B21", "B23", "B24", "B25",
               "B26", "B27", "B28", "B29", "B30", "B31", "B32", "B33", "B34", "B35",
               "B36", "B37", "B38", "B40"]})
TRUTH.update({c: "health" for c in ["B05", "B16", "B39"]})
TRUTH["B22"] = "finance"

rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig")) if r["입력채널"] != "음성"]
missing = [r["case_id"] for r in rows if r["case_id"] not in TRUTH]
if missing:
    sys.exit(f"[중단] 정답 라벨이 없는 케이스: {missing}")

pairs = [(TRUTH[r["case_id"]], detect_domain(r["평가용_제시문구"]), r) for r in rows]

print("=" * 74)
print("혼동표 — 행: 사람이 붙인 정답 / 열: detect_domain() 현재 출력")
print("=" * 74)
cols = ["policy", "health", "finance", "news", "unknown"]
hdr = "정답 / 현재"
print(f"{hdr:12}" + "".join(f"{c:>10}" for c in cols) + f"{'계':>8}")
for t in ["policy", "health", "finance", "commercial"]:
    row = Counter(p for gt, p, _ in pairs if gt == t)
    n = sum(row.values())
    print(f"{t:12}" + "".join(f"{row.get(c, 0):>10}" for c in cols) + f"{n:>8}")

print("\n" + "=" * 74)
print("★ commercial (대조할 공식 원문이 없는 문자) 이 어디로 새는가")
print("=" * 74)
com = [(p, r) for gt, p, r in pairs if gt == "commercial"]
print(f"  총 {len(com)}건 → {dict(Counter(p for p, _ in com))}")
print("  * detect_domain 에 commercial 이라는 출력 자체가 없다. 전부 다른 값으로 간다.")
for p, r in com:
    print(f"    {r['case_id']:5} {p:9} | {r['평가용_제시문구'][:46]}")

print("\n" + "=" * 74)
print("정확도 (commercial 은 현재 분류 체계에 없어 원천적으로 맞출 수 없다)")
print("=" * 74)
hit = sum(1 for gt, p, _ in pairs if gt == p)
gt_known = [(gt, p) for gt, p, _ in pairs if gt != "commercial"]
hit_known = sum(1 for gt, p in gt_known if gt == p)
print(f"  전체        {hit}/{len(pairs)} ({hit / len(pairs) * 100:.1f}%)")
print(f"  commercial 제외 {hit_known}/{len(gt_known)} ({hit_known / len(gt_known) * 100:.1f}%)")

print("\n  오분류 내역(commercial 제외):")
mis = defaultdict(list)
for gt, p, r in pairs:
    if gt != "commercial" and gt != p:
        mis[(gt, p)].append(r["case_id"])
for (gt, p), ids in sorted(mis.items(), key=lambda x: -len(x[1])):
    print(f"    {gt:9} → {p:9} {len(ids):>3}건  {', '.join(ids[:12])}")
