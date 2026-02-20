"""FFprobe helpers for extracting audio track metadata."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from core.speech.sts_models import AudioFormatModel, AudioProbeModel, AudioTrackModel, STSBackendError


def ensure_ffprobe_available() -> str:
    """Return ffprobe executable path or raise structured setup error."""
    exe = os.getenv("STS_FFPROBE_BIN", "ffprobe").strip()
    found = shutil.which(exe)
    if not found:
        raise STSBackendError(
            error_code="ffprobe_not_available",
            error_message=f"FFprobe binary not found: {exe}",
            backend="sts",
            remediation="Install FFmpeg/FFprobe and ensure it is available on PATH.",
            status_code=503,
        )
    return found


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _run_ffprobe(path: Path) -> dict[str, Any]:
    ffprobe = ensure_ffprobe_available()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        raise STSBackendError(
            error_code="ffprobe_execution_error",
            error_message=str(exc),
            backend="sts",
            remediation="Verify FFprobe installation and runtime permissions.",
            status_code=503,
        ) from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise STSBackendError(
            error_code="ffprobe_failed",
            error_message=f"FFprobe failed: {stderr or stdout or f'exit {proc.returncode}'}",
            backend="sts",
            remediation="Verify the uploaded audio format is supported by FFprobe.",
            status_code=422,
        )
    if not stdout:
        raise STSBackendError(
            error_code="ffprobe_empty_output",
            error_message="FFprobe returned empty output.",
            backend="sts",
            remediation="Retry with a valid audio file.",
            status_code=422,
        )
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise STSBackendError(
            error_code="ffprobe_parse_error",
            error_message=f"Invalid ffprobe JSON output: {exc}",
            backend="sts",
            remediation="Retry with a valid audio file.",
            status_code=422,
        ) from exc


def _parse_probe(payload: dict[str, Any]) -> AudioProbeModel:
    streams = payload.get("streams") or []
    parsed_tracks: list[AudioTrackModel] = []

    for stream in streams:
        if str(stream.get("codec_type", "")).lower() != "audio":
            continue
        parsed_tracks.append(
            AudioTrackModel(
                source="ffprobe",
                stream_index=int(stream.get("index", 0) or 0),
                codec_name=stream.get("codec_name"),
                codec_long_name=stream.get("codec_long_name"),
                sample_rate_hz=_as_int(stream.get("sample_rate")),
                channels=_as_int(stream.get("channels")),
                channel_layout=stream.get("channel_layout"),
                bit_rate_bps=_as_int(stream.get("bit_rate")),
                duration_seconds=_as_float(stream.get("duration")),
                time_base=stream.get("time_base"),
            )
        )

    format_raw = payload.get("format") or {}
    audio_format = AudioFormatModel(
        container_name=format_raw.get("format_name"),
        duration_seconds=_as_float(format_raw.get("duration")),
        bit_rate_bps=_as_int(format_raw.get("bit_rate")),
        size_bytes=_as_int(format_raw.get("size")),
        filename=format_raw.get("filename"),
    )

    return AudioProbeModel(tracks=parsed_tracks, audio_format=audio_format, raw=payload)


def probe_audio_path(path: Path | str, required: bool = True) -> AudioProbeModel:
    """Probe an audio file path and normalize ffprobe output."""
    try:
        payload = _run_ffprobe(Path(path))
        return _parse_probe(payload)
    except STSBackendError:
        if required:
            raise
        return AudioProbeModel()


def probe_audio_bytes(audio_bytes: bytes, filename: str = "audio.webm", required: bool = True) -> AudioProbeModel:
    """Probe in-memory audio bytes by writing to a temporary file first."""
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = Path(tmp.name)
    try:
        return probe_audio_path(tmp_path, required=required)
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
