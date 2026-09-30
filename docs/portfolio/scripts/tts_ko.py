#!/usr/bin/env python3
"""곁눈 포트폴리오 영상용 한국어 내레이션 합성기.

espeak-ng 공유 라이브러리(espeakng-loader 패키지에 동봉)를 ctypes 로 직접 호출해
장면별 WAV 파일을 만든다. 네트워크와 유료 API 없이 재현 가능한 것이 목적이다.

주의: espeak-ng 는 포먼트 합성기라 사람 목소리가 아니다. 결과물에는 반드시
"TTS 합성 음성"이라고 표기한다. 더 자연스러운 음성으로 바꾸려면
docs/portfolio/영상제작_템플릿.md 의 "음성 트랙 교체" 절차를 따른다.

사용법:
    pip install espeakng-loader --break-system-packages
    python3 tts_ko.py <출력디렉터리>
"""
from __future__ import annotations

import ctypes
import json
import struct
import sys
import wave
from pathlib import Path

import espeakng_loader

# espeak-ng 상수
AUDIO_OUTPUT_RETRIEVAL = 1
ESPEAK_CHARS_UTF8 = 1
ESPEAK_RATE = 1
ESPEAK_VOLUME = 2
ESPEAK_PITCH = 3

# 장면별 내레이션. scene_id 는 자막·장면표·영상 빌드에서 공통으로 쓰인다.
NARRATION: list[dict[str, str]] = [
    {
        "id": "s0_title",
        "text": "곁눈. 받은 문자와 이미지를 스스로 확인하도록 돕는 시니어 정보판단 코치입니다.",
        "caption": "곁눈 — 스스로 확인하도록 돕는 시니어 정보판단 코치",
    },
    {
        "id": "s1_input",
        "text": "받은 사진을 그대로 올립니다. 진위를 대신 정해 드리지 않습니다.",
        "caption": "① 입력 — 받은 사진을 그대로",
    },
    {
        "id": "s2_signal",
        "text": "확인할 점이 남으면 그 이유를 먼저 보여 주고, 무엇을 확인할지 질문으로 여쭤봅니다.",
        "caption": "② 위험 신호와 확인 질문 — 판정 대신 질문",
    },
    {
        "id": "s3_evidence",
        "text": "질문 옆에 금융위원회 같은 공식 자료를 붙여, 직접 눌러 확인하게 했습니다.",
        "caption": "③ 공식 근거 — 눌러서 직접 확인",
    },
    {
        "id": "s4_decision",
        "text": "판단은 사용자가 합니다. 미뤄 두는 선택도 그대로 기록합니다.",
        "caption": "④ 사용자 판단 — 미뤄 두는 것도 선택",
    },
    {
        "id": "s5_training",
        # text 는 TTS 발음용("오분"), subtitle 은 화면·자막 표기용("5분").
        "text": "확인한 내용과 비슷한 유형으로 오분 연습을 제공합니다. 화면 실습은 고정 예시입니다.",
        "subtitle": "확인한 내용과 비슷한 유형으로 5분 연습을 제공합니다. 화면 실습은 고정 예시입니다.",
        "caption": "⑤ 5분 연습 — 화면 실습은 고정 예시",
    },
    {
        "id": "s6_end",
        "text": "과거 화면 캡처로 재구성한 영상이며, 현재 서버는 운영하지 않습니다.",
        "caption": "과거 화면 캡처 기반 재구성 · 현재 서버 미운영",
    },
]


def synth(lib: ctypes.CDLL, text: str, out_path: Path, sample_rate: int) -> float:
    """text 를 합성해 out_path 에 16bit mono WAV 로 저장하고 길이(초)를 돌려준다."""
    chunks: list[bytes] = []

    # int cb(short *wav, int numsamples, espeak_EVENT *events)
    CB = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p
    )

    def _cb(wav, numsamples, events):  # noqa: ANN001
        if wav and numsamples > 0:
            chunks.append(ctypes.string_at(wav, numsamples * 2))
        return 0

    cb = CB(_cb)
    lib.espeak_SetSynthCallback(cb)

    payload = text.encode("utf-8")
    rc = lib.espeak_Synth(
        payload,
        len(payload) + 1,
        0,
        0,
        0,
        ESPEAK_CHARS_UTF8,
        None,
        None,
    )
    if rc != 0:
        raise RuntimeError(f"espeak_Synth 실패 rc={rc} text={text[:20]!r}")
    lib.espeak_Synchronize()

    pcm = b"".join(chunks)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return len(pcm) / 2 / sample_rate


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "build/audio")
    out_dir.mkdir(parents=True, exist_ok=True)

    lib = ctypes.CDLL(espeakng_loader.get_library_path())
    data_path = espeakng_loader.get_data_path().encode()
    sample_rate = lib.espeak_Initialize(AUDIO_OUTPUT_RETRIEVAL, 0, data_path, 0)
    if sample_rate <= 0:
        raise RuntimeError("espeak_Initialize 실패")
    if lib.espeak_SetVoiceByName(b"ko") != 0:
        raise RuntimeError("한국어 음성(ko) 설정 실패")

    # 또렷하되 40초 안에 들어가도록. 기본값은 175.
    lib.espeak_SetParameter(ESPEAK_RATE, 180, 0)
    lib.espeak_SetParameter(ESPEAK_PITCH, 45, 0)

    manifest = []
    for item in NARRATION:
        wav_path = out_dir / f"{item['id']}.wav"
        duration = synth(lib, item["text"], wav_path, sample_rate)
        manifest.append({**item, "wav": wav_path.name, "tts_duration": round(duration, 3)})
        print(f"{item['id']:14s} {duration:6.2f}s  {wav_path}")

    manifest_path = out_dir / "narration.json"
    manifest_path.write_text(
        json.dumps(
            {"sample_rate": sample_rate, "engine": "espeak-ng (formant TTS)", "scenes": manifest},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
