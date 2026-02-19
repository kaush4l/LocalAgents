"""Qwen3-ASR backend — warm in-process model singleton.

The model is loaded once via ``warmup()`` (called at server startup) and
held in memory for all subsequent transcription calls.  No subprocess
overhead, no per-call model reload.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── module-level singleton ──────────────────────────────────────────────
_model: Any = None
_lock = threading.Lock()


def _resolve_allow_remote(allow_remote: bool | None) -> bool:
    if allow_remote is None:
        return os.getenv("QWEN3_ASR_ALLOW_REMOTE", "false").lower() in ("true", "1", "yes")
    return bool(allow_remote)


def _load_model(*, model_name: str, device_map: str, allow_remote: bool) -> Any:
    """Import qwen_asr and load the model. Raises RuntimeError on failure."""
    try:
        from qwen_asr import Qwen3ASRModel
    except Exception as exc:
        raise RuntimeError(
            "qwen-asr is not installed or incompatible. "
            "Run `uv sync` and verify qwen_asr imports."
        ) from exc

    local_candidate = Path(model_name).expanduser()
    if not allow_remote and not local_candidate.exists():
        raise RuntimeError(
            f"Qwen3-ASR local model path not found: {local_candidate}. "
            "Set QWEN3_ASR_MODEL to a local folder and download offline assets."
        )

    model_kwargs: dict[str, Any] = {"device_map": device_map}
    if not allow_remote:
        model_kwargs["local_files_only"] = True

    try:
        return Qwen3ASRModel.from_pretrained(model_name, **model_kwargs)
    except Exception as exc:
        message = str(exc).strip().lower()
        if not allow_remote and any(
            token in message
            for token in (
                "local_files_only",
                "not found in local cache",
                "couldn't find",
                "not a local folder",
                "repository not found",
                "is not a directory",
            )
        ):
            raise RuntimeError(
                f"Qwen3-ASR local model path not found: {local_candidate}. "
                "Download offline assets or set QWEN3_ASR_ALLOW_REMOTE=1."
            ) from exc
        raise RuntimeError(
            f"Qwen3-ASR model load failed for '{model_name}' "
            f"(device_map={device_map}): {str(exc).strip()}"
        ) from exc


def _get_model(*, model_name: str, device_map: str, allow_remote: bool) -> Any:
    """Return the cached model, loading it on first call (thread-safe)."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        _model = _load_model(
            model_name=model_name,
            device_map=device_map,
            allow_remote=allow_remote,
        )
        logger.info("Qwen3-ASR model loaded and warm (model=%s, device_map=%s)", model_name, device_map)
        return _model


# ── public API ──────────────────────────────────────────────────────────


def warmup(
    *,
    model_name: str | None = None,
    device_map: str | None = None,
    allow_remote: bool | None = None,
) -> None:
    """Pre-load the ASR model so it is warm for the first request."""
    _get_model(
        model_name=model_name or os.getenv("QWEN3_ASR_MODEL", "models/qwen3-asr-0.6b"),
        device_map=device_map or os.getenv("QWEN3_ASR_DEVICE_MAP", "auto"),
        allow_remote=_resolve_allow_remote(allow_remote),
    )


def health_check(
    *,
    model_name: str,
    device_map: str,
    allow_remote: bool | None = None,
) -> dict[str, Any]:
    """Return readiness status for Qwen3-ASR backend."""
    resolved = _resolve_allow_remote(allow_remote)

    # Quick import check
    try:
        import qwen_asr  # noqa: F401
    except Exception as exc:
        return {"ready": False, "reason": f"qwen_asr import error: {exc}"}

    if not resolved:
        local_candidate = Path(model_name).expanduser()
        if not local_candidate.exists():
            return {
                "ready": False,
                "reason": (
                    f"Qwen3-ASR local model path not found: {local_candidate}. "
                    "Download/copy model files there or set QWEN3_ASR_ALLOW_REMOTE=1."
                ),
            }

    # If model is already loaded, report that
    if _model is not None:
        return {"ready": True, "reason": "Qwen3-ASR model loaded and warm."}

    return {"ready": True, "reason": "qwen_asr import ok, model not yet loaded."}


def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    model_name: str = "Qwen/Qwen3-ASR-0.6B",
    device_map: str = "auto",
    allow_remote: bool | None = None,
) -> str:
    """Transcribe audio bytes using the warm in-process model."""
    resolved = _resolve_allow_remote(allow_remote)
    model = _get_model(
        model_name=model_name,
        device_map=device_map,
        allow_remote=resolved,
    )

    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        temp_path = Path(tmp.name)

    try:
        results = model.transcribe(audio=str(temp_path))
    except Exception as exc:
        raise RuntimeError(f"Qwen3-ASR transcription failed: {exc}") from exc
    finally:
        try:
            temp_path.unlink()
        except Exception:
            pass

    if not results:
        raise RuntimeError("Qwen3-ASR returned no transcription segments.")

    first = results[0]
    text = str(getattr(first, "text", "") or "").strip()
    if not text:
        raise RuntimeError("Qwen3-ASR returned an empty transcription.")
    return text
