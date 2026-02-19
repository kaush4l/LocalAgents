"""Qwen3-ASR wrapper that runs transcription in an isolated subprocess."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from time import monotonic
from typing import Any

from experimental.base import SubprocessWorker

_worker = SubprocessWorker(worker_module="experimental.qwen3_asr_worker")
_HEALTH_CACHE_SECONDS = 20.0
_HEALTH_CACHE: dict[tuple[str, str, bool], tuple[float, dict[str, Any]]] = {}


def _resolve_allow_remote(allow_remote: bool | None) -> bool:
    if allow_remote is None:
        return os.getenv("QWEN3_ASR_ALLOW_REMOTE", "false").lower() in ("true", "1", "yes")
    return bool(allow_remote)


def health_check(
    *,
    model_name: str,
    device_map: str,
    allow_remote: bool | None = None,
) -> dict[str, Any]:
    """Return readiness status for Qwen3-ASR backend."""
    resolved_allow_remote = _resolve_allow_remote(allow_remote)
    key = (model_name, device_map, resolved_allow_remote)
    now = monotonic()
    cached = _HEALTH_CACHE.get(key)
    if cached and now < cached[0]:
        return dict(cached[1])

    args = [
        "--mode",
        "health",
        "--model-name",
        model_name,
        "--device-map",
        device_map,
    ]
    if resolved_allow_remote:
        args.append("--allow-remote")

    try:
        payload = _worker.run(args)
        result = {
            "ready": bool(payload.get("ready", True)),
            "reason": str(payload.get("reason") or "qwen_asr import ok"),
        }
    except Exception as exc:
        result = {
            "ready": False,
            "reason": str(exc),
        }

    _HEALTH_CACHE[key] = (now + _HEALTH_CACHE_SECONDS, result)
    return dict(result)


def transcribe_audio_bytes(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    model_name: str = "Qwen/Qwen3-ASR-0.6B",
    device_map: str = "auto",
    allow_remote: bool | None = None,
) -> str:
    """Transcribe local audio bytes with Qwen3-ASR in a child process."""
    resolved_allow_remote = _resolve_allow_remote(allow_remote)
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        temp_path = Path(tmp.name)

    try:
        args = [
            "--mode",
            "transcribe",
            "--audio-path",
            str(temp_path),
            "--model-name",
            model_name,
            "--device-map",
            device_map,
        ]
        if resolved_allow_remote:
            args.append("--allow-remote")

        payload = _worker.run(args)
        text = str(payload.get("text", "")).strip()
        if not text:
            raise RuntimeError("Qwen3-ASR returned an empty transcription.")
        return text
    finally:
        try:
            temp_path.unlink()
        except Exception:
            pass
