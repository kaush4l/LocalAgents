"""Registry and option catalog for TTS backends."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from core.engine import RuntimeObject
from core.speech.sts_models import BackendOptionModel, STSBackendError, SynthesisRequestModel
from core.speech.tts_backends import LocalModelSynthesizerBase, Qwen3TTSSynthesizer, SpeechSynthesizerBaseModel


class TTSRegistry(RuntimeObject):
    """Owns TTS backend instances, option metadata, and warmup."""

    name: str = "tts_registry"

    tts_options: tuple[BackendOptionModel, ...] = Field(
        default_factory=lambda: (
            BackendOptionModel(
                id="qwen3_tts",
                label="Qwen3-TTS-12Hz-0.6B",
                description="Local Qwen model from Qwen/Qwen3-TTS-12Hz-0.6B-Base.",
            ),
        )
    )
    synthesizers: dict[str, SpeechSynthesizerBaseModel] = Field(
        default_factory=lambda: {
            "qwen3_tts": Qwen3TTSSynthesizer(),
        }
    )

    def list_tts_options(self) -> list[BackendOptionModel]:
        return [opt.model_copy(deep=True) for opt in self.tts_options]

    def get_synthesizer(self, backend_id: str) -> SpeechSynthesizerBaseModel:
        return self.synthesizers[backend_id]

    async def warmup_tts_models(self) -> dict[str, dict[str, Any]]:
        status: dict[str, dict[str, Any]] = {}
        for backend in self.list_tts_options():
            synthesizer = self.get_synthesizer(backend.id)
            if isinstance(synthesizer, LocalModelSynthesizerBase):
                local_dir = await synthesizer.ensure_ready()
                try:
                    probe = await synthesizer.synthesize(
                        SynthesisRequestModel(
                            text="Warmup health check.",
                            backend=backend.id,
                        )
                    )
                except STSBackendError as exc:
                    if exc.error_code in {
                        "tts_model_download_failed",
                        "tts_model_load_failed",
                        "tts_reference_audio_prepare_failed",
                        "tts_reference_audio_invalid",
                    }:
                        raise
                    raise STSBackendError(
                        error_code="tts_warmup_synthesis_failed",
                        error_message=f"{backend.id} warmup synthesis failed: {exc.error_message}",
                        backend=backend.id,
                        remediation=exc.remediation or "Verify TTS runtime dependencies and model compatibility.",
                        status_code=503,
                        meta={"cause": exc.error_code},
                    ) from exc
                status[backend.id] = {
                    "ready": True,
                    "path": str(local_dir),
                    "repo": synthesizer.repo_id,
                    "probe_mode": probe.mode,
                    "probe_audio_bytes": len(probe.audio_bytes or b""),
                }
            else:
                ready, reason, remediation = await synthesizer.health_check()
                if not ready:
                    raise STSBackendError(
                        error_code="tts_backend_not_ready",
                        error_message=reason,
                        backend=backend.id,
                        remediation=remediation,
                        status_code=503,
                    )
                status[backend.id] = {"ready": True, "reason": reason}
        return status


tts_registry = TTSRegistry()


__all__ = ["TTSRegistry", "tts_registry"]
