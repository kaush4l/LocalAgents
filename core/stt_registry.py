"""Registry and option catalog for STT backends."""

from __future__ import annotations

from pydantic import Field

from core.engine import RuntimeObject
from core.sts_models import BackendOptionModel
from core.stt_backends import (
    AudioTranscriberBaseModel,
    Qwen3ASRTranscriber,
    WhisperAPITranscriber,
)


class STTRegistry(RuntimeObject):
    """Owns STT backend instances and option metadata."""

    name: str = "stt_registry"

    transcription_options: tuple[BackendOptionModel, ...] = Field(
        default_factory=lambda: (
            BackendOptionModel(
                id="whisper_api",
                label="Whisper API",
                description="Upload audio to your OpenAI-compatible /audio/transcriptions endpoint.",
            ),
            BackendOptionModel(
                id="qwen3_asr",
                label="Qwen3-ASR (Experimental)",
                description="Local transcription with Qwen/Qwen3-ASR.",
            ),
        )
    )
    transcribers: dict[str, AudioTranscriberBaseModel] = Field(
        default_factory=lambda: {
            "whisper_api": WhisperAPITranscriber(),
            "qwen3_asr": Qwen3ASRTranscriber(),
        }
    )

    def list_transcription_options(self) -> list[BackendOptionModel]:
        return [opt.model_copy(deep=True) for opt in self.transcription_options]

    def get_transcriber(self, backend_id: str) -> AudioTranscriberBaseModel:
        return self.transcribers[backend_id]


stt_registry = STTRegistry()


__all__ = ["STTRegistry", "stt_registry"]
