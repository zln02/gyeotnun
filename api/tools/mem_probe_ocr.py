"""
OCR 후보별 메모리 실측 (2026-08, 채택 가부를 가르는 값)
실행(격리 컨테이너 안):
    python3 tools/mem_probe_ocr.py tesseract
    python3 tools/mem_probe_ocr.py easyocr
    python3 tools/mem_probe_ocr.py rapidocr

★ 후보마다 반드시 별도 프로세스로 돌린다. 한 프로세스에서 여러 모델을 연달아
  올리면 앞 모델이 남긴 메모리 때문에 뒤 모델 수치가 오염된다.

측정값
  baseline_rss_mb : 모델 로드 전 상주 메모리
  loaded_rss_mb   : 모델 로드 직후 상주 메모리   ← "상주 메모리" (서비스가 계속 물고 있는 양)
  peak_rss_mb     : 프로세스 전체 최대 상주(VmHWM) ← "추론 중 최대"
  model_delta_mb  : loaded - baseline (모델 자체가 차지하는 양)
  infer_delta_mb  : peak - loaded    (추론이 추가로 쓰는 양)

VmRSS/VmHWM 는 /proc/self/status 에서 읽는다(ru_maxrss 는 피크만 나와서 '상주'를
구분할 수 없다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

import _guard  # noqa: F401  ★ services/models 보다 먼저 (운영 DB 보호)
IMG_DIR = Path("/app/tests/fixtures/ocr_eval")
SENDER = "정부지원금 안내센터"


def _proc_kb(field: str) -> float:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(field + ":"):
            return float(line.split()[1])
    return 0.0


def rss_mb() -> float:
    return _proc_kb("VmRSS") / 1024


def peak_mb() -> float:
    return _proc_kb("VmHWM") / 1024


def main(provider: str) -> None:
    imgs = sorted(IMG_DIR.glob("*.jpg"))[:5]
    baseline = rss_mb()

    if provider == "rapidocr":
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        loaded = rss_mb()
        for p in imgs:
            engine(str(p))
    else:
        from services import local_ocr
        if provider == "easyocr":
            local_ocr._get_easyocr_reader()          # 모델 로드만 먼저
        loaded = rss_mb()
        for p in imgs:
            local_ocr.extract(p, provider=provider, sender_name=SENDER)

    peak = peak_mb()
    print(json.dumps({
        "provider": provider,
        "baseline_rss_mb": round(baseline, 1),
        "loaded_rss_mb": round(loaded, 1),
        "peak_rss_mb": round(peak, 1),
        "model_delta_mb": round(loaded - baseline, 1),
        "infer_delta_mb": round(peak - loaded, 1),
        "images_processed": len(imgs),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tesseract")
