"""
Channels package — connection mediums between clients and the application.

Architecture:
    BaseChannel            — abstract interface every channel implements
    ├─ WebSocketChannel    — real-time browser UI connection
    └─ TelegramChannel     — Telegram bot polling adapter

Each channel handles its own lifecycle (connect, receive, send, disconnect)
while delegating actual query processing to the orchestrator queue.

Usage:
    from channels import WebSocketChannel, TelegramChannel
"""

from .base import BaseChannel
from .telegram_channel import TelegramChannel
from .websocket_channel import WebSocketChannel

__all__ = [
    "BaseChannel",
    "WebSocketChannel",
    "TelegramChannel",
]
