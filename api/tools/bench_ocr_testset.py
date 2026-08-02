"""
신규 카카오톡 합성 데이터셋(ocr_testset, 24장) 평가 (2026-08)
실행(격리 컨테이너 안): python3 tools/bench_ocr_testset.py

이 세트가 채우는 조건: 다크모드(명암 반전) · 큰 글씨(font_scale 1.35) · 말풍선 잘림.
셋 다 기존 자체 제작 세트(ocr_eval / ocr_eval_hard)에는 없던 조건이다.

정답(txt)은 말풍선 본문만 담고 있어 "본문만 뽑았는가"를 그대로 측정할 수 있다.
따라서 상태바·대화방 제목·발신자명·시각·입력창 문구를 걸러내는 후처리 성능까지
정확도에 반영된다(Claude Vision 은 프롬프트로, 로컬 엔진은 정규식 후처리로 처리).

★ 다크모드 전처리 가설 검증: 현재 tesseract 경로는 그레이스케일 변환을 쓰는데,
  다크모드는 명암이 반대라 역효과일 수 있다. tesseract 를 (a) 현행 그레이스케일
  (b) 그레이스케일+명암반전 두 가지로 돌려 조건별로 비교한다.

★ services/ocr.py 등 프로덕션 코드는 호출만 하고 수정하지 않는다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import warnings
from difflib import SequenceMatcher
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, "/app")

IMG_DIR = Path("/app/tests/fixtures/ocr_testset/images")
OUT_PATH = Path("/app/data/ocr_testset_bench.json")

# 정답에서 제외된 UI 요소들을 로컬 엔진 출력에서도 걸러낸다(같은 조건으로 비교하기 위해).
_UI = [
    re.compile(r"^\d{1,2}\s*[.:’']\s*\d{2}$"),
    re.compile(r"^(오전|오후)\s*\d{0,2}\s*[.:’']?\s*\d{0,2}$"),
    re.compile(r"^(오전|오후)$"),
    re.compile(r"^LTE\s*\d{0,3}\s*%?$", re.I),
    re.compile(r"^\d{1,3}\s*%$"),
    re.compile(r"^메시지\s*입력.{0,4}$"),
    re.compile(r"^\d{4}년\s*\d{1,2}월\s*\d{1,2}일.*$"),   # 날짜 구분선
    re.compile(r"^[\s+<>‹›□\W]{0,3}$"),                    # 아이콘/기호 파편
]


def strip_ui(lines, room: str) -> str:
    out = []
    for s in lines:
        s = s.strip()
        if not s or s == room.strip():
            continue
        if any(p.match(s) for p in _UI):
            continue
        out.append(s)
    return " ".join(out)


def acc(expected: str, got: str) -> float:
    exp = " ".join(expected.split())
    return SequenceMatcher(None, exp, " ".join(got.split())).ratio()


def run_engine(items, engine: str) -> list[dict]:
    from services import local_ocr, ocr as prod_ocr
    import pytesseract
    from PIL import Image, ImageOps

    rows = []
    for it in items:
        path = IMG_DIR / it["image"]
        truth = (IMG_DIR / it["truth"]).read_text(encoding="utf-8").strip()
        room = it["room"]

        t0 = time.perf_counter()
        if engine == "vision":
            text = prod_ocr.extract_from_image(path.read_bytes()).text
        elif engine == "easyocr":
            reader = local_ocr._get_easyocr_reader()
            text = strip_ui(reader.readtext(str(path), detail=0, paragraph=False), room)
        elif engine == "tesseract_gray":
            img = ImageOps.grayscale(Image.open(path))
            text = strip_ui(pytesseract.image_to_string(img, lang="kor+eng").splitlines(), room)
        elif engine == "tesseract_invert":
            img = ImageOps.invert(ImageOps.grayscale(Image.open(path)))
            text = strip_ui(pytesseract.image_to_string(img, lang="kor+eng").splitlines(), room)
        else:
            raise ValueError(engine)
        elapsed = time.perf_counter() - t0

        rows.append({
            "image": it["image"], "engine": engine,
            "theme": it["theme"], "font_scale": it["font_scale"],
            "degraded": it["degraded"], "cropped": it["cropped"], "label": it["label"],
            "accuracy": round(acc(truth, text), 3), "sec": round(elapsed, 2),
            "extracted": text[:100],
        })
        print(f"  [{engine}] {it['image']:<28} acc={rows[-1]['accuracy']:.3f} "
              f"({it['theme']}/{it['font_scale']}/deg={it['degraded']}/crop={it['cropped']})", flush=True)
    return rows


def group_stats(rows, key) -> dict:
    buckets: dict = {}
    for r in rows:
        buckets.setdefault(str(r[key]), []).append(r["accuracy"])
    return {k: {"n": len(v), "avg": round(sum(v) / len(v), 3)} for k, v in sorted(buckets.items())}


def main() -> None:
    manifest = json.loads((IMG_DIR / "manifest.json").read_text(encoding="utf-8"))
    items = manifest["items"]
    print(f"데이터셋: {len(items)}장 / note: {manifest['note']}\n")

    report = {"note": manifest["note"], "count": len(items), "engines": {}}
    for engine in ("vision", "easyocr", "tesseract_gray", "tesseract_invert"):
        print(f"=== {engine} ===", flush=True)
        rows = run_engine(items, engine)
        report["engines"][engine] = {
            "per_image": rows,
            "overall": round(sum(r["accuracy"] for r in rows) / len(rows), 3),
            "avg_sec": round(sum(r["sec"] for r in rows) / len(rows), 2),
            "by_theme": group_stats(rows, "theme"),
            "by_font_scale": group_stats(rows, "font_scale"),
            "by_degraded": group_stats(rows, "degraded"),
            "by_cropped": group_stats(rows, "cropped"),
            "by_label": group_stats(rows, "label"),
        }
        print(f">> {engine}: 전체 {report['engines'][engine]['overall']} "
              f"/ theme {report['engines'][engine]['by_theme']}\n", flush=True)

    Path("/app/data").mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 조건별 요약 ===")
    print(f"{'엔진':<18}{'전체':>7}{'light':>8}{'dark':>8}{'1.0':>8}{'1.35':>8}{'정상':>8}{'열화':>8}{'잘림':>8}")
    for e, r in report["engines"].items():
        bt, bf, bd, bc = r["by_theme"], r["by_font_scale"], r["by_degraded"], r["by_cropped"]
        print(f"{e:<18}{r['overall']:>7.3f}{bt.get('light',{}).get('avg',0):>8.3f}"
              f"{bt.get('dark',{}).get('avg',0):>8.3f}{bf.get('1.0',{}).get('avg',0):>8.3f}"
              f"{bf.get('1.35',{}).get('avg',0):>8.3f}{bd.get('False',{}).get('avg',0):>8.3f}"
              f"{bd.get('True',{}).get('avg',0):>8.3f}{bc.get('True',{}).get('avg',0):>8.3f}")
    print(f"\n저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
