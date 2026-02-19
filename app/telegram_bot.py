"""
Telegram bot module entrypoint.

The bot is started by the application lifespan via the TelegramModule.
"""

from app.modules.telegram import TelegramModule

telegram_module = TelegramModule()

__all__ = ["telegram_module"]
