"""TTS backend base classes and concrete implementations."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import sounddevice as sd
import soundfile as sf
from pydantic import BaseModel, Field, PrivateAttr

from core import observability
from core.speech.sts_models import STSBackendError, SynthesisRequestModel, SynthesisResultModel
from core.utils.helpers import compact_reason as _compact_reason
from core.utils.helpers import download_hf_snapshot as _download_hf_snapshot

logger = logging.getLogger(__name__)


def _resolve_torch_device(preferred: str) -> str:
    value = str(preferred or "auto").strip().lower()
    if value and value != "auto":
        return value
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def _as_mono_float32(audio: Any) -> np.ndarray:
    if audio is None:
        raise RuntimeError("Audio payload is empty.")

    if hasattr(audio, "detach") and hasattr(audio, "cpu"):
        audio = audio.detach().cpu().numpy()

    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 0:
        return np.asarray([float(arr)], dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.shape[0] <= 8 and arr.shape[0] < arr.shape[-1]:
        return np.mean(arr, axis=0, dtype=np.float32)
    return np.mean(arr, axis=-1, dtype=np.float32)


def _coerce_audio_output(output: Any, *, default_sample_rate: int) -> tuple[np.ndarray, int]:
    sample_rate = int(default_sample_rate)
    audio = output

    if isinstance(output, tuple) and len(output) == 2 and isinstance(output[1], (int, float)):
        audio = output[0]
        sample_rate = int(output[1])
    elif isinstance(output, dict):
        for key in ("sample_rate", "sampling_rate", "sr"):
            if key in output and isinstance(output[key], (int, float)):
                sample_rate = int(output[key])
                break
        for key in ("audio", "waveform", "wav"):
            if key in output:
                audio = output[key]
                break

    if isinstance(audio, (bytes, bytearray)):
        decoded, sr = sf.read(io.BytesIO(bytes(audio)), dtype="float32")
        return _as_mono_float32(decoded), int(sr)

    return _as_mono_float32(audio), sample_rate


def _audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    signal = _as_mono_float32(audio)
    if signal.size == 0:
        raise RuntimeError("Generated audio is empty.")
    peak = float(np.max(np.abs(signal))) if signal.size else 0.0
    if peak > 1.0:
        signal = signal / peak
    buf = io.BytesIO()
    sf.write(buf, signal, int(sample_rate), format="WAV")
    return buf.getvalue()


class SpeechSynthesizerBaseModel(BaseModel):
    """Template flow for TTS backends."""

    backend_id: str
    display_label: str = ""

    model_config = {"arbitrary_types_allowed": True}

    async def synthesize(self, request: SynthesisRequestModel | dict[str, Any]) -> SynthesisResultModel:
        req = request if isinstance(request, SynthesisRequestModel) else SynthesisRequestModel.model_validate(request)
        if not req.text.strip():
            raise STSBackendError(
                error_code="text_required",
                error_message="Text is required for synthesis.",
                backend=self.backend_id,
                remediation="Provide non-empty text and retry.",
                status_code=400,
            )

        ready, reason, remediation = await self.preflight_check()
        if not ready:
            raise STSBackendError(
                error_code="backend_not_ready",
                error_message=str(reason or "Selected TTS backend is not ready."),
                backend=self.backend_id,
                remediation=str(remediation or "Check backend configuration."),
                status_code=503,
            )

        t0 = time.perf_counter()
        observability.log_event(
            "tts_start",
            agent="sts",
            meta={"backend": self.backend_id, "text_len": len(req.text)},
        )
        try:
            result = await self._synthesize_impl(req)
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            observability.log_event(
                "tts_end",
                agent="sts",
                meta={
                    "backend": self.backend_id,
                    "duration_ms": elapsed_ms,
                    "mode": result.mode,
                    "has_audio": result.audio_bytes is not None,
                },
            )
            logger.info("TTS %s completed in %dms (mode=%s)", self.backend_id, elapsed_ms, result.mode)
            return result
        except Exception:
            elapsed_ms = round((time.perf_counter() - t0) * 1000)
            observability.log_event(
                "tts_error",
                agent="sts",
                status="error",
                meta={"backend": self.backend_id, "duration_ms": elapsed_ms},
            )
            raise

    async def _synthesize_impl(self, request: SynthesisRequestModel) -> SynthesisResultModel:
        raise NotImplementedError("Synthesizer backend must implement _synthesize_impl().")

    async def preflight_check(self) -> tuple[bool, str, str]:
        return await self.health_check()

    async def health_check(self) -> tuple[bool, str, str]:
        raise NotImplementedError("Synthesizer backend must implement health_check().")


class PlayableSynthesizerBase(SpeechSynthesizerBaseModel):
    """Base class for synthesizers that support real-time audio playback via sounddevice."""

    async def speak(
        self,
        text: str,
        voice: str | None = None,
        blocking: bool = True,
    ) -> None:
        try:
            req = SynthesisRequestModel(text=text, backend=self.backend_id, voice=voice)
            result = await self.synthesize(req)

            if not result.audio_bytes:
                raise STSBackendError(
                    error_code="no_audio_bytes",
                    error_message="Synthesis returned no audio bytes.",
                    backend=self.backend_id,
                    remediation="Verify TTS backend configuration.",
                    status_code=503,
                )

            await asyncio.to_thread(self._play_audio_bytes, result.audio_bytes, blocking)
            logger.info("Playback completed for backend %s", self.backend_id)
        except STSBackendError:
            raise
        except Exception as exc:
            raise STSBackendError(
                error_code="playback_failed",
                error_message=_compact_reason(f"Audio playback failed: {exc}"),
                backend=self.backend_id,
                remediation="Check sounddevice configuration and audio device availability.",
                status_code=503,
            ) from exc

    @staticmethod
    def _play_audio_bytes(audio_bytes: bytes, blocking: bool = True) -> None:
        try:
            data, sample_rate = sf.read(io.BytesIO(audio_bytes))

            if data.ndim == 1:
                data = data.reshape(-1, 1)

            if blocking:
                sd.play(data, samplerate=sample_rate, blocking=True)
            else:
                sd.play(data, samplerate=sample_rate, blocking=False)

            logger.debug("Audio playback started: %d samples at %d Hz", len(data), sample_rate)
        except Exception as exc:
            raise RuntimeError(f"Failed to play audio: {exc}") from exc


class LocalModelSynthesizerBase(SpeechSynthesizerBaseModel):
    """Base class for local HF model-backed synthesizers."""

    repo_id: str
    sample_rate_hz: int = 24_000

    _model: Any = PrivateAttr(default=None)
    _download_dir: Path | None = PrivateAttr(default=None)
    _warmup_lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _snapshot_ready: bool = PrivateAttr(default=False)

    def _model_dirname(self) -> str:
        return self.repo_id.replace("/", "--").replace("\\", "--")

    def _resolve_local_dir(self) -> Path:
        if self._download_dir is None:
            root = Path(os.getenv("TTS_MODELS_DIR", "models/tts")).expanduser()
            self._download_dir = root / self._model_dirname()
        return self._download_dir

    def _load_model_impl(self, local_dir: Path) -> Any:
        raise NotImplementedError("Synthesizer backend must implement _load_model_impl().")

    def _generate_audio_impl(self, request: SynthesisRequestModel) -> tuple[np.ndarray, int]:
        raise NotImplementedError("Synthesizer backend must implement _generate_audio_impl().")

    async def ensure_ready(self) -> Path:
        async with self._warmup_lock:
            local_dir = self._resolve_local_dir()
            if not self._snapshot_ready:
                snapshot_exists = local_dir.exists() and any(local_dir.iterdir())
                if not snapshot_exists:
                    try:
                        await asyncio.to_thread(_download_hf_snapshot, self.repo_id, local_dir)
                    except STSBackendError:
                        raise
                    except Exception as exc:
                        raise STSBackendError(
                            error_code="tts_model_download_failed",
                            error_message=_compact_reason(f"Failed to download TTS model {self.repo_id}: {exc}"),
                            backend=self.backend_id,
                            remediation=f"Ensure network/HF access for {self.repo_id} and retry startup.",
                            status_code=503,
                        ) from exc
                self._snapshot_ready = True
            if self._model is None:
                try:
                    self._model = await asyncio.to_thread(self._load_model_impl, local_dir)
                except STSBackendError:
                    raise
                except Exception as exc:
                    raise STSBackendError(
                        error_code="tts_model_load_failed",
                        error_message=_compact_reason(f"Failed to load TTS model {self.repo_id}: {exc}"),
                        backend=self.backend_id,
                        remediation="Verify torch/qwen-tts compatibility and selected TTS device.",
                        status_code=503,
                    ) from exc
            return local_dir

    async def _synthesize_impl(self, request: SynthesisRequestModel) -> SynthesisResultModel:
        try:
            await self.ensure_ready()
            audio, sample_rate = await asyncio.to_thread(self._generate_audio_impl, request)
            wav = await asyncio.to_thread(_audio_to_wav_bytes, audio, sample_rate)
            return SynthesisResultModel(mode="audio_bytes", backend=self.backend_id, audio_bytes=wav)
        except STSBackendError:
            raise
        except Exception as exc:
            raise STSBackendError(
                error_code="tts_backend_failure",
                error_message=_compact_reason(f"{self.backend_id} synthesis failed: {exc}"),
                backend=self.backend_id,
                remediation="Check model downloads, dependencies, and selected voice.",
                status_code=503,
            ) from exc

    async def health_check(self) -> tuple[bool, str, str]:
        try:
            local_dir = await self.ensure_ready()
            return True, f"Model ready at {local_dir}", "No action required."
        except Exception as exc:
            return (
                False,
                _compact_reason(exc),
                f"Ensure network access and dependencies for {self.repo_id}, then restart.",
            )


class Qwen3TTSSynthesizer(LocalModelSynthesizerBase, PlayableSynthesizerBase):
    backend_id: str = "qwen3_tts"
    display_label: str = "Qwen3-TTS-12Hz-0.6B"
    repo_id: str = Field(default_factory=lambda: os.getenv("TTS_QWEN_REPO", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"))

    default_voice: str = Field(default_factory=lambda: os.getenv("TTS_QWEN_VOICE", "english"))
    _reference_audio_path: Path | None = PrivateAttr(default=None)
    _DEFAULT_REF_DURATION_SECONDS: ClassVar[float] = 2.5

    async def ensure_ready(self) -> Path:
        local_dir = await super().ensure_ready()
        if self._reference_audio_path is None or not self._reference_audio_path.exists():
            self._reference_audio_path = await asyncio.to_thread(self._ensure_reference_audio, local_dir)
        return local_dir

    def _load_model_impl(self, local_dir: Path) -> Any:
        from qwen_tts import Qwen3TTSModel

        _tts_device = os.getenv("TTS_DEVICE", "auto")
        device_map = _tts_device if _tts_device and _tts_device != "auto" else "auto"
        try:
            import torch

            # Use float16 for MPS (Apple Silicon) as it has native hardware support
            dtype = torch.bfloat16 if _resolve_torch_device(_tts_device) in {"cuda", "mps"} else torch.float32
            return Qwen3TTSModel.from_pretrained(
                str(local_dir),
                device_map=device_map,
                torch_dtype=dtype,
            )
        except TypeError:
            return Qwen3TTSModel.from_pretrained(str(local_dir), device_map=device_map)

    def _generate_audio_impl(self, request: SynthesisRequestModel) -> tuple[np.ndarray, int]:
        import torch

        ref_audio = self._reference_audio_path
        if ref_audio is None or not ref_audio.exists():
            ref_audio = self._ensure_reference_audio(self._resolve_local_dir())
            self._reference_audio_path = ref_audio

        ref_audio_input = str(ref_audio)
        voice_candidate_path = Path((request.voice or "").strip()).expanduser()
        if request.voice and voice_candidate_path.exists() and voice_candidate_path.is_file():
            ref_audio_input = str(voice_candidate_path)

        language = "English"
        supported = {
            str(lang).strip().lower()
            for lang in (
                self._model.get_supported_languages() if hasattr(self._model, "get_supported_languages") else []
            )
            if str(lang).strip()
        }
        voice_candidate = (request.voice or self.default_voice or "").strip().lower()
        if voice_candidate in supported:
            language = voice_candidate.title()

        wavs: list[np.ndarray]
        sample_rate: int
        with torch.inference_mode():
            try:
                wavs, sample_rate = self._model.generate_voice_clone(
                    text=request.text,
                    language=language,
                    ref_audio=ref_audio_input,
                    x_vector_only_mode=True,
                )
            except TypeError:
                wavs, sample_rate = self._model.generate_voice_clone(
                    text=request.text,
                    language=language,
                    ref_audio=ref_audio_input,
                    x_vector_only_mode=True,
                )

        if not wavs:
            raise RuntimeError("Qwen3TTSModel returned no audio frames.")
        # Concatenate all streaming chunks into a single waveform
        if len(wavs) == 1:
            audio = _as_mono_float32(wavs[0])
        else:
            audio = np.concatenate([_as_mono_float32(w) for w in wavs])
        return audio, int(sample_rate)

    def _ensure_reference_audio(self, local_dir: Path) -> Path:
        reference_dir = local_dir / "references"
        reference_path = reference_dir / "default_clone.wav"
        if reference_path.exists() and reference_path.stat().st_size > 0:
            return reference_path

        reference_dir.mkdir(parents=True, exist_ok=True)
        try:
            sample_rate = int(self.sample_rate_hz)
            duration = float(self._DEFAULT_REF_DURATION_SECONDS)
            t = np.linspace(0.0, duration, int(sample_rate * duration), endpoint=False, dtype=np.float32)
            carrier = (0.08 * np.sin(2.0 * np.pi * 220.0 * t)) + (0.04 * np.sin(2.0 * np.pi * 440.0 * t))
            envelope = np.minimum(1.0, np.minimum(t / 0.2, (duration - t) / 0.2))
            envelope = np.clip(envelope, 0.0, 1.0).astype(np.float32)
            signal = (carrier * envelope).astype(np.float32)
            sf.write(reference_path, signal, sample_rate, format="WAV")
        except Exception as exc:
            raise STSBackendError(
                error_code="tts_reference_audio_prepare_failed",
                error_message=_compact_reason(f"Failed to prepare local Qwen reference audio: {exc}"),
                backend=self.backend_id,
                remediation="Ensure the TTS models directory is writable, then restart.",
                status_code=503,
            ) from exc

        if reference_path.stat().st_size <= 0:
            raise STSBackendError(
                error_code="tts_reference_audio_invalid",
                error_message="Prepared Qwen reference audio is empty.",
                backend=self.backend_id,
                remediation="Clear the TTS models directory and restart warmup.",
                status_code=503,
            )
        return reference_path


__all__ = [
    "SpeechSynthesizerBaseModel",
    "PlayableSynthesizerBase",
    "LocalModelSynthesizerBase",
    "Qwen3TTSSynthesizer",
]
