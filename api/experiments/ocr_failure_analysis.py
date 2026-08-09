"""
로컬 OCR 근거검색 저하 원인 분해 (실험 A, 2026-08-05)
실행: docker compose exec api python3 experiments/ocr_failure_analysis.py

★ services/ocr.py 를 수정하지 않는다. 원인 규명과 기획서 근거 확보가 목적이다.
★ 평가셋을 검색 코퍼스에 넣지 않는다 - 읽기만 한다.

측정 설계
  같은 30장(ocr_eval)에 대해 세 가지 텍스트를 나란히 놓는다.
    GT      : 평가세트 원문 (정답)
    vision  : Claude Vision 추출 (상한)
    easyocr : 로컬 OCR 추출 (말풍선 필터 적용 = 현재 코드 상태)
  세 텍스트를 각각 같은 collect_evidence() 에 넣어 근거검색 결과를 본다.

  ★ 조건이 두 번 바뀌었으므로 기준선을 다시 잡는다:
    - 0.600 은 말풍선 필터 도입 "전" 값이다(2026-08-04 이전)
    - 그때는 임베딩도 Upstage 였다. 지금은 로컬 e5-small-ko-v2 다.
    → GT/vision/easyocr 을 모두 "지금 코드"로 다시 재야 OCR 만의 효과가 분리된다.

원인 분류(중복 표기)
  1) 기관명 오인식   2) 조사·어미 손상   3) 문장 누락·잘림
  4) UI 텍스트 혼입  5) 숫자·기호 오류   6) 기타
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, "/app")

from services import local_ocr, ocr as prod_ocr, search  # noqa: E402

CSV_PATH = Path("/corpus/곁눈_평가세트_30건.csv")
IMG_DIR = Path("/app/tests/fixtures/ocr_eval")
OUT_PATH = Path("/app/data/ocr_failure_analysis.json")
SENDER = "정부지원금 안내센터"

# 평가 코퍼스에 등장하는 공공기관/제도 명칭. CSV 의 참고_출처·제시문구에서 뽑았다.
# ★ 이 목록은 "기관명이 망가졌는지" 판정에만 쓴다. 후보정 사전이 아니다(그건 실험 B).
AGENCY_TERMS = [
    "복지로", "정부24", "국민연금", "국민연금공단", "건강보험", "국민건강보험공단",
    "보건복지부", "질병관리청", "국세청", "한국사회보장정보원", "근로복지공단",
    "주민센터", "행정복지센터", "고용노동부", "여성가족부", "국가보훈부",
    "노후준비서비스", "기초연금", "장애인일자리지원", "농어가목돈마련저축",
    "주거상향", "개발제한구역", "독립유공자", "산재근로자", "노인복지",
]

_JOSA = ("은", "는", "이", "가", "을", "를", "에", "의", "로", "으로", "와", "과",
         "도", "만", "에서", "부터", "까지", "입니다", "습니다", "합니다", "하세요")
_DIGIT_SYM = re.compile(r"[\d%~\-.,·/()]")


def norm(s: str) -> str:
    return " ".join((s or "").split())


def classify_diff(gt: str, got: str) -> dict:
    """GT 대비 OCR 출력의 차이를 6가지로 분류한다(중복 가능).

    difflib 의 opcode 로 실제 편집 지점을 뽑아 각각을 판정한다 - 문장 전체를
    눈대중으로 라벨링하지 않고, 바뀐 조각마다 근거를 남긴다.
    """
    g, o = norm(gt), norm(got)
    flags = {k: False for k in
             ("기관명오인식", "조사어미손상", "문장누락잘림", "UI혼입", "숫자기호오류", "기타")}
    detail = []

    sm = SequenceMatcher(None, g, o)
    ratio = sm.ratio()

    # 1) 기관명 오인식 - GT 에 있던 기관 용어가 OCR 결과에서 사라졌는가
    for term in AGENCY_TERMS:
        if term in g and term not in o:
            flags["기관명오인식"] = True
            # 어떻게 망가졌는지 근처 조각을 찾아 남긴다
            best, bestr = "", 0.0
            for i in range(max(0, len(o) - len(term) + 1)):
                cand = o[i:i + len(term)]
                r = SequenceMatcher(None, term, cand).ratio()
                if r > bestr:
                    best, bestr = cand, r
            detail.append(f"기관명 '{term}' → '{best}'(유사도 {bestr:.2f})")

    # 2~5) 편집 지점별 판정
    lost_chars = 0
    added_chars = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        src, dst = g[i1:i2], o[j1:j2]
        if tag == "delete":
            lost_chars += len(src)
        elif tag == "insert":
            added_chars += len(dst)
        else:  # replace
            lost_chars += len(src)
            added_chars += len(dst)

        seg = (src or "") + (dst or "")
        if _DIGIT_SYM.search(seg) and src.strip() and dst.strip():
            flags["숫자기호오류"] = True
            detail.append(f"숫자·기호 '{src}' → '{dst}'")
        # 조사/어미: 짧은 치환이고 조사·어미 문자열이 걸린 경우
        if tag == "replace" and len(src) <= 4 and any(j in src or j in dst for j in _JOSA):
            flags["조사어미손상"] = True
            detail.append(f"조사·어미 '{src}' → '{dst}'")

    # 3) 문장 누락·잘림 - GT 문자의 상당량이 사라짐
    if lost_chars >= max(8, len(g) * 0.15):
        flags["문장누락잘림"] = True
        detail.append(f"누락 {lost_chars}자 (GT {len(g)}자의 {lost_chars/len(g)*100:.0f}%)")

    # 4) UI 혼입 - GT 에 없는 문자가 상당량 추가됨
    if added_chars >= max(8, len(g) * 0.15):
        flags["UI혼입"] = True
        detail.append(f"추가 {added_chars}자")

    if not any(flags.values()) and ratio < 0.999:
        flags["기타"] = True
        detail.append(f"기타 차이(유사도 {ratio:.3f})")

    return {"flags": flags, "detail": detail, "ratio": round(ratio, 3),
            "lost_chars": lost_chars, "added_chars": added_chars}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30

    out = {"cases": [], "note": "말풍선 필터 적용 상태, 임베딩=로컬 e5-small-ko-v2"}
    for i, row in enumerate(rows, 1):
        cid, gt = row["case_id"], row["평가용_제시문구"]
        img = IMG_DIR / f"{cid}.jpg"
        print(f"[{i:>2}/30] {cid}", flush=True)

        v = prod_ocr.extract_from_image(img.read_bytes()).text
        e = local_ocr.extract(img, provider="easyocr", sender_name=SENDER).text

        rec = {"case_id": cid, "유형": row["유형"], "gt": gt, "vision": v, "easyocr": e}
        for name, txt in (("gt", gt), ("vision", v), ("easyocr", e)):
            ev = search.collect_evidence(txt)
            rec[f"{name}_refs"] = len(ev.references)
            rec[f"{name}_verdict"] = ev.verdict_hint
        rec["diff"] = classify_diff(gt, e)
        out["cases"].append(rec)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    n = len(out["cases"])
    print("\n════ 근거검색 성공률 (같은 검색 스택, 입력 텍스트만 다름) ════")
    for k in ("gt", "vision", "easyocr"):
        ok = sum(1 for c in out["cases"] if c[f"{k}_refs"] > 0)
        print(f"  {k:<9} {ok}/{n} = {ok/n:.3f}")

    print("\n════ 원인 분포 (중복 표기) ════")
    keys = ["기관명오인식", "조사어미손상", "문장누락잘림", "UI혼입", "숫자기호오류", "기타"]
    print(f"  {'유형':<14}{'발생':>6}{'그중 검색실패':>14}")
    for k in keys:
        hit = [c for c in out["cases"] if c["diff"]["flags"][k]]
        fail = [c for c in hit if c["easyocr_refs"] == 0]
        print(f"  {k:<14}{len(hit):>6}{len(fail):>14}")

    fails = [c for c in out["cases"] if c["easyocr_refs"] == 0]
    print(f"\n════ easyocr 근거검색 실패 {len(fails)}건 상세 ════")
    for c in fails:
        on = [k for k in keys if c["diff"]["flags"][k]]
        print(f"  {c['case_id']} ({c['유형']}) 유사도={c['diff']['ratio']} 원인={on}")
        print(f"     GT : {norm(c['gt'])[:70]}")
        print(f"     OCR: {norm(c['easyocr'])[:70]}")
        for d in c["diff"]["detail"][:3]:
            print(f"     · {d}")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
