#!/usr/bin/env python3
"""사칭 40건 정답근거 재라벨 (2026-08-12)

■ 왜
  지금까지 사칭 케이스의 `출처_URL` 은 **그 수법이 실린 공개 경보문**이었다.
  그런데 시스템은 공식 제도 문서(OFFICIAL_DOCS)를 찾도록 만들어져 있다.
  즉 공식문서 검색을 사기사례 매칭의 잣대로 재고 있었다.
  (진단: docs/evaluation/후보0개_원인진단_2026-08-12.md §진단3)

■ 두 갈래로 나눈다
  doc   사칭당한 **제도의 진짜 안내문**  → OFFICIAL_DOCS 로 찾아야 함
  scam  수법 **경보문**                → SCAM_CASES 로 찾아야 함
  한 건에 둘 다 있을 수 있다. 사칭당한 제도가 실재하지 않으면(순수 창작) doc 은 none.

■ 라벨을 붙인 방법
  1) 문구를 읽고 '무엇을 사칭했는가'를 사람이 적는다(아래 IMPERSONATED).
  2) 그 제도명을 **코퍼스 제목으로 조회**해 URL 을 채운다. 못 찾으면 doc=none.
     ★ URL 을 창작하지 않는다. 제목이 코퍼스에 없으면 그대로 none 이다.
  3) scam 은 기존 출처_URL(경보문)을 그대로 승계한다.

  ★ 시스템 실행 결과를 보고 라벨을 정하지 않았다. 문구와 코퍼스만 봤다.
  ★ 기존 CSV 는 건드리지 않는다. 별도 파일로 낸다(구 라벨 병기용).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "corpus/곁눈_평가세트_120건.csv"
RECS = REPO / "corpus/public_data/gyeotnun_data"
OUT = REPO / "corpus/사칭_정답근거_재라벨_2026-08-12.csv"

# case_id -> (사칭당한 제도명 또는 None, 판단 근거)
#   None = 사칭당한 '제도' 자체가 없다(수사기관·가족·거래 사칭, 순수 창작 상품 등)
#   문자열 = 그 제도명으로 코퍼스를 조회한다. 없으면 doc=none 이 된다.
IMPERSONATED: dict[str, tuple[str | None, str]] = {
    "S01": (None, "'생활안정지원금'은 특정 제도명이 아니라 포괄 표현"),
    "S02": (None, "안전계좌 수수료 요구 — 대응하는 제도 없음"),
    "S03": ("정부24 미환급금", "미환급금 찾기 서비스는 실재하나 코퍼스에 안내문 없음"),
    "S04": ("국민연금", "국민연금 사칭. 코퍼스에는 '국민연금 출산크레딧'만 있어 일반 안내문 부재"),
    "S05": ("긴급복지 연료비 및 전기요금", "'긴급 난방비 지급' → 실재 제도"),
    "S06": (None, "경찰 수사 사칭 — 제도 아님"),
    "S07": (None, "'특별지원금 당첨'은 창작. 당첨 절차를 가진 제도가 없음"),
    "S08": ("건강보험료 환급", "환급 제도는 실재하나 코퍼스에 안내문 없음"),
    "S09": ("기초연금", "기초연금 미수령분 사칭"),
    "S10": (None, "금감원 예금 이전 요구 — 제도 아님"),
    "S11": ("기초연금", "보건복지부 기초연금 담당자 사칭"),
    "S12": (None, "검찰 안전계좌 — 제도 아님"),
    "S13": ("대환대출", "'정부 지원 저금리 대환대출'. 코퍼스에 대환대출 안내문 없음"),
    "S14": ("긴급재난지원금", "코퍼스에는 KISA 경보문만 있고 제도 안내문 없음"),
    "S15": ("민생회복 소비쿠폰", "코퍼스에는 KISA 경보문만 있고 제도 안내문 없음"),
    "S16": ("주민등록등본 발급", "정부24 민원. 코퍼스에 안내문 없음"),
    "S17": (None, "'시스템 장애'는 제도가 아니라 상황 사칭"),
    "S18": (None, "'개인정보 유출 피해보상금' 창작"),
    "S19": (None, "가족 사칭 — 제도 아님"),
    "S20": (None, "국민연금을 언급하나 상품 자체가 창작 투자상품"),
    "S21": (None, "관공서 노쇼 사기 — 거래 사칭"),
    "S22": (None, "KISA 보안공지 사칭 — 제도 아님"),
    "S23": (None, "택배 사칭 — 제도 아님"),
    "S24": (None, "'연금 지급 지연'만으로는 기초연금·국민연금 중 무엇인지 특정 불가"),
    "S25": ("건강보험료 환급", "건강보험공단 환급금 사칭. 코퍼스에 안내문 없음"),
    "S26": (None, "의원실 노쇼 사기 — 거래 사칭"),
    "S27": ("종합소득세 환급", "국세청 사칭. 코퍼스에 안내문 없음"),
    "S28": (None, "금감원 예치 요구 — 제도 아님"),
    "S29": ("서민금융 활성화 지원(근로자햇살론 보증사업)", "햇살론 사전승인 사칭 → 실재 제도"),
    "S30": ("노인일자리 및 사회활동 지원사업", "노인일자리 참여자 모집 사칭 → 실재 제도"),
    "S31": ("건강보험 자격", "자격 변동 확인 사칭. 코퍼스에 안내문 없음"),
    "S32": ("에너지바우처", "'난방비 특별지원금' → 냉난방비 지원 제도"),
    "S33": (None, "퇴직연금 투자 권유 — 창작 상품"),
    "S34": (None, "가족 사고 합의금 — 제도 아님"),
    "S35": (None, "보건소 납품 사칭 — 거래 사칭"),
    "S36": (None, "해외 결제 승인 알림 — 제도 아님"),
    "S37": ("모바일 신분증", "발급 신청 사칭. 코퍼스에 안내문 없음"),
    "S38": ("기초연금", "복지로 점검을 빌미로 한 기초연금 사칭"),
    "S39": ("장기요양급여이용지원", "장기요양 등급 심사 결과 통보 사칭 → 실재 제도"),
    "S40": (None, "지자체 행사 참가비 — 거래 사칭"),
    # ---- 홀드아웃 사칭 10건 (2026-08-12 승인. 평가셋과 같은 기준)
    "H21": ("주민등록 사실조사", "행안부 사칭. 코퍼스에 안내문 없음"),
    "H22": ("대환대출", "은행 대출 신용보강 사칭. 코퍼스에 안내문 없음"),
    "H23": (None, "경찰 사이버수사대 자금 이전 — 제도 아님"),
    "H24": ("에너지바우처", "'정부 에너지 지원금' → 냉난방비 지원 제도"),
    "H25": ("국민연금", "국민연금공단 미납 사칭. 코퍼스에 일반 안내문 없음"),
    "H26": (None, "가족 사칭 — 제도 아님"),
    "H27": (None, "휴대폰 보안 업데이트 — 제도 아님"),
    "H28": (None, "지자체 케이터링 선결제 — 거래 사칭"),
    "H29": ("어르신 교통비 지원", "지자체 사업. 코퍼스의 '교통시설 이용지원'은 보훈대상자용이라 다름"),
    "H30": (None, "노후자금 운용 — 창작 투자상품"),
}
HOLD = REPO / "api/tests/fixtures/holdout/holdout_30.csv"


def load_titles() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for p in sorted(RECS.glob("records_*.jsonl")):
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            idx.setdefault(r.get("title", ""), r)
    return idx


def main() -> None:
    if not RECS.exists():
        sys.exit(f"[중단] 코퍼스 원본이 없다: {RECS}")
    titles = load_titles()
    rows = {r["case_id"]: r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig"))}
    rows.update({r["case_id"]: r for r in csv.DictReader(HOLD.open(encoding="utf-8-sig"))})

    missing = [c for c in IMPERSONATED if c not in rows]
    if missing:
        sys.exit(f"[중단] 평가셋에 없는 case_id: {missing}")
    unlabeled = [c for c, r in rows.items() if r["유형"] == "사칭" and c not in IMPERSONATED]
    if unlabeled:
        sys.exit(f"[중단] 재라벨이 빠진 사칭 케이스: {unlabeled}")

    COLS = ["case_id", "입력채널", "평가용_제시문구", "사칭대상_제도",
            "정답doc_URL", "정답scam_URL", "doc_라벨", "판단근거", "구_출처_URL"]
    out = []
    for cid, (prog, why) in sorted(IMPERSONATED.items()):
        r = rows[cid]
        doc_url = ""
        if prog:
            rec = titles.get(prog)
            if rec:
                doc_url = rec.get("source_url") or ""
        out.append(dict(zip(COLS, [
            cid, r["입력채널"], r["평가용_제시문구"], prog or "(제도 아님)",
            doc_url, r["출처_URL"],                    # scam = 기존 경보문 승계
            "doc" if doc_url else "none",
            why, r["출처_URL"],
        ])))

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(out)

    import collections
    doc = [o for o in out if o["doc_라벨"] == "doc"]
    none_prog = [o for o in out if o["사칭대상_제도"] == "(제도 아님)"]
    none_absent = [o for o in out if o["doc_라벨"] == "none" and o["사칭대상_제도"] != "(제도 아님)"]
    print(f"재라벨 표: {OUT.relative_to(REPO)}  {len(out)}건")
    print(f"  doc  (사칭당한 제도가 코퍼스에 실재)   : {len(doc):2}건  "
          + ", ".join(o["case_id"] for o in doc))
    print(f"  none (제도 자체가 없음 — 창작·거래·가족): {len(none_prog):2}건")
    print(f"  none (제도는 실재하나 코퍼스에 없음)    : {len(none_absent):2}건  "
          + ", ".join(o["case_id"] for o in none_absent))
    print(f"  scam (수법 경보문) — 전 건 승계        : {sum(1 for o in out if o['정답scam_URL']):2}건")
    print("\n  코퍼스에 없어 수집이 필요한 제도:")
    for p, n in collections.Counter(o["사칭대상_제도"] for o in none_absent).most_common():
        print(f"     {p}  ({n}건)")


if __name__ == "__main__":
    main()
