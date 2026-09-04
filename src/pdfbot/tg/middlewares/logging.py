"""Structured per-update logging."""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


logger = logging.getLogger(__name__)


class LoggingMiddleware(BaseMiddleware):
    """Log one line per handled update, with user id, kind and duration."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        started = time.monotonic()

        match event:
            case CallbackQuery():
                kind, detail = "callback", event.data or ""
            case Message() if event.document is not None:
                kind, detail = "document", event.document.file_name or ""
            case Message():
                # Truncated: message text can be arbitrarily long and is often the user's own data.
                kind, detail = "message", (event.text or "")[:64]
            case _:
                kind, detail = type(event).__name__, ""

        try:
            return await handler(event, data)
        finally:
            logger.info(
                "update handled",
                extra={
                    "user_id": getattr(user, "id", None),
                    "kind": kind,
                    "detail": detail,
                    "ms": round((time.monotonic() - started) * 1000),
                },
            )
