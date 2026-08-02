"""
docs/error_codes.md 생성 - services/error_codes.py(단일 소스)를 표로 옮긴다.
실행: cd api && python tools/gen_error_codes_doc.py

★ 이 문서를 손으로 고치지 마라. 코드/문구를 바꾸려면 services/error_codes.py 를
  고친 뒤 이 스크립트를 다시 돌려라 - 그래야 "단일 소스" 원칙이 실제로 지켜진다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.error_codes import ERROR_CODES  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[2] / "docs" / "error_codes.md"


def _cell(text: str) -> str:
    """빈 문자열은 표에서 '(자동 대체, 화면에 노출 안 됨)'으로 명시한다 - 빈 칸으로
    두면 '표를 만들다 빠뜨린 건가' 오해를 살 수 있다."""
    text = (text or "").strip()
    if not text:
        return "(자동 대체 - 화면에 노출되지 않음)"
    return text.replace("\n", " ").replace("|", "\\|")


def main() -> None:
    lines = [
        "# 곁눈(Gyeotnun) 오류 코드 표",
        "",
        "8/2 보안 멘토링 지시사항 대응 - 기획서 3.6 을 이 표로 교체한다.",
        "",
        "단일 소스: `api/services/error_codes.py`. 이 문서는 그 파일에서 자동",
        "생성된다(`api/tools/gen_error_codes_doc.py`) - 손으로 고치지 말 것.",
        "",
        "영역별 접두어: 입력(IN) · 인식(RC) · 마스킹(MK) · 검색(SR) · 생성(GN) · "
        "저장(ST) · 외부연동(EX) · 공통(SYS)",
        "",
        "| 코드 | 상황 | 사용자 안내 | 복구 방법 |",
        "|---|---|---|---|",
    ]
    for c in ERROR_CODES:
        lines.append(
            f"| {c['code']} | {_cell(c['situation'])} | {_cell(c['user_message'])} | {_cell(c['recovery'])} |"
        )

    lines += [
        "",
        "## 코드 체계 설계 원칙",
        "",
        "- **화면·API 응답 모두에 코드가 보인다.** 문의 시 사용자가 이 코드를 읽어",
        "  주면 팀이 바로 어느 지점인지 식별할 수 있다.",
        "- **사용자 안내가 빈 칸인 코드**(GN-001/GN-002/EX-003/ST-003)는 기존에",
        "  이미 있던 자동 폴백이 그대로 동작해 화면이 바뀌지 않는 경우다 - 사용자에게",
        "  보여줄 필요가 없지만, 서버는 `services/incident_log.py` 로 발생 사실을",
        "  스스로 기록해 둔다(멘토 조언: 저장 실패 시 사용자에게 조치를 요구하지",
        "  말고 서버가 인지하게 하라).",
        "- **코드를 부여하는 작업이지, 폴백 동작을 바꾸는 작업이 아니다.** 이번",
        "  도입으로 어떤 응답값·상태 코드·폴백 경로도 바뀌지 않았다(마스킹 처리",
        "  MK-001 지점만 예외 - 기존에 보호되지 않던 곳이라 이번에 새로 감쌌다).",
        "",
        "## 장애 로그 수집 & 조회",
        "",
        "- 서버가 스스로 인지한 장애: `error_logs` 테이블(코드/화면/기기해시/짧은",
        "  진단정보/시각만 - 개인정보 없음).",
        "- 프론트가 신고한 오류: 기존 `events` 테이블(`event_type=error`)을 그대로",
        "  쓰되, `target` 에 이제 실제 오류 코드가 실린다.",
        "- 집계 조회: `GET /api/v1/errors/summary` - 두 표를 코드 기준으로 합쳐",
        "  최근 발생 건수·최근 발생 시각을 보여준다.",
        "- 코드 정의 조회(프론트가 실제로 쓰는 API): `GET /api/v1/errors/codes`.",
        "",
    ]

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"생성 완료: {OUT_PATH} ({len(ERROR_CODES)}개 코드)")


if __name__ == "__main__":
    main()
