"""Backward-compatible STS backend exports.

This module preserves legacy imports by re-exporting symbols from the new
split modules:
    - ``core.stt_backends`` / ``core.stt_registry``
    - ``core.tts_backends`` / ``core.tts_registry``
"""

from __future__ import annotations

from pydantic import Field

from core.engine import RuntimeObject
from core.stt_backends import (
    AudioTranscriberBaseModel,
    MacOSNativeLiveTranscriber,
    Qwen3ASRTranscriber,
    WhisperAPITranscriber,
)
from core.stt_registry import STTRegistry
from core.stt_registry import stt_registry as _default_stt_registry
from core.tts_backends import (
    LocalModelSynthesizerBase,
    PlayableSynthesizerBase,
    Qwen3TTSSynthesizer,
    SpeechSynthesizerBaseModel,
)
from core.tts_registry import TTSRegistry
from core.tts_registry import tts_registry as _default_tts_registry


class STSRegistry(RuntimeObject):
    """Compatibility wrapper exposing the pre-split combined registry API."""

    name: str = "sts_registry"
    stt_registry: STTRegistry = Field(default_factory=lambda: _default_stt_registry)
    tts_registry: TTSRegistry = Field(default_factory=lambda: _default_tts_registry)

    @property
    def transcription_options(self):  # pragma: no cover - compatibility surface
        return self.stt_registry.transcription_options

    @property
    def tts_options(self):  # pragma: no cover - compatibility surface
        return self.tts_registry.tts_options

    @property
    def transcribers(self):  # pragma: no cover - compatibility surface
        return self.stt_registry.transcribers

    @property
    def synthesizers(self):  # pragma: no cover - compatibility surface
        return self.tts_registry.synthesizers

    def list_transcription_options(self):
        return self.stt_registry.list_transcription_options()

    def list_tts_options(self):
        return self.tts_registry.list_tts_options()

    def get_transcriber(self, backend_id: str) -> AudioTranscriberBaseModel:
        return self.stt_registry.get_transcriber(backend_id)

    def get_synthesizer(self, backend_id: str) -> SpeechSynthesizerBaseModel:
        return self.tts_registry.get_synthesizer(backend_id)

    async def warmup_tts_models(self):
        return await self.tts_registry.warmup_tts_models()


sts_registry = STSRegistry(
    stt_registry=_default_stt_registry,
    tts_registry=_default_tts_registry,
)


__all__ = [
    "AudioTranscriberBaseModel",
    "SpeechSynthesizerBaseModel",
    "PlayableSynthesizerBase",
    "LocalModelSynthesizerBase",
    "STSRegistry",
    "sts_registry",
    "STTRegistry",
    "TTSRegistry",
    "WhisperAPITranscriber",
    "Qwen3ASRTranscriber",
    "MacOSNativeLiveTranscriber",
    "Qwen3TTSSynthesizer",
]
