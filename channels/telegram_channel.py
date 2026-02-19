"""
TelegramChannel — Telegram bot polling adapter.

Wraps the existing ``TelegramModule`` (runtime object) and exposes it
through the ``BaseChannel`` interface so the application can treat all
communication mediums uniformly.

The heavy lifting (polling, history, typing indicators) is still handled
by ``app.modules.telegram.TelegramModule`` — this channel is a thin
adapter that satisfies the channel contract.
"""

from __future__ import annotations

from typing import Any

from pydantic import PrivateAttr

from core.logging_core import log_info, log_warning

from .base import BaseChannel


class TelegramChannel(BaseChannel):
    """Telegram channel — polling-based bot integration."""

    name: str = "telegram"
    _module: Any = PrivateAttr(default=None)

    async def connect(self, **kwargs: Any) -> None:
        """Start the Telegram polling module."""
        from app.modules.telegram import TelegramModule

        self._module = TelegramModule()
        await self._module.initialize()
        if self._module.is_initialized:
            log_info(__name__, "TelegramChannel connected (polling started)")
        else:
            log_warning(__name__, "TelegramChannel: module did not initialize (token missing?)")

    async def disconnect(self) -> None:
        """Stop the Telegram polling module."""
        if self._module is not None:
            try:
                await self._module.shutdown()
            except Exception as exc:
                log_warning(__name__, "TelegramChannel shutdown error: %s", exc)
            self._module = None

    async def send(self, payload: dict, **kwargs: Any) -> None:
        """Send a message via Telegram to the owner / last chat.

        payload must contain ``content`` (str) and optionally ``chat_id``.
        """
        if self._module is None:
            return
        content = payload.get("content") or payload.get("data", {}).get("content", "")
        chat_id = payload.get("chat_id") or kwargs.get("chat_id")
        if content:
            self._module.notify_owner(str(content), chat_id=chat_id)

    async def broadcast(self, payload: dict, *, scope: str | list[str] | None = None) -> None:
        """Telegram doesn't support broadcast in the same sense.

        This sends to the last known chat or configured notification chat.
        """
        await self.send(payload)

    @property
    def is_connected(self) -> bool:
        return self._module is not None and self._module.is_initialized
