"""STS type definitions: errors, request/response models, and backend options."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ── Errors ──────────────────────────────────────────────────────────────────


class STSBackendError(Exception):
    """Structured backend error used by STS layers."""

    def __init__(
        self,
        *,
        error_code: str,
        error_message: str,
        backend: str = "",
        remediation: str = "",
        status_code: int = 400,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.backend = backend
        self.remediation = remediation
        self.status_code = int(status_code)
        self.meta = dict(meta or {})

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "backend": self.backend,
            "remediation": self.remediation,
        }
        if self.meta:
            payload["meta"] = self.meta
        return payload


# ── Models ──────────────────────────────────────────────────────────────────


class BackendOptionModel(BaseModel):
    id: str
    label: str
    description: str
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class BackendHealthModel(BaseModel):
    id: str
    label: str
    ready: bool
    reason: str
    remediation: str

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class AudioTrackModel(BaseModel):
    source: str = Field(description="Metadata source: ffprobe or native_live")
    stream_index: int = 0
    codec_name: str | None = None
    codec_long_name: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None
    channel_layout: str | None = None
    bit_rate_bps: int | None = None
    duration_seconds: float | None = None
    time_base: str | None = None


class AudioFormatModel(BaseModel):
    container_name: str | None = None
    duration_seconds: float | None = None
    bit_rate_bps: int | None = None
    size_bytes: int | None = None
    filename: str | None = None


class AudioProbeModel(BaseModel):
    tracks: list[AudioTrackModel] = Field(default_factory=list)
    audio_format: AudioFormatModel | None = None
    raw: dict[str, Any] | None = None


class TranscriptionRequestModel(BaseModel):
    audio_bytes: bytes | None = None
    filename: str = "audio.webm"
    backend: str
    model_name: str | None = None
    locale: str | None = None


class TranscriptionResultModel(BaseModel):
    text: str
    backend: str
    model: str | None = None
    audio_tracks: list[AudioTrackModel] = Field(default_factory=list)
    audio_format: AudioFormatModel | None = None


class LiveStartRequestModel(BaseModel):
    backend: str
    locale: str | None = None


class LiveStateModel(BaseModel):
    running: bool
    locale: str | None = None
    partial: str = ""
    segments: list[str] = Field(default_factory=list)
    transcript: str = ""
    last_error: str = ""
    last_seq: int = 0
    events: list[dict[str, Any]] = Field(default_factory=list)
    backend: str
    audio_tracks: list[AudioTrackModel] = Field(default_factory=list)
    audio_format: AudioFormatModel | None = None


class SynthesisRequestModel(BaseModel):
    text: str
    backend: str
    voice: str | None = None
    model_name: str | None = None


class SynthesisResultModel(BaseModel):
    mode: Literal["audio_bytes", "local_playback"]
    backend: str
    audio_bytes: bytes | None = None


class STSBackendErrorPayloadModel(BaseModel):
    error_code: str
    error_message: str
    backend: str = ""
    remediation: str = ""
