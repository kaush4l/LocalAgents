"""Base class for subprocess-isolated model workers.

Provides a standard pattern for running Python worker modules in child
processes with JSON-over-stdout communication.  Both Qwen3-ASR and MLX-TTS
workers share this foundation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SubprocessWorker:
    """Run a Python worker module in a child process and parse JSON output.

    Subclasses set ``worker_module`` to the dotted Python module path
    (e.g. ``"experimental.qwen3_asr_worker"``).
    """

    worker_module: str = ""

    def __init__(self, *, worker_module: str = "") -> None:
        if worker_module:
            self.worker_module = worker_module

    def run(self, args: list[str]) -> dict[str, Any]:
        """Execute the worker with *args* and return the parsed JSON payload.

        Raises ``RuntimeError`` on any non-success outcome (nonzero exit,
        signal termination, missing ``ok`` flag, or empty output).
        """
        if not self.worker_module:
            raise RuntimeError("SubprocessWorker.worker_module is not set.")

        cmd = [sys.executable, "-m", self.worker_module, *args]
        result = subprocess.run(
            cmd,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        payload: dict[str, Any] = {}

        if stdout:
            try:
                # Worker may emit logs before the final JSON line.
                payload = json.loads(stdout.splitlines()[-1])
            except Exception:
                payload = {"ok": False, "error": stdout}

        if result.returncode == 0 and payload.get("ok", False):
            return payload

        if result.returncode < 0:
            signal_code = abs(result.returncode)
            raise RuntimeError(f"{self.worker_module} terminated by signal {signal_code}. stderr={stderr or 'n/a'}")

        reason = (
            payload.get("error")
            or payload.get("reason")
            or stderr
            or stdout
            or f"{self.worker_module} failed with exit code {result.returncode}"
        )
        raise RuntimeError(str(reason))
