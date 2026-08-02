"""
평가용 이미지에 '실촬영 열화'를 입힌 어려운 표본 생성 (2026-08)
실행: python3 api/tools/gen_ocr_eval_images_hard.py

★★ 이것은 '실제 스마트폰으로 찍은 사진'이 아니다 ★★
  CLI 환경에서는 실물 촬영이 불가능하다. 대신 gen_ocr_eval_images.py 가 만든
  깨끗한 카톡 화면 렌더링에, 실제로 폰으로 화면을 찍을 때 생기는 열화를
  프로그램으로 입혔다. 실촬영을 대체하지는 못하지만, "합성 8건은 너무 쉽다"는
  지적에 대해 난이도를 올린 표본으로는 쓸 수 있다.
  → 보고서에는 반드시 '시뮬레이션'으로 표기할 것.

입히는 열화(실제 촬영에서 흔한 순서대로 적용)
  1) 원근/회전 기울어짐  : 손으로 들고 찍어 생기는 각도
  2) 조명 그라데이션     : 화면 한쪽이 밝고 반대쪽이 어두워짐
  3) 밝기 저하(어두운 조명)
  4) 가우시안 블러       : 초점이 살짝 나감
  5) 센서 노이즈
  6) 저해상도            : 축소 후 재확대(디테일 손실)
  7) JPEG 재압축 손실

케이스별로 강도를 3단계(약/중/강)로 순환시켜, 30건 중 20건 이상이 열화를 갖게 한다.
"""
from __future__ import annotations

import csv
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "corpus" / "곁눈_평가세트_30건.csv"
SRC_DIR = ROOT / "api" / "tests" / "fixtures" / "ocr_eval"
OUT_DIR = ROOT / "api" / "tests" / "fixtures" / "ocr_eval_hard"

# (회전각, 원근강도, 밝기, 블러반경, 노이즈, 축소비율, jpeg품질)
LEVELS = {
    "light":  (1.5, 0.010, 0.85, 0.4, 4,  0.85, 80),
    "medium": (3.5, 0.022, 0.62, 0.8, 9,  0.65, 62),
    "heavy":  (6.0, 0.035, 0.45, 1.2, 15, 0.50, 45),
}


def _perspective(img: Image.Image, strength: float) -> Image.Image:
    w, h = img.size
    dx, dy = w * strength, h * strength
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [(dx, dy * 0.5), (w - dx * 0.6, 0), (w - dx * 0.3, h - dy), (dx * 0.4, h)]
    # dst -> src 계수를 푼다(PIL 은 역방향 매핑을 요구한다)
    a = []
    b = []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    coeffs = np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float))
    return img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(30, 30, 30))


def _light_gradient(img: Image.Image) -> Image.Image:
    w, h = img.size
    grad = np.linspace(0.65, 1.15, w, dtype=np.float32)[None, :, None]
    arr = np.asarray(img, dtype=np.float32) * grad
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def degrade(img: Image.Image, level: str, seed: int) -> Image.Image:
    rng = random.Random(seed)
    rot, persp, bright, blur, noise, scale, quality = LEVELS[level]

    out = img.convert("RGB")
    out = out.rotate(rng.uniform(-rot, rot), resample=Image.BICUBIC, expand=False, fillcolor=(30, 30, 30))
    out = _perspective(out, persp)
    out = _light_gradient(out)
    out = ImageEnhance.Brightness(out).enhance(bright)
    out = out.filter(ImageFilter.GaussianBlur(blur))

    arr = np.asarray(out, dtype=np.float32)
    arr += np.random.default_rng(seed).normal(0, noise, arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    w, h = out.size
    small = out.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)
    out = small.resize((w, h), Image.BILINEAR)
    return out, quality


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    order = ["light", "medium", "heavy"]
    counts = {k: 0 for k in order}
    for i, row in enumerate(rows):
        case_id = row["case_id"]
        src = SRC_DIR / f"{case_id}.jpg"
        if not src.exists():
            raise SystemExit(f"원본이 없습니다: {src} (gen_ocr_eval_images.py 를 먼저 실행)")
        level = order[i % 3]
        counts[level] += 1
        out, quality = degrade(Image.open(src), level, seed=i)
        out.save(OUT_DIR / f"{case_id}.jpg", "JPEG", quality=quality)

    print(f"생성 완료: {OUT_DIR} ({len(rows)}장)")
    print("강도 분포:", counts)


if __name__ == "__main__":
    main()
