"""
FastAPI backend — WebSocket-based real-time communication with the orchestrator.

Routes:
    GET  /                — Chat page
    GET  /observability   — Trace viewer
    GET  /sts             — Speech-to-speech page
    WS   /ws              — Bidirectional WebSocket
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import protocol
from app.state import app_state, orchestrator_queue
from channels.websocket_channel import WebSocketChannel
from core import observability
from core.logging_core import configure_logging, log_error, log_info, log_warning
from core.sts import sts_service

# ── logging ──────────────────────────────────────────────────────────────────

configure_logging(os.getenv("LOG_LEVEL", "INFO"))

# ── WebSocket channel (replaces raw dict) ────────────────────────────────────

ws_channel = WebSocketChannel()


async def broadcast_event(
    payload: dict,
    *,
    scope: str | list[str] | None = None,
) -> None:
    """Send a message to connected WebSocket clients via the channel."""
    await ws_channel.broadcast(payload, scope=scope)


# ── lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init agents, queues, sinks. Shutdown: cleanup."""

    # 1. Build orchestrator with all sub-agents
    from agents.orchestrator import build_orchestrator

    build_orchestrator()
    app_state.add_event("system", "Orchestrator built")

    # 2. Start orchestrator queue (now that orchestrator exists)
    orchestrator_queue.start()
    app_state.add_event("system", "Orchestrator queue started")

    # 4. Load existing observability events
    app_state.load_observability_events(observability.read_recent_events(limit=200))

    # Register observability sink to broadcast to WebSocket clients
    loop = asyncio.get_running_loop()

    # Scope constants for _obs_sink broadcasts
    _STEP_PAGES: list[str] = ["chat", "sts"]

    def _obs_sink(event: dict) -> None:
        """Fan-out every observability event into typed WebSocket messages.

        This is the bridge between the core observability layer and
        the real-time frontend.

        • Raw observability events → observability page only.
        • Step-level feedback      → chat + sts pages only.
        • The "answer" step is NOT emitted here because the chat
          handler already sends a scoped ``chat_response``.
        """
        try:
            # 1. Forward raw observability event (Traces page only)
            loop.call_soon_threadsafe(
                asyncio.create_task,
                broadcast_event(
                    protocol.observability_event(event),
                    scope="observability",
                ),
            )

            etype = event.get("type", "")
            meta = event.get("meta") or {}
            agent_name = event.get("agent", "")
            trace_id = event.get("trace_id", "")
            tool_name = str(meta.get("tool") or "")
            message = event.get("message", "")
            iteration = meta.get("iteration", "")

            # 2. Step-level feedback for chat + sts activity panels
            step: dict | None = None

            if etype == "iteration_start":
                step = protocol.step_event(
                    "iteration",
                    f"Iteration {iteration} — {agent_name}",
                    agent_name,
                    trace_id,
                )

            elif etype == "thought":
                step = protocol.step_event(
                    "thought",
                    message,
                    agent_name,
                    trace_id,
                )

            elif etype == "tool_start" and tool_name:
                step = protocol.step_event(
                    "tool_call",
                    f"{tool_name}({json.dumps(meta.get('inputs', {}))})",
                    agent_name,
                    trace_id,
                )

            elif etype == "tool_end":
                step = protocol.step_event(
                    "tool_result",
                    f"{tool_name}: {message[:300]}",
                    agent_name,
                    trace_id,
                )

            elif etype == "tool_error":
                err = meta.get("error") or message or "Tool error"
                step = protocol.step_event(
                    "error",
                    f"{tool_name}: {err}" if tool_name else str(err),
                    agent_name,
                    trace_id,
                )

            elif etype == "model_end":
                action = meta.get("action", "")
                dur = meta.get("duration_ms", "")
                step = protocol.step_event(
                    "model",
                    f"Model → {action} ({dur}ms)",
                    agent_name,
                    trace_id,
                )

            elif etype == "answer":
                # Only push the orchestrator's final answer as an activity step.
                # Sub-agent answers are intermediate results and would cause
                # duplicate "answer" steps in the activity panel.
                if agent_name != "orchestrator":
                    return
                step = protocol.step_event(
                    "answer",
                    message,
                    agent_name,
                    trace_id,
                )
                loop.call_soon_threadsafe(
                    asyncio.create_task,
                    broadcast_event(step, scope="chat"),
                )
                return

            if step is not None:
                loop.call_soon_threadsafe(
                    asyncio.create_task,
                    broadcast_event(step, scope=_STEP_PAGES),
                )

        except Exception:
            pass

    observability.register_sink(_obs_sink)
    observability.log_event("system", message="server_start", agent="server")
    app_state.add_event("system", "Server ready")

    # 5. Start Telegram channel (non-fatal; requires TELEGRAM_BOT_TOKEN)
    telegram_ch = None
    try:
        from channels.telegram_channel import TelegramChannel

        telegram_ch = TelegramChannel()
        await telegram_ch.connect()
        if telegram_ch.is_connected:
            app_state.add_event("system", "Telegram channel connected")
    except Exception as e:
        log_warning(__name__, "Telegram channel init skipped: %s", e)

    # 6. Init STS service (required; warms/downloads TTS models at startup)
    try:
        await sts_service.initialize()
        app_state.add_event("system", "STS service initialized")
    except Exception as e:
        log_error(__name__, "STS service init failed: %s", e)
        raise

    try:
        yield
    finally:
        log_info(__name__, "Shutting down...")
        observability.log_event("system", message="server_shutdown", agent="server")
        observability.unregister_sink(_obs_sink)

        # Shutdown channels
        if telegram_ch:
            try:
                await telegram_ch.disconnect()
            except Exception as e:
                log_warning(__name__, "Telegram channel shutdown error: %s", e)

        try:
            await sts_service.shutdown()
        except Exception as e:
            log_warning(__name__, "STS shutdown error: %s", e)

        await orchestrator_queue.stop()

        # Close all WebSocket connections via channel
        await ws_channel.disconnect()


# ── app ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="LocalAgents", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & templates
_app_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_app_dir / "static")), name="static")
templates = Jinja2Templates(directory=str(_app_dir / "templates"))


# ── page routes ──────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.j2",
        {"state": app_state.get_full_state()},
    )


@app.get("/observability", response_class=HTMLResponse)
async def observability_page(request: Request):
    return templates.TemplateResponse(
        request,
        "observability.j2",
        {"state": app_state.get_full_state()},
    )


@app.get("/sts", response_class=HTMLResponse)
async def sts_page(request: Request):
    # Gather backend options for dynamic dropdowns
    stt_backends = []
    tts_backends = []
    try:
        stt_backends = sts_service.stt.list_transcription_backends()
        tts_backends = sts_service.tts.list_tts_backends()
        # Seed active backends if not yet set
        if not app_state.active_stt_backend:
            app_state.active_stt_backend = sts_service.stt.default_transcription_backend()
        if not app_state.active_tts_backend:
            app_state.active_tts_backend = sts_service.tts.default_tts_backend()
    except Exception:
        pass

    return templates.TemplateResponse(
        request,
        "sts.j2",
        {
            "state": app_state.get_full_state(),
            "stt_backends": stt_backends,
            "tts_backends": tts_backends,
        },
    )


@app.get("/self", response_class=HTMLResponse)
async def self_page(request: Request):
    return templates.TemplateResponse(
        request,
        "self.j2",
        {"state": app_state.get_full_state()},
    )


# ── API routes ───────────────────────────────────────────────────────────────


@app.get("/api/state")
async def get_state():
    return app_state.get_full_state()


@app.post("/api/clear")
async def clear_chat():
    app_state.clear_messages()
    return {"status": "ok"}


@app.post("/api/speak")
async def speak_text(request: Request):
    """Invoke the configured TTS backend to speak text.

    Body: { "text": "...", "backend": "qwen3_tts" | null }
    Returns: { "ok": true, "mode": "audio_bytes" } or raw ``audio/wav``.
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "No text provided."}

    backend_id = body.get("backend") or app_state.active_tts_backend or None
    try:
        mode, audio_bytes = await sts_service.tts.speak(text, backend=backend_id)
        if mode == "audio_bytes" and audio_bytes:
            from fastapi.responses import Response

            return Response(content=audio_bytes, media_type="audio/wav")
        return {"ok": True, "mode": mode}
    except Exception as e:
        log_error(__name__, "TTS speak error: %s", e)
        from fastapi.responses import JSONResponse

        payload, status_code = sts_service.error_payload(
            e,
            backend=str(backend_id or ""),
            default_code="tts_speak_failed",
        )
        return JSONResponse(content=payload, status_code=status_code)


# ── Self-page API ─────────────────────────────────────────────────────────────


@app.get("/api/self/state")
async def get_self_state_route():
    return app_state.get_self_state()


@app.post("/api/self/habits")
async def create_habit_route(request: Request):
    from fastapi.responses import JSONResponse as _JSONResponse

    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return _JSONResponse({"ok": False, "error": "name is required"}, status_code=422)
    habit = app_state.add_habit(name)
    await broadcast_event(
        {
            "type": "self_state_update",
            "timestamp": protocol._utc_now_iso(),
            "data": app_state.get_self_state(),
        },
        scope="self",
    )
    return {"ok": True, "habit": habit}


@app.delete("/api/self/habits/{habit_id}")
async def delete_habit_route(habit_id: str):
    from fastapi.responses import JSONResponse as _JSONResponse

    removed = app_state.remove_habit(habit_id=habit_id)
    if not removed:
        return _JSONResponse({"ok": False, "error": "habit not found"}, status_code=404)
    await broadcast_event(
        {
            "type": "self_state_update",
            "timestamp": protocol._utc_now_iso(),
            "data": app_state.get_self_state(),
        },
        scope="self",
    )
    return {"ok": True}


@app.post("/api/self/habits/{habit_id}/check")
async def check_habit_route(habit_id: str, request: Request):
    from fastapi.responses import JSONResponse as _JSONResponse

    body = await request.json()
    done_raw = body.get("done", True)
    done = done_raw if isinstance(done_raw, bool) else str(done_raw).lower() not in ("false", "0", "no")
    date = (body.get("date") or "").strip() or None
    success = app_state.check_habit(habit_id=habit_id, date=date, done=done)
    if not success:
        return _JSONResponse({"ok": False, "error": "habit not found"}, status_code=404)
    await broadcast_event(
        {
            "type": "self_state_update",
            "timestamp": protocol._utc_now_iso(),
            "data": app_state.get_self_state(),
        },
        scope="self",
    )
    return {"ok": True}


# ── WebSocket ────────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Determine page scope from query parameter
    page_scope = ws.query_params.get("page", "chat")
    seen_request_ids: set[str] = set()
    last_accepted_chat_text: str = ""
    last_accepted_chat_at: float = 0.0
    await ws_channel.connect(ws, scope=page_scope)

    # Send current state on connect
    try:
        await ws_channel.send(
            {
                "type": "state_sync",
                "timestamp": protocol._utc_now_iso(),
                "data": app_state.get_full_state(),
            },
            ws=ws,
        )
    except Exception:
        pass

    try:
        while True:
            raw = await ws_channel.receive_text(ws)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws_channel.send(protocol.error_event("Invalid JSON"), ws=ws)
                continue

            msg_type = msg.get("type", "")
            data = msg.get("data", {})

            if msg_type == "chat":
                text = data.get("content", "").strip()
                if not text:
                    continue
                request_id = str(data.get("request_id") or "").strip()
                if request_id:
                    if request_id in seen_request_ids:
                        continue
                    seen_request_ids.add(request_id)
                    # Keep the set bounded for long-lived sessions.
                    if len(seen_request_ids) > 1024:
                        seen_request_ids.clear()
                        seen_request_ids.add(request_id)
                else:
                    now = time.monotonic()
                    if text == last_accepted_chat_text and (now - last_accepted_chat_at) < 1.0:
                        continue
                    last_accepted_chat_text = text
                    last_accepted_chat_at = now

                app_state.is_processing = True
                app_state.current_query = text
                app_state.add_message("user", text)

                # Determine broadcast scope from message source
                msg_source = data.get("source", "text")
                if msg_source == "voice":
                    chat_scope = "sts"
                elif msg_source == "self_voice":
                    chat_scope = "self"
                else:
                    chat_scope = page_scope

                # Notify relevant clients that processing started
                await broadcast_event(
                    protocol.status_update("thinking", text),
                    scope=["chat", "sts", "self"],
                )

                try:
                    result = await orchestrator_queue.submit(text)
                    answer = orchestrator_queue.extract_response(result)
                    app_state.add_message("assistant", answer)
                    await broadcast_event(protocol.chat_response(answer), scope=chat_scope)
                    # After a self-voice command the agent may have mutated habits/checkins;
                    # push a fresh state snapshot so the self page can re-render.
                    if chat_scope == "self":
                        await broadcast_event(
                            {
                                "type": "self_state_update",
                                "timestamp": protocol._utc_now_iso(),
                                "data": app_state.get_self_state(),
                            },
                            scope="self",
                        )
                except Exception as e:
                    error_msg = f"Error: {e}"
                    app_state.add_message("assistant", error_msg)
                    await broadcast_event(protocol.error_event(error_msg), scope=["chat", "sts"])
                finally:
                    app_state.is_processing = False
                    app_state.current_query = ""
                    await broadcast_event(
                        protocol.status_update("done"),
                        scope=["chat", "sts", "self"],
                    )

            elif msg_type == "clear":
                app_state.clear_messages()
                await broadcast_event(protocol.status_update("cleared"))

            elif msg_type == "toggle_theme":
                new_theme = app_state.toggle_theme()
                await broadcast_event(
                    {
                        "type": "theme_change",
                        "timestamp": protocol._utc_now_iso(),
                        "data": {"theme": new_theme.value},
                    }
                )

            elif msg_type == "switch_backend":
                # Hot-reload STT / TTS backend selection
                stage = data.get("stage", "")  # "stt" or "tts"
                backend_id = data.get("backend", "").strip()
                if stage == "stt" and backend_id:
                    app_state.active_stt_backend = backend_id
                    app_state.add_event("system", f"STT backend → {backend_id}")
                    observability.log_event(
                        "backend_switch",
                        agent="sts",
                        meta={"stage": "stt", "backend": backend_id},
                    )
                    await broadcast_event(
                        {
                            "type": "backend_changed",
                            "timestamp": protocol._utc_now_iso(),
                            "data": {"stage": "stt", "backend": backend_id},
                        },
                        scope="sts",
                    )
                elif stage == "tts" and backend_id:
                    app_state.active_tts_backend = backend_id
                    app_state.add_event("system", f"TTS backend → {backend_id}")
                    observability.log_event(
                        "backend_switch",
                        agent="sts",
                        meta={"stage": "tts", "backend": backend_id},
                    )
                    await broadcast_event(
                        {
                            "type": "backend_changed",
                            "timestamp": protocol._utc_now_iso(),
                            "data": {"stage": "tts", "backend": backend_id},
                        },
                        scope="sts",
                    )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log_error(__name__, "WebSocket error: %s", e)
    finally:
        await ws_channel.disconnect(ws)
