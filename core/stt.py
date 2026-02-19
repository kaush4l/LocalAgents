"""STT service layer built on STT backends/registry."""

from __future__ import annotations

import os
from typing import Any

from pydantic import Field

from core import observability
from core.engine import RuntimeObject
from core.sts_ffmpeg import ensure_ffprobe_available
from core.sts_models import STSBackendError, TranscriptionRequestModel, TranscriptionResultModel
from core.stt_registry import STTRegistry, stt_registry


class STTService(RuntimeObject):
    """Facade for speech-to-text operations."""

    name: str = "stt_service"
    registry: STTRegistry = Field(default_factory=lambda: stt_registry)

    def list_transcription_backends(self) -> list[dict[str, Any]]:
        return [backend.to_dict() for backend in self.registry.list_transcription_options()]

    def default_transcription_backend(self) -> str:
        configured = os.getenv("STS_TRANSCRIBE_BACKEND", "").strip()
        valid_ids = {opt.id for opt in self.registry.list_transcription_options()}
        if configured and configured in valid_ids:
            return configured
        options = self.registry.list_transcription_options()
        return options[0].id if options else "whisper_api"

    def normalize_transcription_backend(self, value: str | None) -> str:
        candidate = str(value or self.default_transcription_backend()).strip()
        valid_ids = {opt.id for opt in self.registry.list_transcription_options()}
        if candidate not in valid_ids:
            raise STSBackendError(
                error_code="unsupported_backend",
                error_message=f"Unsupported transcription backend: {candidate}",
                backend=candidate,
                remediation=f"Select one of {', '.join(sorted(valid_ids))}.",
                status_code=400,
            )
        return candidate

    async def _transcriber_health(self, backend_id: str) -> tuple[bool, str, str]:
        transcriber = self.registry.get_transcriber(backend_id)
        ready, reason, remediation = await transcriber.health_check()
        if transcriber.supports_file and os.getenv("STS_FFPROBE_REQUIRED", "true").lower() in ("true", "1", "yes"):
            try:
                ensure_ffprobe_available()
            except STSBackendError as exc:
                return False, exc.error_message, exc.remediation
        return bool(ready), str(reason), str(remediation)

    async def get_backend_health(self) -> list[dict[str, Any]]:
        status: list[dict[str, Any]] = []
        for backend in self.registry.list_transcription_options():
            ready, reason, remediation = await self._transcriber_health(backend.id)
            status.append(
                {
                    "id": backend.id,
                    "label": backend.label,
                    "ready": ready,
                    "reason": reason,
                    "remediation": remediation,
                }
            )
        return status

    async def transcribe_with_metadata(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "audio.webm",
        backend: str | None = None,
        model_name: str | None = None,
    ) -> TranscriptionResultModel:
        selected = self.normalize_transcription_backend(backend)
        observability.log_event(
            "sts_backend_selected",
            agent="sts",
            meta={"stage": "stt", "backend": selected},
        )

        transcriber = self.registry.get_transcriber(selected)
        result = await transcriber.transcribe(
            TranscriptionRequestModel(
                audio_bytes=audio_bytes,
                filename=filename,
                backend=selected,
                model_name=model_name,
            )
        )

        observability.log_event(
            "sts_audio_tracks",
            agent="sts",
            meta={
                "backend": selected,
                "tracks": [t.model_dump() for t in result.audio_tracks],
                "audio_format": result.audio_format.model_dump() if result.audio_format else None,
            },
        )
        return result

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "audio.webm",
        backend: str | None = None,
        model_name: str | None = None,
    ) -> str:
        result = await self.transcribe_with_metadata(
            audio_bytes,
            filename=filename,
            backend=backend,
            model_name=model_name,
        )
        return result.text


stt_service = STTService()


__all__ = ["STTService", "stt_service"]
