"""Isolated worker process for Qwen3-ASR transcription."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _load_model(*, model_name: str, device_map: str, allow_remote: bool) -> Any:
    try:
        from qwen_asr import Qwen3ASRModel
    except Exception as exc:
        raise RuntimeError(
            "qwen-asr is not installed or incompatible. Run `uv sync` and verify qwen_asr imports."
        ) from exc

    local_candidate = Path(model_name).expanduser()
    if not allow_remote and not local_candidate.exists():
        raise RuntimeError(
            f"Qwen3-ASR local model path not found: {local_candidate}. "
            "Set QWEN3_ASR_MODEL to a local folder and download offline assets."
        )

    model_kwargs: dict[str, Any] = {"device_map": device_map}
    if not allow_remote:
        model_kwargs["local_files_only"] = True

    try:
        return Qwen3ASRModel.from_pretrained(model_name, **model_kwargs)
    except Exception as exc:
        message = str(exc).strip()
        lowered = message.lower()
        if not allow_remote and any(
            token in lowered
            for token in (
                "local_files_only",
                "not found in local cache",
                "couldn't find",
                "not a local folder",
                "repository not found",
                "is not a directory",
            )
        ):
            raise RuntimeError(
                f"Qwen3-ASR local model path not found: {local_candidate}. "
                "Download offline assets or set QWEN3_ASR_ALLOW_REMOTE=1."
            ) from exc
        raise RuntimeError(
            f"Qwen3-ASR model load failed for '{model_name}' (device_map={device_map}): {message}"
        ) from exc


def _quick_health(*, model_name: str, allow_remote: bool) -> tuple[bool, str]:
    try:
        import qwen_asr  # noqa: F401
    except Exception as exc:
        return False, f"qwen_asr import error: {exc}"

    if not allow_remote:
        local_candidate = Path(model_name).expanduser()
        if not local_candidate.exists():
            return (
                False,
                f"Qwen3-ASR local model path not found: {local_candidate}. "
                "Download/copy model files there or set QWEN3_ASR_ALLOW_REMOTE=1.",
            )

    return True, "qwen_asr import ok"


def _run_health(*, model_name: str, device_map: str, allow_remote: bool, load_model: bool) -> int:
    ready, reason = _quick_health(model_name=model_name, allow_remote=allow_remote)
    if not ready:
        _emit({"ok": False, "ready": False, "reason": reason})
        return 2

    if not load_model:
        _emit({"ok": True, "ready": True, "reason": reason})
        return 0

    try:
        _load_model(model_name=model_name, device_map=device_map, allow_remote=allow_remote)
    except Exception as exc:
        _emit({"ok": False, "ready": False, "reason": str(exc)})
        return 3

    _emit({"ok": True, "ready": True, "reason": "Qwen3-ASR model loaded."})
    return 0


def _run_transcribe(
    *,
    audio_path: str,
    model_name: str,
    device_map: str,
    allow_remote: bool,
) -> int:
    path = Path(audio_path)
    if not path.exists():
        _emit({"ok": False, "error": f"Audio file not found: {path}"})
        return 4

    try:
        model = _load_model(model_name=model_name, device_map=device_map, allow_remote=allow_remote)
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        return 5

    try:
        results = model.transcribe(audio=str(path))
    except Exception as exc:
        _emit({"ok": False, "error": f"Qwen3-ASR transcription failed: {exc}"})
        return 6

    if not results:
        _emit({"ok": False, "error": "Qwen3-ASR returned no transcription segments."})
        return 7

    first = results[0]
    text = str(getattr(first, "text", "") or "").strip()
    if not text:
        _emit({"ok": False, "error": "Qwen3-ASR returned an empty transcription."})
        return 8

    _emit({"ok": True, "text": text})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated Qwen3-ASR worker")
    parser.add_argument("--mode", choices=["health", "transcribe"], required=True)
    parser.add_argument("--audio-path", default="")
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--load-model", action="store_true")
    args = parser.parse_args()

    if args.mode == "health":
        return _run_health(
            model_name=args.model_name,
            device_map=args.device_map,
            allow_remote=bool(args.allow_remote),
            load_model=bool(args.load_model),
        )

    return _run_transcribe(
        audio_path=args.audio_path,
        model_name=args.model_name,
        device_map=args.device_map,
        allow_remote=bool(args.allow_remote),
    )


if __name__ == "__main__":
    raise SystemExit(main())
