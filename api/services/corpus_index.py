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
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

log = logging.getLogger("gyeotnun.corpus_index")

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
EVIDENCE_TABLE_PATH = CORPUS_DIR / "근거_검증표.csv"
EVAL_SET_PATH = CORPUS_DIR / "곁눈_평가세트_30건.csv"
RELABELED_CASES_PATH = CORPUS_DIR / "사례_20-46건_재라벨링표.csv"

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
    """알려진 사기/사칭 사례 1건. 재라벨링표(운영 참조 데이터)에서만 온다.

    ★ 평가세트(EVAL_CASES)는 여기 절대 섞지 않는다 - 위 모듈 docstring 참고.
    """

    id: str
    text: str              # 사례 원문/제시문구
    source_label: str        # 참고_출처 또는 출처 (사람이 읽는 출처 설명)
    url: str
    published_at: Optional[str]
    risk_clues: List[str] = field(default_factory=list)     # 위험단서 / 신뢰단서
    error_types: List[str] = field(default_factory=list)     # 오판유형 (복수 라벨)
    questions: List[str] = field(default_factory=list)        # 놓친확인요소
    rationale: str = ""
    origin: str = "relabeled"   # 재라벨링표만 소스이므로 항상 "relabeled"
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

SCAM_CASES: List[ScamCase] = _load_relabeled_cases()
log.info(
    "[corpus] SCAM_CASES %s건 적재 (출처: %s만 - 평가세트 CSV는 제외)",
    len(SCAM_CASES), RELABELED_CASES_PATH.name,
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


def summary() -> dict:
    """기동 로그/헬스체크용 적재 현황."""
    return {
        "evidence_docs": len(EVIDENCE),
        "eval_cases": len(EVAL_CASES),
        "scam_cases": len(SCAM_CASES),
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
    """
    df = _SCAM_DOC_FREQ.get(keyword, 0)
    return math.log((_SCAM_N_DOCS + 1) / (df + 1)) + 1.0


def match_scam_cases(text: str, limit: int = 2, min_score: float = 5.0) -> List[ScamCase]:
    """알려진 사기 사례와 대조한다.

    ★ 오매칭 방지 (docs/evaluation/eval_30_report_before_stopword_fix.md §3에서 실측으로 발견된 문제):
      예전엔 STOPWORDS 없이 '단어 일치 개수 >= 2'로만 판단해서, "안내/지원/내용"처럼
      어떤 공공 안내문에도 흔한 단어 2개만 겹쳐도 정상 안내문이 사기 사례로 오매칭됐다.
      지금은 (1) STOPWORDS 를 채점에서 아예 빼고, (2) 남은 키워드는 코퍼스 내 희귀도로
      가중치를 매겨(_keyword_weight) 합산한다 - 흔한 단어 여러 개보다 희귀한 단어
      하나가 더 강한 신호가 되게 하기 위해서다.
    ★ 임계값(min_score=5.0)의 근거: 평가세트 30건 전체로 실측한 결과(코드가 아니라 데이터로
      정했다), '정상' 10건이 우연히 얻는 최고 점수는 4.43(단어 1개, 예: '복지'/'사업'
      같은 일반명사)이었고, 실제 사기/경계 사례가 진짜로 맞는 경우는 대부분 6점대 이상
      부터 시작했다(단어 2개 이상 조합). 4.43과 6.1 사이가 비어 있어 5.0 을 그 사이에
      놓으면 이 데이터셋 기준 '정상' 오매칭 10건을 전부 걸러내면서 사칭/경계의 진짜 일치는
      대부분 그대로 잡는다. 코퍼스가 커지면 이 값도 같은 방식(재측정)으로 다시 잡아야 한다.
    """
    kws = [k for k in extract_keywords(text) if k not in STOPWORDS]
    if not kws:
        return []
    scored = []
    for case in SCAM_CASES:
        matched = [k for k in kws if k in case._blob]
        if not matched:
            continue
        score = sum(_keyword_weight(k) for k in matched)
        if score >= min_score:
            scored.append((score, matched, case))
    scored.sort(key=lambda x: -x[0])
    # ★ 매칭 근거를 로그로 남긴다 - 어떤 단어 때문에 어떤 사례와 연결됐는지 나중에
    #   오매칭을 추적할 수 있어야 한다는 요구사항(재측정 시 오매칭 재발 여부 확인용).
    for score, matched, case in scored[:limit]:
        log.info(
            "[match_scam] case=%s score=%.2f 매칭단어=%s",
            case.id, score, matched,
        )
    return [c for _, _, c in scored[:limit]]
