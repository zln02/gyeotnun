"""
로컬 OCR 실험 모듈 (2026-08, 8/2 멘토 지적 대응)
담당: 조희진(실험)

멘토 지적(8/2, 원문): "이미지를 보내는 순간부터 문제다. 외부·해외 서버로
보내는 것 자체가 문제가 된다. 상용화하려면 자체 OCR이 핵심이다."

★ 이 모듈은 services/ocr.py 를 대체하지 않는다. 기존 경로(Claude Vision) 는
  전혀 건드리지 않고, 이미지를 외부로 보내지 않는 대안이 실제로 쓸 만한지
  나란히 실험하기 위해서만 존재한다. 채택 여부는 사용자가 결정한다.

후보 선정 기준: 한국어 지원 · CPU 동작 · 메모리 사용량. 카카오톡 캡처는
말풍선·발신자명·시각·상태바가 섞여 있어 일반 스캔 문서보다 어렵다는 점을
감안해 아래 두 후보로 좁혔다(둘 다 완전 오프라인 - 이미지가 프로세스 밖으로
나가지 않는다).

  - tesseract : 가장 가벼움(수십MB, 시스템 tesseract-ocr + 한국어 언어팩).
    전통적 LSTM 엔진이라 레이아웃 분석이 약해, 배경색 있는 말풍선·작은
    UI 글자에서 정확도가 떨어질 수 있다.
  - easyocr   : 딥러닝 기반(CRAFT 검출 + CRNN 인식), PyTorch CPU 로 동작.
    복잡한 배경에 더 강하지만 모델 로드 메모리가 더 크다(실측치는
    docs/evaluation/local_pipeline_report.md 참고).

★ 두 후보 모두 requirements-local-experiment.txt 에만 있고 프로덕션
  requirements.txt 에는 없다. 이 모듈을 import 하면 ImportError 가 날 수
  있는데, 격리된 실험 컨테이너(Dockerfile.local-experiment) 밖에서는 애초에
  쓸 일이 없으므로 의도된 동작이다.

★ UI 잡음 제거: 두 엔진 모두 "본문만 뽑는다"는 개념이 없다 - 상태바 시각,
  배터리 표시, 발신자명 반복, 입력창 placeholder 까지 전부 텍스트로 뽑는다
  (Claude Vision 경로는 프롬프트로 이 구분을 명시적으로 시킨다 - services/
  ocr.py VISION_SYSTEM_PROMPT 참고). 완전히 공정한 비교를 위해 최소한의
  정규식 기반 후처리(_strip_ui_noise)만 적용했다 - 말풍선 검출 같은 본격적인
  레이아웃 분석은 "상용화 단계에서 자체 OCR 개발" 몫으로 남겨 둔다.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

log = logging.getLogger("gyeotnun.local_ocr")

Provider = Literal["tesseract", "easyocr"]

# ★ OCR 이 글자를 조금씩 틀리게 읽는다는 전제로 만든 패턴들이다(예: "메시지를"을
#   "메시지틀"로, "9:41"을 "9.41"로 읽는다). 정확히 일치하는 문자열만 지우면
#   실제로는 하나도 안 지워진다 - 시각 구분자는 [.:’'] 를 모두 허용하고,
#   입력창 문구는 앞부분("메시지")만으로 잡는다.
_UI_NOISE_PATTERNS = [
    re.compile(r"^\d{1,2}\s*[.:’']\s*\d{2}$"),                  # 9:41 / 9.41 (상태바 시각)
    re.compile(r"^(오전|오후)\s*\d{0,2}\s*[.:’']?\s*\d{0,2}$"),  # 오후 2:15 / "오루" 같은 파편 제외용
    re.compile(r"^(오전|오후)$"),
    re.compile(r"^LTE\s*\d{0,3}\s*%?$", re.IGNORECASE),
    re.compile(r"^\d{1,3}\s*%$"),
    re.compile(r"^메시지.{0,3}\s*입력하세요$"),                   # 메시지를/메시지틀 입력하세요
]


def _strip_ui_noise(raw_text: str, sender_name: str | None = None) -> str:
    """상태바·시각·입력창 placeholder·발신자명 반복 줄을 제거한다(정규식 기반,
    본격적인 말풍선 레이아웃 분석은 아니다 - 위 모듈 docstring 참고)."""
    out_lines = []
    for line in raw_text.splitlines():
        s = line.strip()
        if not s:
            continue
        if sender_name and s == sender_name.strip():
            continue
        if any(p.match(s) for p in _UI_NOISE_PATTERNS):
            continue
        out_lines.append(s)
    return " ".join(out_lines).strip()


@dataclass
class LocalOcrResult:
    text: str
    provider: str
    elapsed_sec: float
    status: str = "extracted"   # extracted | failed


_easyocr_reader = None


def _get_easyocr_reader():
    """★ 모델 저장 위치를 api/data/easyocr 로 고정한다 - 기본값(~/.EasyOCR)은
    일회성 컨테이너가 사라질 때 같이 날아가서, 실행할 때마다 수백 MB 를 다시
    받는다(측정 시간도 그만큼 오염된다)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        model_dir = Path(__file__).resolve().parents[1] / "data" / "easyocr"
        model_dir.mkdir(parents=True, exist_ok=True)
        log.info("[local_ocr] easyocr 모델 로드 중(최초 1회, 시간이 걸릴 수 있음)...")
        _easyocr_reader = easyocr.Reader(
            ["ko", "en"], gpu=False,
            model_storage_directory=str(model_dir),
            user_network_directory=str(model_dir),
            verbose=False,     # 다운로드 진행바가 로그를 덮는 것을 막는다
        )
    return _easyocr_reader


def extract_tesseract(image_path: str | Path, sender_name: str | None = None) -> LocalOcrResult:
    import pytesseract
    from PIL import Image, ImageOps

    t0 = time.perf_counter()
    try:
        # ★ 그레이스케일 변환은 필수다(실측): 카톡 캡처는 배경에 색이 깔려 있고
        #   말풍선만 흰색이라, 원본 컬러 그대로 넣으면 tesseract 가 본문을 통째로
        #   놓치고 상태바("LTE 100%")만 읽는 경우가 있었다. 8건 표본에서 평균
        #   정확도 0.192 -> 0.369 로 올랐다.
        #   ※ 확대(2x/3x)는 오히려 더 나빠져서 넣지 않았다 - 이미 화면 캡처라
        #     픽셀이 선명해서, 보간으로 늘리면 글자 경계가 뭉개지는 것으로 보인다.
        img = ImageOps.grayscale(Image.open(image_path))
        raw = pytesseract.image_to_string(img, lang="kor+eng")
        text = _strip_ui_noise(raw, sender_name)
        elapsed = time.perf_counter() - t0
        return LocalOcrResult(text=text, provider="tesseract", elapsed_sec=elapsed,
                               status="extracted" if text else "failed")
    except Exception as e:  # noqa: BLE001 - 실험 스크립트라 실패 원인을 그대로 남긴다
        log.warning("[local_ocr] tesseract 실패: %s", e)
        return LocalOcrResult(text="", provider="tesseract", elapsed_sec=time.perf_counter() - t0, status="failed")


def extract_easyocr(image_path: str | Path, sender_name: str | None = None) -> LocalOcrResult:
    t0 = time.perf_counter()
    try:
        reader = _get_easyocr_reader()
        # ★ paragraph=False 로 둔다: True 면 검출된 박스들을 한 문단으로 합쳐 버려서
        #   상태바 시각·입력창 문구가 본문과 같은 줄에 섞이고, 그러면 줄 단위
        #   UI 잡음 제거(_strip_ui_noise)가 아예 동작하지 못한다(실측 확인).
        lines = reader.readtext(str(image_path), detail=0, paragraph=False)
        text = _strip_ui_noise("\n".join(lines), sender_name)
        elapsed = time.perf_counter() - t0
        return LocalOcrResult(text=text, provider="easyocr", elapsed_sec=elapsed,
                               status="extracted" if text else "failed")
    except Exception as e:  # noqa: BLE001
        log.warning("[local_ocr] easyocr 실패: %s", e)
        return LocalOcrResult(text="", provider="easyocr", elapsed_sec=time.perf_counter() - t0, status="failed")


def extract(image_path: str | Path, provider: Provider = "tesseract", sender_name: str | None = None) -> LocalOcrResult:
    if provider == "tesseract":
        return extract_tesseract(image_path, sender_name)
    if provider == "easyocr":
        return extract_easyocr(image_path, sender_name)
    raise ValueError(f"알 수 없는 provider: {provider}")
