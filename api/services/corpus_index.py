"""
곁눈(Gyeotnun) - CSV 근거 데이터 로컬 인덱스
담당: 김유리 (검색 대조) / 원본 데이터: 장지석

데이터팀이 corpus/ 에 올려 둔 3개 CSV를 기동 시(모듈 임포트 시) 메모리에 적재해
검색 가능한 형태로 만든다.

  EVIDENCE   ← 근거_검증표.csv                 기관·자료명·페이지·URL이 확인된 공식 통계
  SCAM_CASES ← 사례_20-46건_재라벨링표.csv      실제/합성 피싱 사례. 오판유형(복수 라벨) 보존.
  EVAL_CASES ← 곁눈_평가세트_30건.csv 전체 30건(정상 포함). 평가/회귀 전용 원본 보존.

★ 절대 하지 않는 것
  - url이 없거나 http 로 시작하지 않는 행은 인덱스에서 제외한다. (누를 수 없는 링크는 근거가 아니다)
  - 상태가 '사용금지'인 행은 제외한다. (근거_검증표의 E14/E15 - 원문 미확인)
  - 기관명·URL을 새로 만들지 않는다. publisher/source_type 은 CSV 값 또는
    URL 도메인에서 기계적으로 뽑아낸 값만 쓴다 (추측하지 않는다).
  - ★★ 평가 데이터는 참조 코퍼스에 포함하지 않는다 ★★
    EVAL_CASES(곁눈_평가세트_30건.csv)는 SCAM_CASES(실제 매칭에 쓰이는 코퍼스)에
    절대 섞지 않는다. 예전에는 평가세트의 사칭/경계 20행을 SCAM_CASES 에 그대로
    편입시켰는데, 그러면 이 CSV로 평가를 돌릴 때 각 케이스가 평가셋 안의 자기
    자신/형제 케이스와 매칭되는 자기참조(self-reference) 오염이 생겨 측정이
    무의미해진다(docs/evaluation/eval_30_report.md §6-2 에서 실측으로 확인됨).
    평가/회귀 목적이면 EVAL_CASES 를 그대로 읽되, 매칭 코퍼스(SCAM_CASES/EVIDENCE)에는
    절대 합치지 않는다.
"""
from __future__ import annotations

import csv
import json
import logging
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from rank_bm25 import BM25Okapi

from . import scam_taxonomy

log = logging.getLogger("gyeotnun.corpus_index")

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
EVIDENCE_TABLE_PATH = CORPUS_DIR / "근거_검증표.csv"
EVAL_SET_PATH = CORPUS_DIR / "곁눈_평가세트_30건.csv"
RELABELED_CASES_PATH = CORPUS_DIR / "사례_20-46건_재라벨링표.csv"

# ★ 공식 문서(공공데이터 1,017건, 2026-07-30 전달) - corpus/README.md 참고. 용량 때문에
#   git에 커밋하지 않는다(별도 전달). 로컬에 이 경로가 없으면 그냥 0건으로 적재된다
#   (기존 public_data/*.json 레거시 로더와 같은 관용 - 없어도 서비스는 죽지 않는다).
OFFICIAL_DATA_DIR = CORPUS_DIR / "public_data" / "gyeotnun_data"
OFFICIAL_RECORDS_PATH = OFFICIAL_DATA_DIR / "records_merged.jsonl"

_SYMBOLS_RE = re.compile(r'[★☆■□▶►\[\]()!?※·,."\'…\n]+')

# ---- 불용어: 어떤 공공 안내문/사기 사례 설명에도 흔히 등장해 변별력이 없는 단어.
#   이 단어들만 겹쳐서는 match_scam_cases() 가 매칭시키지 않는다(정상 안내문까지
#   사기 사례로 오매칭되는 문제의 원인이었다 - docs/evaluation/eval_30_report_before_stopword_fix.md §3).
#   상수로 분리해 둔다 - 오매칭 사례가 더 발견되면 여기에만 추가하면 된다.
STOPWORDS = {
    "안내", "지원", "내용", "확인", "신청", "정보", "서비스", "대상", "관련",
}

# 한국어 조사. 사용자가 붙여넣는 문장엔 조사가 그대로 붙어 있어 부분일치가 잘 안 걸린다.
# 길이가 긴 조사부터 검사해야 짧은 조사가 먼저 걸려 잘못 잘리는 일을 막는다.
_PARTICLES = sorted(
    ["에서", "에게", "한테", "으로", "까지", "부터", "이라도", "라도", "이나",
     "보다", "께서", "께", "만큼", "마저", "조차", "마다", "와", "과", "의",
     "을", "를", "이", "가", "은", "는", "도", "만", "로", "에"],
    key=len, reverse=True,
)


def _clean(text: str) -> str:
    return _SYMBOLS_RE.sub(" ", text or "")


def extract_keywords(text: str) -> List[str]:
    """입력 문장에서 핵심 키워드를 뽑는다.

    단순 공백 분리에 조사 제거를 더한다. '정부에서' 처럼 조사가 붙은 채로는
    문서 원문(정부 24, 정부 지원금 등)과 부분일치가 거의 안 걸리기 때문이다.
    """
    out: List[str] = []
    for token in _clean(text).split():
        if len(token) < 2:
            continue
        out.append(token)
        for p in _PARTICLES:
            if len(token) - len(p) >= 2 and token.endswith(p):
                out.append(token[: -len(p)])
                break
    # 긴 키워드부터: '오늘까지'가 '오늘'보다 먼저 매칭 시도되게 해 더 구체적인 신호를 우선한다.
    return sorted(set(out), key=len, reverse=True)


def _domain(url: str) -> str:
    return (urlparse(url).netloc or "").lower()


def classify_source_type(url: str) -> str:
    """URL 도메인만 보고 기계적으로 분류한다. 추측이 아니라 문자열 판별이다.

    Reference.source_type 은 Literal["public_data","news","gov","unknown"] 로
    제한돼 있어, 새 값을 만들지 않고 이 네 값 중 하나로만 매핑한다.
    """
    host = _domain(url)
    if host.endswith(".go.kr") or host.endswith(".or.kr"):
        return "gov"
    if any(k in host for k in ("news", "media")):
        return "news"
    return "unknown"


# ==================================================== 데이터 구조
@dataclass
class EvidenceDoc:
    """근거_검증표.csv 한 행. 기관이 확인해 준 공식 통계 1건."""

    id: str
    title: str          # 자료명
    publisher: str       # 기관 (CSV 값 그대로, 지어내지 않는다)
    url: str
    published_at: Optional[str]   # 기준연도
    claim: str            # 주장 (예: "65세 이상 인구 비율")
    value: str             # 수치 (예: "20.3%")
    population: str         # 조사대상
    usage_note: str          # 본문_사용조건 - 이 수치를 어떤 맥락에서만 써야 하는지
    _blob: str = field(default="", repr=False)

    def to_reference(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "publisher": self.publisher,
            "published_at": self.published_at or None,
            "source_type": classify_source_type(self.url),
        }


@dataclass
class ScamCase:
    """알려진 사기/사칭 사례 1건. 두 소스에서 온다 - origin 으로 구분한다.

    - origin="relabeled"           : 사례_재라벨링표.csv 30건. 사람이 위험단서·
      오판유형까지 직접 라벨링한 고품질 데이터.
    - origin="public_data_warning" : records_merged.jsonl 의 warning_case/
      press_release 179건(피싱안심SOS 예·경보, KISA 피싱·사칭 보도자료, 경찰청
      보이스피싱 현황). 공공데이터 원문 그대로라 오판유형 라벨이 없다
      (error_types 는 항상 빈 리스트).

    ★ 평가세트(EVAL_CASES)는 여기 절대 섞지 않는다 - 위 모듈 docstring 참고.
    """

    id: str
    text: str              # 사례 원문/제시문구
    source_label: str        # 참고_출처 또는 출처 (사람이 읽는 출처 설명)
    url: str
    published_at: Optional[str]
    risk_clues: List[str] = field(default_factory=list)     # 위험단서 / 신뢰단서 / risk_types
    error_types: List[str] = field(default_factory=list)     # 오판유형 (복수 라벨, relabeled만 있음)
    questions: List[str] = field(default_factory=list)        # 놓친확인요소
    rationale: str = ""
    origin: str = "relabeled"   # "relabeled" | "public_data_warning"
    _blob: str = field(default="", repr=False)

    def signal_label(self) -> str:
        """이 사례가 매칭됐을 때 signals 에 넣을 한 줄 설명."""
        if self.error_types:
            return f"이전에 확인된 사기 수법과 비슷합니다 (오판유형: {', '.join(self.error_types)})."
        if self.risk_clues:
            return f"이전에 확인된 사기 수법과 비슷합니다 (특징: {', '.join(self.risk_clues[:3])})."
        return "이전에 확인된 사기 수법과 비슷합니다."

    def to_reference(self) -> dict:
        # publisher 는 URL 도메인에서 기계적으로 뽑는다(예: counterscam112.go.kr).
        # source_label(출처/참고_출처 텍스트)을 그대로 쓰면 title 과 중복돼 읽기 어렵다.
        host = _domain(self.url)
        if host.startswith("www."):
            host = host[4:]
        return {
            "title": self.source_label or "유사 사기 사례 경보",
            "url": self.url,
            "publisher": host or (self.source_label or "출처 불명"),
            "published_at": self.published_at or None,
            "source_type": classify_source_type(self.url),
        }


@dataclass
class EvalCase:
    """곁눈_평가세트_30건.csv 원본 한 행 (정상 포함 전체). 평가/회귀 테스트용."""

    id: str
    category: str     # 정상 | 사칭 | 경계
    text: str
    expected_verdict: str
    risk_clues: List[str]
    questions: List[str]
    rationale: str
    url: str


@dataclass
class OfficialDoc:
    """공식 근거 문서 1건 (records_merged.jsonl, 공공데이터 1,017건).

    ★ SCAM_CASES(사기 사례)와 완전히 분리된 별도 인덱스다. 곁눈이 "이런 공식 문서를
      찾았다"와 "이런 사기 사례와 비슷하다"를 사용자에게 절대 섞어 말하지 않기
      위해서다 - 두 개념을 같은 자료구조/신호로 합치면 나중에 실수로 뒤섞이기 쉽다.
    """

    id: str
    title: str
    content: str
    source_agency: str
    source_url: str
    published_at: Optional[str]
    domain: str
    data_type: str

    def to_reference(self) -> dict:
        return {
            "title": self.title,
            "url": self.source_url,
            "publisher": self.source_agency,
            "published_at": self.published_at or None,
            "source_type": classify_source_type(self.source_url),
        }


@dataclass
class OfficialChunk:
    """OfficialDoc 본문을 검색 단위로 재청킹한 조각 1건. BM25 색인 대상.

    ★ 사용자에게는 절대 노출되지 않는다 - references 는 항상 OfficialDoc(문서) 단위로
      묶어서 돌려준다(청크 그대로 보여주면 문장이 잘려 나온 것처럼 보인다).
    """

    chunk_id: str
    record_id: str    # OfficialDoc.id 를 가리키는 외래키
    text: str
    tokens: List[str] = field(default_factory=list, repr=False)   # BM25 색인용 (기동 시 1회 계산)


# ==================================================== 로더
def _read_csv(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if any((v or "").strip() for v in row.values())]


def _split_pipe(value: str) -> List[str]:
    return [p.strip() for p in (value or "").split("|") if p.strip()]


def _load_evidence() -> List[EvidenceDoc]:
    docs: List[EvidenceDoc] = []
    for row in _read_csv(EVIDENCE_TABLE_PATH):
        url = (row.get("원문_URL") or "").strip()
        status = (row.get("상태") or "").strip()
        # ★ 사용금지(원문 미확인) 이거나 클릭 가능한 http(s) 링크가 아니면 근거로 쓰지 않는다.
        if status != "확인완료" or not url.startswith(("http://", "https://")):
            continue
        title = (row.get("자료명") or "").strip()
        publisher = (row.get("기관") or "").strip()
        if not title or not publisher:
            continue
        claim = (row.get("주장") or "").strip()
        population = (row.get("조사대상") or "").strip()
        blob = _clean(" ".join([claim, title, publisher, population]))
        docs.append(EvidenceDoc(
            id=(row.get("근거_ID") or "").strip(),
            title=title,
            publisher=publisher,
            url=url,
            published_at=(row.get("기준연도") or "").strip() or None,
            claim=claim,
            value=(row.get("수치") or "").strip(),
            population=population,
            usage_note=(row.get("본문_사용조건") or "").strip(),
            _blob=blob,
        ))
    return docs


def _load_eval_cases() -> List[EvalCase]:
    cases: List[EvalCase] = []
    for row in _read_csv(EVAL_SET_PATH):
        url = (row.get("출처_URL") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        cases.append(EvalCase(
            id=(row.get("case_id") or "").strip(),
            category=(row.get("유형") or "").strip(),
            text=(row.get("평가용_제시문구") or "").strip(),
            expected_verdict=(row.get("기대판단") or "").strip(),
            risk_clues=_split_pipe(row.get("위험단서", "")),
            questions=_split_pipe(row.get("필요한_확인질문", "")),
            rationale=(row.get("정답근거") or "").strip(),
            url=url,
        ))
    return cases


def _load_relabeled_cases() -> List[ScamCase]:
    out: List[ScamCase] = []
    for row in _read_csv(RELABELED_CASES_PATH):
        url = (row.get("사례URL") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        text = (row.get("사례내용") or "").strip()
        trust_clues = _split_pipe(row.get("신뢰단서", ""))
        missed = _split_pipe(row.get("놓친확인요소", ""))
        error_types = _split_pipe(row.get("오판유형", ""))
        source = (row.get("출처") or "").strip()
        blob = _clean(" ".join([text, *trust_clues, row.get("요구행동", ""), row.get("위험결과", "")]))
        out.append(ScamCase(
            id=(row.get("사례ID") or "").strip(), text=text, source_label=source,
            url=url, published_at=(row.get("발행일") or "").strip() or None,
            risk_clues=trust_clues, error_types=error_types, questions=missed,
            rationale=(row.get("정답근거") or "").strip(), origin="relabeled", _blob=blob,
        ))
    return out


# ★ records_merged.jsonl 의 data_type 중 warning_case(155건)/press_release(24건),
#   합쳐서 179건은 "공식 정책/통계 안내"가 아니라 "사기 사례·경보"다(피싱안심SOS
#   예·경보, KISA 피싱·사칭 보도자료, 경찰청 보이스피싱 현황). 처음엔 이 179건도
#   OFFICIAL_DOCS 에 그대로 들어가 있었는데, 사용자 입력이 이 문서들과 겹치면
#   "공식 자료를 찾았습니다"(official_source_found, info)로 안내됐다 - 사기 경보문을
#   중립적인 참고자료처럼 보여준 셈이라 신호의 의미가 어긋난다.
#
#   그런데 이 179건을 통째로 SCAM_CASES(키워드 겹침 매칭)로 옮겨 봤더니, 179건 중
#   대부분(158건)이 보도자료 전문(평균 1,093자, 최대 4,868자)이라 여러 주제를 한
#   문서가 동시에 다루는 바람에 무관한 문장과도 범용 단어로 겹쳐 정상 안내문을
#   '의심'으로 오판시켰다(실측 확인, docs/evaluation/eval_30_report.md). 짧은
#   21건(39~94자, 재라벨링표 30건과 비슷한 스케일)만 그 문제가 없었다(아래
#   _SCAM_PATTERN_MAX_CHARS 주석 참고). 그래서 최종적으로 나눴다:
#     - 짧은 21건(<=200자) → SCAM_CASES 로 옮긴다(_load_public_data_warning_cases).
#       개별 사건 하나를 짧게 알리는 경보문이라 '유사 사기 사례'로 매칭하기에 적합하다.
#     - 긴 158건(>200자) → OFFICIAL_DOCS 에 그대로 남긴다. 여러 사기 유형을 종합
#       설명하는 보도자료라 "공식 자료"로 부르는 게 오히려 정확하고, OFFICIAL_DOCS는
#       BM25 청크 검색이라 문서 길이에 특별히 취약하지 않다(§match_official_docs).
#   즉 같은 문서가 두 인덱스에 동시에 들어가지는 않는다("공식 문서와 사기 사례를
#   같은 인덱스에 넣지 마라" 원칙은 유지) - data_type 만이 아니라 길이까지 함께
#   기준으로 어느 인덱스가 맞는지 가른다.
_SCAM_PATTERN_DATA_TYPES = {"warning_case", "press_release"}

# ★ 길이 상한 - 실측으로 발견한 문제(docs/evaluation/eval_30_report.md 재측정 참고):
#   재라벨링표 30건은 평균 77자(최대 104자)짜리 짧은 단일 시나리오 문장인데, 179건
#   원문은 평균 1,093자(중앙값 1,033자)짜리 보도자료 전문이다. 179건의 길이 분포
#   자체에 자연스러운 틈이 있다 - 39~94자짜리가 21건 있고, 그다음은 바로 610자로
#   뛴다(94~610자 구간은 0건). 200자를 상한으로 두면(94자와 610자 사이 아무 값이나
#   동일하게 동작) 그 21건만 남아 재라벨링표(30건)와 비슷한 스케일(51건)이 되고,
#   실측으로 확인한 대로 임계값 5.0을 그대로 써도 정상 오판 0건이 유지된다
#   (§match_scam_cases 근거 참고).
_SCAM_PATTERN_MAX_CHARS = 200


def _load_official_docs() -> List[OfficialDoc]:
    """records_merged.jsonl(1줄 1건)을 읽는다. 파일이 없으면(아직 전달 전 로컬 등) 0건으로
    조용히 넘어간다 - 이 코퍼스는 별도 전달본이라 항상 있으리라는 보장이 없다.

    ★ data_type 이 warning_case/press_release 이면서 길이가 짧은(<=200자) 문서는
      여기서 제외한다 - 위 _SCAM_PATTERN_DATA_TYPES/_SCAM_PATTERN_MAX_CHARS 주석
      참고, SCAM_CASES 쪽에서 읽는다. 같은 data_type 이라도 긴 문서는 그대로
      OFFICIAL_DOCS 에 남는다.
    """
    docs: List[OfficialDoc] = []
    # ★ 2026-08-05 추가: 직접 수집분(질병관리청·보건복지부)을 함께 읽는다.
    #   원본 전달본(records_merged.jsonl)을 건드리지 않고 별도 파일로 두는 이유는
    #   출처와 수집 시점을 분리해 두어야 나중에 재수집·롤백이 쉽기 때문이다.
    #   수집 스크립트: api/tools/collect_public_docs.py
    paths = [p for p in (OFFICIAL_RECORDS_PATH, *sorted(OFFICIAL_DATA_DIR.glob("records_collected_*.jsonl")))
             if p.exists()]
    if not paths:
        return docs
    seen_urls: set = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            _is_scam_pattern = (row.get("data_type") or "").strip() in _SCAM_PATTERN_DATA_TYPES
            _is_short = len((row.get("content") or "").strip()) <= _SCAM_PATTERN_MAX_CHARS
            if _is_scam_pattern and _is_short:
                continue
            url = (row.get("source_url") or "").strip()
            title = (row.get("title") or "").strip()
            # ★ url이 없거나 http로 시작하지 않는 문서는 근거로 쓰지 않는다 (누를 수 없는
            #   링크는 근거가 아니다 - 이 파일 맨 위 docstring의 원칙을 그대로 따른다)
            if not title or not url.startswith(("http://", "https://")):
                continue
            if url in seen_urls:      # 파일 간 중복(재수집분과 원본이 겹칠 때)
                continue
            seen_urls.add(url)
            docs.append(OfficialDoc(
                id=(row.get("id") or "").strip(),
                title=title,
                content=(row.get("content") or "").strip(),
                source_agency=(row.get("source_agency") or "").strip(),
                source_url=url,
                published_at=(row.get("published_at") or "").strip() or None,
                domain=(row.get("domain") or "").strip(),
                data_type=(row.get("data_type") or "").strip(),
            ))
    return docs


def _load_public_data_warning_cases() -> List[ScamCase]:
    """records_merged.jsonl 중 warning_case/press_release 로, 길이 상한 이하인 것만
    ScamCase 로 읽는다(위 _SCAM_PATTERN_MAX_CHARS 주석 참고 - 179건 중 21건만 남는다).

    ★ 재라벨링표(30건)와 품질이 다르다 - 재라벨링표는 사람이 위험단서·오판유형까지
      직접 라벨링했지만, 이 데이터는 공공데이터 원문 그대로다(오판유형 라벨 없음).
      origin="public_data_warning" 으로 명확히 구분한다 - tagger.py 의 few-shot
      선택 로직(`origin != "relabeled"`)이 이미 origin 으로 필터링하므로, 오판유형
      라벨이 없는 이 건들은 자동으로 few-shot 예시에서 제외된다(추가 코드 불필요).
    """
    out: List[ScamCase] = []
    if not OFFICIAL_RECORDS_PATH.exists():
        return out
    with OFFICIAL_RECORDS_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get("data_type") or "").strip() not in _SCAM_PATTERN_DATA_TYPES:
                continue
            url = (row.get("source_url") or "").strip()
            title = (row.get("title") or "").strip()
            text = (row.get("content") or "").strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            if len(text) > _SCAM_PATTERN_MAX_CHARS:
                continue
            risk_types = [r for r in (row.get("risk_types") or []) if r]
            agency = (row.get("source_agency") or "").strip()
            blob = _clean(" ".join([title, text, *risk_types]))
            out.append(ScamCase(
                id=(row.get("id") or "").strip(),
                text=text or title,
                source_label=f"{agency} - {title}"[:80] if agency else title[:80],
                url=url,
                published_at=(row.get("published_at") or "").strip() or None,
                risk_clues=risk_types,
                error_types=[],       # 사람이 라벨링하지 않았다 - 항상 빈 리스트
                questions=[],
                rationale="",
                origin="public_data_warning",
                _blob=blob,
            ))
    return out


# 데이터팀이 전달한 chunks_merged.jsonl 은 999/1,017 문서만 커버한다(너무 짧은 경보문
# 18건이 청크 생성 기준에서 빠짐 - corpus/README.md 참고). 그 파일을 그대로 쓰지 않고
# records_merged.jsonl(1,017건 전체)을 원본으로 직접 재청킹해서 전체를 커버한다.
# 목표 청크 크기는 실측으로 정했다: 전달받은 chunks_merged.jsonl 의 평균 청크 길이가
# 585.8자였고, 이 상수(900)로 잘랐을 때 평균이 577.8자로 가장 가까웠다(빈도 분포상
# 문단 경계에서 못 채우고 남는 조각들 때문에 목표값보다 항상 조금 낮게 나온다).
_CHUNK_TARGET_CHARS = 900


def _split_into_chunks(text: str, target: int = _CHUNK_TARGET_CHARS) -> List[str]:
    """문단(줄바꿈) 경계를 최대한 지키면서 target 근처 길이로 텍스트를 쪼갠다.

    문장 단위가 아니라 문단 단위로 자르는 이유: 공식 문서 원문(보도자료·안내문)은
    문단이 이미 의미 단위로 나뉘어 있어, 문단 경계를 지키는 것만으로도 문장이
    중간에 잘리는 것을 대부분 막는다 - 별도 문장 분리기(sentencizer)를 붙이는
    비용을 정당화할 만큼 효과 차이가 크지 않다.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= target:
        return [text]
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paragraphs:
        candidate = f"{buf}\n{p}" if buf else p
        if len(candidate) <= target:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        # 문단 자체가 target보다 길면(예: 표를 통째로 텍스트로 뽑은 PDF 구간) 어쩔 수
        # 없이 강제로 잘라서 담는다 - 문단 하나를 통째로 청크 하나로 만들면 너무 커진다.
        while len(p) > target:
            chunks.append(p[:target])
            p = p[target:]
        buf = p
    if buf:
        chunks.append(buf)
    return chunks


def _rechunk_official_docs(docs: List[OfficialDoc]) -> List[OfficialChunk]:
    """OfficialDoc.content 를 검색 단위(OfficialChunk)로 재청킹한다.

    제목을 모든 청크 앞에 붙인다 - 원문이 "담당부서/날짜/조회수" 같은 상용구로
    시작하는 경우가 많아(records_merged.jsonl 실측), 제목이 없으면 첫 청크의 핵심
    주제어가 희석된다.
    """
    chunks: List[OfficialChunk] = []
    for doc in docs:
        pieces = _split_into_chunks(doc.content) or [""]
        for i, piece in enumerate(pieces):
            text = f"{doc.title}\n{piece}".strip()
            if not text:
                continue
            chunks.append(OfficialChunk(chunk_id=f"{doc.id}-{i:04d}", record_id=doc.id, text=text))
    return chunks


# ---- BM25(공식 문서) 전용 추가 불용어. records_merged.jsonl 실측으로 발견한 문제:
#   복지로(bokjiro.go.kr) 문서 상당수가 본문에 "사이트: 복지로http://www.bokjiro.go.kr"
#   같은 정형 필드를 갖는데, 이 정확한 형태("복지로"라는 토큰)는 코퍼스 전체 1,903개
#   청크 중 딱 2개에만 등장한다(df=2, 나머지 문서는 대표문의처가 NH농협/근로복지공단 등
#   다른 기관이라 "복지로"라는 단어 자체가 없다). 반면 실제 사용자는 "복지로에서
#   확인하세요"처럼 이 포털 이름을 문서 주제와 무관하게 아주 흔하게 언급한다(평가세트
#   N01/N02/N10 실측 - "복지로 노후준비서비스...", "복지로 원문에서..."). df가 낮으니
#   BM25 idf가 높게(6.6점대) 잡히고, 그 결과 완전히 무관한 문서 2건이 "복지로"라는
#   말 한마디로 최상위 매칭에 튀어 오르는 오매칭이 실측으로 확인됐다. match_scam_cases()
#   의 STOPWORDS 와는 별개로 이 코퍼스에서만 드러난 문제라 여기 따로 추가한다.
_OFFICIAL_EXTRA_STOPWORDS = {"복지로", "복지"}


def _bm25_tokenize(text: str) -> List[str]:
    """BM25 입력 토큰화.

    ★ 형태소 분석기(mecab/konlpy 등)를 새로 붙이는 대신, match_scam_cases() 에서 이미
      실측으로 검증한 조사 제거 로직(extract_keywords)과 STOPWORDS 를 그대로 재사용한다.
      이유: (1) 이 코퍼스 규모(문서 1,017건, 청크 2천 건 안팎)에서는 형태소 분석기를
      새로 설치·운영하는 비용(네이티브 의존성, 사전 관리) 대비 검색 정밀도 이득이 크지
      않다. (2) 조사 제거만으로도 한국어 부분일치 문제의 상당 부분이 해결됨을 이미
      SCAM_CASES 매칭에서 확인했다. (3) BM25 자체가 문서빈도 기반 가중치(IDF)를 내부적으로
      계산하므로, STOPWORDS 필터는 그 위에 얹는 보조 잡음 제거일 뿐 핵심 변별력은 BM25가
      맡는다 - 형태소 분석기 없이도 안전하다.
    """
    return [k for k in extract_keywords(text) if k not in STOPWORDS and k not in _OFFICIAL_EXTRA_STOPWORDS]


# ==================================================== 기동 시 적재 (모듈 임포트 시 1회)
# ★ 출처 파일명을 로그로 남긴다 - "이 CSV가 매칭 코퍼스에 들어갔는지"를 코드를 다시
#   읽지 않고도 기동 로그만으로 바로 확인할 수 있게 하기 위해서다(평가세트를 실수로
#   다시 섞어 넣는 것을 조기에 알아채기 위한 안전장치).
EVIDENCE: List[EvidenceDoc] = _load_evidence()
log.info("[corpus] EVIDENCE %s건 적재 (출처: %s)", len(EVIDENCE), EVIDENCE_TABLE_PATH.name)

EVAL_CASES: List[EvalCase] = _load_eval_cases()
log.info(
    "[corpus] EVAL_CASES %s건 적재 (출처: %s, 평가/회귀 전용 - 매칭 코퍼스에 포함 안 함)",
    len(EVAL_CASES), EVAL_SET_PATH.name,
)

_RELABELED_CASES: List[ScamCase] = _load_relabeled_cases()
_PUBLIC_DATA_WARNING_CASES: List[ScamCase] = _load_public_data_warning_cases()
SCAM_CASES: List[ScamCase] = _RELABELED_CASES + _PUBLIC_DATA_WARNING_CASES
log.info(
    "[corpus] SCAM_CASES %s건 적재 (출처: %s %s건 + records_merged.jsonl "
    "warning_case/press_release %s건 - 평가세트 CSV는 제외)",
    len(SCAM_CASES), RELABELED_CASES_PATH.name, len(_RELABELED_CASES), len(_PUBLIC_DATA_WARNING_CASES),
)


def _doc_freq(blobs: List[str]) -> dict:
    """키워드별로 몇 개 문서(blob)에 등장하는지 센다. match_scam_cases() 의 가중치 계산용."""
    freq: dict[str, int] = {}
    for blob in blobs:
        for kw in set(extract_keywords(blob)):
            freq[kw] = freq.get(kw, 0) + 1
    return freq


# SCAM_CASES 안에서 흔한 단어(예: 여러 사례에 공통으로 등장하는 "계좌", "요구")일수록
# 가중치를 낮추기 위한 문서빈도표. 코퍼스가 바뀔 때만 다시 계산하면 되므로 기동 시 1회.
_SCAM_DOC_FREQ: dict = _doc_freq([c._blob for c in SCAM_CASES])
_SCAM_N_DOCS: int = len(SCAM_CASES)

# ---- 공식 문서(공공데이터 1,017건) - SCAM_CASES 와 완전히 분리된 별도 인덱스.
#      로컬에 별도 전달본이 없으면(corpus/README.md 참고) OFFICIAL_DOCS 는 그냥 0건이다.
OFFICIAL_DOCS: List[OfficialDoc] = _load_official_docs()
log.info("[corpus] OFFICIAL_DOCS %s건 적재 (출처: %s)", len(OFFICIAL_DOCS), OFFICIAL_RECORDS_PATH.name)

_OFFICIAL_DOCS_BY_ID: dict = {d.id: d for d in OFFICIAL_DOCS}

_OFFICIAL_CHUNKS: List[OfficialChunk] = _rechunk_official_docs(OFFICIAL_DOCS)
if _OFFICIAL_CHUNKS:
    for _c in _OFFICIAL_CHUNKS:
        _c.tokens = _bm25_tokenize(_c.text)
    _OFFICIAL_BM25: Optional[BM25Okapi] = BM25Okapi([c.tokens for c in _OFFICIAL_CHUNKS])
    _avg_chunk_len = sum(len(c.text) for c in _OFFICIAL_CHUNKS) / len(_OFFICIAL_CHUNKS)
else:
    _OFFICIAL_BM25 = None
    _avg_chunk_len = 0
log.info(
    "[corpus] OFFICIAL_CHUNKS %s개 재청킹 (원본 %s건 전체 커버, 평균 %.0f자, BM25 색인 완료)",
    len(_OFFICIAL_CHUNKS), len(OFFICIAL_DOCS), _avg_chunk_len,
)


def summary() -> dict:
    """기동 로그/헬스체크용 적재 현황."""
    return {
        "evidence_docs": len(EVIDENCE),
        "eval_cases": len(EVAL_CASES),
        "scam_cases": len(SCAM_CASES),
        "scam_cases_relabeled": len(_RELABELED_CASES),
        "scam_cases_public_data_warning": len(_PUBLIC_DATA_WARNING_CASES),
        "official_docs": len(OFFICIAL_DOCS),
        "official_chunks": len(_OFFICIAL_CHUNKS),
    }


# ==================================================== 검색
def match_evidence(text: str, limit: int = 2, min_score: int = 1) -> List[EvidenceDoc]:
    """근거_검증표와 대조한다. 통계 근거라 임계값을 낮게 둬도(1건 일치) 큰 위험이 없다."""
    kws = extract_keywords(text)
    if not kws:
        return []
    scored = []
    for doc in EVIDENCE:
        score = sum(1 for k in kws if k in doc._blob)
        if score >= min_score:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:limit]]


def _keyword_weight(keyword: str) -> float:
    """희귀한 단어일수록 점수를 높게 준다(idf류 가중치).

    df(문서빈도)가 낮을수록(=SCAM_CASES 안에서 드물게 등장할수록) 그 단어가 우연히
    겹칠 확률이 낮다는 뜻이라 변별력이 높다고 본다. +1 스무딩을 쓰는 이유는 코퍼스가
    30건 안팎으로 작아서 df=0(전혀 안 나오는 단어)이거나 전체 문서 수 자체가 작을 때도
    나눗셈이 안정적으로 동작하게 하기 위해서다.

    ★ 2026-08-05 결함 수정 - df 를 매칭 규칙과 같은 방식으로 센다.
      기존에는 df 를 '토큰 단위'로 세면서 매칭은 '부분 문자열'로 했다. 그래서
      토큰으로는 한 번도 등장하지 않지만 부분 문자열로는 걸리는 단어(예: '앱을',
      '화면', '하는')가 df=0 이 되어 **최대 가중치 4.951** 을 받았다 - 실제로
      존재하는 어떤 토큰의 가중치(최대 4.258)보다도 높았다. 희귀할수록 높은
      점수를 주려던 의도와 정반대로, '사기 코퍼스에 아예 없는 흔한 말'이 가장
      강한 신호가 되어 버렸다(docs/evaluation/judgment_basis.md).
      실측: B03 은 조사 '하는'(4.951) 하나로 임계값 5.0 에 육박했다.
    """
    df = _scam_substring_df(keyword)
    return math.log((_SCAM_N_DOCS + 1) / (df + 1)) + 1.0


@lru_cache(maxsize=256)
def _case_categories(case_id: str) -> frozenset:
    """사기 사례가 '요구하는 행위' 카테고리. 본문이 없으면 빈 집합이다."""
    case = next((c for c in SCAM_CASES if c.id == case_id), None)
    if case is None:
        return frozenset()
    return frozenset(scam_taxonomy.describe_categories(case._blob))


@lru_cache(maxsize=4096)
def _scam_substring_df(keyword: str) -> int:
    """매칭에 쓰는 것과 동일한 부분 문자열 규칙으로 문서빈도를 센다."""
    return sum(1 for c in SCAM_CASES if keyword in c._blob)


def _dedup_morph_variants(matched: List[str]) -> List[str]:
    """조사가 붙은 변형과 원형이 함께 잡힌 경우 하나만 남긴다.

    ★ 2026-08-05 결함 수정 - 중복 계상.
      extract_keywords() 는 '계좌로'와 조사를 뗀 '계좌'를 **둘 다** 내놓는다.
      둘 다 사례 본문의 부분 문자열이라 둘 다 점수에 더해졌고, 같은 단어
      하나가 사실상 두 번 계산됐다. 실측(H05): '계좌로'(4.258) + '계좌'(3.853)
      = 8.111 로, 단어 하나로 임계값 5.0 을 훌쩍 넘겼다.
      긴 쪽이 짧은 쪽을 포함하면 같은 어휘로 보고 긴 쪽만 남긴다.
    """
    out: List[str] = []
    for k in sorted(matched, key=len, reverse=True):
        if not any(k in kept for kept in out):
            out.append(k)
    return out


def match_scam_cases(text: str, limit: int = 2, min_score: float = 5.0) -> List[ScamCase]:
    """알려진 사기 사례와 대조한다.

    ★★ 2026-08-05 전면 수정 ★★
      이전 구현은 **어휘 중첩만** 봤다. 그 결과 정상 안내문 H05("기초연금이
      등록하신 계좌로 입금되며")가 대환대출·통장협박 사례와 매칭돼 '의심'으로
      오판됐다. '계좌·지급·신청' 같은 행정 어휘는 정상 문서에도 항상 나오기
      때문이다. 진단 전문: docs/evaluation/judgment_basis.md

      임계값을 올려서 덮지 않았다. 임계값 조정은 증상만 가리고, 올리면
      사칭 검출이 같이 떨어진다. 대신 판정 축 자체를 바꿨다.

      (1) 수법 카테고리 게이트 - 어휘가 겹쳐도 '요구하는 행위'가 다르면
          같은 수법이 아니다. 사용자 글이 아무 수법도 요구하지 않으면
          (= 정상 안내문) 아예 대조하지 않는다.
            정상 "계좌로 입금되며"      → 요구 없음 → 매칭 0건
            사칭 "안전계좌로 보내세요"  → 자금이체 요구 → 대조 진행
      (2) 점수는 어휘 합산이 아니라 **수법 일치도**로 낸다. 어휘 중첩은
          같은 카테고리 안에서 순위를 가르는 보조 지표로만 쓴다.
          어휘 합산을 주 지표로 두면, 흔한 행정 어휘가 여러 개 겹친 정상
          문서가 수법이 정확히 일치하는 사기 사례보다 높은 점수를 받는다.
      (3) 본문이 없는 레코드는 대조에서 제외한다(아래 주석).

      (4) ★ 2026-08-08 복구 - 어휘 하한선(min_score) 을 다시 적용한다.
          위 (2)로 판정축을 바꾸면서 min_score 가 인자로만 남고 코드에서 빠졌다.
          그 결과 **하한선이 사라져** '수법 카테고리 1개 + 키워드 1개' 만 겹쳐도
          근거로 승격됐다. 실측 사례(B07 대출 이미지):
            단어 '은행' 하나 → C09(금융위 카드뉴스)가 근거로 붙음
            단어 '직원' 하나 → C12(경찰청 투자리딩방)가 근거로 붙음
                              ※ C12 는 투자리딩방 사칭 사례라 대출과 무관하다
          이 근거가 프롬프트에 '사칭 사례' 신호로 들어가 질문 생성까지 오염시켰다
          (docs/reports/2026-08-08_은행명질문_금융위근거_원인조사.txt).
          카테고리 게이트는 '무엇을 요구하는가'만 보므로 정상 서술문도 통과할 수
          있다 - 하한선은 그 뒤에서 '얼마나 겹치는가'를 보는 두 번째 관문이다.

      ※ 값은 기존 기본값 5.0 을 그대로 쓴다. 임계값을 새로 튜닝하지 않았다.
        적용 전 실측(experiments/sim_scam_min_score.py):
          정상 10건 오판 0건 유지 / 사칭 10건 위험신호 10/10 유지 /
          홀드아웃 5건·실사용 SMS 11건 판정 불변 / B07 오매칭 2건 제거
        대가: S02(어휘 3.34)의 사기사례 매칭이 함께 빠져 의심→확인불가로 내려간다.
        S02 는 다른 신호(no_official_source)로 위험신호는 유지되므로 검출 10/10 은
        지켜지지만, 화면 단계는 한 칸 낮아진다. B07(3.85)보다 S02(3.34)가 낮아
        **둘을 가르는 임계값은 존재하지 않는다** - 하한선을 살리는 한 감수해야 하는
        비용이라 그대로 적었다(숫자를 S02 에 맞춰 조정하지 않았다).
    """
    kws = [k for k in extract_keywords(text) if k not in STOPWORDS]
    if not kws:
        return []

    # ---- (1) 게이트: 사용자 글이 무엇을 '요구'하는가
    text_cats = scam_taxonomy.detect_categories(text)
    if not text_cats:
        return []

    scored = []
    for case in SCAM_CASES:
        # ---- (3) 본문 없는 레코드 제외.
        #   SCAM_CASES 51건 중 19건이 '담당부서신고대응센터 / 2026-07-24 /
        #   첨부 이미지 또는 문서 3개' 같은 스크랩 메타데이터뿐이다. 실제
        #   수법 설명이 없어 어휘가 겹쳐도 근거가 되지 않는다.
        case_cats = _case_categories(case.id)
        if not case_cats:
            continue
        shared = text_cats & case_cats
        if not shared:
            continue

        matched = _dedup_morph_variants([k for k in kws if k in case._blob])
        if not matched:
            continue
        # ---- (2) 1순위 = 수법 일치 개수, 2순위 = 어휘 중첩 가중치
        lexical = sum(_keyword_weight(k) for k in matched)
        # ---- (4) 어휘 하한선. 수법이 같은 범주라도 겹치는 어휘가 이 정도는
        #      돼야 '같은 수법'이라 부를 수 있다. 단어 하나짜리 우연한 겹침을
        #      근거로 승격시키지 않기 위한 관문이다(위 docstring (4) 참고).
        if lexical < min_score:
            log.debug("[match_scam] 하한선 미달 제외: case=%s 어휘=%.2f < %.2f 단어=%s",
                      case.id, lexical, min_score, matched)
            continue
        scored.append(((len(shared), lexical), matched, case))
    scored.sort(key=lambda x: (-x[0][0], -x[0][1]))
    # ★ 매칭 근거를 로그로 남긴다 - 어떤 단어 때문에 어떤 사례와 연결됐는지, 어느
    #   소스(origin)에서 왔는지 나중에 추적할 수 있어야 한다는 요구사항(재측정 시
    #   오매칭 재발 여부 확인용). relabeled(사람 라벨링) 인지 public_data_warning
    #   (원문 그대로) 인지가 매칭 결과의 신뢰도 해석에 영향을 준다.
    for (n_shared, lexical), matched, case in scored[:limit]:
        log.info(
            "[match_scam] case=%s origin=%s 수법일치=%d 어휘=%.2f 매칭단어=%s 수법=%s",
            case.id, case.origin, n_shared, lexical, matched,
            sorted(text_cats & _case_categories(case.id)),
        )
    return [c for _, _, c in scored[:limit]]


# ★ 임계값(12.0)의 근거 - SCAM_CASES 때와 달리 '정상 오매칭 최고점'과 '진짜 매칭
#   최저점' 사이에 깨끗한 빈 구간이 없었다(코퍼스가 1,017건으로 훨씬 크고 주제가
#   다양해서 어떤 문장이든 대충 겹치는 문서가 하나쯤은 나온다). 그래서 실측 노이즈
#   바닥을 기준으로 잡았다:
#     - 완전히 무관한 문장("오늘 날씨가 좋네요", "저녁에 뭐 먹을지 고민이에요" 등)의
#       최고 점수는 4.9~10.6 사이였다.
#     - 평가세트 30건 중 실제로 그 프로그램이 존재하는 케이스(N03~N07: 농어가목돈마련
#       저축, 주거상향 지원사업 등)는 19~31점대로 확실히 높게 나왔다.
#     - 10~15점대는 회색지대다(N08/N09처럼 진짜 맞는데 약하게 나오는 경우와, 순수
#       잡음이 우연히 겹치는 경우가 섞여 있다).
#   12.0은 노이즈 바닥(최대 10.6)보다는 위, 확실한 진짜 매칭 시작점(14.79)보다는
#   아래에 놓은 값이다 - 약한 진짜 매칭 일부(예: N01/N02/N08/N10, 10점대)를 놓치는
#   대가로 순수 잡음 매칭을 대부분 걸러낸다. SCAM_CASES 때처럼 완벽한 분리는 아니다 -
#   이 한계를 docs/evaluation/eval_30_report.md 재측정 결과에 그대로 적었다.
_OFFICIAL_MIN_SCORE = 12.0


def match_official_docs(text: str, limit: int = 2, min_score: float = _OFFICIAL_MIN_SCORE) -> List[OfficialDoc]:
    """공식 문서(OFFICIAL_DOCS, 공공데이터 1,017건)를 BM25로 검색한다.

    ★ SCAM_CASES 매칭과는 완전히 다른 인덱스·점수 체계다 - 절대 섞지 않는다.
    ★ 검색은 청크 단위(OfficialChunk, 재청킹된 ~1,900개)로 하고, 같은 문서에 속한
      여러 청크가 매칭되면 그 문서의 최고 점수만 남겨 references 는 문서 단위로
      묶는다 - 사용자에게 청크(문서 조각)를 그대로 보여주지 않는다.
    ★ 임계값은 위 _OFFICIAL_MIN_SCORE 주석 참고 - 코퍼스가 바뀌면 다시 실측해야 한다.
    """
    if _OFFICIAL_BM25 is None:
        return []
    tokens = _bm25_tokenize(text)
    if not tokens:
        return []
    scores = _OFFICIAL_BM25.get_scores(tokens)
    best_per_doc: dict = {}
    for chunk, score in zip(_OFFICIAL_CHUNKS, scores):
        if score <= 0:
            continue
        prev = best_per_doc.get(chunk.record_id)
        if prev is None or score > prev:
            best_per_doc[chunk.record_id] = score
    scored = [(score, record_id) for record_id, score in best_per_doc.items() if score >= min_score]
    scored.sort(key=lambda x: -x[0])
    result: List[OfficialDoc] = []
    for score, record_id in scored[:limit]:
        doc = _OFFICIAL_DOCS_BY_ID.get(record_id)
        if doc is None:
            continue
        # ★ 매칭 근거 로그 - 어떤 문서가 어떤 점수로 매칭됐는지 추적할 수 있어야 한다
        #   (match_scam_cases 의 매칭단어 로그와 같은 취지, BM25는 개별 청크 점수만
        #   나오므로 doc 단위로 집계한 점수를 남긴다).
        log.info("[match_official] doc=%s score=%.2f domain=%s", doc.id, score, doc.domain)
        result.append(doc)
    return result
