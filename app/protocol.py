"""
WebSocket message protocol — the standard contract between backend and any frontend.

Any frontend that speaks these message types can plug into the backend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ═════════════════════════════════════════════════════════════════════════════
# Outbound (server → client)
# ═════════════════════════════════════════════════════════════════════════════


class WSMessage(BaseModel):
    """Base WebSocket message."""

    type: str
    timestamp: str = Field(default_factory=_utc_now_iso)
    data: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(WSMessage):
    """Assistant chat message."""

    type: str = "chat_response"


class StatusUpdate(WSMessage):
    """Processing status change (thinking, tool_call, done, error)."""

    type: str = "status"


class ObservabilityEvent(WSMessage):
    """Observability trace event pushed to the frontend."""

    type: str = "observability_event"


class ToolCallEvent(WSMessage):
    """A tool invocation notification."""

    type: str = "tool_call"


class ToolResultEvent(WSMessage):
    """A tool result notification."""

    type: str = "tool_result"


class ErrorEvent(WSMessage):
    """An error notification."""

    type: str = "error"


# ═════════════════════════════════════════════════════════════════════════════
# Inbound (client → server)
# ═════════════════════════════════════════════════════════════════════════════


class InboundMessage(BaseModel):
    """Message received from the frontend."""

    type: str  # "chat", "clear", "sts_audio", etc.
    data: dict[str, Any] = Field(default_factory=dict)


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def chat_response(content: str, agent: str | None = None) -> dict:
    return ChatResponse(data={"content": content, "agent": agent or "orchestrator"}).model_dump()


def status_update(status: str, detail: str = "") -> dict:
    return StatusUpdate(data={"status": status, "detail": detail}).model_dump()


def error_event(message: str, agent: str | None = None) -> dict:
    return ErrorEvent(data={"content": message, "agent": agent}).model_dump()


def tool_call_event(tool: str, args: dict, agent: str = "", trace_id: str = "") -> dict:
    return ToolCallEvent(
        data={
            "content": f"{tool}({args})",
            "tool": tool,
            "args": args,
            "agent": agent,
            "trace_id": trace_id,
        }
    ).model_dump()


def tool_result_event(tool: str, result: str, agent: str = "", trace_id: str = "") -> dict:
    return ToolResultEvent(
        data={
            "content": result,
            "tool": tool,
            "result": result,
            "agent": agent,
            "trace_id": trace_id,
        }
    ).model_dump()


class StepEvent(WSMessage):
    """A step-level feedback event for the chat activity feed."""

    type: str = "step"


def step_event(step_type: str, content: str, agent: str = "", trace_id: str = "") -> dict:
    """Create a step event for the activity feed.

    step_type: iteration | thought | tool_call | tool_result | model | answer | error
    """
    return StepEvent(
        data={
            "step_type": step_type,
            "content": content,
            "agent": agent,
            "trace_id": trace_id,
        }
    ).model_dump()


def observability_event(event: dict) -> dict:
    return ObservabilityEvent(data=event).model_dump()
