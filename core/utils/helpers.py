"""Shared utility functions used across the core package."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_HF_ASR_REPO = "Qwen/Qwen3-ASR-0.6B"


def download_hf_snapshot(repo_id: str, local_dir: Path) -> None:
    """Download a HuggingFace model snapshot into *local_dir* if not already present.

    Uses ``huggingface_hub.snapshot_download`` so the call is idempotent —
    already-cached files are not re-fetched.
    """
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    from huggingface_hub import snapshot_download

    local_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo_id, local_dir=str(local_dir))


def compact_reason(value: Any, *, limit: int = 320) -> str:
    """Collapse whitespace and truncate an error/status string."""
    text = str(value or "").strip()
    if not text:
        return "Unknown error."
    collapsed = " ".join(text.split())
    max_len = max(80, int(limit))
    return collapsed if len(collapsed) <= max_len else collapsed[: max_len - 3].rstrip() + "..."
