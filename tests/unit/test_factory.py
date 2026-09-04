"""Bot, Redis and Dispatcher construction.

Small, but it covers the local-Bot-API branch, which is the single most error-prone piece of
configuration in the project.
"""

from pathlib import Path

import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from pydantic import SecretStr

from pdfbot.config import Settings
from pdfbot.enums import Operation
from pdfbot.tg.factory import MissingTokenError, create_bot, create_dispatcher, create_redis


def test_create_bot_requires_a_token(settings: Settings) -> None:
    """Workers boot without BOT_TOKEN by design; the bot process must not."""
    with pytest.raises(MissingTokenError):
        create_bot(settings.model_copy(update={"bot_token": SecretStr("")}))


async def test_cloud_api_bot_uses_the_default_session(settings: Settings) -> None:
    bot = create_bot(settings.model_copy(update={"use_local_bot_api": False}))
    assert "api.telegram.org" in bot.session.api.base
    await bot.session.close()


async def test_local_api_bot_points_at_the_self_hosted_server(settings: Settings) -> None:
    """`is_local=True` is what makes aiogram treat getFile's result as a path, not a URL."""
    bot = create_bot(
        settings.model_copy(
            update={"use_local_bot_api": True, "local_bot_api_url": "http://bot-api:8081"}
        )
    )
    assert isinstance(bot.session, AiohttpSession)
    assert "bot-api:8081" in bot.session.api.base
    assert bot.session.api.is_local is True
    await bot.session.close()


def test_cloud_api_clamps_the_size_limit(settings: Settings) -> None:
    """Telegram refuses downloads over 20 MB, so a larger configured limit would be a lie."""
    clamped = Settings(
        bot_token=SecretStr("1:x"),
        data_dir=settings.data_dir,
        use_local_bot_api=False,
        max_file_size_mb=2000,
        _env_file=None,
    )
    assert clamped.max_file_size_mb == 20
    assert clamped.max_file_size_bytes == 20 * 1024 * 1024


def test_local_api_keeps_the_configured_limit(settings: Settings) -> None:
    assert settings.use_local_bot_api is True
    assert settings.max_file_size_mb == 50


def test_settings_reject_a_relative_data_dir(settings: Settings) -> None:
    with pytest.raises(ValueError, match="absolute path"):
        Settings(data_dir=Path("relative/path"), _env_file=None)


def test_settings_reject_an_inverted_time_limit(settings: Settings) -> None:
    with pytest.raises(ValueError, match="must exceed"):
        Settings(
            data_dir=settings.data_dir,
            task_soft_time_limit=100,
            task_time_limit=50,
            _env_file=None,
        )


def test_dispatcher_wires_every_router(settings: Settings) -> None:
    dispatcher = create_dispatcher(settings, create_redis(settings))
    names = {r.name for r in dispatcher.sub_routers[0].sub_routers}
    assert names == {"cancel", "common", "split", "options", "documents"}
    # cancel must come first, or /cancel loses to the state-specific handlers.
    assert dispatcher.sub_routers[0].sub_routers[0].name == "cancel"


def test_dispatcher_can_be_built_twice(settings: Settings) -> None:
    """Routers are factories, not singletons: aiogram refuses to re-attach the same Router."""
    create_dispatcher(settings, create_redis(settings))
    create_dispatcher(settings, create_redis(settings))


def test_jobs_dir_is_under_data_dir(settings: Settings) -> None:
    assert settings.jobs_dir == settings.data_dir / "jobs"


def test_every_operation_has_a_first_step_or_is_multi_file() -> None:
    """A menu entry with no следующий шаг would dead-end the conversation."""
    from pdfbot.tg.handlers.common import _FIRST_STEP

    for operation in Operation:
        assert operation in _FIRST_STEP or operation.is_multi_file
