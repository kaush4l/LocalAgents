"""
WebSocketChannel — real-time browser UI connection.

Manages a set of active WebSocket connections and provides
broadcast / scoped-send capabilities.

This channel is used by the FastAPI WebSocket endpoint in ``app/main.py``
to push live updates (chat responses, activity steps, observability events)
to connected browser tabs.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import WebSocket
from pydantic import PrivateAttr

from core.logging_core import log_info

from .base import BaseChannel


class WebSocketChannel(BaseChannel):
    """WebSocket channel — manages browser connections."""

    name: str = "websocket"
    _connections: dict[WebSocket, str] = PrivateAttr(default_factory=dict)

    @property
    def connections(self) -> dict[WebSocket, str]:
        """Read-only access to the active connections map."""
        return self._connections

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, ws: WebSocket, *, scope: str = "chat", **kwargs: Any) -> None:  # type: ignore[override]
        """Accept and register a WebSocket connection.

        Args:
            ws:    The FastAPI WebSocket object.
            scope: Page scope identifier (``chat``, ``sts``, ``observability``, etc.).
        """
        await ws.accept()
        self._connections[ws] = scope
        log_info(__name__, "WebSocket connected (page=%s, total=%d)", scope, len(self._connections))

    async def disconnect(self, ws: WebSocket | None = None) -> None:  # type: ignore[override]
        """Remove a specific connection, or close all connections."""
        if ws is not None:
            self._connections.pop(ws, None)
            log_info(__name__, "WebSocket disconnected (%d remaining)", len(self._connections))
        else:
            for _ws in list(self._connections):
                try:
                    await _ws.close()
                except Exception:
                    pass
            self._connections.clear()

    async def send(self, payload: dict, *, ws: WebSocket | None = None, **kwargs: Any) -> None:
        """Send a message to a specific WebSocket client."""
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            self._connections.pop(ws, None)

    async def broadcast(self, payload: dict, *, scope: str | list[str] | None = None) -> None:
        """Send a message to all connected clients, optionally filtered by scope.

        Args:
            payload: JSON-serialisable message dict.
            scope:   ``None`` → all clients. ``str`` → only that page.
                     ``list[str]`` → any of the listed pages.
        """
        data = json.dumps(payload)
        for ws, page in list(self._connections.items()):
            if scope is not None:
                if isinstance(scope, list):
                    if page not in scope:
                        continue
                elif page != scope:
                    continue
            try:
                await ws.send_text(data)
            except Exception:
                self._connections.pop(ws, None)

    async def receive_text(self, ws: WebSocket) -> str:
        """Receive raw text from a specific WebSocket."""
        return await ws.receive_text()
