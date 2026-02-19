"""Telegram module: polling adapter for orchestrator queue."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
from collections import deque
from pathlib import Path
from typing import Any

from pydantic import PrivateAttr
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from app.state import app_state, orchestrator_queue
from core.engine import RuntimeObject
from core.logging_core import log_debug, log_exception, log_info, log_warning, set_logger_level
from core.responses import Message, ReActResponse

# Silence verbose libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


_TYPING_INTERVAL_SECONDS = 4
_LOG_DIR_NAME = "bot logs"
_HISTORY_TURNS = 20


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sanitize_filename(value: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return sanitized.strip("_") or "user"


def _log_dir() -> Path:
    base = _project_root() / _LOG_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _log_path(chat_id: int, username: str | None) -> Path:
    base = _log_dir()
    preferred = base / f"{_sanitize_filename(username or '')}_{chat_id}.jsonl"
    if preferred.exists():
        return preferred

    matches = sorted(base.glob(f"*_{chat_id}.jsonl"))
    if matches:
        return matches[0]

    return preferred


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_response(value: object) -> str:
    raw = _normalize_text(value)
    if not raw:
        return ""

    looks_like_structured = False
    if raw.lstrip().startswith("{") and '"response"' in raw:
        looks_like_structured = True
    if any(marker in raw for marker in ("\nobservation:", "\nthinking:", "\nplan:", "\naction:", "\nresponse:")):
        looks_like_structured = True
    if raw.startswith(("observation:", "thinking:", "plan:", "action:", "response:")):
        looks_like_structured = True

    cleaned = raw
    if looks_like_structured:
        parsed = ReActResponse.from_raw(raw)
        response = parsed.response
        if isinstance(response, list):
            cleaned = "\n".join(str(item) for item in response if item is not None).strip()
        else:
            cleaned = str(response).strip()

    cleaned = ReActResponse._strip_wrapping_quotes(cleaned).strip()
    return cleaned


def _append_log(chat_id: int, username: str | None, query: str, response: str) -> None:
    payload = {"query": query, "response": response}
    path = _log_path(chat_id, username)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _extract_turn(payload: dict) -> tuple[str, str] | None:
    query = _normalize_text(payload.get("query") or payload.get("question"))
    response = _normalize_response(payload.get("response") or payload.get("answer"))
    if not query or not response:
        return None
    return query, response


def _rewrite_log(path: Path, turns: list[tuple[str, str]]) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for query, response in turns:
            handle.write(json.dumps({"query": query, "response": response}, ensure_ascii=False) + "\n")
    tmp_path.replace(path)


def _seed_chat_log_if_missing(chat_id: int, username: str | None) -> None:
    chat_log = _log_path(chat_id, username)
    if chat_log.exists() or not username:
        return

    legacy = _log_dir() / f"{_sanitize_filename(username)}.jsonl"
    if not legacy.exists():
        return

    turns: list[tuple[str, str]] = []
    try:
        with legacy.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                turn = _extract_turn(payload) if isinstance(payload, dict) else None
                if turn:
                    turns.append(turn)
    except Exception as exc:
        log_debug(__name__, "Failed to seed Telegram history from legacy log %s: %s", legacy, exc)
        return

    if turns:
        with contextlib.suppress(Exception):
            _rewrite_log(chat_log, turns)
        with contextlib.suppress(Exception):
            _rewrite_log(legacy, turns)


def _load_history(chat_id: int, username: str | None, limit_turns: int = _HISTORY_TURNS) -> list[Message]:
    _seed_chat_log_if_missing(chat_id, username)
    path = _log_path(chat_id, username)
    if not path.exists():
        return []

    turns: deque[tuple[str, str]] = deque(maxlen=max(0, limit_turns))
    all_turns: list[tuple[str, str]] = []
    needs_compaction = False

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(payload, dict):
                    continue

                turn = _extract_turn(payload)
                if not turn:
                    continue

                all_turns.append(turn)
                turns.append(turn)

                if set(payload.keys()) != {"query", "response"}:
                    needs_compaction = True
    except Exception as exc:
        log_debug(__name__, "Failed to read Telegram history for chat_id=%s: %s", chat_id, exc)
        return []

    if needs_compaction and all_turns:
        with contextlib.suppress(Exception):
            _rewrite_log(path, all_turns)

    history: list[Message] = []
    for query, response in turns:
        history.append(Message(role="user", content=query))
        history.append(Message(role="assistant", content=response))
    return history


class TelegramModule(RuntimeObject):
    """Telegram polling integration module."""

    name: str = "telegram_module"

    _thread: threading.Thread | None = PrivateAttr(default=None)
    _loop: asyncio.AbstractEventLoop | None = PrivateAttr(default=None)
    _stop_event: asyncio.Event | None = PrivateAttr(default=None)
    _chat_locks: dict[int, asyncio.Lock] = PrivateAttr(default_factory=dict)
    _application: Any = PrivateAttr(default=None)
    _last_chat_id: int | None = PrivateAttr(default=None)

    def _get_chat_lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
        return lock

    def _initialize_impl(self) -> None:
        if not os.getenv("TELEGRAM_BOT_TOKEN", ""):
            log_info(__name__, "TELEGRAM_BOT_TOKEN not set; Telegram module disabled.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="telegram-module", daemon=True)
        self._thread.start()

    def _shutdown_impl(self) -> Any:
        return self._shutdown_async()

    async def _shutdown_async(self) -> None:
        if not self._thread:
            return
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        thread = self._thread
        await asyncio.to_thread(thread.join)
        self._thread = None

    def _run(self) -> None:
        set_logger_level("telegram", "WARNING")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        application = ApplicationBuilder().token(os.getenv("TELEGRAM_BOT_TOKEN", "")).build()
        self._application = application
        application.add_handler(MessageHandler(filters.TEXT, self._handle_message, block=False))
        application.add_error_handler(self._error_handler)

        try:
            self._loop.run_until_complete(self._runner(application))
        finally:
            self._loop.close()

    async def _runner(self, application) -> None:
        await application.initialize()
        try:
            await application.bot.delete_webhook(drop_pending_updates=True)
            log_debug(__name__, "Telegram webhook cleared; polling enabled.")
        except Exception as exc:
            log_warning(__name__, "Failed to clear Telegram webhook: %s", exc)

        await application.start()
        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )

        try:
            me = await application.bot.get_me()
            log_debug(__name__, "Telegram bot connected as @%s (id=%s)", me.username, me.id)
        except Exception as exc:
            log_warning(__name__, "Telegram getMe failed: %s", exc)

        try:
            await self._stop_event.wait()
        finally:
            with contextlib.suppress(Exception):
                await application.updater.stop()
            with contextlib.suppress(Exception):
                await application.stop()
            with contextlib.suppress(Exception):
                await application.shutdown()

    async def _typing_loop(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
        try:
            while True:
                try:
                    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                except Exception as exc:
                    log_debug(__name__, "Failed to send typing action: %s", exc)
                await asyncio.sleep(_TYPING_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        if not text:
            return

        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            return
        self._last_chat_id = chat_id

        username = update.effective_user.username if update.effective_user else None
        async with self._get_chat_lock(chat_id):
            typing_task = asyncio.create_task(self._typing_loop(context, chat_id))
            app_state.add_message("user", text)
            log_debug(__name__, "Telegram message received from chat_id=%s user=%s", chat_id, username or "")

            try:
                history = _load_history(chat_id, username)
                future = orchestrator_queue.submit_threadsafe(
                    text,
                    {"source": "telegram", "chat_id": chat_id, "username": username or ""},
                    history=history,
                )
                result = await asyncio.wrap_future(future)
                response = _normalize_response(orchestrator_queue.extract_response(result))
                _append_log(chat_id, username, text, response)

                app_state.add_message("assistant", response, "Orchestrator")
                await update.message.reply_text(response)
            except Exception as exc:
                log_exception(__name__, "Telegram message handling failed: %s", exc)
                with contextlib.suppress(Exception):
                    error_text = f"Error: {exc}"
                    _append_log(chat_id, username, text, error_text)
                    await update.message.reply_text(error_text)
            finally:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await typing_task

    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log_exception(__name__, "Telegram error: %s", context.error)

    def notify_owner(self, text: str, chat_id: str | int | None = None) -> str:
        message = (text or "").strip()
        if not message:
            return "ignored: empty message"

        target_chat = str(chat_id or os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "")).strip()
        if not target_chat and self._last_chat_id is not None:
            target_chat = str(self._last_chat_id)

        if not target_chat:
            return "disabled: missing TELEGRAM_NOTIFY_CHAT_ID and no prior chat"

        if not self._loop or not self._application:
            return "disabled: telegram module not running"

        max_len = 3800
        if len(message) > max_len:
            message = message[:max_len] + "\n...[truncated]"

        async def _send() -> None:
            await self._application.bot.send_message(chat_id=target_chat, text=message)

        future = asyncio.run_coroutine_threadsafe(_send(), self._loop)
        try:
            future.result()
            return "ok"
        except Exception as exc:
            return f"error: {exc}"


__all__ = ["TelegramModule"]
