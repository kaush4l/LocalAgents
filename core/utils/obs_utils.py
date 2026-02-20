"""
Observability utilities — read and analyze JSONL trace logs.

Usage from Python::

    from core.obs_utils import list_traces, show_trace, stats, tail

Or from CLI::

    uv run python obs.py traces
    uv run python obs.py trace <trace_id>
    uv run python obs.py stats
    uv run python obs.py tail 20
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _load_events(path: Path | None = None) -> list[dict]:
    """Load all events from the JSONL log."""
    p = path or Path(os.getenv("OBSERVABILITY_LOG_PATH", "data/observability.jsonl"))
    if not p.exists():
        return []
    events: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


# ── traces ───────────────────────────────────────────────────────────────────


def list_traces(path: Path | None = None) -> list[dict[str, Any]]:
    """Group events by trace_id and return summary per trace.

    Returns list of dicts:
        trace_id, agent, event_count, duration_ms, started, types
    """
    events = _load_events(path)
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        tid = e.get("trace_id")
        if tid:
            by_trace[tid].append(e)

    summaries: list[dict[str, Any]] = []
    for tid, tevents in by_trace.items():
        tevents.sort(key=lambda e: e.get("seq", 0))
        agents = {e.get("agent") for e in tevents if e.get("agent")}
        types = Counter(e.get("type", "?") for e in tevents)
        # Duration from first to last event
        duration_ms = None
        for e in tevents:
            meta = e.get("meta") or {}
            if "duration_ms" in meta and e.get("type") in ("trace_end", "agent_end"):
                duration_ms = meta["duration_ms"]
                break

        summaries.append(
            {
                "trace_id": tid,
                "agents": sorted(agents - {None}),
                "event_count": len(tevents),
                "duration_ms": duration_ms,
                "started": tevents[0].get("ts", ""),
                "types": dict(types),
            }
        )
    return summaries


def show_trace(trace_id: str, path: Path | None = None) -> list[dict]:
    """Return the ordered sequence of events for a specific trace."""
    events = _load_events(path)
    matched = [e for e in events if e.get("trace_id") == trace_id]
    matched.sort(key=lambda e: e.get("seq", 0))
    return matched


# ── stats ────────────────────────────────────────────────────────────────────


def stats(path: Path | None = None) -> dict[str, Any]:
    """Aggregate statistics: counts by type, agents, avg durations, errors."""
    events = _load_events(path)
    type_counts = Counter(e.get("type", "?") for e in events)
    agent_counts = Counter(e.get("agent", "?") for e in events)

    # Duration stats for tool calls
    tool_durations: list[int] = []
    model_durations: list[int] = []
    error_count = 0

    for e in events:
        meta = e.get("meta") or {}
        etype = e.get("type", "")
        dur = meta.get("duration_ms")

        if etype == "tool_end" and dur is not None:
            tool_durations.append(dur)
        elif etype == "model_end" and dur is not None:
            model_durations.append(dur)
        elif etype in ("error", "tool_error"):
            error_count += 1

    def _avg(lst: list[int]) -> float:
        return round(sum(lst) / len(lst), 1) if lst else 0

    return {
        "total_events": len(events),
        "by_type": dict(type_counts.most_common()),
        "by_agent": dict(agent_counts.most_common()),
        "tool_calls": len(tool_durations),
        "tool_avg_ms": _avg(tool_durations),
        "tool_p95_ms": sorted(tool_durations)[int(len(tool_durations) * 0.95)] if tool_durations else 0,
        "model_calls": len(model_durations),
        "model_avg_ms": _avg(model_durations),
        "errors": error_count,
    }


# ── tail ─────────────────────────────────────────────────────────────────────


def tail(n: int = 20, path: Path | None = None) -> list[dict]:
    """Return the last N events."""
    events = _load_events(path)
    return events[-n:] if len(events) > n else events


# ── formatting ───────────────────────────────────────────────────────────────


def format_event(e: dict) -> str:
    """Pretty-format a single event for terminal output."""
    ts = e.get("ts", "")[:19]
    seq = e.get("seq", "?")
    etype = e.get("type", "?")
    agent = e.get("agent", "")
    msg = e.get("message", "")
    meta = e.get("meta") or {}

    parts = [f"[{seq:>4}] {ts} {etype:<16} {agent:<20}"]
    if msg:
        parts.append(f"  {msg[:120]}")
    if meta:
        compact = {k: v for k, v in meta.items() if k not in ("tool",)}
        if compact:
            parts.append(f"  meta: {json.dumps(compact, ensure_ascii=False)[:200]}")
    return "\n".join(parts)


def format_trace_summary(s: dict) -> str:
    """Pretty-format a trace summary for terminal output."""
    agents = ", ".join(s["agents"]) or "?"
    dur = f"{s['duration_ms']}ms" if s["duration_ms"] is not None else "?"
    return (
        f"  {s['trace_id'][:20]}…  "
        f"events={s['event_count']:<4}  "
        f"duration={dur:<8}  "
        f"agents={agents}  "
        f"started={s['started'][:19]}"
    )
