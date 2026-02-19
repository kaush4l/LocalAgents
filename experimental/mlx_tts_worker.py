"""Isolated worker process for MLX TTS."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _run_check(model_path: str) -> int:
    try:
        from mlx_audio.tts.generate import generate_audio  # noqa: F401
    except Exception as exc:
        _emit({"ok": False, "error": f"mlx-audio import failed: {exc}"})
        return 2

    local_path = Path(model_path).expanduser()
    if not local_path.exists():
        _emit(
            {
                "ok": False,
                "error": f"MLX model path not found: {local_path}. "
                "Download offline models or set TTS_MLX_MODEL to an existing local path.",
            }
        )
        return 3

    _emit({"ok": True, "message": "mlx-audio import ok and model path exists"})
    return 0


def _run_speak(
    *,
    text: str,
    model_path: str,
    voice: str,
    speed: float,
    lang_code: str,
) -> int:
    if not text.strip():
        _emit({"ok": False, "error": "text is empty"})
        return 3

    try:
        from mlx_audio.tts.generate import generate_audio
    except Exception as exc:
        _emit({"ok": False, "error": f"mlx-audio import failed: {exc}"})
        return 2

    try:
        generate_audio(
            text=text.strip(),
            model_path=model_path,
            voice=voice,
            speed=float(speed),
            lang_code=lang_code,
            stream=True,
            play=True,
            verbose=False,
        )
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        return 4

    _emit({"ok": True, "message": "spoken"})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated MLX TTS worker")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--text", default="")
    parser.add_argument("--model-path", default="prince-canuma/Kokoro-82M")
    parser.add_argument("--voice", default="bf_emma")
    parser.add_argument("--speed", type=float, default=0.9)
    parser.add_argument("--lang-code", default="a")
    args = parser.parse_args()

    if args.check:
        return _run_check(args.model_path)
    return _run_speak(
        text=args.text,
        model_path=args.model_path,
        voice=args.voice,
        speed=args.speed,
        lang_code=args.lang_code,
    )


if __name__ == "__main__":
    raise SystemExit(main())
