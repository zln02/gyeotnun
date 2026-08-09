"""
공개 안내 문서 수집기 (2026-08-05)
실행(호스트에서): python3 api/tools/collect_public_docs.py

목적: OFFICIAL_DOCS 의 공백(질병관리청·건강보험공단·국민연금공단·기초연금)을 메운다.

★★ 수집 원칙 ★★
  1. robots.txt 를 먼저 확인하고 금지된 경로는 절대 받지 않는다.
     - basicpension.mohw.go.kr : Disallow: /        → 전면 금지. 받지 않는다.
     - www.nhis.or.kr          : Disallow: /nhis/   → 본문 경로 금지. 받지 않는다.
     두 기관은 공개가 허용된 대체 출처(보건복지부 보도자료, 정책브리핑)로 우회한다.
  2. 요청 간격 1.5초 이상. 목록은 RSS 를 우선 쓴다(서버 부담이 가장 적다).
  3. 기관당 30~50건. 양보다 대표성.
  4. 로그인 영역·검색 페이지는 받지 않는다.
  5. 본문이 없는 문서는 저장하지 않는다(SCAM_CASES 의 메타데이터 레코드와 같은 실패 방지).

★ 평가셋 30건과 홀드아웃 5건은 이 스크립트가 읽지도 쓰지도 않는다.
  수집물은 별도 파일(records_collected_2026-08-05.jsonl)로만 저장한다.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = ROOT / "corpus" / "public_data" / "gyeotnun_data" / "records_collected_2026-08-05.jsonl"

UA = "Mozilla/5.0 (compatible; gyeotnun-research/1.0; +https://gyeotnun.duckdns.org)"
SLEEP = 1.5
TIMEOUT = 25

_TAG = re.compile(r"(?s)<[^>]+>")
_SCRIPT = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_WS = re.compile(r"[ \t ]+")
_NL = re.compile(r"\n{3,}")


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "ko"})
    with urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def to_text(page: str) -> str:
    s = _SCRIPT.sub(" ", page)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    s = "\n".join(ln.strip() for ln in s.split("\n"))
    return _NL.sub("\n\n", s).strip()


def rss_items(xml: str) -> list[dict]:
    out = []
    for block in re.findall(r"(?s)<item>(.*?)</item>", xml):
        def pick(tag):
            m = re.search(rf"(?s)<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block)
            return html.unescape(m.group(1)).strip() if m else ""
        title = pick("title").rstrip("}").strip()
        link = pick("link")
        if title and link:
            out.append({"title": title, "link": link, "date": pick("pubDate")})
    return out


def norm_date(s: str) -> str:
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    m = re.search(r"(20\d\d)[.\-/](\d{1,2})[.\-/](\d{1,2})", s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else ""


def make_record(*, title, content, agency, url, published, domain, source_name):
    return {
        "id": hashlib.sha1(url.encode()).hexdigest()[:20],
        "domain": domain,
        "data_type": "official_reference",
        "title": title,
        "content": content,
        "source_name": source_name,
        "source_agency": agency,
        "source_url": url,
        "published_at": published,
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "original_id": "",
        "risk_types": "[]",
        "trust_cues": "[]",
        "attachment_urls": "[]",
        "license": "공공누리 - 각 기관 저작권정책 확인",
        "content_hash": hashlib.sha256(content.encode()).hexdigest()[:60],
    }


# 본문에서 걷어낼 사이트 공통 상용구(메뉴/푸터). 남기면 문서마다 같은 텍스트가 끼어
# 유사도가 왜곡된다 - SCAM_CASES 의 '담당부서…첨부 이미지' 문제와 같은 실패다.
_BOILER = [
    "본 공공저작물은", "공공누리", "만족도 조사", "현재페이지", "페이지 인쇄",
    "화면크기", "글자크기", "누리집", "관련링크", "SNS", "바로가기",
]


def extract_region(page: str, class_names: list[str]) -> str:
    """본문 컨테이너만 잘라낸다.

    ★ 이걸 안 하면 사이트 전체 메뉴(질병관리청 기준 약 2,000자)가 모든 문서
      앞에 똑같이 붙는다. 그러면 문서들이 서로 비슷해져 유사도 검색이 무너진다
      - SCAM_CASES 가 '담당부서…첨부 이미지' 상용구만 남아 못 쓰게 된 것과 같은
      실패다. 실측으로 확인하고 고쳤다(2026-08-05).

    여는 태그부터 시작해 div 중첩을 세면서 짝이 맞는 닫는 태그까지 잘라낸다.
    """
    for cls in class_names:
        m = re.search(rf'<div[^>]*class="[^"]*\b{re.escape(cls)}\b[^"]*"[^>]*>', page)
        if not m:
            continue
        start = m.end()
        depth, i = 1, start
        for tok in re.finditer(r"(?i)<div\b|</div>", page[start:]):
            depth += 1 if tok.group(0).lower().startswith("<div") else -1
            if depth == 0:
                i = start + tok.start()
                break
        else:
            continue
        return page[start:i]
    return ""


def clean_body(text: str, min_len: int = 200) -> str:
    lines = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if len(ln) < 2 or any(b in ln for b in _BOILER):
            continue
        lines.append(ln)
    body = "\n".join(lines)
    return body if len(body) >= min_len else ""


# ══════════════════════════════════════════ 1) 질병관리청 (robots 허용)
#  ★ 게시판 40(건강소식·예방수칙)은 뺐다. 본문이 PDF 첨부뿐이라 텍스트가
#    185자(작성일·담당부서·첨부파일명)밖에 안 나온다 - SCAM_CASES 의 메타데이터
#    레코드와 같은 형태라 근거로 쓸 수 없다. 실측으로 확인했다(2026-08-05).
KDCA_BOARDS = {
    "42": "보도자료",
    "45": "건강정보",
    "46": "안내문·홍보물",
}
KDCA_ROWS = 100   # RSS 한 번에 받는 글 수. 목록 요청 자체를 줄이려고 크게 잡는다.
# 시니어가 실제로 받는 안내와 겹치는 주제만 남긴다(채용·인사·연구용역 제외).
KDCA_KEEP = re.compile(
    r"예방접종|백신|인플루엔자|독감|감염병|예방수칙|손씻기|결핵|폐렴|대상포진|"
    r"코로나|호흡기|온열질환|한랭|진드기|말라리아|수족구|노로|식중독|건강|검진"
)
KDCA_DROP = re.compile(r"채용|공고|입찰|용역|서포터즈|발대식|연보|지침|공모")


def collect_kdca(limit=50):
    out = []
    for bid, name in KDCA_BOARDS.items():
        try:
            xml = fetch(f"https://www.kdca.go.kr/bbs/kdca/{bid}/rssList.do?row={KDCA_ROWS}")
        except Exception as e:
            print(f"  [kdca {bid}] 목록 실패: {e}")
            continue
        time.sleep(SLEEP)
        items = [it for it in rss_items(xml)
                 if KDCA_KEEP.search(it["title"]) and not KDCA_DROP.search(it["title"])]
        print(f"  [kdca {bid} {name}] 후보 {len(items)}건")
        for it in items:
            if len(out) >= limit:
                break
            url = urljoin("https://www.kdca.go.kr/", it["link"])
            try:
                page = fetch(url)
                body = clean_body(to_text(extract_region(page, ["view viewCont", "viewCont", "board-view"])))
            except Exception as e:
                print(f"      본문 실패 {url}: {e}")
                time.sleep(SLEEP)
                continue
            time.sleep(SLEEP)
            if not body:
                continue
            out.append(make_record(
                title=it["title"], content=body[:6000],
                agency="질병관리청", url=url,
                published=norm_date(it["date"]), domain="health",
                source_name=f"질병관리청 {name}"))
            print(f"      + {it['title'][:52]}")
        if len(out) >= limit:
            break
    return out


# ══════════════════════════════════════════ 2) 보건복지부 보도자료 (robots 허용 경로)
#  ★ 기초연금 전용 사이트(basicpension.mohw.go.kr)는 Disallow: / 라 받지 않는다.
#    기초연금·건강보험·국민연금 안내는 복지부 보도자료에서 가져온다.
MOHW_LIST = "https://www.mohw.go.kr/board.es?mid=a10501010100&bid=0003&nPage={p}"
#  ★ 필터를 좁혔다(2026-08-05 1차 수집 후). '복지' 같은 넓은 말을 넣었더니
#    '사회복지시설 평가 결과', '과장급 공모직위', '행정처분 공시송달' 처럼
#    시니어 안내와 무관한 행정 문서가 들어왔다.
MOHW_KEEP = re.compile(r"기초연금|국민연금|노령연금|연금\s*지급|건강검진|국가건강검진|"
                       r"건강보험료|예방접종|어르신|노인\s*(돌봄|일자리|장기요양)|"
                       r"장기요양|의료급여|치매")
#  ★ 2차 정정(2026-08-05): 1차 수집분 4건이 전부 공고·모집·초빙·광고제였다.
#    실제로 H02(국민연금 수급 안내)가 '국민연금공단 복지이사 초빙 공고'에
#    매칭돼 근거 품질이 오히려 나빠졌다. 시민 대상 안내가 아닌 문서를 전부 뺀다.
MOHW_DROP = re.compile(r"채용|공모직위|공모|모집|초빙|입찰|용역|인사|공시송달|행정처분|"
                       r"평가\s*결과|지침.*개정|시범사업|위원.*위촉|간담회|업무협약|"
                       r"광고제|공고|수상|선정 결과")


def collect_mohw(limit=45, pages=25):
    out, seen = [], set()
    for p in range(1, pages + 1):
        try:
            page = fetch(MOHW_LIST.format(p=p))
        except Exception as e:
            print(f"  [mohw p{p}] 목록 실패: {e}")
            break
        time.sleep(SLEEP)
        links = re.findall(r'href="(/board\.es\?mid=a10501010100&amp;bid=0003&amp;act=view'
                           r'&amp;list_no=\d+[^"]*)"', page)
        titles = re.findall(r'href="/board\.es\?mid=a10501010100&amp;bid=0003&amp;act=view'
                            r'&amp;list_no=\d+[^"]*"[^>]*>([^<]{4,120})<', page)
        print(f"  [mohw p{p}] 링크 {len(links)}개")
        for href, title in zip(links, titles):
            if len(out) >= limit:
                return out
            title = html.unescape(title).strip()
            if not MOHW_KEEP.search(title) or MOHW_DROP.search(title):
                continue
            url = urljoin("https://www.mohw.go.kr/", html.unescape(href))
            if url in seen:
                continue
            seen.add(url)
            try:
                page = fetch(url)
                body = clean_body(to_text(extract_region(page, ["board_view", "contents"])))
            except Exception as e:
                print(f"      본문 실패: {e}")
                time.sleep(SLEEP)
                continue
            time.sleep(SLEEP)
            if not body:
                continue
            out.append(make_record(
                title=title, content=body[:6000],
                agency="보건복지부", url=url,
                published=norm_date(body[:200]), domain="public_support",
                source_name="보건복지부 보도자료"))
            print(f"      + {title[:52]}")
    return out


def main() -> None:
    print("공개 문서 수집 시작 (robots.txt 준수, 요청 간격 1.5초)\n")
    print("※ 제외한 출처")
    print("   basicpension.mohw.go.kr : robots.txt Disallow: /  → 수집 안 함")
    print("   www.nhis.or.kr          : robots.txt Disallow: /nhis/ → 수집 안 함\n")

    records = []
    print("[1/2] 질병관리청")
    records += collect_kdca(limit=60)
    print(f"\n[2/2] 보건복지부 보도자료")
    records += collect_mohw(limit=45, pages=25)

    # 본문 없는 문서는 애초에 담기지 않지만 한 번 더 확인한다
    records = [r for r in records if len((r["content"] or "").strip()) >= 200]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    from collections import Counter
    print(f"\n════ 수집 완료 {len(records)}건 → {OUT_PATH}")
    for a, n in Counter(r["source_agency"] for r in records).most_common():
        print(f"   {n:>3}  {a}")
    lens = [len(r["content"]) for r in records]
    if lens:
        print(f"   본문 길이 최소 {min(lens)} / 중앙 {sorted(lens)[len(lens)//2]} / 최대 {max(lens)}")


if __name__ == "__main__":
    sys.exit(main())
