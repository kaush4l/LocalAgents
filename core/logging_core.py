"""Core logging bridge.

This module is the only place where stdlib ``logging`` is imported directly.
Non-core modules should use these helpers instead of importing ``logging``.
"""

from __future__ import annotations

import logging
from typing import Any

_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging once for the whole application."""
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format=_FORMAT,
    )


def set_logger_level(name: str, level: str | int) -> None:
    """Set level for a named logger."""
    resolved: int
    if isinstance(level, int):
        resolved = level
    else:
        resolved = getattr(logging, str(level).upper(), logging.INFO)
    logging.getLogger(name).setLevel(resolved)


def _format_message(message: str, args: tuple[Any, ...]) -> str:
    if not args:
        return message
    try:
        return message % args
    except Exception:
        joined = " ".join(str(arg) for arg in args)
        return f"{message} {joined}".strip()


def log_debug(component: str, message: str, *args: Any, meta: dict[str, Any] | None = None) -> None:
    payload = _format_message(message, args)
    if meta:
        payload = f"{payload} | meta={meta}"
    logging.getLogger(component).debug(payload)


def log_info(component: str, message: str, *args: Any, meta: dict[str, Any] | None = None) -> None:
    payload = _format_message(message, args)
    if meta:
        payload = f"{payload} | meta={meta}"
    logging.getLogger(component).info(payload)


def log_warning(component: str, message: str, *args: Any, meta: dict[str, Any] | None = None) -> None:
    payload = _format_message(message, args)
    if meta:
        payload = f"{payload} | meta={meta}"
    logging.getLogger(component).warning(payload)


def log_error(component: str, message: str, *args: Any, meta: dict[str, Any] | None = None) -> None:
    payload = _format_message(message, args)
    if meta:
        payload = f"{payload} | meta={meta}"
    logging.getLogger(component).error(payload)


def log_exception(component: str, message: str, *args: Any, meta: dict[str, Any] | None = None) -> None:
    payload = _format_message(message, args)
    if meta:
        payload = f"{payload} | meta={meta}"
    logging.getLogger(component).exception(payload)
