"""Speech-to-Speech pipeline facade over STT + TTS services."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import Field, PrivateAttr

from core import observability
from core.engine import RuntimeObject
from core.speech.sts_models import STSBackendError
from core.speech.stt import STTService, stt_service
from core.speech.tts import TTSService, tts_service
from core.utils.helpers import compact_reason

logger = logging.getLogger(__name__)


class STSService(RuntimeObject):
    """Pipeline facade: STT → LLM → TTS.

    Access STT/TTS directly via ``stt`` and ``tts`` attributes.
    """

    name: str = "sts_service"
    stt: STTService = Field(default_factory=lambda: stt_service)
    tts: TTSService = Field(default_factory=lambda: tts_service)

    _model_status: dict[str, dict[str, Any]] = PrivateAttr(default_factory=dict)

    # ── lifecycle ────────────────────────────────────────────────────────

    def _initialize_impl(self) -> Any:
        return self._initialize_services()

    def _shutdown_impl(self) -> Any:
        return self._shutdown_services()

    async def _initialize_services(self) -> None:
        await self._verify_local_asr_model()
        await self.stt.initialize()
        await self.tts.initialize()
        self._model_status.update(
            {f"tts::{bid}": dict(payload) for bid, payload in self.tts.get_model_status().items()}
        )

    async def _shutdown_services(self) -> None:
        await self.stt.shutdown()
        await self.tts.shutdown()

    async def _verify_local_asr_model(self) -> None:
        """Verify the local ASR model; auto-download if qwen3_asr is the active backend."""
        path = Path(os.getenv("QWEN3_ASR_MODEL", "models/qwen3-asr-0.6b")).expanduser()
        active_backend = os.getenv("STS_TRANSCRIBE_BACKEND", "macos_native_bridge")
        exists = path.exists() and any(path.iterdir()) if path.exists() else False

        if not exists and active_backend == "qwen3_asr":
            from core.utils.helpers import _HF_ASR_REPO, download_hf_snapshot

            repo_id = os.getenv("QWEN3_ASR_REPO", _HF_ASR_REPO)
            logger.info("Downloading ASR model %s → %s", repo_id, path)
            try:
                await asyncio.get_running_loop().run_in_executor(None, download_hf_snapshot, repo_id, path)
                exists = True
            except Exception as exc:
                logger.warning("ASR model download failed: %s", exc)

        self._model_status["qwen3_asr"] = {"path": str(path), "exists": exists}
        if exists:
            logger.info("Local model verified: qwen3_asr -> %s", path)
        else:
            logger.warning(
                "Local model NOT found: %s (set QWEN3_ASR_MODEL or switch to whisper_api/macos_native_bridge)", path
            )
        observability.log_event("sts_model_verification", agent="sts", meta={"models": dict(self._model_status)})

    def get_model_status(self) -> dict[str, dict[str, Any]]:
        return dict(self._model_status)

    # ── aggregated health ────────────────────────────────────────────────

    async def get_backend_health(self) -> dict[str, Any]:
        summary = {
            "transcription_backends": await self.stt.get_backend_health(),
            "tts_backends": await self.tts.get_backend_health(),
            "defaults": {
                "transcription": self.stt.default_transcription_backend(),
                "tts": self.tts.default_tts_backend(),
            },
        }
        observability.log_event("sts_backend_health", agent="sts", meta=summary)
        return summary

    # ── error handling ───────────────────────────────────────────────────

    def error_payload(
        self,
        exc: Exception,
        *,
        backend: str = "",
        default_code: str = "sts_error",
    ) -> tuple[dict[str, Any], int]:
        if isinstance(exc, STSBackendError):
            return exc.to_payload(), exc.status_code

        payload = {
            "error_code": default_code,
            "error_message": compact_reason(exc),
            "backend": backend,
            "remediation": "Check logs and backend configuration.",
        }
        status_code = 500
        lowered = payload["error_message"].lower()
        if any(tok in lowered for tok in ("connecterror", "connection refused", "all connection attempts failed")):
            payload["error_code"] = "backend_connection_failed"
            payload["remediation"] = (
                "Selected backend is unreachable. Start the local server or switch to a ready backend."
            )
            status_code = 503

        observability.log_event(
            "sts_backend_failure",
            agent="sts",
            status="error",
            message=payload.get("error_message"),
            meta=payload,
        )
        return payload, status_code

    # ── main pipeline ────────────────────────────────────────────────────

    async def process_speech(
        self,
        audio_bytes: bytes,
        *,
        filename: str = "audio.webm",
        stt_backend: str | None = None,
        tts_backend: str | None = None,
        model_name: str | None = None,
        tts_voice: str | None = None,
        orchestrator_fn: Callable[[str], Awaitable[str]] | None = None,
        auto_speak: bool = True,
    ) -> dict[str, Any]:
        stages: dict[str, Any] = {}

        transcribed = await self.stt.transcribe_with_metadata(
            audio_bytes,
            filename=filename,
            backend=stt_backend,
            model_name=model_name,
        )
        transcript = transcribed.text
        stages["asr"] = {"text": transcript, "backend": transcribed.backend, "model": transcribed.model}

        if not transcript.strip():
            return {
                "transcript": "",
                "response": "",
                "tts_mode": None,
                "tts_audio_bytes": None,
                "stages": stages,
                "error": "Empty transcription - no audio content detected.",
            }

        response = ""
        if orchestrator_fn is not None:
            try:
                response = await orchestrator_fn(transcript)
            except Exception as exc:
                logger.error("STS pipeline LLM error: %s", exc)
                response = f"Sorry, something went wrong: {exc}"
        stages["llm"] = {"response": response}

        tts_mode: str | None = None
        tts_audio: bytes | None = None
        if auto_speak and response.strip():
            try:
                tts_mode, tts_audio = await self.tts.speak(response, backend=tts_backend, voice=tts_voice)
            except Exception as exc:
                logger.error("STS pipeline TTS error: %s", exc)
                stages["tts_error"] = str(exc)
            stages["tts"] = {"mode": tts_mode, "backend": tts_backend or self.tts.default_tts_backend()}

        return {
            "transcript": transcript,
            "response": response,
            "tts_mode": tts_mode,
            "tts_audio_bytes": tts_audio,
            "stages": stages,
        }


sts_service = STSService()

__all__ = ["STSService", "sts_service"]
