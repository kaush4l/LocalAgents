"""MLX TTS backend — warm in-process model singleton.

The MLX-audio model is loaded once via ``warmup()`` (called at server
startup) and reused for every subsequent ``speak_text()`` call.  No
subprocess overhead, no per-call model reload.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── module-level singleton ──────────────────────────────────────────────
_generate_fn: Any = None  # cached reference to mlx_audio generate_audio
_lock = threading.Lock()
_ready = False


def _ensure_ready(*, model_path: str) -> Any:
    """Import mlx_audio and verify the model path. Thread-safe."""
    global _generate_fn, _ready
    if _ready and _generate_fn is not None:
        return _generate_fn
    with _lock:
        if _ready and _generate_fn is not None:
            return _generate_fn
        try:
            from mlx_audio.tts.generate import generate_audio
        except Exception as exc:
            raise RuntimeError(f"mlx-audio import failed: {exc}") from exc

        local_path = Path(model_path).expanduser()
        if not local_path.exists():
            raise RuntimeError(
                f"MLX model path not found: {local_path}. "
                "Download offline models or set TTS_MLX_MODEL to an existing local path."
            )

        _generate_fn = generate_audio
        _ready = True
        logger.info("MLX-TTS ready (model_path=%s)", model_path)
        return _generate_fn


# ── public API ──────────────────────────────────────────────────────────


def warmup(*, model_path: str = "prince-canuma/Kokoro-82M") -> None:
    """Pre-import mlx-audio and validate model path at startup."""
    _ensure_ready(model_path=model_path)


def preflight_check(*, model_path: str = "prince-canuma/Kokoro-82M") -> dict[str, Any]:
    """Lightweight MLX backend readiness check."""
    try:
        _ensure_ready(model_path=model_path)
        return {"ok": True, "message": "mlx-audio import ok and model path exists"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def speak_text(
    text: str,
    *,
    model_path: str = "prince-canuma/Kokoro-82M",
    voice: str = "bf_emma",
    speed: float = 0.9,
    lang_code: str = "a",
) -> None:
    """Speak text locally with mlx-audio, using the warm in-process model."""
    if not isinstance(text, str) or not text.strip():
        return

    generate_audio = _ensure_ready(model_path=model_path)
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
