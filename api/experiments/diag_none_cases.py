"""작업5-① '근거 없음이 정답'(none) 8건에서 시스템이 실제로 무엇을 내보냈는지 분해 (2026-08-09)
실행: docker compose exec api python3 experiments/diag_none_cases.py

★ 측정만 한다. 임계값을 건드리지 않는다.

왜 이걸 성공률보다 먼저 보는가
  none 라벨은 '가리킬 공식 문서가 없는' 케이스다(출처_URL 이 포털 홈).
  기대판단은 전부 '확인불가'다. 여기서 근거를 붙이면 그게 곧 '잘못된 근거 제시'의
  실체다 - 성공률 지표에는 잡히지 않는다.

무엇을 보는가 (케이스별)
  · 붙은 참고자료가 무엇인가(제목/기관/점수)
  · 점수가 표시 하한(EMBEDDING_MIN_SCORE)과 확신 임계(CONFIDENT) 사이인가
    = '임계 근처 문서 노출'인가
  · 판정(verdict_hint)이 확인불가로 유지됐는가 = 사용자에게 단정했는가
  · 사기사례 매칭이 붙었는가(별도 신호)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app")
import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)

from services import embeddings as emb  # noqa: E402
from services import search  # noqa: E402

EVAL_CSV = Path("/corpus/곁눈_평가세트_30건.csv")
OUT = Path("/app/data/diag_none_cases.json")

MIN_SCORE = emb.EMBEDDING_MIN_SCORE
CONFIDENT = search.CONFIDENT_MATCH_THRESHOLD
VK = {"needs_check": "확인됨", "partially_matched": "의심", "no_source_found": "확인불가"}


def is_portal_home(url: str) -> bool:
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return False
    return bool(p.netloc) and p.path.rstrip("/") == "" and not p.query


def main() -> None:
    rows = [r for r in csv.DictReader(EVAL_CSV.open(encoding="utf-8-sig"))
            if is_portal_home(r.get("출처_URL", ""))]
    print(f"none(근거 없음이 정답) 라벨 {len(rows)}건")
    print(f"표시 하한 EMBEDDING_MIN_SCORE={MIN_SCORE:.4f} / 확신 임계 CONFIDENT={CONFIDENT:.4f}\n")

    out = []
    for r in rows:
        text = r["평가용_제시문구"]
        ev = search.collect_evidence(text)
        try:
            hits = emb.match_embedding_docs(text, limit=3)
        except emb.EmbeddingUnavailableError:
            hits = []

        refs = ev.references
        scam = [s for s in ev.signals if s["key"] == "similar_scam_case"]
        # 붙은 참고자료 중 '임계 근처'(표시는 되지만 확신은 못 하는 구간) 건수
        near = [(s, d) for s, d in hits if MIN_SCORE <= s < CONFIDENT]
        over = [(s, d) for s, d in hits if s >= CONFIDENT]

        rec = {
            "id": r["case_id"], "기대판단": r.get("기대판단", ""),
            "text": text, "gold_url": r.get("출처_URL", ""),
            "n_refs": len(refs),
            "verdict": ev.verdict_hint, "verdict_ko": VK.get(ev.verdict_hint, ev.verdict_hint),
            "top_score": round(hits[0][0], 4) if hits else None,
            "near_threshold": len(near), "over_confident": len(over),
            "n_scam_signals": len(scam),
            "refs": [{"title": d.title[:52], "publisher": d.source_agency,
                      "score": round(s, 4)} for s, d in hits[:len(refs)]],
        }
        out.append(rec)

        head = "근거 안 붙음 ✅" if rec["n_refs"] == 0 else f"근거 {rec['n_refs']}건 붙음"
        print("=" * 78)
        print(f"[{rec['id']}] 기대판단={rec['기대판단']} → 실제판정={rec['verdict_ko']}  |  {head}")
        print(f"  입력: {text[:66]}")
        if rec["refs"]:
            for x in rec["refs"]:
                band = ("확신구간" if x["score"] >= CONFIDENT else
                        "임계근처(표시만)" if x["score"] >= MIN_SCORE else "하한미만")
                print(f"    · {x['score']:.4f} [{band}] {x['title']} / {x['publisher']}")
        if rec["n_scam_signals"]:
            print(f"    · 사기사례 신호 {rec['n_scam_signals']}건(별도 인덱스)")

    print("\n" + "=" * 78)
    print("집계")
    print("=" * 78)
    no_ref = [x for x in out if x["n_refs"] == 0]
    with_ref = [x for x in out if x["n_refs"] > 0]
    verdict_ok = [x for x in out if x["verdict"] == "no_source_found"]
    over_conf = [x for x in out if x["over_confident"]]
    print(f"  근거를 아예 안 붙임(가장 깨끗)     : {len(no_ref)}/{len(out)}  {[x['id'] for x in no_ref]}")
    print(f"  참고자료를 붙임                    : {len(with_ref)}/{len(out)}  {[x['id'] for x in with_ref]}")
    print(f"    └ 전부 임계 근처(표시만, 확신 X) : "
          f"{sum(1 for x in with_ref if not x['over_confident'])}/{len(with_ref)}")
    print(f"    └ 확신 임계를 넘은 문서 노출     : {len(over_conf)}  {[x['id'] for x in over_conf]}")
    print(f"  ★ 판정이 '확인불가'로 유지된 건수  : {len(verdict_ok)}/{len(out)}")
    print()
    if len(verdict_ok) == len(out):
        print("  → 참고자료는 붙었지만 **사용자에게 단정하지 않았다**. 표시(0.6155)와")
        print("     확신(0.6790)을 분리한 설계가 의도대로 동작했다는 뜻이다.")
    else:
        bad = [x['id'] for x in out if x["verdict"] != "no_source_found"]
        print(f"  → ★ 단정한 케이스가 있다: {bad} - 이건 실제 결함이다.")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
