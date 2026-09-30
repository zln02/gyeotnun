#!/usr/bin/env python3
"""곁눈 포트폴리오 시연 영상 빌더.

docs/demo/ 의 실제 앱 화면 캡처를 픽셀 그대로 사용해 1920x1080 영상을 만든다.
UI 와 글자는 생성하지 않는다. 확대·패닝·전환·자막 같은 연출만 입힌다.

산출물
  gyeotnun-screen-walkthrough.mp4   영상(자막 번인 + 내레이션)
  gyeotnun-screen-walkthrough.srt   별도 자막 파일

사용법
  python3 tts_ko.py /tmp/build/audio
  python3 build_video.py --audio-dir /tmp/build/audio --out docs/portfolio
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 30
GAP = 0.35  # 장면 사이 여유(초)
XFADE = 0.40  # 교차 전환 길이(초)

FONT_B = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_R = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
KR_INDEX = 1  # Noto Sans CJK KR

# 앱 화면에서 뽑은 팔레트
NAVY = (27, 58, 107)
NAVY_DEEP = (16, 35, 66)
BLUE = (44, 95, 168)
INK = (31, 41, 51)
MUTED = (107, 118, 132)
BG_TOP = (243, 247, 252)
BG_BOT = (219, 230, 245)
WHITE = (255, 255, 255)
AMBER = (176, 122, 12)
GREEN = (30, 122, 76)

DISCLAIMER = "과거 화면 캡처 기반 재구성 · 합성 입력 · 현재 서버 미운영 · 정적 데모 별도 제공"

# 장면 정의. shot = 캡처 파일과 세로 패닝 구간(원본 픽셀 y 비율), focus = 강조 사각형(원본 픽셀)
SCENES = {
    "s0_title": {"kind": "title"},
    "s1_input": {
        "kind": "screen",
        "shot": "01_home.png",
        "pan": (0.00, 0.32),
        "step": "1단계 · 입력",
        "title": "받은 사진을 그대로 올립니다",
        "note": "사진 올리기 · 글로 붙여넣기",
    },
    "s2_signal": {
        "kind": "screen",
        "shot": "02_question.png",
        "pan": (0.00, 0.06),
        "focus": (47, 236, 738, 640),
        "step": "2단계 · 위험 신호",
        "title": "판정 대신 확인 질문",
        "note": "의심 이유를 먼저 표시",
    },
    "s3_evidence": {
        "kind": "screen",
        "shot": "02_question.png",
        "pan": (0.30, 0.46),
        "focus": (47, 1712, 738, 2185),
        "step": "3단계 · 공식 근거",
        "title": "눌러서 직접 확인",
        "note": "fsc.go.kr 공식 자료 링크",
    },
    "s4_decision": {
        "kind": "screen",
        "shot": "03_decision_result.png",
        "pan": (0.00, 0.26),
        "step": "4단계 · 사용자 판단",
        "title": "미뤄 두는 것도 선택",
        "note": "오판 유형과 함께 기록",
    },
    "s5_training": {
        "kind": "screen",
        "shot": "04_training.png",
        "pan": (0.02, 0.34),
        "step": "5단계 · 5분 연습",
        "title": "비슷한 유형으로 반복",
        "note": "고정 예시 · 개인화 루프 미완성",
    },
    "s6_end": {"kind": "outro"},
}

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    key = ("b" if bold else "r", size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(FONT_B if bold else FONT_R, size, index=KR_INDEX)
    return _font_cache[key]


def ease(t: float) -> float:
    """부드러운 가감속 (smoothstep)."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """한국어는 어절 단위로 줄바꿈한다."""
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def soft_rect(img: Image.Image, box, radius: int, rgba) -> None:
    """RGBA 이미지 위에 반투명 둥근 사각형을 '합성'한다.

    RGBA 이미지에 ImageDraw 로 반투명 색을 직접 그리면 알파가 합성되지 않고
    픽셀이 교체된다. 그래서 별도 레이어를 만들어 alpha_composite 로 올린다.
    """
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius=radius, fill=rgba)
    img.alpha_composite(layer)


def make_background() -> Image.Image:
    grad = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    top, bot = np.array(BG_TOP, np.float32), np.array(BG_BOT, np.float32)
    arr = (top[None, None, :] * (1 - grad[:, :, None]) + bot[None, None, :] * grad[:, :, None])
    img = Image.fromarray(np.repeat(arr.astype(np.uint8), W, axis=1))
    d = ImageDraw.Draw(img, "RGBA")
    # 옅은 장식 원 (앱 팔레트)
    d.ellipse((-260, -320, 520, 460), fill=(44, 95, 168, 16))
    d.ellipse((1500, 700, 2260, 1460), fill=(27, 58, 107, 14))
    return img


BASE_BG = None


def chrome(img: Image.Image, scene_no: str | None) -> None:
    """워드마크와 상시 고지 띠를 그린다. 모든 장면에 공통."""
    d = ImageDraw.Draw(img, "RGBA")
    d.text((96, 62), "곁눈", font=font(True, 40), fill=NAVY)
    d.text((176, 76), "Gyeotnun", font=font(False, 22), fill=MUTED)
    if scene_no:
        d.text((W - 96, 70), scene_no, font=font(True, 26), fill=(150, 162, 178), anchor="ra")
    # 하단 상시 고지 띠
    d.rectangle((0, H - 74, W, H), fill=NAVY_DEEP)
    d.text(
        (W // 2, H - 37),
        DISCLAIMER,
        font=font(False, 25),
        fill=(214, 226, 242),
        anchor="mm",
    )


def phone_plate(shot: Image.Image, win_h: int, pan_y: int, focus: tuple | None, scale: float) -> Image.Image:
    """폰 목업 안에 캡처를 넣은 RGBA 이미지를 만든다. 캡처 픽셀은 변형하지 않는다."""
    sw = 430
    s = sw / shot.width
    scaled_h = int(shot.height * s)
    view = Image.new("RGB", (sw, win_h), WHITE)
    view.paste(shot.resize((sw, scaled_h), Image.LANCZOS), (0, -pan_y))

    if focus:
        d = ImageDraw.Draw(view, "RGBA")
        x0, y0, x1, y1 = [int(v * s) for v in focus]
        y0 -= pan_y
        y1 -= pan_y
        d.rectangle((x0 - 6, y0 - 6, x1 + 6, y1 + 6), outline=(230, 92, 60), width=5)

    # 베젤 + 라운드 + 그림자
    pad, radius = 16, 44
    pw, ph = sw + pad * 2, win_h + pad * 2
    phone = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    pd = ImageDraw.Draw(phone)
    pd.rounded_rectangle((0, 0, pw - 1, ph - 1), radius=radius, fill=(24, 30, 40, 255))
    mask = Image.new("L", (sw, win_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, win_h - 1), radius=radius - 14, fill=255)
    phone.paste(view, (pad, pad), mask)
    pd.rounded_rectangle((pw // 2 - 52, 7, pw // 2 + 52, 17), radius=5, fill=(48, 56, 68, 255))

    shadow = Image.new("RGBA", (pw + 90, ph + 90), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (45, 56, pw + 44, ph + 50), radius=radius + 8, fill=(20, 38, 70, 92)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(24))
    shadow.alpha_composite(phone, (45, 45))

    if scale != 1.0:
        nw, nh = int(shadow.width * scale), int(shadow.height * scale)
        shadow = shadow.resize((nw, nh), Image.LANCZOS)
    return shadow


def draw_screen(img, sc, caption, narration, progress, scene_no, shot_img):
    d = ImageDraw.Draw(img, "RGBA")
    win_h = 800
    s = 430 / shot_img.width
    scaled_h = int(shot_img.height * s)
    a, b = sc["pan"]
    max_pan = max(0, scaled_h - win_h)
    pan = int((a + (b - a) * ease(progress)) * scaled_h)
    pan = max(0, min(max_pan, pan))
    scale = 1.0 + 0.015 * ease(progress)

    plate = phone_plate(shot_img, win_h, pan, sc.get("focus"), scale)
    img.alpha_composite(plate, (1360 - plate.width // 2, 486 - plate.height // 2))

    x, y = 118, 268
    chip = sc["step"]
    cw = int(d.textlength(chip, font=font(True, 28))) + 48
    soft_rect(img, (x, y, x + cw, y + 54), 27, (44, 95, 168, 38))
    d.text((x + 24, y + 28), chip, font=font(True, 28), fill=BLUE, anchor="lm")

    title = sc["title"]
    ty = y + 92
    for line in wrap(d, title, font(True, 52), 940):
        d.text((x, ty), line, font=font(True, 52), fill=INK)
        ty += 70

    ty += 18
    for line in wrap(d, narration, font(False, 33), 940):
        d.text((x, ty), line, font=font(False, 33), fill=(72, 84, 98))
        ty += 50

    if sc.get("note"):
        ty += 16
        d.rectangle((x, ty + 6, x + 5, ty + 34), fill=BLUE)
        d.text((x + 20, ty + 4), sc["note"], font=font(False, 27), fill=MUTED)

    chrome(img, scene_no)


def draw_title(img, narration, progress):
    d = ImageDraw.Draw(img, "RGBA")
    slide = int(22 * (1 - ease(min(1.0, progress * 3))))
    cx = W // 2
    d.text((cx, 330 + slide), "곁눈", font=font(True, 132), fill=NAVY, anchor="mm")
    d.text((cx, 432 + slide), "Gyeotnun", font=font(False, 40), fill=(120, 138, 162), anchor="mm")
    d.text(
        (cx, 528 + slide),
        "받은 문자·이미지를 스스로 확인하도록 돕는 시니어 정보판단 코치",
        font=font(False, 36),
        fill=INK,
        anchor="mm",
    )
    badge = "제8회 K-디지털 트레이닝 해커톤 장려상 · Second Look 6인 팀 · 2026.07–08"
    bw = int(d.textlength(badge, font=font(False, 27))) + 64
    soft_rect(img, (cx - bw // 2, 596 + slide, cx + bw // 2, 654 + slide), 29, (27, 58, 107, 30))
    d.text((cx, 625 + slide), badge, font=font(False, 27), fill=NAVY, anchor="mm")

    ty = 754
    for line in wrap(d, narration, font(False, 32), 1280):
        d.text((cx, ty), line, font=font(False, 32), fill=(90, 102, 118), anchor="mm")
        ty += 48
    chrome(img, None)


def draw_outro(img, narration, progress):
    d = ImageDraw.Draw(img, "RGBA")
    cx = W // 2
    d.text((cx, 214), "이 영상에 대하여", font=font(True, 58), fill=NAVY, anchor="mm")
    rows = [
        ("영상 구성", "저장소의 과거 앱 화면 캡처(docs/demo/)를 확대·패닝으로 재구성. UI·글자 생성 없음"),
        ("입력 사례", "합성 사례. 실제 이용자의 문자나 개인정보가 아님"),
        ("음성", "espeak-ng TTS 합성. 사람이 녹음한 음성이 아님"),
        ("서버 상태", "현재 서버 미운영. 정적 브라우저 데모는 zln02.github.io/gyeotnun 에서 별도 제공"),
        ("미검증", "60대 대면 효과 테스트 미실시. 판단력 향상은 입증하지 않음"),
    ]
    y = 320
    for i, (k, v) in enumerate(rows):
        a = ease(min(1.0, max(0.0, progress * 3.0 - i * 0.14)))
        if a <= 0.01:
            y += 98
            continue
        soft_rect(img, (300, y, 1620, y + 84), 14, (255, 255, 255, int(215 * a)))
        d.text((338, y + 42), k, font=font(True, 28), fill=NAVY, anchor="lm")
        d.text((548, y + 42), v, font=font(False, 26), fill=(72, 84, 98), anchor="lm")
        y += 98
    chrome(img, None)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-dir", required=True)
    ap.add_argument("--demo-dir", default="docs/demo")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="gyeotnun-screen-walkthrough")
    args = ap.parse_args()

    audio_dir, out_dir = Path(args.audio_dir), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((audio_dir / "narration.json").read_text(encoding="utf-8"))

    shots = {
        name: Image.open(Path(args.demo_dir) / name).convert("RGB")
        for name in {s["shot"] for s in SCENES.values() if s.get("shot")}
    }

    global BASE_BG
    BASE_BG = make_background().convert("RGBA")

    timeline, t = [], 0.0
    for idx, sc in enumerate(manifest["scenes"]):
        dur = sc["tts_duration"] + GAP
        timeline.append({**sc, "start": t, "dur": dur, "index": idx})
        t += dur
    total = t

    # 자막 파일. subtitle 이 있으면 그쪽을 쓴다(TTS 발음용 표기와 화면 표기가 다른 경우).
    srt = []
    for i, sc in enumerate(timeline, 1):
        srt.append(
            f"{i}\n{srt_time(sc['start'])} --> {srt_time(sc['start'] + sc['tts_duration'])}\n"
            f"{sc.get('subtitle') or sc['text']}\n"
        )
    (out_dir / f"{args.name}.srt").write_text("\n".join(srt), encoding="utf-8")

    # 오디오 트랙 합성
    concat = audio_dir / "_concat.txt"
    sil = audio_dir / "_gap.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
         f"anullsrc=r={manifest['sample_rate']}:cl=mono", "-t", str(GAP), str(sil)],
        check=True,
    )
    concat.write_text(
        "".join(f"file '{audio_dir / sc['wav']}'\nfile '{sil}'\n" for sc in timeline),
        encoding="utf-8",
    )
    raw_voice = audio_dir / "_voice_raw.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-c", "copy", str(raw_voice)],
        check=True,
    )
    # espeak 출력은 0dBFS 를 그대로 찍어 클리핑 위험이 있다. 방송 기준으로 정규화한다.
    voice = audio_dir / "_voice.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw_voice),
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
         "-ar", str(manifest["sample_rate"]), str(voice)],
        check=True,
    )

    mp4 = out_dir / f"{args.name}.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(voice),
         "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", "-shortest", str(mp4)],
        stdin=subprocess.PIPE,
    )

    n_frames = int(total * FPS)
    prev_key = None
    for fi in range(n_frames):
        now = fi / FPS
        cur = timeline[-1]
        for sc in timeline:
            if sc["start"] <= now < sc["start"] + sc["dur"]:
                cur = sc
                break
        local = (now - cur["start"]) / cur["dur"]
        frame = render(cur, local, shots)

        # 장면 진입 0.4초 크로스페이드
        into = now - cur["start"]
        if into < XFADE and prev_key is not None and prev_key != cur["id"]:
            pass
        if into < XFADE and cur["index"] > 0:
            prev = timeline[cur["index"] - 1]
            prev_frame = render(prev, 1.0, shots)
            frame = Image.blend(prev_frame, frame, ease(into / XFADE))
        prev_key = cur["id"]

        proc.stdin.write(frame.convert("RGB").tobytes())
        if fi % 150 == 0:
            print(f"  frame {fi}/{n_frames}", file=sys.stderr)

    proc.stdin.close()
    proc.wait()
    print(f"완료: {mp4}  ({total:.2f}s, {n_frames} frames)")
    return 0


def render(sc, local, shots) -> Image.Image:
    img = BASE_BG.copy()
    meta = SCENES[sc["id"]]
    if meta["kind"] == "title":
        draw_title(img, sc["text"], local)
    elif meta["kind"] == "outro":
        draw_outro(img, sc["text"], local)
    else:
        no = f"{sc['index']} / {len(SCENES) - 2}"
        body = sc.get("subtitle") or sc["text"]
        draw_screen(img, meta, sc["caption"], body, local, no, shots[meta["shot"]])
    return img


if __name__ == "__main__":
    raise SystemExit(main())
