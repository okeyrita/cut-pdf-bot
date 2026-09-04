"""Shared fixtures.

Settings are built per test from a temp directory rather than read from a developer's real ``.env``
-- otherwise a stray environment variable on one machine changes what the suite asserts.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from pydantic import SecretStr

from pdfbot.config import Settings, get_settings
from pdfbot.tg.handlers import build_root_router
from pdfbot.tg.middlewares.errors import ErrorsMiddleware
from pdfbot.tg.middlewares.logging import LoggingMiddleware
from tests.fixtures.telegram import (
    CHAT_ID,
    TEST_TOKEN,
    USER_ID,
    FakeRedis,
    RecordingSession,
    make_bot,
)


@pytest.fixture(autouse=True)
def _clean_settings_cache() -> Iterator[None]:
    """Stop a cached Settings from one test leaking into the next."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide any real PDFBOT env vars and .env file from the tests."""
    for key in list(os.environ):
        if key.upper() in {
            "BOT_TOKEN",
            "DATA_DIR",
            "REDIS_URL",
            "USE_LOCAL_BOT_API",
            "MAX_FILE_SIZE_MB",
            "MAX_PAGES",
        }:
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    (path / "jobs").mkdir(parents=True)
    return path


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    return Settings(
        bot_token=SecretStr("42:TESTTOKEN"),
        data_dir=data_dir,
        use_local_bot_api=True,  # keeps max_file_size_mb un-clamped in tests
        max_file_size_mb=50,
        max_pages=500,
        max_merge_files=5,
        log_json=False,
        _env_file=None,
    )


@pytest.fixture
def session() -> RecordingSession:
    return RecordingSession()


@pytest.fixture
async def bot(session: RecordingSession) -> Bot:
    return make_bot(session)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def dispatcher(storage: MemoryStorage, settings: Settings, fake_redis: FakeRedis) -> Dispatcher:
    """A real dispatcher with the real routers, so filters and FSM are genuinely exercised."""
    dp = Dispatcher(storage=storage, settings=settings, redis=fake_redis)
    # Same middleware stack as production, so their behaviour is under test too.
    for middleware in (LoggingMiddleware(), ErrorsMiddleware()):
        dp.message.middleware(middleware)
        dp.callback_query.middleware(middleware)
    dp.include_router(build_root_router())
    return dp


@pytest.fixture
def state(storage: MemoryStorage, bot: Bot) -> FSMContext:
    return FSMContext(
        storage=storage,
        key=StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID),
    )


@pytest.fixture
def token() -> str:
    return TEST_TOKEN
