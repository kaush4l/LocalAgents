"""Shared utility functions used across the core package."""

from __future__ import annotations

from typing import Any


def compact_reason(value: Any, *, limit: int = 320) -> str:
    """Collapse whitespace and truncate an error/status string."""
    text = str(value or "").strip()
    if not text:
        return "Unknown error."
    collapsed = " ".join(text.split())
    max_len = max(80, int(limit))
    return collapsed if len(collapsed) <= max_len else collapsed[: max_len - 3].rstrip() + "..."
