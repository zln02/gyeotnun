"""
곁눈(Gyeotnun) - 공공데이터 대조 + 실시간 검색
담당: 김유리 (검색)

역할
  추출된 텍스트에서 '확인 포인트'를 뽑고, 실제로 존재하는 출처를 모아 온다.
  ★ 여기서 모은 references 의 URL 집합이 곧 prompt_chain 의 화이트리스트가 된다.
    즉 이 모듈이 근거의 진실성을 책임진다. 링크를 임의 생성하면 안 된다.

검색 우선순위
  1) corpus_index.OFFICIAL_DOCS - 공공데이터 1,017건, BM25 검색 (2026-07-30 확장)
  2) corpus_index.EVIDENCE - 근거_검증표.csv 11건, 수작업 검증 통계
  3) 로컬 공공데이터 레거시 코퍼스(public_data/*.json) - 사실상 미사용(빈 폴더)
  4) 네이버 검색 API - 최신 이슈 보강 (NAVER_CLIENT_ID/SECRET 필요, 미구현)
  (별도) corpus_index.SCAM_CASES - 사기 사례 대조. 위 공식 문서 검색과는 완전히
  분리된 신호(similar_scam_case)로, 같은 인덱스/신호에 절대 섞지 않는다.

★★ 3단계 확인 결과 판정 기준 (collect_evidence 참고, 신호 조합으로 판단한다) ★★
  확인됨(needs_check)        : 공식 출처에서 동일 내용을 찾았고, 사기 패턴 일치나
                                문장 자체의 위험 신호가 없다.
  의심(partially_matched)    : 알려진 사기 패턴과 일치하거나(similar_scam_case),
                                문장 자체에 위험 신호(조건 생략·서두름)가 있다.
  확인 불가(no_source_found) : 공식 출처를 전혀 찾지 못했다 - 기본값. 애매하면
                                '의심'이나 '확인됨'으로 단정하지 않고 여기로 유보한다.

★ 절대 하지 않는 것
  - 참/거짓 판정 반환. 이 모듈은 verdict_hint 로 '확인 필요 정도'만 돌려준다.
  - URL·기관명 생성. references 는 corpus_index/CSV 에 실제로 있던 값만 담는다.
"""
from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from config import MissingKeyError, settings
from services import corpus_index
from services import fallback_watch
# ★ 최상위 import 다. 순환하지 않는다 - embeddings → corpus_index → scam_taxonomy 로
#   내려갈 뿐, 어느 쪽도 search 를 다시 import 하지 않는다(2026-08-15 확인).
from services import embeddings

log = logging.getLogger("gyeotnun.search")

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus" / "public_data"

# 문장 자체에서 뽑는 '요구 행동의 위험도' 신호 - 출처 매칭 결과와는 무관하게 문장만 본다.
SIGNAL_RULES = [
    ("condition_omitted", ["전원", "누구나", "무조건", "모두에게", "전부"],
     "'모두에게'라는 표현이 있습니다. 공식 자료에 조건이 붙어 있는지 확인이 필요합니다."),
    ("urgency_pressure", ["긴급", "마감", "오늘까지", "서둘러", "신청 안 하면", "선착순"],
     "서두르게 만드는 표현이 있습니다. 시간을 두고 확인해도 되는 내용인지 살펴보세요."),
    ("contact_in_image", ["계좌", "입금", "송금", "연락처"],
     "개인 연락처나 계좌 정보가 들어 있습니다."),
]

# ★ 발행기관 명시 여부: 예전엔 보건복지부·질병관리청 등 특정 기관명 8개를 정확히
#   써야만 "명시됨"으로 인정했다. 실제 문장은 '복지로에서 확인하세요'처럼 서술형이
#   많아 이 좁은 목록에 잘 안 걸렸고, 그 결과 정상적인 공식 안내조차 '미명시'로
#   오판되어 needs_check(확인됨)에 아예 도달하지 못했다(docs/evaluation/eval_30_report.md
#   §6-1). 특정 기관명을 나열하는 대신 한국 공공기관 이름에 흔한 접미사로 넓게 잡고,
#   아래 collect_evidence() 에서 이 신호를 severity="info"(참고용)로만 쓴다 - 판정은
#   실제로 공식 출처를 찾았는지(코퍼스 매칭)로 하는 게 키워드 나열보다 신뢰도가 높다.
_ORG_SUFFIX_RE = re.compile(r"(부|처|청|원|공단|공사|재단|센터|협회|위원회|복지로|정부24|건강보험|국민연금)")


@dataclass
class SearchResult:
    verdict_hint: str = "no_source_found"   # needs_check | partially_matched | no_source_found
    signals: List[dict] = field(default_factory=list)
    references: List[dict] = field(default_factory=list)


# ★★ 긴급성 단독 경고 억제 (2026-08-12 채택) ★★
#   정상 마케팅 문자가 "선착순·마지막 기회·완판직전"을 쓴다. 긴급성 하나만으로
#   경고를 띄우면 정상 광고가 경고를 받는다 - 실측으로 정상 오판 4건 중 3건이
#   이것이었다(R04 취업멘토링, R05 취업멘토링, R09 아파트 분양).
#   → 긴급성은 '위험한 행동을 요구할 때'만 경고로 올린다. 단독이면 info 로 남긴다.
#
#   실측(확대 112건 / 홀드아웃 30건, docs/evaluation/실험_신호결합_도메인_2026-08-12.md)
#     정상 오판   4/37 → 1/37     |  2/10 → 1/10
#     사칭 판정   94.6% → 94.6%   |  100% → 100%    ← 1건도 안 떨어짐
#     경계 판정   65.8% → 68.4%   |  70.0% → 80.0%
#     축2 헛경고  15.7% → 2.9%    |  33.3% → 16.7%
#
#   ★ 되돌리려면 이 상수 하나만 False 로 바꾼다(임계값 상수와 같은 방식).
#     False 면 2026-08-12 이전 동작(긴급성 단독으로도 경고)으로 즉시 복귀한다.
URGENCY_REQUIRES_ACTION = True

# ★★ 경보문이 근거로 매칭되면 주의 신호로 올린다 (2026-08-12 채택) ★★
#   근거·실측: docs/evaluation/IDF척도이동_A안_2026-08-12.md §4
#     정상 오판 불변(1/37, 1/10) · 축2 헛경고 불변(2/70, 3/18)
#     사칭 경고 14→18(확대) / 2→4(홀드) · S22 가 초록에서 경고로 바뀐다
#   ★ 되돌리기: 이 상수를 False 로 두면 2026-08-12 이전 동작으로 즉시 복귀한다
#     (임계값 상수·URGENCY_REQUIRES_ACTION 과 같은 방식).
ALERT_DOC_AS_ATTENTION = True

# 경보문으로 볼 data_type. records_merged.jsonl 의 원본 필드를 그대로 쓴다.
# ★ press_release(24건)는 data_type 으로 넣지 않는다 - "업무협약 체결"·"출범 6개월
#   성과" 같은 정책·성과 발표가 섞여 있어 통째로 경보문이라 부를 수 없다.
#   대신 사람이 검수한 8건만 아래 ALERT_DOC_IDS 로 개별 지정한다.
ALERT_DOC_DATA_TYPES = {"warning_case"}

# ★★ 사람이 검수해 확정한 경보문 문서 id 허용목록 (2026-08-13) ★★
#   press_release 24건을 A/B/C 로 분류한 결과 B(사기 경보문) 8건.
#   분류 초안·근거: docs/evaluation/press_release_24건_분류초안_2026-08-13.md
#   기준: 금융코퍼스_수집조사_2026-08-12.md §2 (A·B 둘 다면 B 우선, 애매하면 C)
#
#   ★ 왜 data_type 이 아니라 id 목록인가
#     ALERT_DOC_DATA_TYPES 에 "press_release" 를 넣으면 C 16건(업무협약·시상식·
#     단속실적·성과통계)이 함께 딸려 온다. 그것들은 사용자가 받은 문자를 대조할
#     근거도, 사기 수법 설명도 아니다. **id 목록이어야 "사람이 확인한 것만
#     들어간다"가 코드에서도 성립한다.** 새 문서를 자동으로 포함시키지 않는 것이
#     이 자료구조의 목적이다 - 늘리려면 사람이 다시 분류해야 한다.
#
#   ★ C 로 남긴 것 중 판단이 갈렸던 둘 (2026-08-13 사람 확인 완료, C 유지)
#     #24 소상공인시장진흥공단 협업 - 수법 1문단이 실려 B 요건을 글자대로는
#          충족하나 문서 목적이 협약 발표다. "애매하면 C" 규칙 적용.
#     #17 조달청 노쇼사기 협약 - 제목에 '노쇼 사기'가 있으나 수법 묘사가 없다.
#          제목 단어만으로 넘기면 협약문이 대거 딸려 들어온다.
ALERT_DOC_IDS = {
    "1cd77fbda81a4fef75cf",  # 24.10.16. 나도 모르는 사이에 내 휴대전화가 좀비 폰으로?
    "37a6132cf4a6384ac918",  # 25.10.2. 국가정보자원관리원 화재 상황을 악용한 피싱 주의
    "70e0c6e28a0d988ac80f",  # 25.1.22. 갈수록 진짜 같은 전화금융사기, 가스라이팅의 덫
    "71894b4e7748634ff2f6",  # 24.10.24. 기관사칭형 보이스피싱, 60대 여성을 노린다
    "8a19ce4581ea7665b51c",  # 25.4.28. 그놈 목소리, 치밀한 각본 주인공이 되시겠습니까
    "c17b9a29ba832ccb32db",  # 24.11.8. 딥페이크를 악용한 자녀납치형 전화금융사기 주의
    "cf16ec150722322d2079",  # 26.3.24. 중동 사태 악용 피싱 '주의 경보' 발령
    "d9537fcb58ca6f781e7a",  # 26.2.12. 신종 스캠 주의보 - 설 명절
}


def _is_alert_doc(doc) -> bool:
    """이 공식 문서를 '사기 경보문'으로 볼 것인가.

    두 경로다 - data_type 이 warning_case 이거나(134건, 원본 라벨을 그대로 신뢰),
    사람이 검수해 허용목록에 올린 문서이거나(press_release 중 8건).
    """
    return getattr(doc, "data_type", "") in ALERT_DOC_DATA_TYPES or doc.id in ALERT_DOC_IDS

# 문장이 '요구하는 행동'을 텍스트만 보고 고른다.
# ★ 평가셋의 위험행동 컬럼을 절대 참조하지 않는다 - 그건 라벨 누수이고 배포할 수 없다.
#   키워드는 요구 행동의 동사에서 뽑았고, 실패 사례를 보고 고르지 않았다.
#   (실측 재현율: 확대 112건에서 37/39. 놓친 2건은 B09·S24 인데 둘 다 이 변경으로
#    tier 가 달라지지 않는 것을 확인하고 채택했다. 그 2건을 통과시키려고 키워드를
#    덧붙이지 않는다 - 그건 평가셋 맞춤이다.)
RISK_ACTION_KEYWORDS = {
    "계좌이체": ["입금", "송금", "이체", "선결제", "예치", "상환", "납부",
                 "보내 주", "보내주", "보내줘", "계좌로", "결제해"],
    "앱설치": ["앱을 설치", "앱 설치", "설치하시", "설치해", "설치하고", "다운로드",
               "파일을 설치", "깔아"],
    "인증번호": ["인증번호", "본인인증", "인증서", "공동인증", "본인 인증"],
    "개인정보요구": ["주민등록번호", "주민번호", "신분증", "통장 사본", "통장사본",
                     "계좌번호를 입력", "계좌를 등록", "계좌 등록", "카드번호",
                     "생년월일 뒤", "뒤 7자리", "연락처를 알려", "시세를 먼저 알려",
                     "주소를 다시 입력", "정보를 다시 입력", "사진을 보내", "사진을 업로드"],
}


# ══════════════════════════════════════════ 유형 정확도 보정 (2026-08-13)
# ★ 왜 고쳤나
#   이 함수는 지금까지 urgency_pressure 를 attention 으로 둘지 info 로 내릴지만
#   가르는 **이진 게이트**였다. "무언가 요구가 있다"만 맞으면 됐고 유형이 틀려도
#   무해했다. 그런데 화면이 유형을 말하기 시작하면 **유형 오류가 곧 거짓말이 된다.**
#     N17(정상) "응급안전안심 장비를 설치해 드리는 서비스" → 앱설치로 검출됐다
#     B25/H40   "통장 사본을 보내 주세요"                  → 계좌이체로 검출됐다
#   실측: docs/evaluation/위험행동_신호_설계측정_2026-08-13.md
#
# ★ 수정 두 가지. 둘 다 **유형 정의에서 나온다** - 평가셋 실패를 보고 맞춘 게 아니다.
#   (가) 최장 매칭 우선 - dict 순서에 기대던 것을 없앤다. 겹치면 더 구체적인(긴)
#        어휘가 이긴다. "통장 사본"(5자) > "보내 주"(4자) → 개인정보요구.
#        근거: '통장 사본을 보내라'는 개인정보 요구이지 자금 이체가 아니다.
#   (나) 문맥 조건 - 아래 두 사전. 근거: 유형 이름이 '앱 설치'다. 장비 설치는
#        앱 설치가 아니다. '보내 주'는 무엇을 보내는지에 따라 유형이 갈린다.
#   ※ (가)만으로는 N17 이 안 고쳐지고, (나)만으로는 순서 의존이 남는다. 둘 다 쓴다.
#
# ★ 실측 결과: 유형일치 88.0% → 92.0% · 정상 과검출 1건 → 0건 · **tier 변경 0건**
#   검출률(92.0%)은 그대로다 - 재현율은 손대지 않았다. 미검출 4건(B09·S24·H23·H24)
#   은 여전히 미검출이고, 그 2건을 통과시키려 어휘를 덧붙이지 않았다.

# 그 자체로 유형이 확실해 문맥 조건을 면제하는 어휘
_RISK_SELF_EVIDENT = {
    "계좌이체": {"입금", "송금", "이체", "선결제", "예치", "상환", "납부", "계좌로", "결제해"},
    "앱설치": {"앱을 설치", "앱 설치", "다운로드", "파일을 설치"},
}
# 위 목록에 없는 어휘는 이 문맥이 함께 있어야 그 유형으로 본다
_RISK_CONTEXT_REQUIRED = {
    "계좌이체": ["돈", "원을", "원 을", "만원", "만 원", "금액", "대금", "요금", "비용",
                 "계좌", "입금", "송금", "이체", "결제", "수수료", "보증금", "공탁금",
                 "합의금", "예치금", "선입금", "지급"],
    "앱설치": ["앱", "어플", "애플리케이션", "app", "APP", "앱스토어", "플레이스토어",
               "다운로드", "프로그램", "apk", "APK", "파일", "링크"],
}


def detect_risk_action_detail(text: str) -> tuple[Optional[str], str]:
    """요구된 '위험한 행동'과 **그 근거가 된 원문 어휘**를 함께 돌려준다.

    반환: (유형 or None, 매칭된 어휘)
    ★ 어휘를 함께 돌려주는 이유: 화면에 근거 구절을 그대로 인용하기 위해서다.
      유형 라벨이 만에 하나 어긋나도 사용자는 실제 구절을 본다.
    """
    t = text or ""
    best_label: Optional[str] = None
    best_kw = ""
    for label, keywords in RISK_ACTION_KEYWORDS.items():
        for k in keywords:
            if k not in t:
                continue
            # (나) 문맥 조건
            if label in _RISK_CONTEXT_REQUIRED and k not in _RISK_SELF_EVIDENT.get(label, set()):
                if not any(c in t for c in _RISK_CONTEXT_REQUIRED[label]):
                    continue
            # (가) 최장 매칭 우선
            if len(k) > len(best_kw):
                best_label, best_kw = label, k
    return best_label, best_kw


def detect_risk_action(text: str) -> str | None:
    """이 글이 사용자에게 요구하는 '위험한 행동'을 고른다. 없으면 None.

    계좌이체 / 앱설치 / 인증번호 / 개인정보요구 중 하나를 돌려준다.
    """
    return detect_risk_action_detail(text)[0]


# ══════════════════════════════════════ 위험행동을 화면 신호로 내보낸다 (2026-08-13)
# ★ 왜: R11(KB국민카드 당첨 + 앱설치)은 warn 이 뜨는데 이유가 similar_scam_case 라
#   화면에 "이전에 확인된 사례와 비슷한 문장이 있어요" 가 나갔다. 실제로 검출한 것은
#   "앱 설치를 요구한다" 다. **경고는 옳고 이유가 틀렸다.**
#   verdict.js 머리말 원칙 - "'사실 한 줄'은 실제로 검출한 것만 적는다" - 위반이다.
#
# ★★ 되돌리기·단계 적용 스위치 ★★
#   RISK_ACTION_SIGNAL      False 로 두면 신호 자체를 안 내보낸다 (2026-08-13 이전 동작)
#   RISK_ACTION_RAISES_TIER False = 안B. severity=info 로 내보내 **tier 를 올리지 않고
#                                   이미 경고인 글의 '이유'만 바로잡는다.**
#                                   정상 오판이 원리적으로 늘지 않는다.
#                           True  = 안A. severity=attention. hold 였던 글이 warn 으로
#                                   올라간다(확대 26건). 사칭 검출 +10/+5, 축2 38/39.
#   ★ True 로 켜기 전에 화면 변형이 먼저다. 위험행동 warn 을 사기사례 유사 화면
#     ("확인이 필요한 문자예요")으로 재사용하면 그건 의심 프레임이라
#     "정상을 의심으로 표시하지 않는다"는 절대 조건과 충돌한다.
#     실측·결정: docs/evaluation/위험행동_신호_설계측정_2026-08-13.md
RISK_ACTION_SIGNAL = True
RISK_ACTION_RAISES_TIER = True

# 서버 label 은 고정 문구다(no_official_source·urgency_pressure 와 같은 형식).
# ★ 화면 문구는 verdict.js 가 detail 로 분기해 따로 정한다 - 60대 대상 문구를
#   서버에서 확정하지 않는다는 기존 기준 그대로다.
RISK_ACTION_LABEL = {
    "계좌이체": "돈을 보내라는 내용이 있습니다.",
    "앱설치": "앱을 설치하라는 내용이 있습니다.",
    "인증번호": "본인인증을 하라는 내용이 있습니다.",
    "개인정보요구": "개인정보를 보내라는 내용이 있습니다.",
}
_RISK_QUOTE_MAX = 60


def risk_action_quote(text: str, keyword: str) -> str:
    """검출 근거가 된 어휘가 들어 있는 문장을 그대로 뽑는다.

    ★ 입력은 이미 마스킹된 텍스트다 - collect_evidence 가 받는 값이
      routers/checks.py 의 stored["masked_text"] 이기 때문이다. 그래서 이 인용에는
      전화번호·계좌·주민번호가 원본 그대로 실릴 수 없다.
      ★ 그럼에도 어휘가 마스킹으로 사라졌으면 인용하지 않는다(빈 문자열).
        없는 문장을 지어내느니 유형 문구만 내보내는 편이 낫다.
    """
    if not keyword or keyword not in (text or ""):
        return ""
    for sentence in re.split(r"(?<=[.!?])\s|\n", text):
        if keyword in sentence:
            s = sentence.strip()
            return s if len(s) <= _RISK_QUOTE_MAX else s[:_RISK_QUOTE_MAX - 1] + "…"
    return ""


def detect_signals(text: str) -> List[dict]:
    """텍스트 자체에서 '요구 행동의 위험도' + '발행기관 명시 여부' 신호를 뽑는다.

    ★ source_missing 은 severity="info" 다 - 이것만으로 확인불가/의심을 정하지
      않는다. 실제 판정은 collect_evidence() 가 공식 출처 매칭 여부까지 함께 본다.
    ★ urgency_pressure 는 위험행동과 함께 있을 때만 attention 이다
      (URGENCY_REQUIRES_ACTION 참고).
    """
    text = text or ""
    risk_action = detect_risk_action(text) if URGENCY_REQUIRES_ACTION else None
    out: List[dict] = []
    for key, keywords, label in SIGNAL_RULES:
        if any(k in text for k in keywords):
            severity = "info" if key == "contact_in_image" else "attention"
            # 긴급성 단독(요구하는 행동이 없음)은 참고 정보로만 남긴다.
            if URGENCY_REQUIRES_ACTION and key == "urgency_pressure" and risk_action is None:
                severity = "info"
            out.append({"key": key, "label": label, "severity": severity})
    if not _ORG_SUFFIX_RE.search(text):
        out.append({
            "key": "source_missing",
            "label": "이 글 자체에는 어느 기관이 발표했는지가 적혀 있지 않습니다.",
            "severity": "info",
        })
    return out


def search_corpus(query: str, domain: str | None = None, limit: int = 5) -> List[dict]:
    """레거시: 공공데이터 577건 코퍼스(corpus/public_data/*.json)에서 찾는다 (키 불필요).

    아직 원문이 수집되지 않아 현재는 항상 빈 리스트를 돌려준다(폴더가 비어 있음).
    수집이 끝나면 collect_evidence() 에서 corpus_index 결과에 보조로 합쳐진다.
    TODO(김유리): 임베딩 기반 유사도 검색으로 교체 (장지석 RAG 인덱스와 공유).
    """
    if not CORPUS_DIR.exists():
        return []
    tokens = [t for t in (query or "").replace("\n", " ").split() if len(t) >= 2]
    hits: List[dict] = []
    for path in sorted(CORPUS_DIR.glob("*.json")):
        try:
            docs = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(docs, dict):
            docs = [docs]
        for doc in docs:
            blob = f"{doc.get('title', '')} {doc.get('body', '')}"
            score = sum(1 for t in tokens if t in blob)
            if domain and doc.get("domain") == domain:
                score += 1
            if score > 0:
                hits.append((score, doc))
    hits.sort(key=lambda x: -x[0])
    return [
        {
            "title": d.get("title", ""),
            "url": d.get("url", ""),
            "publisher": d.get("publisher", ""),
            "published_at": d.get("published_at"),
            "source_type": "public_data",
        }
        for _, d in hits[:limit]
        if d.get("url")            # ★ URL 없는 문서는 근거로 쓰지 않는다
    ]


def search_web(query: str, display: int = 5) -> List[dict]:
    """TODO(김유리): 네이버 검색 API(news/webkr) 호출.

    구현 스케치::

        headers = {
            "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
        }
        r = httpx.get("https://openapi.naver.com/v1/search/news.json",
                      params={"query": query, "display": display, "sort": "sim"},
                      headers=headers, timeout=10)
        → title 의 <b> 태그 제거, originallink 를 url 로 사용

    ★ 응답에 실제로 들어 있던 링크만 references 에 담는다. 가공/추측 금지.
    """
    if not settings.has_search:
        raise MissingKeyError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET", owner="김유리")
    raise NotImplementedError("search_web 미구현. ?mock=1 을 사용하세요.")


def _dedup_refs(refs: List[dict]) -> List[dict]:
    """URL 기준으로 중복을 없앤다. 먼저 들어온 순서(우선순위)를 지킨다."""
    seen: set[str] = set()
    out: List[dict] = []
    for r in refs:
        u = r.get("url")
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


# ==================================================== 하이브리드 검색 (BM25 + 임베딩)
# ★ 실험/벤치마크용이다. collect_evidence() 는 아직 이 함수들을 쓰지 않는다 - BM25/
#   임베딩/하이브리드 중 어느 것을 실제로 쓸지는 3방식 벤치마크 결과를 보고 사용자가
#   결정한다(docs/evaluation/hybrid_search_report.md). 그 전까지 프로덕션 경로는
#   기존 BM25 단독(corpus_index.match_official_docs)이다.

def _reciprocal_rank_fusion(
    rankings: List[List[str]],
    weights: List[float] | None = None,
    k: int = 60,
) -> dict:
    """순위 기반 결합(RRF). 점수를 직접 더하지 않는 이유:

    BM25 점수(코퍼스 크기에 따라 0~30점대까지 요동)와 코사인 유사도(항상 0~1)는
    척도가 완전히 달라서, 그대로 더하면 절대값이 큰 BM25 가 결과를 사실상 지배해
    버린다(정규화를 해도 분포 형태가 다르면 여전히 왜곡된다). RRF 는 "몇 점인지"가
    아니라 "몇 등인지"만 보므로 척도가 다른 신호를 안전하게 섞을 수 있다 - 정보
    검색에서 표준적으로 쓰이는 결합 방식이다(Cormack et al., 2009).

        score(d) = Σ_r  weight_r / (k + rank_r(d))   (그 방법의 결과에 없으면 0)

    k=60 은 RRF 원 논문의 기본값을 그대로 썼다 - 상위 몇 등 차이의 영향을 과하게
    키우지 않으면서도 순위 정보를 반영하는 값으로 이미 널리 검증돼 있어, 우리
    데이터로 다시 튜닝할 특별한 이유를 찾지 못했다(바꾸게 되면 이 주석에 실측
    근거를 추가할 것).
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    scores: dict = {}
    for ranking, w in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return scores


# ★ 결합 가중치(BM25:임베딩)의 근거는 docs/evaluation/hybrid_search_report.md
#   §가중치 튜닝 참고 - 30건 평가세트로 실측해서 정했다. 아래는 그 실측 결과값이다.
HYBRID_WEIGHT_BM25 = 1.0
HYBRID_WEIGHT_EMBEDDING = 1.0


def match_official_docs_hybrid(
    text: str,
    limit: int = 2,
    weight_bm25: float = HYBRID_WEIGHT_BM25,
    weight_embedding: float = HYBRID_WEIGHT_EMBEDDING,
    k: int = 60,
):
    """BM25 순위 + 임베딩 순위를 RRF 로 결합한 공식 문서 검색 (실험/벤치마크용).

    한쪽이 후보를 못 찾아도(예: 임베딩 인덱스 파일이 아직 없음) 나머지 하나만으로
    계속 동작한다 - 하이브리드가 반쪽만 살아 있어도 서비스가 죽지 않는다.
    """
    bm25_docs = corpus_index.match_official_docs(text, limit=max(limit, 10))
    bm25_ranking = [d.id for d in bm25_docs]

    embedding_hits = embeddings.match_embedding_docs(text, limit=max(limit, 10))
    embedding_ranking = [d.id for _, d in embedding_hits]

    if not bm25_ranking and not embedding_ranking:
        return []

    fused = _reciprocal_rank_fusion(
        [bm25_ranking, embedding_ranking],
        weights=[weight_bm25, weight_embedding],
        k=k,
    )
    ranked_ids = sorted(fused, key=lambda rid: -fused[rid])[:limit]
    return [
        corpus_index._OFFICIAL_DOCS_BY_ID[rid]
        for rid in ranked_ids
        if rid in corpus_index._OFFICIAL_DOCS_BY_ID
    ]


# ★ 2026-08 채택 결정: 임베딩 단독(Upstage) - 30건 벤치마크에서 BM25 대비 뚜렷한
#   우위(정상 근거매칭 7/10→10/10, Recall@3 30%→65%)를 실측으로 확인했다
#   (docs/evaluation/hybrid_search_report.md). 하이브리드(RRF)는 미채택이지만
#   코드는 지우지 않고 남겨 뒀다(match_official_docs_hybrid, 위) - 나중에 다시
#   검토하거나 폴백 전략을 바꿀 때 재활용한다.
#
# ★ 발표 당일 최대 리스크는 외부 API(Upstage) 의존이다(사용자 명시) - 그래서
#   임베딩을 기본으로 쓰되, 실패하면 로컬 BM25 로 즉시 폴백한다. BM25 는 "공짜
#   보험" - 어떤 이유로든 임베딩이 안 되면 서비스가 멈추는 대신 조용히 BM25 로
#   내려간다.
# ══════════════════════════════════════════════ 검색 폴백률 상시 관측 (2026-08-13)
# ★ 왜 넣는가: 폴백이 발동하는 상황은 **이미 장애 상황**인데, 화면은 평소와 똑같다.
#   사용자는 지금 임베딩이 아니라 BM25 로 근거를 붙이고 있다는 사실을 알 수 없고,
#   BM25 하한선(_OFFICIAL_MIN_SCORE=12.0)은 코퍼스가 커질수록 실질적으로 느슨해진다
#   (docs/evaluation/본선과제_BM25폴백_척도이동.md). 즉 장애 중에 평소보다 무른
#   기준으로 근거가 붙는다. 그런데 지금은 "계속 이러고 있다"를 말해 주는 게 없다.
#
#   개별 발생은 이미 남는다 - log.warning + log_incident("EX-003") → error_logs 테이블.
#   없는 것은 **비율**이다. 8/9 에 외부 LLM 이 8시간 동안 폴백률 100% 였는데
#   아무도 인지하지 못한 사건이 정확히 이 구조였고, 그때 질문 생성 쪽에 붙인 관측이
#   GN-003 이다. 검색 쪽에 같은 형식으로 맞춘다.
#
# ★ 관측만 한다. 폴백 동작도, 임계값도, 판정 로직도 건드리지 않는다.
#   - 프로세스 메모리라 재시작하면 초기화된다. 워커 1개 전제도 GN-003 과 같다.
#   - 임계를 넘는 동안에는 한 번만 경고하고, 정상으로 돌아오면 다시 무장한다.
#   - 창 크기·최소 표본·임계는 GN-003 과 **같은 판단**이므로 한곳에서 가져온다
#     (services/fallback_watch.py). 전에는 값을 복사해 둬서, 한쪽만 고쳐도
#     테스트가 통과하고 두 관측이 조용히 다른 기준으로 도는 상태였다.
_recent_search_fallbacks: deque = deque(maxlen=fallback_watch.FALLBACK_WINDOW)
_search_fallback_alerted = False


def _observe_search_fallback(is_fallback: bool) -> None:
    """검색 1건의 폴백 여부를 기록하고, 비율이 임계를 넘으면 EX-006 을 한 번 남긴다."""
    global _search_fallback_alerted
    _recent_search_fallbacks.append(bool(is_fallback))
    if len(_recent_search_fallbacks) < fallback_watch.FALLBACK_MIN_SAMPLES:
        return
    n = len(_recent_search_fallbacks)
    hit = sum(_recent_search_fallbacks)
    rate = hit / n
    if rate > fallback_watch.FALLBACK_ALERT_RATE:
        if not _search_fallback_alerted:
            _search_fallback_alerted = True
            log.warning("[search_fallback_rate] 최근 %d건 중 %d건이 BM25 폴백 (%.0f%%) "
                        "- 임베딩 인덱스·모델 상태를 점검할 것", n, hit, rate * 100)
            from services.incident_log import log_incident
            log_incident("EX-006", detail=f"최근 {n}건 중 BM25 폴백 {hit}건 ({rate * 100:.0f}%)")
    elif _search_fallback_alerted:
        _search_fallback_alerted = False   # 정상 복귀 - 다음 악화 때 다시 경고할 수 있게 무장
        log.info("[search_fallback_rate] 폴백률이 임계 아래로 돌아왔다 (%.0f%%)", rate * 100)


def match_official_docs_safe(text: str, limit: int = 2) -> tuple:
    """공식 문서 검색 - 임베딩을 우선 쓰고, 실패하면 즉시 BM25 로 폴백한다.

    반환값: (문서 리스트, 실제 쓰인 방식("embedding"|"bm25_fallback"),
    임베딩 최상위 유사도 - BM25 폴백이면 None, 척도가 달라 비교 불가하다).
    """
    try:
        hits = embeddings.match_embedding_docs(text, limit=limit)
        docs = [d for _, d in hits]
        top_score = hits[0][0] if hits else None
        log.info("[official_search] 임베딩 검색 성공 (%d건)", len(docs))
        _observe_search_fallback(False)
        return docs, "embedding", top_score
    except embeddings.EmbeddingUnavailableError as e:
        log.warning("[official_search] 임베딩 검색 실패 - BM25 로 폴백: %s", e)
        # ★ 오류 코드 체계(2026-08): 폴백 동작 자체는 그대로 두고(BM25 결과를 반환),
        #   서버가 이 발생 빈도를 스스로 인지하도록 EX-003 을 남긴다. 사용자 화면은
        #   바뀌지 않는다("주의: 기존 폴백 동작을 바꾸지 마라").
        from services.incident_log import log_incident
        log_incident("EX-003", detail=str(e)[:120])
        docs = corpus_index.match_official_docs(text, limit=limit)
        log.info("[official_search] BM25 폴백 완료 (%d건)", len(docs))
        # ★ 개별 발생(EX-003)은 위에서 이미 남겼다. 여기서는 '반복되고 있다'만 본다.
        _observe_search_fallback(True)
        return docs, "bm25_fallback", None


# ★ 임계값(0.52)의 근거: 30건 평가세트 실측(docs/evaluation/hybrid_search_report.md
#   §0-1과 같은 실측 세션). '정상' 10건 중 최저 유사도는 0.5378(N02)이었고,
#   '경계'(모호한 사례, 확인불가가 기대판단) 10건 중 최고 유사도는 0.5058(B01)
#   이었다 - 0.5058과 0.5378 사이가 비어 있어 0.52 를 그 사이에 놓았다. 이 값
#   아래면 "근거는 찾았지만(레퍼런스로는 보여주되) 확인됨으로 단정할 만큼
#   확신하지는 않는다"로 취급해 확인불가로 유보한다 - 검색 성공 여부(참고자료
#   유무)와 판정 확신도(needs_check로 볼지)를 분리한 것이다.
#   ★ 2026-08-04 로컬 임베딩 전환에 맞춰 재실측했다. 모델이 바뀌면 유사도 분포가
#     달라서 0.52 를 그대로 쓰면 판정이 무너진다.
#       e5-small-ko-v2: 경계 최고 0.6760 < 정상 최저 0.6820 → 사이값 0.6790
#     ※ 간격이 0.006 으로 좁다(Upstage 는 0.032). 표본 30건 기준이므로, 실사용
#       데이터가 쌓이면 재보정할 것.
_CONFIDENT_BY_PROVIDER = {"upstage": 0.52, "local": 0.6790}
CONFIDENT_MATCH_THRESHOLD = _CONFIDENT_BY_PROVIDER[embeddings.EMBEDDING_PROVIDER]


def collect_evidence(text: str, domain: str | None = None) -> SearchResult:
    """근거 수집 파이프라인.

    우선순위: 공식 문서(임베딩 우선, 실패 시 BM25 폴백 - match_official_docs_safe)
    → corpus_index 근거_검증표(EVIDENCE, 11건 수작업 검증 통계) → public_data 레거시
    (577건, 아직 비어 있음). 셋 다 못 찾으면 '못 찾았다'는 사실 자체를 신호로 남긴다
    (판정하지 않는다).

    ★ 사기 사례(SCAM_CASES) 매칭은 공식 문서 매칭과 완전히 별개의 신호(similar_scam_case)
      다 - "공식 자료를 찾았다"와 "사기 사례와 비슷하다"를 절대 같은 신호로 섞지 않는다.
    """
    signals = detect_signals(text)

    # ---- 공식 문서를 먼저 검색한다 (임베딩 우선, 실패 시 BM25 폴백)
    matched_official, official_mode, official_top_score = match_official_docs_safe(text)
    matched_evidence = corpus_index.match_evidence(text)
    matched_scam = corpus_index.match_scam_cases(text)
    legacy_refs = search_corpus(text, domain=domain)

    # ---- 신호: 공식 문서/통계 매칭. matched_official 과 matched_evidence 는 인덱스는
    #      다르지만 사용자 입장에서는 둘 다 "공식 자료를 찾았다"는 같은 의미라
    #      같은 신호 키(official_source_found)를 쓴다 - 어느 코퍼스에서 왔는지는
    #      내부 구현일 뿐, 사용자에게 중요한 건 '공식 자료인지 여부'다.
    for doc in matched_official:
        signals.append({
            "key": "official_source_found",
            "label": f"공식 자료와 대조했습니다: {doc.source_agency} - {doc.title}",
            "severity": "info",
        })
    for doc in matched_evidence:
        signals.append({
            "key": "official_source_found",
            "label": f"공식 통계·자료와 대조했습니다: {doc.publisher} - {doc.title}",
            "severity": "info",
        })

    # ---- 신호: 근거로 붙은 공식 문서가 '사기 경보문'이면 주의 신호로 올린다.
    #      ★ 왜 필요한가 (2026-08-12, S22)
    #        KISA 사칭 문자에 대해 "KISA 보안공지를 사칭한 스미싱 문자 주의"라는
    #        바로 그 경보문을 0.7023 으로 정확히 찾아 놓고, 경보문이 OFFICIAL_DOCS 에
    #        있다는 이유로 official_source_found(info)만 붙어 화면에 초록
    #        "공식 자료를 찾았어요"가 나갔다. 사용자는 "이 문자가 확인됐다"로 읽는다.
    #        찾은 것은 맞는데 의미가 정반대로 전달된 것이다.
    #      → "공식 기관이 낸 문서"와 "이 글이 사실이라는 근거"를 구분한다.
    #
    #      ★ press_release 는 제외한다. 정책·성과 발표(협약 체결, 출범 성과)가
    #        섞여 있어 경보문이라 부를 수 없다. 사람 검수 후 별도로 다룬다.
    #      ★ label 은 고정 문구다. 기관·제목은 references(to_reference)에 이미
    #        들어가므로 label 에 또 넣으면 중복이다 - no_official_source·
    #        urgency_pressure 등 다른 attention 키와 같은 형식을 따른다.
    #      ★ "찾았습니다"를 쓰지 않는다. 초록 화면의 "공식 자료를 찾았어요"와
    #        같은 표현이라, 고치려는 그 오해를 label 로 다시 만들게 된다.
    if ALERT_DOC_AS_ATTENTION and any(_is_alert_doc(d) for d in matched_official):
        signals.append({
            "key": "official_alert_matched",
            "label": "받으신 내용과 비슷한 사례를 알리는 공식 안내가 있습니다.",
            "severity": "attention",
        })

    # ---- 신호: 이 글이 요구하는 '위험한 행동' (2026-08-13)
    #   ★ 지금까지 detect_risk_action 의 결과는 urgency_pressure 강등 판단에만 쓰이고
    #     화면으로 나가지 않았다. 그 탓에 R11 은 경고가 뜨는데 이유가 사기사례 유사로
    #     표시됐다 - 검출한 것은 '앱 설치 요구'인데 다른 것을 적고 있었다.
    #   ★ severity 는 스위치가 정한다. 기본값(False)은 tier 를 올리지 않는다.
    if RISK_ACTION_SIGNAL:
        _risk, _kw = detect_risk_action_detail(text)
        if _risk:
            signals.append({
                "key": "risk_action_requested",
                "label": RISK_ACTION_LABEL[_risk],
                "severity": "attention" if RISK_ACTION_RAISES_TIER else "info",
                "detail": _risk,
                "quote": risk_action_quote(text, _kw),
            })

    # ---- 신호: 유사 사기 사례 일치 (강한 경고 신호) - 위 official_source_found 와
    #      명확히 다른 키를 쓴다. 같은 텍스트가 공식 문서와도, 사기 사례와도 동시에
    #      매칭될 수 있다(예: 실제 제도명을 사칭한 문자) - 그때도 두 신호를 각각 보여준다.
    for case in matched_scam:
        signals.append({"key": "similar_scam_case", "label": case.signal_label(), "severity": "attention"})

    refs = _dedup_refs(
        [d.to_reference() for d in matched_official]
        + [d.to_reference() for d in matched_evidence]
        + [c.to_reference() for c in matched_scam]
        + legacy_refs
    )

    # ★★ 3단계 판정 - 모듈 docstring의 기준을 그대로 코드로 옮긴 것이다.
    #   official_source_found/source_missing(둘 다 severity="info")은 판정에 영향을
    #   주지 않는다 - "출처를 찾았다"는 사실 자체와 "위험하다"는 신호는 다른 질문이다.
    #   attention 신호(사기 패턴 일치, 조건 생략, 서두름)가 있을 때만 '의심'으로 올린다.
    risky = any(s["severity"] == "attention" for s in signals)

    # ★ 경계 케이스 개선(2026-08): "근거를 찾았는가"와 "그 근거를 확인됨으로 볼
    #   만큼 확신하는가"를 분리한다. matched_evidence(수작업 검증 통계)·
    #   matched_scam(사기사례 매칭, 자체 임계값 5.0 통과)·BM25 폴백(자체 임계값
    #   12.0 통과)은 이미 각자의 검증을 거쳤으니 그대로 확신 있는 근거로 본다.
    #   임베딩 경로만 추가로 CONFIDENT_MATCH_THRESHOLD 를 넘는지 본다 - 넘지
    #   못하면(예: 0.45~0.52 사이의 약한 유사도) references 에는 그대로 보여주되
    #   (근거는 찾되) needs_check 로 단정하지는 않는다.
    if official_mode == "embedding":
        official_confident = official_top_score is not None and official_top_score >= CONFIDENT_MATCH_THRESHOLD
    else:  # bm25_fallback 이거나 애초에 매칭이 없었던 경우
        official_confident = bool(matched_official)
    # ★ matched_evidence(근거_검증표)는 min_score=1 키워드 매칭이라 흔한 단어 하나로도
    #   걸린다(예: "이용" → NIA 디지털정보격차 통계). 유사도 확신 검증을 못 거치므로
    #   '확신 있는 근거'에서 제외하고 references(참고자료)로만 남긴다 - 표시 임계값
    #   우회로 배민 문자에 NIA 문서가 "찾았습니다"로 나가던 오매칭을 막는다.
    #   (2026-08-06 안전수정. 평가셋 30건·홀드아웃 판정 불변 확인 후 적용. 0.679·
    #   match_evidence.min_score 는 건드리지 않는다.)
    has_confident_source = official_confident or bool(matched_scam)

    if not refs:
        # ★ 확인 불가가 기본값이다. 출처를 못 찾았을 때 '가짜'라고 단정하지 않고
        #   '못 찾았다'는 사실만 남긴다 - 애매할 때 의심/확인됨으로 넘기지 않는다.
        hint = "no_source_found"
        signals.append({
            "key": "no_official_source",
            "label": "공식 자료에서 같은 내용을 찾지 못했습니다. 찾지 못했다는 것 자체가 확인 신호입니다.",
            "severity": "attention",
        })
    elif risky:
        hint = "partially_matched"
    elif not has_confident_source:
        # ★ 근거는 있다(refs 는 비어 있지 않다 - 화면에 참고자료로 계속 보여준다)
        #   그런데 그 근거가 임베딩의 약한 유사도뿐이라 확신하기엔 부족하다.
        #   확인됨으로 단정하지 않고 확인불가로 유보한다.
        hint = "no_source_found"
    else:
        hint = "needs_check"

    return SearchResult(verdict_hint=hint, signals=signals, references=refs)
