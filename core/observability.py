"""
Lightweight observability — append-only JSONL log with in-memory fan-out.

Usage:
    from core.observability import log_event, trace_scope

    with trace_scope("my_agent", query) as trace_id:
        log_event("step", message="doing work", agent="my_agent", trace_id=trace_id)
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

# ── internal state ───────────────────────────────────────────────────────────

_TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)
_EVENT_SEQ = 0
_LOCK = threading.Lock()
_SINKS: list[Callable[[dict], None]] = []


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _next_seq() -> int:
    global _EVENT_SEQ
    with _LOCK:
        _EVENT_SEQ += 1
        return _EVENT_SEQ


def _ensure_log_path() -> Path:
    path = Path(os.getenv("OBSERVABILITY_LOG_PATH", "data/observability.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _truncate(text: str | None, max_len: int) -> str | None:
    if text is None:
        return None
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[: max(0, max_len - 3)] + "..."


def _sanitize(value: Any, max_len: int) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return _truncate(value, max_len)
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, list):
        return [_sanitize(item, max_len) for item in value]
    if isinstance(value, dict):
        return {str(k): _sanitize(v, max_len) for k, v in value.items()}
    try:
        return _truncate(json.dumps(value, ensure_ascii=False), max_len)
    except Exception:
        return _truncate(str(value), max_len)


def _write_event(event: dict) -> None:
    path = _ensure_log_path()
    line = json.dumps(event, ensure_ascii=False)
    with _LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── public API ───────────────────────────────────────────────────────────────


def register_sink(sink: Callable[[dict], None]) -> None:
    """Register a callback that receives every event dict."""
    if sink not in _SINKS:
        _SINKS.append(sink)


def unregister_sink(sink: Callable[[dict], None]) -> None:
    if sink in _SINKS:
        _SINKS.remove(sink)


def current_trace_id() -> str | None:
    return _TRACE_ID.get()


def new_trace_id() -> str:
    return f"trc_{uuid4().hex}"


def log_event(
    event_type: str,
    message: str | None = None,
    *,
    agent: str | None = None,
    trace_id: str | None = None,
    status: str | None = None,
    meta: dict | None = None,
) -> dict | None:
    """Append an observability event to the JSONL log and fan out to sinks.

    This function **never** raises — observability must not break the app.
    """
    if os.getenv("OBSERVABILITY_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return None

    trace = trace_id or _TRACE_ID.get()
    max_len = int(os.getenv("OBSERVABILITY_MAX_DETAIL", "2000"))

    event: dict[str, Any] = {
        "id": f"evt_{uuid4().hex[:12]}",
        "seq": _next_seq(),
        "ts": _utc_now_iso(),
        "type": event_type,
        "agent": agent,
        "trace_id": trace,
    }
    if message:
        event["message"] = _truncate(message, max_len)
    if status:
        event["status"] = status
    if meta:
        event["meta"] = _sanitize(meta, max_len)

    try:
        _write_event(event)
    except Exception:
        pass

    for sink in list(_SINKS):
        try:
            sink(event)
        except Exception:
            continue

    return event


@contextmanager
def trace_scope(agent: str, query: str | None = None, meta: dict | None = None) -> Iterable[str]:
    """Context manager that creates (or inherits) a trace ID and emits start/end events."""
    existing = _TRACE_ID.get()
    is_root = existing is None
    trace_id = existing or new_trace_id()
    token = _TRACE_ID.set(trace_id) if is_root else None
    start = time.perf_counter()

    log_event(
        "trace_start" if is_root else "agent_start",
        message=query,
        agent=agent,
        trace_id=trace_id,
        meta=meta,
    )

    try:
        yield trace_id
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_event(
            "trace_end" if is_root else "agent_end",
            agent=agent,
            trace_id=trace_id,
            meta={"duration_ms": duration_ms},
        )
        if is_root and token is not None:
            _TRACE_ID.reset(token)


def read_recent_events(limit: int = 200) -> list[dict]:
    """Read the most recent events from the JSONL log file."""
    path = Path(os.getenv("OBSERVABILITY_LOG_PATH", "data/observability.jsonl"))
    if not path.exists():
        return []

    lines: deque[str] = deque(maxlen=max(1, limit))
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line:
                    lines.append(line)
    except Exception:
        return []

    events: list[dict] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events
