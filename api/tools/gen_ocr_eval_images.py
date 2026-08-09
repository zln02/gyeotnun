"""
30건 평가세트를 카카오톡 캡처 스타일 합성 이미지로 렌더링한다 (OCR 정확도 실측용).
실행: python3 api/tools/gen_ocr_eval_images.py

★ 왜 합성 이미지인가: api/tests/fixtures/kakao_sample.jpg 와 같은 이유다 -
  실제 카톡 캡처를 쓰면 개인정보/저작권 문제가 생긴다. 30건 평가세트
  (corpus/곁눈_평가세트_30건.csv)의 '평가용_제시문구' 텍스트를 같은 스타일
  (상태바+노란 헤더+말풍선+발신자명+시각+입력창)로 그려서, "본문만 뽑고
  UI 요소는 버리는지"를 30건 전체로 실측할 수 있게 한다.

★ 한계(보고서에 반드시 남길 것): 합성 이미지는 실제 폰 사진보다 훨씬 깨끗하다
  (기울어짐·반사·압축 손실·저조도가 없다) - 여기서 나온 정확도는 최선의 경우이고,
  실사용 정확도는 이보다 낮을 가능성이 높다.
"""
from __future__ import annotations

import csv
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "corpus" / "곁눈_평가세트_30건.csv"
OUT_DIR = ROOT / "api" / "tests" / "fixtures" / "ocr_eval"

FONT_DIR = Path("/usr/share/fonts/truetype/nanum")
FONT_REGULAR = FONT_DIR / "NanumGothic.ttf"
FONT_BOLD = FONT_DIR / "NanumGothicBold.ttf"

W = 640
SENDER_NAME = "정부지원금 안내센터"


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """글자 단위로 줄바꿈한다(한글은 띄어쓰기 기준 wrap 이 잘 안 맞는 경우가 많다)."""
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        if draw.textlength(trial, font=font) > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def render_one(text: str) -> Image.Image:
    font_body = ImageFont.truetype(str(FONT_REGULAR), 20)
    font_bold = ImageFont.truetype(str(FONT_BOLD), 24)
    font_sender = ImageFont.truetype(str(FONT_REGULAR), 16)
    font_time = ImageFont.truetype(str(FONT_REGULAR), 14)
    font_status = ImageFont.truetype(str(FONT_BOLD), 18)
    font_input = ImageFont.truetype(str(FONT_REGULAR), 16)

    tmp = Image.new("RGB", (W, 10))
    d = ImageDraw.Draw(tmp)
    bubble_max_text_width = W - 2 * 32 - 2 * 18
    lines = _wrap(d, text, font_body, bubble_max_text_width)

    status_h = 44
    header_h = 64
    sender_h = 26
    line_h = 30
    bubble_pad = 18
    bubble_h = bubble_pad * 2 + line_h * len(lines)
    top_margin = 20
    bottom_input_h = 60
    H = status_h + header_h + top_margin + sender_h + bubble_h + 40 + bottom_input_h

    im = Image.new("RGB", (W, H), "#B9C9BB")
    d = ImageDraw.Draw(im)

    # 상태바
    d.rectangle([0, 0, W, status_h], fill="#1a1a1a")
    d.text((16, status_h // 2), "9:41", font=font_status, fill="white", anchor="lm")
    d.text((W - 16, status_h // 2), "LTE 100%", font=font_status, fill="white", anchor="rm")

    # 헤더(노란 카톡 색)
    y = status_h
    d.rectangle([0, y, W, y + header_h], fill="#FFE300")
    d.text((60, y + header_h // 2), SENDER_NAME, font=font_bold, fill="#111111", anchor="lm")
    d.polygon([(24, y + header_h // 2 - 10), (24, y + header_h // 2 + 10), (36, y + header_h // 2)], fill="#111111")

    # 발신자명
    y = status_h + header_h + top_margin
    d.text((24, y), SENDER_NAME, font=font_sender, fill="#555555", anchor="lm")

    # 말풍선
    y2 = y + sender_h
    bx0, by0 = 24, y2
    bx1 = 24 + bubble_max_text_width + bubble_pad * 2
    by1 = by0 + bubble_h
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=14, fill="white")
    ty = by0 + bubble_pad
    for line in lines:
        d.text((bx0 + bubble_pad, ty), line, font=font_body, fill="#111111")
        ty += line_h

    d.text((bx1 + 10, by1 - 14), "오후 2:15", font=font_time, fill="#666666", anchor="lm")

    # 하단 입력창
    d.rectangle([0, H - bottom_input_h, W, H], fill="#EDEDED")
    d.rounded_rectangle([16, H - bottom_input_h + 12, W - 16, H - 12], radius=20, fill="white", outline="#CCCCCC")
    d.text((30, H - bottom_input_h // 2), "메시지를 입력하세요", font=font_input, fill="#999999", anchor="lm")

    return im


def main() -> None:
    if not FONT_REGULAR.exists():
        raise SystemExit(f"나눔고딕 폰트가 없습니다: {FONT_REGULAR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    assert len(rows) == 30, f"기대한 30건이 아니라 {len(rows)}건"

    for row in rows:
        case_id = row["case_id"]
        text = row["평가용_제시문구"]
        im = render_one(text)
        out_path = OUT_DIR / f"{case_id}.jpg"
        im.save(out_path, "JPEG", quality=92)

    print(f"생성 완료: {OUT_DIR} ({len(rows)}장)")


if __name__ == "__main__":
    main()
