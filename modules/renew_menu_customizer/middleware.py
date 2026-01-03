"""
Middleware для модуля renew_menu_customizer
"""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from logger import logger
from .context import current_key_name


class RenewMenuMiddleware(BaseMiddleware):
    """Middleware для перехвата callback renew_key и сохранения key_name в контекст."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery) and event.data:
            if event.data.startswith("renew_key|"):
                try:
                    parts = event.data.split("|", 1)
                    if len(parts) == 2:
                        key_name = parts[1]
                        current_key_name.set(key_name)
                        logger.debug(f"[RenewMenuMiddleware] Сохранён key_name: {key_name}")
                except Exception as e:
                    logger.error(f"[RenewMenuMiddleware] Ошибка: {e}")

        try:
            return await handler(event, data)
        finally:
            current_key_name.set(None)
