"""Turn exceptions escaping a handler into a message the user can act on.

Without this, a domain error inside a handler shows the user nothing at all -- aiogram logs it and
the chat just goes quiet, which is exactly how the original bot behaved when it met a non-PDF.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from pdfbot.domain.errors import PdfBotError
from pdfbot.tg.error_text import message_for_error


logger = logging.getLogger(__name__)


async def _reply(event: TelegramObject, text: str) -> None:
    """Answer whichever kind of update this is, swallowing delivery failures."""
    try:
        match event:
            case Message():
                await event.answer(text)
            case CallbackQuery() if event.message is not None:
                await event.message.answer(text)
            case CallbackQuery():
                await event.answer(text, show_alert=True)
    except TelegramAPIError:
        logger.warning("could not deliver error message to user", exc_info=True)


class ErrorsMiddleware(BaseMiddleware):
    """Map :class:`PdfBotError` to its specific text; log anything else with a traceback."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except PdfBotError as exc:
            # Expected: the user did something we can explain. No traceback needed.
            logger.info("user-facing error: %s", exc)
            await _reply(event, message_for_error(exc))
        except TelegramAPIError:
            # Telegram itself refused. Re-raise: retrying or alerting is the dispatcher's call, and
            # trying to reply over the same broken session would just fail again.
            raise
        except Exception:
            logger.exception("unhandled error in handler")
            await _reply(event, message_for_error(Exception()))
        return None
