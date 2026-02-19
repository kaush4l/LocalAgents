"""MLX TTS wrapper that executes in a child process for safety."""

from __future__ import annotations

from typing import Any

from experimental.base import SubprocessWorker

_worker = SubprocessWorker(worker_module="experimental.mlx_tts_worker")


def preflight_check(*, model_path: str = "prince-canuma/Kokoro-82M") -> dict[str, Any]:
    """Lightweight MLX backend readiness check."""
    return _worker.run(["--check", "--model-path", model_path])


def speak_text(
    text: str,
    *,
    model_path: str = "prince-canuma/Kokoro-82M",
    voice: str = "bf_emma",
    speed: float = 0.9,
    lang_code: str = "a",
) -> None:
    """Speak text locally with mlx-audio, isolated in a worker process."""
    if not isinstance(text, str) or not text.strip():
        return

    _worker.run(
        [
            "--text",
            text.strip(),
            "--model-path",
            model_path,
            "--voice",
            voice,
            "--speed",
            str(float(speed)),
            "--lang-code",
            lang_code,
        ],
    )
