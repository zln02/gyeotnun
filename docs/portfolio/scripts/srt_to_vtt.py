#!/usr/bin/env python3
"""SRT 자막을 WebVTT 로 변환한다.

<video> 의 <track> 은 SRT 를 읽지 못하고 WebVTT 만 받는다.
GitHub Pages 배포 시 워크플로가 이 스크립트를 돌려 .vtt 를 만든다.

사용법:
    python3 srt_to_vtt.py <입력.srt> <출력.vtt>
"""
from __future__ import annotations

import sys
from pathlib import Path


def convert(srt_text: str) -> str:
    # WebVTT 는 타임코드 구분자가 쉼표가 아니라 마침표다.
    body = srt_text.replace("\r\n", "\n").strip()
    lines_out = ["WEBVTT", ""]
    for line in body.split("\n"):
        if "-->" in line:
            line = line.replace(",", ".")
        lines_out.append(line)
    return "\n".join(lines_out) + "\n"


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(convert(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"{src} -> {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
