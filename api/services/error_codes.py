"""
오류 코드 단일 소스(Single Source of Truth)
담당: 박진영 / 8/2 보안 멘토링 지시사항 대응 (심사 배점: 시스템 오류 대비·복구)

★ 이 파일이 유일한 정의처다. 프론트는 다른 언어라 이 파일을 직접 import 할 수
  없으므로, GET /api/v1/errors/codes 로 이 표 전체를 그대로 받아서 쓴다
  (web/src/errorCodes.js 참고). 새 코드는 반드시 여기에만 추가한다 - 프론트에
  같은 문구를 따로 하드코딩하면 그 순간부터 "단일 소스"가 깨진다.

영역별 접두어
  IN 입력 · RC 인식 · MK 마스킹 · SR 검색 · GN 생성 · ST 저장 · EX 외부연동 · SYS 미분류

각 코드의 5개 필드
  code               문의 시 사용자가 읽어 줄 수 있는 식별자. API 응답과 화면에 그대로 노출.
  situation          내부용 - 언제 이 코드가 붙는지
  user_message       시니어가 이해할 수 있는 안내 문구(기술 용어 금지). 사용자에게 아예
                      노출되지 않는 코드(자동 폴백이라 화면이 그대로인 경우)는 빈 문자열.
  recovery           사용자가 지금 할 수 있는 다음 행동
  internal_handling  내부적으로 어떻게 처리되는지(로그/폴백 등) - 기획서·팀 문서용, 화면에는 안 보임

★ 주의: 이 표는 "기존 처리 지점에 코드를 부여"한 결과다. 코드를 붙였다고 해서
  실제 동작(무엇을 반환하고 어떤 폴백을 타는지)이 바뀐 것은 아니다.
"""
from __future__ import annotations

from typing import List, TypedDict


class ErrorCodeDef(TypedDict):
    code: str
    area: str
    situation: str
    user_message: str
    recovery: str
    internal_handling: str


ERROR_CODES: List[ErrorCodeDef] = [
    # ══════════════════════════════════════════════════════════ 입력 (IN)
    {
        "code": "IN-001",
        "area": "입력",
        "situation": "업로드한 사진 용량이 설정된 상한(기본 10MB)을 초과함",
        "user_message": "사진 용량이 너무 큽니다. 더 작은 사진으로 다시 올리시거나, 글로 붙여넣어 확인해 주세요.",
        "recovery": "10MB 이하 사진으로 다시 올리거나 '글로 붙여넣기'로 직접 입력합니다.",
        "internal_handling": "예외를 던지지 않고 200 + status=failed 로 응답한다(routers/checks.py). "
                              "원본 바이트는 검사 직후 즉시 파기된다.",
    },
    {
        "code": "IN-002",
        "area": "입력",
        "situation": "링크(URL) 입력 - 아직 구현되지 않은 입력 방식을 시도함",
        "user_message": "링크로 확인하는 기능은 아직 준비 중입니다. 사진이나 글로 입력해 주세요.",
        "recovery": "'사진 올리기' 또는 '글로 붙여넣기'로 같은 내용을 다시 입력합니다.",
        "internal_handling": "services/ocr.py extract_from_link() 가 NotImplementedError 를 던지고, "
                              "routers/checks.py 가 501 로 변환한다.",
    },
    {
        "code": "IN-003",
        "area": "입력",
        "situation": "카카오톡 등에서 '공유 → 곁눈'으로 들어왔는데 사진이 실제로 전달되지 않음",
        "user_message": "공유하신 사진을 받지 못했습니다. 아래 '사진 올리기'로 같은 사진을 다시 선택해 주세요.",
        "recovery": "홈 화면에서 '사진 올리기'를 눌러 사진첩에서 같은 사진을 직접 선택합니다.",
        "internal_handling": "프론트 전용 실패(서비스워커 공유 캐시 미스/읽기 오류, web/src/pages/Home.jsx). "
                              "서버에는 POST /events(event_type=error, target=IN-003)로만 통지된다.",
    },
    # ══════════════════════════════════════════════════════════ 인식 (RC)
    {
        "code": "RC-001",
        "area": "인식",
        "situation": "사진에서 글자를 읽지 못함(흐림·비메신저 캡처·모델의 읽기 거절·응답 파싱 실패 등)",
        "user_message": "사진에서 글자를 읽지 못했습니다. 밝은 곳에서 화면 전체가 나오게 다시 찍어 주시거나, "
                        "'글로 붙여넣기'로 내용을 직접 입력해 주세요.",
        "recovery": "다시 촬영하거나 '글로 붙여넣기'로 직접 입력합니다.",
        "internal_handling": "예외가 아니라 정상 반환값이다 - services/ocr.py extract_from_image() 가 "
                              "ExtractResult(status='failed') 를 돌려준다.",
    },
    # ══════════════════════════════════════════════════════════ 마스킹 (MK)
    {
        "code": "MK-001",
        "area": "마스킹",
        "situation": "개인정보 비식별 처리(전화·계좌·주민번호 등 가리기) 중 예상치 못한 오류",
        "user_message": "처리 중 문제가 생겼습니다. 처음 화면으로 돌아가 다시 시도해 주세요.",
        "recovery": "처음 화면으로 돌아가 다시 시도합니다. 반복되면 오류 코드를 알려 주세요.",
        "internal_handling": "masking.mask_text() 호출을 감싼 try/except 가 501 로 변환한다(routers/checks.py). "
                              "이 지점은 오류 코드 체계 도입 전에는 보호되지 않던 지점이라 이번에 새로 감쌌다.",
    },
    # ══════════════════════════════════════════════════════════ 검색 (SR)
    {
        "code": "SR-001",
        "area": "검색",
        "situation": "근거 검색(공식 문서 대조) 처리 중 예상치 못한 오류",
        "user_message": "자료를 찾는 중 문제가 생겼습니다. 처음 화면으로 돌아가 다시 시도해 주세요.",
        "recovery": "처음 화면으로 돌아가 다시 시도합니다.",
        "internal_handling": "services/search.py collect_evidence() 자체 예외를 501 로 변환한다"
                              "(routers/checks.py, routers/dialogue.py). 임베딩·BM25 는 각자 자체 폴백을 "
                              "이미 갖고 있으므로(EX-003) 이 코드까지 올라오는 경우는 그 이상의 예상 밖 버그다.",
    },
    # ══════════════════════════════════════════════════════════ 생성 (GN)
    {
        "code": "GN-001",
        "area": "생성",
        "situation": "확인 질문 재생성을 반복 시도했지만 전부 원칙(가드레일) 검증에 실패해 "
                     "안내형 기본 질문으로 자동 대체됨",
        "user_message": "",
        "recovery": "사용자 조치 불필요 - 평소와 같은 질문 화면이 그대로 보인다(자동 대체). 반복되면 팀이 대응한다.",
        "internal_handling": "services/prompt_chain.py _fallback_question() 사용 시 발생(기존 폴백, 동작 변경 "
                              "없음). log_incident() 로 서버가 빈도를 인지한다.",
    },
    {
        "code": "GN-002",
        "area": "생성",
        "situation": "오판유형 분류(AI)가 실패해 규칙 기반 분류로 자동 대체됨",
        "user_message": "",
        "recovery": "사용자 조치 불필요 - 판단 기록 화면은 평소와 동일하게 보인다(자동 대체).",
        "internal_handling": "services/tagger.py tag_error_type_llm() 실패 시 tag_error_type() 규칙 기반으로 "
                              "대체(기존 폴백, 동작 변경 없음). log_incident() 로 서버가 빈도를 인지한다.",
    },
    # ══════════════════════════════════════════════════════════ 저장 (ST)
    {
        "code": "ST-001",
        "area": "저장",
        "situation": "요청한 확인 건을 임시 저장소에서 찾을 수 없음(서버 재시작·만료 등)",
        "user_message": "확인 중이던 내용을 찾지 못했습니다. 처음 화면으로 돌아가 다시 시작해 주세요.",
        "recovery": "홈 화면으로 돌아가 사진이나 글을 다시 올립니다.",
        "internal_handling": "_MEMORY_STORE.get() 실패를 501 로 변환한다(routers/checks.py, dialogue.py, "
                              "verdict.py 공통).",
    },
    {
        "code": "ST-002",
        "area": "저장",
        "situation": "오늘의 훈련카드 데이터 파일을 읽지 못함(파일 없음/손상)",
        "user_message": "오늘의 연습을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        "recovery": "홈 화면으로 돌아가 잠시 후 다시 시도합니다.",
        "internal_handling": "services/rag.py load_sample_cards() 의 JSON/파일 오류를 501 로 변환한다"
                              "(routers/training.py). log_incident() 로 서버가 인지한다.",
    },
    {
        "code": "ST-003",
        "area": "저장",
        "situation": "사용자 행동 계측(이벤트) 1건을 DB에 저장하는 데 실패함",
        "user_message": "",
        "recovery": "사용자 조치 불필요(fire-and-forget) - 서버 로그로 팀이 인지 후 조치한다.",
        "internal_handling": "routers/events.py DB insert 실패 시 그대로 200(accepted=0) 을 돌려주고"
                              "(기존 폴백, 동작 변경 없음), log_incident() 로 서버가 스스로 인지한다 - "
                              "멘토 조언('저장 실패는 사용자에게 요구하지 말고 서버가 인지')의 직접 적용 사례.",
    },
    # ══════════════════════════════════════════════════════════ 외부연동 (EX)
    {
        "code": "EX-001",
        "area": "외부연동",
        "situation": "사진 인식(AI Vision) 서비스에 연결할 수 없음(키 없음 또는 호출 자체가 실패)",
        "user_message": "사진을 읽는 기능을 잠시 사용할 수 없습니다. '글로 붙여넣기'로 확인해 주세요.",
        "recovery": "'글로 붙여넣기'로 내용을 직접 입력합니다.",
        "internal_handling": "services/ocr.py extract_from_image() 의 MissingKeyError 또는 API 예외를 501 로 "
                              "변환한다(routers/checks.py).",
    },
    {
        "code": "EX-002",
        "area": "외부연동",
        "situation": "확인 질문 생성(AI) 서비스에 연결할 수 없음(키 없음)",
        "user_message": "지금은 확인 질문을 만들 수 없습니다. 잠시 후 다시 시도해 주세요.",
        "recovery": "잠시 후 다시 시도합니다.",
        "internal_handling": "services/prompt_chain.py generate_question() 의 MissingKeyError 를 501 로 "
                              "변환한다(routers/dialogue.py). 키가 있는데 호출 자체가 실패하는 경우는 "
                              "내부에서 재시도 후 GN-001 로 자동 대체되므로 여기까지 오지 않는다.",
    },
    {
        "code": "EX-003",
        "area": "외부연동",
        "situation": "근거 검색(임베딩) API 호출이 실패하거나 시간 안에 응답하지 않아 "
                     "로컬 BM25 검색으로 자동 전환됨",
        "user_message": "",
        "recovery": "사용자 조치 불필요(자동 전환, 평소와 같은 결과 화면). 반복되면 팀이 외부 서비스 상태를 점검한다.",
        "internal_handling": "services/search.py match_official_docs_safe() 가 EmbeddingUnavailableError 를 "
                              "잡아 BM25 로 폴백한다(기존 폴백, 동작 변경 없음). log_incident() 로 폴백 빈도를 "
                              "서버가 인지한다 - '외부 API 의존이 발표 당일 최대 리스크'라는 판단에 따른 조치.",
    },
    {
        "code": "EX-004",
        "area": "외부연동",
        "situation": "인터넷 연결이 없거나 서버에 요청 자체가 닿지 못함(HTTP 응답을 아예 받지 못함)",
        "user_message": "인터넷 연결을 확인해 주세요. 연결 후 다시 시도하시면 됩니다.",
        "recovery": "인터넷(와이파이/데이터) 연결을 확인한 뒤 다시 시도합니다.",
        "internal_handling": "프론트에서 fetch() 자체가 실패(TypeError, 오프라인 등)할 때 이 코드로 변환한다"
                              "(web/src/api.js) - 서버는 이 실패를 볼 수 없으므로(요청이 도달하지 않음) "
                              "전적으로 클라이언트 쪽에서만 판단·표시한다.",
    },
    # ══════════════════════════════════════════════════════════ 공통(미분류)
    {
        "code": "SYS-000",
        "area": "공통",
        "situation": "위 목록에 없는, 분류되지 않은 예상치 못한 오류(안전망 기본값)",
        "user_message": "잠시 문제가 생겼습니다. 처음 화면으로 돌아가 다시 시도해 주세요.",
        "recovery": "처음 화면으로 돌아가 다시 시도합니다. 반복되면 이 오류 코드를 알려 주세요.",
        "internal_handling": "코드가 명시되지 않은 not_implemented() 호출, 또는 프론트가 알 수 없는 코드를 "
                              "받았을 때의 기본값.",
    },
]

_BY_CODE = {c["code"]: c for c in ERROR_CODES}


def get_error_code(code: str) -> ErrorCodeDef:
    """정의되지 않은 코드가 들어와도 항상 뭔가(SYS-000)를 돌려준다 - 이 조회 자체가
    또 다른 예외를 만들면 안 되기 때문이다."""
    return _BY_CODE.get(code, _BY_CODE["SYS-000"])
