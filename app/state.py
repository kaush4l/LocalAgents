"""
Application state — single Pydantic model for the whole running app.

Import the global singleton:
    from app.state import app_state
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.responses import Message

# ═════════════════════════════════════════════════════════════════════════════
# Supporting models
# ═════════════════════════════════════════════════════════════════════════════


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


class Event(BaseModel):
    id: int
    type: str
    timestamp: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump()


class ObsEvent(BaseModel):
    id: str
    type: str
    timestamp: str
    agent: str | None = None
    trace_id: str | None = None
    status: str | None = None
    message: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump()


# ═════════════════════════════════════════════════════════════════════════════
# AppState
# ═════════════════════════════════════════════════════════════════════════════


class AppState(BaseModel):
    """Global application state — the single source of truth."""

    theme: ThemeMode = ThemeMode.DARK
    sidebar_open: bool = True
    events_panel_open: bool = True

    events: list[Event] = Field(default_factory=list)
    observability_events: list[ObsEvent] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)

    is_processing: bool = False
    current_query: str = ""

    # ── Active STS backend selections (hot-reloadable) ───────────────
    active_stt_backend: str = ""
    active_tts_backend: str = ""

    # ── Self page state (server-authoritative) ───────────────────────
    habits: list[dict] = Field(default_factory=list)
    # checkins: {"YYYY-MM-DD": {"habit_id": True/False}}
    checkins: dict[str, dict] = Field(default_factory=dict)

    _next_event_id: int = 1
    _next_obs_id: int = 1

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _utc_now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # ── events ───────────────────────────────────────────────────────────

    def add_event(self, event_type: str, content: str, metadata: dict | None = None) -> Event:
        event = Event(
            id=self._next_event_id,
            type=event_type,
            timestamp=self._utc_now(),
            content=content,
            metadata=metadata or {},
        )
        self._next_event_id += 1
        self.events.append(event)
        if len(self.events) > 100:
            self.events = self.events[-100:]
        return event

    # ── messages ─────────────────────────────────────────────────────────

    def add_message(self, role: str, content: str, agent: str | None = None) -> Message:
        if agent and role == "assistant":
            self.add_event("log", f"Assistant message from {agent}", {"agent": agent})
        msg = Message(role=role, content=content)
        self.messages.append(msg)
        return msg

    def clear_messages(self) -> None:
        self.messages = []
        self.add_event("system", "Chat history cleared")

    # ── observability ────────────────────────────────────────────────────

    def add_observability_event(self, event: dict) -> ObsEvent:
        obs = ObsEvent(
            id=str(event.get("id", f"obs_{self._next_obs_id}")),
            type=str(event.get("type", "log")),
            timestamp=str(event.get("ts") or event.get("timestamp") or self._utc_now()),
            agent=event.get("agent"),
            trace_id=event.get("trace_id"),
            status=event.get("status"),
            message=event.get("message"),
            meta=event.get("meta") or {},
        )
        if event.get("id") is None:
            self._next_obs_id += 1
        self.observability_events.append(obs)
        if len(self.observability_events) > 300:
            self.observability_events = self.observability_events[-300:]
        return obs

    def load_observability_events(self, events: list[dict]) -> None:
        self.observability_events = []
        for event in events:
            try:
                self.add_observability_event(event)
            except Exception:
                continue

    # ── theme ────────────────────────────────────────────────────────────

    def toggle_theme(self) -> ThemeMode:
        self.theme = ThemeMode.LIGHT if self.theme == ThemeMode.DARK else ThemeMode.DARK
        return self.theme

    # ── habits ───────────────────────────────────────────────────────────

    def add_habit(self, name: str) -> dict:
        habit: dict = {
            "id": f"h_{int(datetime.now(timezone.utc).timestamp() * 1000)}",
            "name": name.strip(),
            "created_at": self._utc_now(),
        }
        self.habits.append(habit)
        return habit

    def remove_habit(self, habit_id: str | None = None, name: str | None = None) -> bool:
        before = len(self.habits)
        if habit_id:
            self.habits = [h for h in self.habits if h.get("id") != habit_id]
            for dk in self.checkins:
                self.checkins[dk].pop(habit_id, None)
        elif name:
            lower = name.strip().lower()
            remove_ids = {h["id"] for h in self.habits if h.get("name", "").strip().lower() == lower}
            self.habits = [h for h in self.habits if h["id"] not in remove_ids]
            for dk in self.checkins:
                for rid in remove_ids:
                    self.checkins[dk].pop(rid, None)
        return len(self.habits) < before

    def check_habit(
        self,
        habit_id: str | None = None,
        name: str | None = None,
        date: str | None = None,
        done: bool = True,
    ) -> bool:
        if not habit_id and name:
            lower = name.strip().lower()
            matched = [h for h in self.habits if h.get("name", "").strip().lower() == lower]
            if not matched:
                return False
            habit_id = matched[0]["id"]
        if not habit_id:
            return False
        dk = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if dk not in self.checkins:
            self.checkins[dk] = {}
        self.checkins[dk][habit_id] = done
        return True

    def get_self_state(self) -> dict:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return {
            "habits": self.habits,
            "checkins": self.checkins,
            "today": today,
            "today_checks": self.checkins.get(today, {}),
        }

    # ── snapshot ──────────────────────────────────────────────────────────

    def get_full_state(self) -> dict:
        return {
            "theme": self.theme.value,
            "sidebar_open": self.sidebar_open,
            "events_panel_open": self.events_panel_open,
            "events": [e.to_dict() for e in self.events[-50:]],
            "observability_events": [e.to_dict() for e in self.observability_events[-200:]],
            "messages": [m.model_dump() for m in self.messages],
            "is_processing": self.is_processing,
            "current_query": self.current_query,
            "active_stt_backend": self.active_stt_backend,
            "active_tts_backend": self.active_tts_backend,
            "self": self.get_self_state(),
        }


# ═════════════════════════════════════════════════════════════════════════════
# Orchestrator Queue
# ═════════════════════════════════════════════════════════════════════════════


class OrchestratorRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    text: str
    future: asyncio.Future
    metadata: dict = Field(default_factory=dict)


class OrchestratorQueue:
    """Serialized queue for orchestrator requests."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[OrchestratorRequest] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def submit(self, text: str, metadata: dict | None = None) -> object:
        if not text:
            raise ValueError("text is required")
        if not self._worker_task:
            self.start()
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(OrchestratorRequest(text=text, future=future, metadata=metadata or {}))
        return await future

    def submit_threadsafe(
        self,
        text: str,
        metadata: dict | None = None,
        *,
        history: list | None = None,
    ) -> Any:
        """Schedule a submission from a non-async thread (e.g. telegram).

        Returns a ``concurrent.futures.Future`` that resolves to the
        orchestrator result.
        """
        import concurrent.futures

        result_future: concurrent.futures.Future = concurrent.futures.Future()

        async def _submit() -> None:
            try:
                res = await self.submit(text, metadata)
                result_future.set_result(res)
            except Exception as exc:
                result_future.set_exception(exc)

        loop = self._worker_task._loop if self._worker_task else None  # type: ignore[union-attr]
        if loop is None:
            import asyncio

            loop = asyncio.get_event_loop()
        loop.call_soon_threadsafe(lambda: loop.create_task(_submit()))
        return result_future

    @staticmethod
    def extract_response(result: object) -> str:
        """Extract the best human-readable text from a ReActResponse.

        Falls back through response → thinking → observation → str(result).
        """
        response = getattr(result, "response", None)
        if isinstance(response, list):
            text = "\n".join(str(item) for item in response if item is not None).strip()
        elif response is not None:
            text = str(response).strip()
        else:
            text = ""

        # Fallback: TOON parser sometimes puts the answer in thinking/observation
        if not text:
            for fallback in ("thinking", "observation"):
                val = getattr(result, fallback, None)
                if val and str(val).strip():
                    text = str(val).strip()
                    break

        return text if text else str(result)

    async def _worker_loop(self) -> None:
        from workflows.general.orchestrator import orchestrator

        while True:
            request = await self._queue.get()
            try:
                if orchestrator is None:
                    raise RuntimeError("Orchestrator not initialized — call build_orchestrator() first")
                result = await orchestrator.invoke(request.text)
                if not request.future.done():
                    request.future.set_result(result)
            except Exception as exc:
                if not request.future.done():
                    request.future.set_exception(exc)
            finally:
                self._queue.task_done()


# ── global singletons ───────────────────────────────────────────────────────

app_state = AppState()
orchestrator_queue = OrchestratorQueue()
