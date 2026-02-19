"""STT backend base classes and concrete implementations."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from core import observability
from core.sts_ffmpeg import probe_audio_bytes
from core.sts_models import (
    AudioProbeModel,
    LiveStateModel,
    STSBackendError,
    TranscriptionRequestModel,
    TranscriptionResultModel,
)
from core.utils import compact_reason as _compact_reason

logger = logging.getLogger(__name__)


async def _check_openai_endpoint(*, base_url: str, backend: str, remediation: str) -> tuple[bool, str, str]:
    endpoint = base_url.rstrip("/") + "/models"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(endpoint)
        if response.status_code < 500:
            return True, f"Endpoint reachable ({response.status_code}).", remediation
        return False, f"Endpoint responded with {response.status_code}.", remediation
    except Exception as exc:
        return False, _compact_reason(f"{backend} unreachable: {exc}"), remediation


class AudioTranscriberBaseModel(BaseModel):
    """Template flow for file and live transcription backends."""

    backend_id: str
    display_label: str = ""
    supports_file: bool = True
    supports_live: bool = False
    ffprobe_required: bool = Field(
        default_factory=lambda: os.getenv("STS_FFPROBE_REQUIRED", "true").lower() in ("true", "1", "yes")
    )

    model_config = {"arbitrary_types_allowed": True}

    async def transcribe(self, request: TranscriptionRequestModel | dict[str, Any]) -> TranscriptionResultModel:
        req = (
            request
            if isinstance(request, TranscriptionRequestModel)
            else TranscriptionRequestModel.model_validate(request)
        )
        if not self.supports_file:
            raise STSBackendError(
                error_code="live_backend_only",
                error_message=f"{self.backend_id} supports live transcription only.",
                backend=self.backend_id,
                remediation="Use the live transcription endpoints for this backend.",
                status_code=400,
            )
        if not req.audio_bytes:
            raise STSBackendError(
                error_code="audio_required",
                error_message="Audio bytes are required for file transcription.",
                backend=self.backend_id,
                remediation="Attach an audio file and retry.",
                status_code=400,
            )

        t0 = time.perf_counter()
        observability.log_event(
            "stt_start",
            agent="sts",
            meta={"backend": self.backend_id, "audio_size": len(req.audio_bytes)},
        )
        try:
            probe = await self.capture_audio_probe(req)
            result = await self._transcribe_impl(req, probe)
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            observability.log_event(
                "stt_end",
                agent="sts",
                meta={
                    "backend": self.backend_id,
                    "duration_ms": elapsed_ms,
                    "text_len": len(result.text),
                },
            )
            logger.info("STT %s completed in %dms (%d chars)", self.backend_id, elapsed_ms, len(result.text))
            return result
        except Exception:
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            observability.log_event(
                "stt_error",
                agent="sts",
                status="error",
                meta={"backend": self.backend_id, "duration_ms": elapsed_ms},
            )
            raise

    async def capture_audio_probe(self, request: TranscriptionRequestModel) -> AudioProbeModel:
        if not request.audio_bytes:
            return AudioProbeModel()
        try:
            return await asyncio.to_thread(
                probe_audio_bytes,
                request.audio_bytes,
                request.filename,
                bool(self.ffprobe_required),
            )
        except STSBackendError:
            raise
        except Exception as exc:
            if self.ffprobe_required:
                raise STSBackendError(
                    error_code="ffprobe_not_available",
                    error_message=str(exc),
                    backend=self.backend_id,
                    remediation="Ensure FFprobe is installed and available on PATH.",
                    status_code=503,
                ) from exc
            return AudioProbeModel()

    async def _transcribe_impl(
        self, request: TranscriptionRequestModel, probe: AudioProbeModel
    ) -> TranscriptionResultModel:
        raise NotImplementedError("Transcriber backend must implement _transcribe_impl().")

    async def live_start(self, request: dict[str, Any]) -> LiveStateModel:
        raise STSBackendError(
            error_code="backend_not_live_capable",
            error_message=f"Live mode is not supported by {self.backend_id}.",
            backend=self.backend_id,
            remediation="Use a live-capable backend.",
            status_code=400,
        )

    def live_state(self, *, since_seq: int = 0) -> LiveStateModel:
        raise STSBackendError(
            error_code="backend_not_live_capable",
            error_message=f"Live mode is not supported by {self.backend_id}.",
            backend=self.backend_id,
            remediation="Use a live-capable backend.",
            status_code=400,
        )

    async def live_stop(self) -> LiveStateModel:
        raise STSBackendError(
            error_code="backend_not_live_capable",
            error_message=f"Live mode is not supported by {self.backend_id}.",
            backend=self.backend_id,
            remediation="Use a live-capable backend.",
            status_code=400,
        )

    def live_clear(self) -> LiveStateModel:
        raise STSBackendError(
            error_code="backend_not_live_capable",
            error_message=f"Live mode is not supported by {self.backend_id}.",
            backend=self.backend_id,
            remediation="Use a live-capable backend.",
            status_code=400,
        )

    async def health_check(self) -> tuple[bool, str, str]:
        raise NotImplementedError("Transcriber backend must implement health_check().")


class WhisperAPITranscriber(AudioTranscriberBaseModel):
    backend_id: str = "whisper_api"
    display_label: str = "Whisper API"
    supports_file: bool = True
    supports_live: bool = False

    async def _transcribe_impl(
        self, request: TranscriptionRequestModel, probe: AudioProbeModel
    ) -> TranscriptionResultModel:
        client = AsyncOpenAI(
            base_url=os.getenv("WHISPER_API_URL", "http://127.0.0.1:1234/v1"),
            api_key=os.getenv("OPENAI_API_KEY", "") or "lm-studio",
        )
        try:
            resp = await client.audio.transcriptions.create(
                model=os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo"),
                file=(request.filename, request.audio_bytes),
            )
            text = str(resp.text or "").strip()
            if not text:
                raise STSBackendError(
                    error_code="empty_transcript",
                    error_message="Whisper returned an empty transcript.",
                    backend=self.backend_id,
                    remediation="Speak clearly and ensure the model supports uploaded audio format.",
                    status_code=422,
                )
            return TranscriptionResultModel(
                text=text,
                backend=self.backend_id,
                model=os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo"),
                audio_tracks=list(probe.tracks),
                audio_format=probe.audio_format,
            )
        except STSBackendError:
            raise
        except Exception as exc:
            raise STSBackendError(
                error_code="stt_backend_failure",
                error_message=_compact_reason(f"Whisper transcription failed: {exc}"),
                backend=self.backend_id,
                remediation="Start a Whisper-compatible endpoint or switch STT backend.",
                status_code=503,
            ) from exc

    async def health_check(self) -> tuple[bool, str, str]:
        return await _check_openai_endpoint(
            base_url=os.getenv("WHISPER_API_URL", "http://127.0.0.1:1234/v1"),
            backend=self.backend_id,
            remediation="Start a Whisper-compatible API server or switch STT backend.",
        )


class Qwen3ASRTranscriber(AudioTranscriberBaseModel):
    backend_id: str = "qwen3_asr"
    display_label: str = "Qwen3-ASR (Experimental)"
    supports_file: bool = True
    supports_live: bool = False

    async def _transcribe_impl(
        self, request: TranscriptionRequestModel, probe: AudioProbeModel
    ) -> TranscriptionResultModel:
        from experimental.qwen3_asr import transcribe_audio_bytes

        model_name = str(request.model_name or os.getenv("QWEN3_ASR_MODEL", "models/qwen3-asr-0.6b")).strip()
        try:
            text = await asyncio.to_thread(
                transcribe_audio_bytes,
                request.audio_bytes,
                filename=request.filename,
                model_name=model_name,
                device_map=os.getenv("QWEN3_ASR_DEVICE_MAP", "auto"),
                allow_remote=os.getenv("QWEN3_ASR_ALLOW_REMOTE", "false").lower() in ("true", "1", "yes"),
            )
            return TranscriptionResultModel(
                text=text,
                backend=self.backend_id,
                model=model_name,
                audio_tracks=list(probe.tracks),
                audio_format=probe.audio_format,
            )
        except Exception as exc:
            raise STSBackendError(
                error_code="stt_backend_failure",
                error_message=_compact_reason(f"Qwen3-ASR transcription failed: {exc}"),
                backend=self.backend_id,
                remediation="Verify local Qwen model, device_map, and qwen_asr runtime.",
                status_code=503,
            ) from exc

    async def health_check(self) -> tuple[bool, str, str]:
        from experimental.qwen3_asr import health_check

        check = await asyncio.to_thread(
            health_check,
            model_name=os.getenv("QWEN3_ASR_MODEL", "models/qwen3-asr-0.6b"),
            device_map=os.getenv("QWEN3_ASR_DEVICE_MAP", "auto"),
            allow_remote=os.getenv("QWEN3_ASR_ALLOW_REMOTE", "false").lower() in ("true", "1", "yes"),
        )
        return (
            bool(check.get("ready")),
            _compact_reason(check.get("reason")),
            "Ensure Qwen model exists at QWEN3_ASR_MODEL or download offline assets.",
        )


__all__ = [
    "AudioTranscriberBaseModel",
    "WhisperAPITranscriber",
    "Qwen3ASRTranscriber",
]
