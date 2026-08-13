"""금융위원회 보도자료 수집기 (2026-08-13)

실행: python3 tools/collect_fsc.py [--limit N] [--sleep 1.0]

■ 이 스크립트가 하지 않는 것 (중요)
  - 검색 인덱스에 넣지 않는다. 결과는 corpus/collect/ 에만 쓴다.
    ★ corpus/public_data/gyeotnun_data/records_collected_*.jsonl 은 corpus_index 가
      기동 시 자동으로 읽는 경로다. 그 이름·그 위치를 절대 쓰지 않는다.
      사람이 검수한 뒤 옮기는 것이 마지막 단계이고, 이 스크립트의 일이 아니다.
  - 중복을 지우지 않는다. 후보 목록만 낸다(수집 지시 '추가 3').
  - 분류를 확정하지 않는다. 자동 규칙은 후보를 정렬하는 데만 쓰고 사람이 확인한다
    (docs/evaluation/금융코퍼스_수집조사_2026-08-12.md §2 의 규칙 그대로).

■ 수집 대상
  https://www.fsc.go.kr/no010101  (보도자료)
  robots.txt: User-agent: * / Allow: /   (2026-08-13 확인)
  제목 검색어로만 받는다 - 전체 15,000여 건을 훑지 않는다.

■ 예의
  요청 간 1초 쉬고, User-Agent 로 우리를 밝힌다. 실패하면 재시도하지 않고 남긴다.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.fsc.go.kr"
LIST = BASE + "/no010101"
UA = "gyeotnun-research/1.0 (public-data collection for a scam-check service)"
OUT_DIR = Path(__file__).resolve().parents[1] / "corpus" / "collect"

# 제목에 이 말이 들어간 보도자료만 받는다.
QUERIES = ["보이스피싱", "스미싱", "피싱", "전기통신금융사기", "불법사금융"]

# ---- 분류 자동 제안 규칙 (사람 확인용 후보 정렬. 확정이 아니다)
#      기준 원문: docs/evaluation/금융코퍼스_수집조사_2026-08-12.md §2
B_MODUS = ["사칭", "가장하여", "가장한", "속여", "명목으로", "빙자", "유도",
           "요구하", "클릭하도록", "설치하도록", "송금하도록", "이체하도록"]
B_ALERT = ["주의", "경보", "유의", "수법", "사기"]
A_HINTS = ["신청 대상", "지원 대상", "신청대상", "지원대상", "신청 자격", "신청자격",
           "신청 조건", "신청조건", "신청 방법", "신청방법", "신청 절차", "신청절차",
           "접수 기간", "접수기간", "신청 기한", "신청기한"]


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</tr>|</div>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def list_page(query: str, page: int) -> tuple[list[str], int]:
    """검색 결과 한 페이지의 상세 id 목록과 **전체 쪽수**를 돌려준다.

    ★ num-page-total 은 건수가 아니라 쪽수다. 무필터 목록에서 15,282건인데
      이 값이 1,529 로 나오는 것으로 확인했다(10건/쪽). 건수로 착각하면
      첫 쪽만 받고 끝난다.
    """
    qs = urllib.parse.urlencode({"srchKey": "sj", "srchText": query, "curPage": page})
    h = fetch(f"{LIST}?{qs}")
    ids = re.findall(r'href="/no010101/(\d+)\?', h)
    m = re.search(r'num-page-total"><em>([\d,]+)', h)
    total = int(m.group(1).replace(",", "")) if m else 0
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out, total


def detail(doc_id: str) -> dict | None:
    h = fetch(f"{LIST}/{doc_id}")
    j = h.find('<div class="board-view-wrap">')
    if j < 0:
        return None
    seg = h[j:]
    title = re.search(r'<div class="subject">(.*?)</div>', seg, re.S)
    day = re.search(r'<div class="day">\s*<span>([\d-]+)</span>', seg, re.S)
    dept = re.findall(r"<strong>담당부서</strong>(.*?)</span>", seg, re.S)
    body = re.search(r'<div class="body">(.*?)<div class="btn-wrap"', seg, re.S) \
        or re.search(r'<div class="body">(.*?)</div>\s*</div>\s*</div>', seg, re.S)
    files = re.findall(r'<a href="(/comm/getFile\?[^"]+)" title="([^"]+)"', seg)
    return {
        "id": f"fsc-{doc_id}",
        "source_agency": "금융위원회",
        "source_url": f"{LIST}/{doc_id}",
        "title": strip_tags(title.group(1)) if title else "",
        # ★ 발행일은 반드시 기록한다(수집 지시 '추가 2'). 없으면 빈 문자열로 두고
        #   추정하지 않는다 - 없는 것을 채워 넣으면 그게 곧 날조다.
        "published_at": day.group(1) if day else "",
        "dept": strip_tags(dept[0]) if dept else "",
        "content": strip_tags(body.group(1))[:20000] if body else "",
        "attachments": [{"url": BASE + html.unescape(u), "name": html.unescape(n)}
                        for u, n in files][:10],
        "data_type": "press_release",
        "collected_at": "2026-08-13",
    }


def suggest_class(rec: dict) -> tuple[str, str]:
    """A/B/C 자동 제안. ★ 확정이 아니다. 사람이 확인한다."""
    blob = f"{rec['title']} {rec['content']}"
    modus = [k for k in B_MODUS if k in blob]
    alert = [k for k in B_ALERT if k in blob]
    a_hits = [k for k in A_HINTS if k in blob]

    if modus and alert:
        # A·B 둘 다면 B 우선 (기준 §2 의 갈림 규칙)
        return "B", f"수법어({','.join(modus[:3])}) + 경보어({','.join(alert[:2])})"
    if len(set(a_hits)) >= 2:
        return "A", f"신청요건어 {len(set(a_hits))}종({','.join(sorted(set(a_hits))[:3])})"
    # 애매하면 C. 잘못 넣는 것보다 안 넣는 게 낫다.
    reason = "B·A 요건 미달"
    if modus and not alert:
        reason = f"수법어는 있으나 경보어 없음({','.join(modus[:2]) })"
    elif alert and not modus:
        reason = f"경보어는 있으나 수법 묘사 없음({','.join(alert[:2])})"
    return "C", reason


def load_existing() -> tuple[set, dict]:
    """이미 가진 코퍼스의 URL·제목. 중복 '후보'를 표시하는 데만 쓴다."""
    urls, titles = set(), {}
    d = Path(__file__).resolve().parents[1] / "corpus" / "public_data" / "gyeotnun_data"
    for p in sorted(d.glob("records_*.jsonl")):
        for line in p.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("source_url"):
                urls.add(r["source_url"].strip())
            t = re.sub(r"[^\w가-힣]", "", r.get("title", ""))[:40]
            if t:
                titles[t] = r.get("id", "")
    return urls, titles


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0이면 제한 없음")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    known_urls, known_titles = load_existing()
    print(f"기존 코퍼스: URL {len(known_urls)}개 · 제목 {len(known_titles)}개")

    ids: dict[str, list[str]] = {}
    for q in QUERIES:
        got, pages = [], None
        page = 1
        while True:
            batch, pages = list_page(q, page)
            if not batch:
                break
            got += batch
            print(f"  [{q}] {page}/{pages}쪽 {len(batch)}건 (누적 {len(got)})")
            if page >= (pages or 1) or page >= 30:
                break
            page += 1
            time.sleep(args.sleep)
        for i in got:
            ids.setdefault(i, []).append(q)
        time.sleep(args.sleep)

    order = list(ids)
    if args.limit:
        order = order[:args.limit]
    print(f"\n중복 제거 후 상세 대상 {len(order)}건 (검색어 합집합)")

    recs, failed = [], []
    for n, doc_id in enumerate(order, 1):
        try:
            r = detail(doc_id)
        except Exception as e:  # noqa: BLE001 - 실패는 재시도하지 않고 그대로 남긴다
            failed.append((doc_id, str(e)[:80]))
            r = None
        if r is None:
            failed.append((doc_id, "본문 구조 불일치"))
        else:
            r["matched_queries"] = ids[doc_id]
            r["suggest_class"], r["suggest_reason"] = suggest_class(r)
            key = re.sub(r"[^\w가-힣]", "", r["title"])[:40]
            r["dup_url"] = r["source_url"] in known_urls
            r["dup_title_of"] = known_titles.get(key, "")
            recs.append(r)
        if n % 10 == 0:
            print(f"  상세 {n}/{len(order)}")
        time.sleep(args.sleep)

    out = OUT_DIR / "fsc_보도자료_2026-08-13.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n저장(스테이징, 인덱스 아님): {out}  {len(recs)}건")
    if failed:
        print(f"실패 {len(failed)}건: {failed[:10]}")

    from collections import Counter
    print("자동 제안 분포:", dict(Counter(r["suggest_class"] for r in recs)))
    print("발행일 없음:", sum(1 for r in recs if not r["published_at"]), "건")
    dups = [r for r in recs if r["dup_url"] or r["dup_title_of"]]
    print(f"중복 후보 {len(dups)}건 (지우지 않았다):")
    for r in dups[:20]:
        print(f"  {r['id']} {r['title'][:44]} url중복={r['dup_url']} 제목중복={r['dup_title_of']}")


if __name__ == "__main__":
    sys.exit(main())
