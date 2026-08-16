"""근거는 붙었는데 '다른 제도' — 확대 112건 실측 (2026-08-16, 라이브 실사용 발견)

실행: docker compose exec -T api python3 experiments/exp_wrong_program_refs.py

■ 왜
  라이브에서 "[국민건강보험공단] 건강보험료 환급금 …" 입력에
  "의료급여수급권자 일반건강검진비 지원"이 근거로 붙었다. 유사도 0.6539 로
  표시 임계(0.6155)와 확신 임계(0.6790) **사이**다.

  ★ 임계값을 올리자는 게 아니다. **규모를 먼저 안다.**

■ 두 가지로 센다 (LLM 호출 없음)
  (A) 라벨 기반 — 엄밀하지만 사칭 일부만 덮는다
      corpus/사칭_정답근거_재라벨_2026-08-12.csv 의 doc_라벨 = "none" 은
      **코퍼스에 맞는 공식 문서가 아예 없다**는 뜻이다. 그런 건에 공식 문서가
      근거로 붙었다면 그건 정의상 '다른 제도'다.
  (B) 구간 기반 — 전수지만 '다른 제도'인지는 판정하지 않는다
      최고 유사도가 [표시임계, 확신임계) 구간에 있으면서 근거가 붙은 건.
      이 구간이 곧 '약한 근거로 무언가를 붙인' 모집단이다.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app")

from services import corpus_index, embeddings, search  # noqa: E402
from services.masking import mask_text  # noqa: E402

EVAL = Path("/corpus/곁눈_평가세트_120건.csv")
RELABEL = Path("/corpus/사칭_정답근거_재라벨_2026-08-12.csv")

# 문서 URL -> data_type. '제도 안내문'은 official_reference 다(복지로 서비스 안내 등).
_DOC_TYPE = {d.source_url: getattr(d, "data_type", "") for d in corpus_index.OFFICIAL_DOCS}

MIN_SHOW = 0.6155      # 표시 임계 (local)
MIN_CONFIDENT = search._CONFIDENT_BY_PROVIDER["local"]


def main() -> None:
    rows = [r for r in csv.DictReader(EVAL.open(encoding="utf-8-sig"))
            if r["입력채널"] != "음성"]
    label = {r["case_id"]: r["doc_라벨"] for r in csv.DictReader(RELABEL.open(encoding="utf-8-sig"))}

    band, band_with_ref, no_doc_but_ref, above = [], [], [], []
    for r in rows:
        cid = r["case_id"]
        text = mask_text(r["평가용_제시문구"]).text
        hits = embeddings.match_embedding_docs(text)
        top = max((s for s, _ in hits), default=0.0)
        ev = search.collect_evidence(text, domain=None)
        # ★ 경보문과 '제도 안내문' 을 가른다.
        #   사칭 건에 사기 경보문이 붙은 것은 **정확한 근거**다 - 그걸 '다른 제도'로
        #   세면 숫자가 부풀고, 없는 문제를 고치려 들게 된다.
        alerted = any(sg["key"] == "official_alert_matched" for sg in ev.signals)
        # ★ 제목 낱말이 아니라 코퍼스의 data_type 라벨로 가른다.
        #   제목만 보면 "공식/금융위원회" 같은 경보문이 제도 안내문으로 잘못 넘어간다.
        program_refs = [x for x in ev.references
                        if _DOC_TYPE.get(x.get("url") or "") == "official_reference"]
        rec = {"case_id": cid, "유형": r["유형"], "top": top,
               "refs": len(ev.references),
               "top_title": (hits[0][1].title if hits else ""),
               "입력": text[:56]}
        if MIN_SHOW <= top < MIN_CONFIDENT:
            band.append(rec)
            if ev.references:
                band_with_ref.append(rec)
        elif top >= MIN_CONFIDENT:
            above.append(rec)
        # (A) 맞는 문서가 없다고 라벨된 건인데 근거가 붙었나
        rec["alerted"] = alerted
        rec["program_titles"] = [x.get("title") for x in program_refs][:2]
        if label.get(cid) == "none" and program_refs:
            no_doc_but_ref.append(rec)

    n = len(rows)
    print(f"확대 평가셋 {n}건 · 표시 임계 {MIN_SHOW} · 확신 임계 {MIN_CONFIDENT}\n")

    print("■ (B) 구간 기반 — 최고 유사도가 [표시, 확신) 사이인 건")
    print(f"    구간에 든 건        {len(band)}건")
    print(f"    그중 근거가 붙은 건 {len(band_with_ref)}건")
    print(f"    유형별: {dict(Counter(x['유형'] for x in band_with_ref))}")
    print(f"    (참고) 확신 임계 이상 {len(above)}건\n")

    print("■ (A) 라벨 기반 — '맞는 공식 문서가 코퍼스에 없다'고 라벨된 건인데 근거가 붙음")
    labeled_none = [c for c in label if label[c] == "none" and any(r["case_id"] == c for r in rows)]
    print(f"    라벨 none 이면서 이 평가셋에 있는 건 {len(labeled_none)}건")
    print(f"    ★ 그중 **제도 안내문**이 붙은 건 {len(no_doc_but_ref)}건 = 정의상 '다른 제도'")
    print("       (사기 경보문이 붙은 건은 제외했다 - 사칭 건에 경보문은 정확한 근거다)")
    print(f"    유형별: {dict(Counter(x['유형'] for x in no_doc_but_ref))}\n")

    print("■ (A) 상세 — 무엇이 붙었나")
    for x in sorted(no_doc_but_ref, key=lambda z: -z["top"]):
        print(f"    {x['case_id']:<5} [{x['유형']}] 유사도 {x['top']:.4f} · 근거 {x['refs']}건")
        print(f"          입력: {x['입력']}")
        print(f"          붙은 제도 안내문: {x['program_titles']}")


if __name__ == "__main__":
    main()
