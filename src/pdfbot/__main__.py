"""Bot entry point: ``python -m pdfbot``."""

import asyncio
import contextlib
import logging

from aiogram.types import BotCommand

from pdfbot.config import Settings, get_settings
from pdfbot.logging_conf import configure_logging
from pdfbot.storage import sweep_stale
from pdfbot.tg.factory import create_bot, create_dispatcher, create_redis
from pdfbot.tg.progress import ProgressConsumer


logger = logging.getLogger(__name__)

_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="help", description="Что я умею"),
    BotCommand(command="cancel", description="Отменить текущую операцию"),
]


async def _run(settings: Settings) -> None:
    redis = create_redis(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings, redis)

    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    swept = sweep_stale(settings.jobs_dir, settings.workspace_ttl_seconds)
    logger.info("startup sweep removed %d stale workspaces", swept)

    await bot.set_my_commands(_COMMANDS)

    consumer = ProgressConsumer(bot, redis, settings, dispatcher.storage)
    consumer_task = asyncio.create_task(consumer.run(), name="progress-consumer")

    try:
        await dispatcher.start_polling(bot, settings=settings, redis=redis)
    finally:
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
        await bot.session.close()
        await redis.aclose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "starting pdfbot",
        extra={"local_api": settings.use_local_bot_api, "max_mb": settings.max_file_size_mb},
    )
    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt, SystemExit:
        logger.info("shutting down")


if __name__ == "__main__":
    main()
