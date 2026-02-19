"""
BaseChannel — abstract interface for all communication channels.

A channel is a connection medium that lets external clients interact
with the application (send queries, receive responses and step-level
feedback).  Concrete implementations handle protocol-specific details
(WebSocket frames, Telegram HTTP polling, etc.) while this base class
enforces a uniform lifecycle contract.

Lifecycle:
    1. ``connect()``     — establish the transport connection.
    2. ``send()``        — push a message to the client.
    3. ``receive()``     — pull the next inbound message (async generator).
    4. ``broadcast()``   — fan-out to all clients of this channel type.
    5. ``disconnect()``  — tear down the connection cleanly.

SOLID notes:
    • Single Responsibility — each channel owns exactly one transport.
    • Open/Closed — new transports are added by subclassing, not editing.
    • Liskov Substitution — any ``BaseChannel`` can be swapped transparently.
    • Interface Segregation — only the methods a channel needs are abstract.
    • Dependency Inversion — the app depends on ``BaseChannel``, not concrete impls.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from core.engine import RuntimeObject


class BaseChannel(RuntimeObject):
    """Runtime contract for all communication channels."""

    name: str = "channel"

    async def connect(self, **kwargs: Any) -> None:
        """Establish the channel connection.

        For WebSocket this accepts and stores the WS object.
        For Telegram this starts the polling loop.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement connect().")

    async def disconnect(self) -> None:
        """Cleanly tear down the channel."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement disconnect().")

    async def send(self, payload: dict, **kwargs: Any) -> None:
        """Send a single message to one client.

        Args:
            payload: JSON-serialisable message dict.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement send().")

    async def broadcast(self, payload: dict, *, scope: str | list[str] | None = None) -> None:
        """Fan-out a message to all connected clients of this channel.

        Args:
            payload: JSON-serialisable message dict.
            scope:   Optional page / topic filter.
        """
        raise NotImplementedError(f"{self.__class__.__name__} must implement broadcast().")

    async def receive(self) -> AsyncIterator[dict]:
        """Yield inbound messages as they arrive.

        Default implementation raises ``NotImplementedError`` — override
        in channels that support bidirectional communication.
        """
        raise NotImplementedError(f"{self.name} does not support receive()")
        # Make this an async generator
        yield  # pragma: no cover  # noqa: E501

    async def on_error(self, error: Exception, *, context: dict[str, Any] | None = None) -> None:
        """Called on processing errors. Override for custom handling."""
