"""Construct the Bot, the Dispatcher and the shared Redis client."""

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis as AsyncRedis

from pdfbot.config import Settings


logger = logging.getLogger(__name__)


class MissingTokenError(RuntimeError):
    """BOT_TOKEN was not set. Only the bot process needs it; workers do not."""


def create_bot(settings: Settings) -> Bot:
    """Build the Bot, pointing it at a local Bot API server when one is configured.

    The cloud Bot API refuses to download anything over 20 MB, which rules out the scanned books
    this bot exists to process. A self-hosted ``telegram-bot-api`` raises that to 2 GB -- at the
    cost of ``getFile`` returning a **local filesystem path** instead of a URL. See
    :mod:`pdfbot.tg.files` for the download side of that.
    """
    token = settings.bot_token.get_secret_value()
    if not token:
        raise MissingTokenError("BOT_TOKEN is not set")

    session: AiohttpSession | None = None
    if settings.use_local_bot_api:
        server = TelegramAPIServer.from_base(settings.local_bot_api_url, is_local=True)
        session = AiohttpSession(api=server)
        logger.info("using local Bot API server at %s", settings.local_bot_api_url)

    return Bot(
        token=token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_redis(settings: Settings) -> AsyncRedis:
    """Async Redis client, shared by FSM storage, the event consumer and the rate limiter."""
    client: AsyncRedis = AsyncRedis.from_url(settings.redis_url, decode_responses=True)
    return client


def create_dispatcher(settings: Settings, redis: AsyncRedis) -> Dispatcher:
    """Assemble the dispatcher with Redis-backed FSM storage and every router.

    Router order matters: ``cancel_router`` goes first so ``/cancel`` and the cancel button
    win from any state, including mid-processing.
    """
    from pdfbot.tg.handlers import build_root_router
    from pdfbot.tg.middlewares.errors import ErrorsMiddleware
    from pdfbot.tg.middlewares.logging import LoggingMiddleware

    storage = RedisStorage(redis=redis)
    dispatcher = Dispatcher(storage=storage, settings=settings, redis=redis)

    for middleware in (LoggingMiddleware(), ErrorsMiddleware()):
        dispatcher.message.middleware(middleware)
        dispatcher.callback_query.middleware(middleware)

    dispatcher.include_router(build_root_router())
    return dispatcher
