"""warning_case 안의 C 성격(기관 활동 발표) 문서 화면 (2026-08-13)

실행(호스트): python3 api/experiments/diag_warning_case_c.py [OFFICIAL_ID_FILE]
  OFFICIAL_ID_FILE 은 OFFICIAL_DOCS 의 id 목록(한 줄 1개). 없으면 표시만 '-' 로 둔다.
    docker compose exec -T api python3 -c "import sys;sys.path.insert(0,'/app');
    from services import corpus_index as ci;print('\n'.join(d.id for d in ci.OFFICIAL_DOCS))"

★ 화면(screen)이지 판정이 아니다. 결과는 사람이 읽고 확정한다.
★ 방향이 press_release 때와 반대다 - '뺄 것'을 고르므로 **애매하면 B 유지**다.
  잘못 빼면 진짜 경보문이 조용히 내려간다.
"""
from __future__ import annotations

import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "corpus" / "collect" / "warning_case_C후보_검토표_2026-08-13.csv"

C_WORDS = re.compile(
    r"(업무협약|기술 ?협약|협약 ?체결|협약식|MOU|MoU|시상|수상|표창|출범|개소|발족|"
    r"공모전|공모|채용|모집|세미나|포럼|워크숍|간담회|설명회|컨퍼런스|웨비나|협의체|"
    r"협의회|착수보고|위촉|임명|성과|실적|경진대회|평가위원|현판식|발표회|국제회의|행사)")
B_MODUS = re.compile(
    r"(사칭|가장하여|가장한|속여|명목으로|빙자|유도|요구하|클릭하도록|설치하도록|송금|"
    r"이체하도록|탈취|악성 ?앱|피싱 ?사이트|문자를 발송|링크를 누르)")
B_ALERT = re.compile(r"(주의|경보|유의|수법|사기|피해 예방)")
# ★ 이 표현이 보이면 빼지 않는다(현상 유지). 빼는 쪽 실수를 줄이기 위한 안전장치다.
KEEP = re.compile(r"(상담소|주의보|경보 ?발령|이런 문자|수법|끊기능력|피해 ?사례)")


def body(r: dict) -> str:
    t = re.sub(r"\s+", " ", (r.get("content") or "")).strip()
    return re.sub(r"^\d+\s+\d{4}-\d{2}-\d{2}\s+\d+\s*", "", t)   # 스크랩 메타 제거


def head(r: dict, n: int = 2) -> str:
    parts = [x.strip() for x in re.split(r"(?<=다\.)\s|(?<=[.!?])\s", body(r)) if x.strip()]
    return " ".join(parts[:n])[:150]


def main() -> None:
    official = set()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        official = set(Path(sys.argv[1]).read_text().split())

    recs = {}
    for p in glob.glob(str(ROOT / "corpus/public_data/gyeotnun_data/records_*.jsonl")):
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            recs[r["id"]] = r
    warn = [r for r in recs.values() if r.get("data_type") == "warning_case"]

    rows = []
    for r in warn:
        blob = f"{r.get('title','')} {head(r, 3)}"
        c = sorted(set(C_WORDS.findall(blob)))
        m = sorted(set(B_MODUS.findall(blob)))
        a = sorted(set(B_ALERT.findall(blob)))
        if not (c and not (m and a)):
            continue                       # C 후보 아님 - 손대지 않는다
        bd = body(r)
        if len(bd) < 200:
            prop, why = "B 유지", "본문이 스크랩 메타데이터뿐이라 판단 불가 - 현상 유지"
        elif KEEP.search(blob):
            prop, why = "B 유지", "제목·머리에 수법·주의보·사례 표현이 있다 - 현상 유지"
        elif "118" in blob or "신고" in (r.get("title") or ""):
            prop, why = "B 유지", "신고·상담 창구 안내라 사용자 행동에 직접 닿는다 - 현상 유지"
        else:
            scam = bool(re.search(
                r"(보이스피싱|스미싱|피싱|불법스팸|스팸|전기통신금융사기|악성문자|사기)", blob))
            prop = "C"
            why = (f"사기·스팸 주제이나 문서 성격은 기관 활동 발표({'·'.join(c[:2])}) - 수법 묘사 없음"
                   if scam else f"사기·스팸과 무관한 기관 활동 발표({'·'.join(c[:2])})")
        rows.append({
            "문서id": r["id"], "발행일": r.get("published_at", ""),
            "OFFICIAL_DOCS": "O" if r["id"] in official else "-",
            "제목": r.get("title", ""), "앞두문장": head(r),
            "자동C신호": "·".join(c), "자동B신호": "·".join(m + a),
            "제안분류": prop, "근거": why, "확정분류(사람이 채움)": "", "비고": "",
        })

    rows.sort(key=lambda x: (x["제안분류"], x["발행일"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"warning_case {len(warn)}건 → C 후보 {len(rows)}건")
    print("제안:", dict(collections.Counter(x["제안분류"] for x in rows)))
    print(f"저장: {OUT}")
    print("※ 화면이다. 적용하지 않는다. 사람이 확정한다.")


if __name__ == "__main__":
    main()
