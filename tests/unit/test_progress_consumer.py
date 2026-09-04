"""The bot side of the worker event stream.

Covers the behaviours that only show up against a live Telegram: flood-control retries, the
"message is not modified" response that two throttled emits reliably produce, and the teardown that
must happen exactly once per job.
"""

from typing import Any

import pytest
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from pdfbot import texts
from pdfbot.config import Settings
from pdfbot.events import EventKind, JobEvent
from pdfbot.storage import JobWorkspace
from pdfbot.tg.progress import ProgressConsumer
from tests.fixtures.telegram import CHAT_ID, USER_ID, FakeRedis, RecordingSession


class StreamRedis(FakeRedis):
    """FakeRedis plus the two stream calls the consumer makes."""

    def __init__(self) -> None:
        super().__init__()
        self.acked: list[str] = []

    async def xack(self, stream: str, group: str, entry_id: str) -> int:
        self.acked.append(entry_id)
        return 1


@pytest.fixture
def consumer(
    bot: Bot, settings: Settings, storage: MemoryStorage
) -> tuple[ProgressConsumer, StreamRedis]:
    redis = StreamRedis()
    return ProgressConsumer(bot, redis, settings, storage), redis  # type: ignore[arg-type]


def make_event(job_id: str, kind: EventKind, **kwargs: Any) -> JobEvent:
    return JobEvent(
        job_id=job_id, chat_id=CHAT_ID, user_id=USER_ID, message_id=99, kind=kind, **kwargs
    )


@pytest.fixture
def workspace(settings: Settings) -> JobWorkspace:
    return JobWorkspace.create(settings.jobs_dir)


# --------------------------------------------------------------------------- progress


async def test_progress_edits_the_message(
    consumer: tuple[ProgressConsumer, StreamRedis],
    session: RecordingSession,
    workspace: JobWorkspace,
) -> None:
    sut, _ = consumer
    await sut.handle(make_event(workspace.job_id, EventKind.PROGRESS, done=45, total=120))

    edits = session.calls("EditMessageText")
    assert len(edits) == 1
    text = str(edits[0].text)  # type: ignore[attr-defined]
    assert "45/120 стр." in text
    assert "38%" in text


async def test_stage_events_show_a_caption_not_a_page_count(
    consumer: tuple[ProgressConsumer, StreamRedis],
    session: RecordingSession,
    workspace: JobWorkspace,
) -> None:
    """Ghostscript and OCR are opaque: showing a fabricated page counter would be a lie."""
    sut, _ = consumer
    await sut.handle(make_event(workspace.job_id, EventKind.STAGE, stage="compressing"))
    assert texts.STAGE_COMPRESSING in str(session.calls("EditMessageText")[0].text)  # type: ignore[attr-defined]


async def test_not_modified_is_swallowed(
    consumer: tuple[ProgressConsumer, StreamRedis],
    bot: Bot,
    workspace: JobWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two throttled emits can land on the same page count; Telegram rejects the identical edit."""
    sut, _ = consumer

    async def raise_not_modified(*args: Any, **kwargs: Any) -> None:
        raise TelegramBadRequest(
            method=None,  # type: ignore[arg-type]
            message="Bad Request: message is not modified",
        )

    monkeypatch.setattr(bot, "edit_message_text", raise_not_modified)
    await sut.handle(make_event(workspace.job_id, EventKind.PROGRESS, done=1, total=2))  # no raise


async def test_flood_control_is_retried_once(
    consumer: tuple[ProgressConsumer, StreamRedis],
    bot: Bot,
    workspace: JobWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sut, _ = consumer
    attempts: list[int] = []
    slept: list[float] = []

    async def flaky(*args: Any, **kwargs: Any) -> None:
        attempts.append(1)
        if len(attempts) == 1:
            raise TelegramRetryAfter(
                method=None,  # type: ignore[arg-type]
                message="Too Many Requests",
                retry_after=3,
            )

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(bot, "edit_message_text", flaky)
    monkeypatch.setattr("pdfbot.tg.progress.asyncio.sleep", fake_sleep)

    await sut.handle(make_event(workspace.job_id, EventKind.PROGRESS, done=1, total=2))

    assert len(attempts) == 2
    assert slept == [3]  # waited exactly as long as Telegram asked


# --------------------------------------------------------------------------- completion


async def test_done_uploads_the_result_and_tears_down(
    consumer: tuple[ProgressConsumer, StreamRedis],
    session: RecordingSession,
    settings: Settings,
    storage: MemoryStorage,
    bot: Bot,
    workspace: JobWorkspace,
) -> None:
    sut, redis = consumer
    output = workspace.output_path()
    output.write_bytes(b"%PDF-1.4\nresult\n")

    key = StorageKey(bot_id=bot.id, chat_id=CHAT_ID, user_id=USER_ID)
    await storage.set_state(key, "Flow:processing")
    await redis.incr(f"pdfbot:active:{USER_ID}")

    await sut.handle(
        make_event(
            workspace.job_id,
            EventKind.DONE,
            result_path=str(output),
            result_name="book_split.pdf",
            caption="Страниц было: 10, стало: 20.",
        )
    )

    uploads = session.calls("SendDocument")
    assert len(uploads) == 1
    assert uploads[0].caption == "Страниц было: 10, стало: 20."  # type: ignore[attr-defined]
    assert session.texts[-1] == texts.DONE

    # Teardown: progress message removed, slot freed, state cleared, workspace deleted.
    assert len(session.calls("DeleteMessage")) == 1
    assert redis.store.get(f"pdfbot:active:{USER_ID}", 0) <= 0
    assert await storage.get_state(key) is None
    assert not workspace.root.exists()


async def test_done_with_a_missing_file_reports_an_error(
    consumer: tuple[ProgressConsumer, StreamRedis],
    session: RecordingSession,
    workspace: JobWorkspace,
) -> None:
    """A worker claiming success without an output must not leave the user waiting forever."""
    sut, _ = consumer
    await sut.handle(
        make_event(workspace.job_id, EventKind.DONE, result_path=str(workspace.root / "gone.pdf"))
    )
    assert session.calls("SendDocument") == []
    assert session.texts[-1] == texts.ERR_UNEXPECTED


# --------------------------------------------------------------------------- failures


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("InvalidPdfError", texts.ERR_BROKEN_PDF),
        ("EncryptedPdfError", texts.ERR_ENCRYPTED),
        ("NoTextLayerError", texts.ERR_NO_TEXT_LAYER),
        ("TimeoutError", texts.ERR_TIMEOUT),
        ("ProcessingFailedError", texts.ERR_PROCESSING_FAILED),
        ("SomethingNobodyMapped", texts.ERR_UNEXPECTED),
        (None, texts.ERR_UNEXPECTED),
    ],
)
async def test_worker_errors_become_specific_messages(
    consumer: tuple[ProgressConsumer, StreamRedis],
    session: RecordingSession,
    workspace: JobWorkspace,
    code: str | None,
    expected: str,
) -> None:
    sut, _ = consumer
    await sut.handle(make_event(workspace.job_id, EventKind.ERROR, error_code=code))
    assert session.texts[-1] == expected
    assert not workspace.root.exists()  # failure still cleans up


async def test_error_frees_the_concurrency_slot(
    consumer: tuple[ProgressConsumer, StreamRedis], workspace: JobWorkspace
) -> None:
    sut, redis = consumer
    await redis.incr(f"pdfbot:active:{USER_ID}")
    await sut.handle(make_event(workspace.job_id, EventKind.ERROR, error_code="InvalidPdfError"))
    assert redis.store.get(f"pdfbot:active:{USER_ID}", 0) <= 0


# --------------------------------------------------------------------------- stream plumbing


async def test_entries_are_acknowledged_even_when_handling_fails(
    consumer: tuple[ProgressConsumer, StreamRedis],
    workspace: JobWorkspace,
    bot: Bot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poison entry must not be redelivered forever."""
    sut, redis = consumer

    async def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(bot, "edit_message_text", boom)
    event = make_event(workspace.job_id, EventKind.PROGRESS, done=1, total=2)
    await sut._process("1-0", event.to_fields())
    assert redis.acked == ["1-0"]


async def test_a_malformed_entry_is_acknowledged_and_dropped(
    consumer: tuple[ProgressConsumer, StreamRedis],
) -> None:
    sut, redis = consumer
    await sut._process("1-1", {"garbage": "yes"})
    assert redis.acked == ["1-1"]
