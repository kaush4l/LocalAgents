"""TTS service layer built on TTS backends/registry."""

from __future__ import annotations

import os
from typing import Any

from pydantic import Field, PrivateAttr

from core import observability
from core.engine import RuntimeObject
from core.sts_models import STSBackendError, SynthesisRequestModel
from core.tts_registry import TTSRegistry, tts_registry


class TTSService(RuntimeObject):
    """Facade for text-to-speech operations."""

    name: str = "tts_service"
    registry: TTSRegistry = Field(default_factory=lambda: tts_registry)

    _model_status: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)

    def _initialize_impl(self) -> Any:
        return self._warmup_models()

    async def _warmup_models(self) -> None:
        warmup_status = await self.registry.warmup_tts_models()
        for backend_id, payload in warmup_status.items():
            self._model_status[backend_id] = dict(payload)
        observability.log_event(
            "sts_tts_warmup",
            agent="sts",
            meta={"tts_models": warmup_status},
        )

    def get_model_status(self) -> dict[str, dict[str, Any]]:
        return dict(self._model_status)

    def list_tts_backends(self) -> list[dict[str, Any]]:
        return [backend.to_dict() for backend in self.registry.list_tts_options()]

    def default_tts_backend(self) -> str:
        configured = os.getenv("STS_TTS_BACKEND", "qwen3_tts").strip()
        valid_ids = {opt.id for opt in self.registry.list_tts_options()}
        if configured and configured in valid_ids:
            return configured
        options = self.registry.list_tts_options()
        return options[0].id if options else "qwen3_tts"

    def normalize_tts_backend(self, value: str | None) -> str:
        candidate = str(value or self.default_tts_backend()).strip()
        valid_ids = {opt.id for opt in self.registry.list_tts_options()}
        if candidate not in valid_ids:
            raise STSBackendError(
                error_code="unsupported_backend",
                error_message=f"Unsupported TTS backend: {candidate}",
                backend=candidate,
                remediation="Select 'qwen3_tts'.",
                status_code=400,
            )
        return candidate

    async def _synthesizer_health(self, backend_id: str) -> tuple[bool, str, str]:
        synthesizer = self.registry.get_synthesizer(backend_id)
        ready, reason, remediation = await synthesizer.health_check()
        return bool(ready), str(reason), str(remediation)

    async def get_backend_health(self) -> list[dict[str, Any]]:
        status: list[dict[str, Any]] = []
        for backend in self.registry.list_tts_options():
            ready, reason, remediation = await self._synthesizer_health(backend.id)
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

    async def preflight_speak_backend(self, backend: str | None) -> dict[str, Any]:
        selected = self.normalize_tts_backend(backend)
        ready, reason, remediation = await self._synthesizer_health(selected)
        return {
            "backend": selected,
            "ready": ready,
            "reason": reason,
            "remediation": remediation,
        }

    async def speak(
        self,
        text: str,
        *,
        backend: str | None = None,
        voice: str | None = None,
        model_name: str | None = None,
    ) -> tuple[str, bytes | None]:
        selected = self.normalize_tts_backend(backend)
        observability.log_event(
            "sts_backend_selected",
            agent="sts",
            meta={"stage": "tts", "backend": selected},
        )
        synthesizer = self.registry.get_synthesizer(selected)
        result = await synthesizer.synthesize(
            SynthesisRequestModel(text=text, backend=selected, voice=voice, model_name=model_name)
        )
        return result.mode, result.audio_bytes


tts_service = TTSService()


__all__ = ["TTSService", "tts_service"]
