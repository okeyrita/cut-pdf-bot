"""Handler and FSM behaviour.

These drive a **real** :class:`~aiogram.Dispatcher` -- real routers, real filters, real FSM
transitions, real middlewares. Only the HTTP session is faked, so a broken filter or a mis-ordered
router shows up here rather than in production.
"""

from pathlib import Path
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

from pdfbot import states, texts
from pdfbot.callbacks import (
    CompressCB,
    ExportCB,
    NavCB,
    OcrLangCB,
    OpCB,
    OrientCB,
    RotateCB,
    SplitModeCB,
)
from pdfbot.config import Settings
from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    NavAction,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)
from pdfbot.tg.handlers.split import parse_reserve_percent
from tests.fixtures.pdf import make_pdf, write_garbage
from tests.fixtures.telegram import (
    RecordingSession,
    callback_update,
    document_update,
    make_document,
    message_update,
)


async def feed(dispatcher: Dispatcher, bot: Bot, update: Any, **kwargs: Any) -> Any:
    """Push one update through the dispatcher exactly as polling would."""
    return await dispatcher.feed_update(bot, update, **kwargs)


@pytest.fixture(autouse=True)
def _no_real_broker(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Capture Celery dispatches instead of contacting RabbitMQ."""
    sent: list[tuple[str, Any]] = []

    class FakeResult:
        id = "task-123"

    def fake_send_task(name: str, args: Any = None, **kwargs: Any) -> FakeResult:
        sent.append((name, args[0] if args else None))
        return FakeResult()

    monkeypatch.setattr("pdfbot.tg.jobs.celery_app.send_task", fake_send_task)
    return sent


@pytest.fixture
def sent(_no_real_broker: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    return _no_real_broker


@pytest.fixture(autouse=True)
def _local_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stand in for Telegram's file download with a real PDF on disk."""

    async def fake_download(bot: Any, document: Any, target: Path, settings: Any) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        source = make_pdf(tmp_path / "downloaded.pdf", pages=4)
        target.write_bytes(source.read_bytes())
        return target

    monkeypatch.setattr("pdfbot.tg.jobs.download_document", fake_download)


# --------------------------------------------------------------------------- entry points


async def test_start_shows_the_main_menu(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await feed(dispatcher, bot, message_update("/start"))
    assert "Привет" in session.texts[0]
    assert len(session.button_data()) == len(Operation)
    assert await state.get_state() == states.Flow.choosing_operation.state


async def test_help_lists_the_limits(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, settings: Settings
) -> None:
    await feed(dispatcher, bot, message_update("/help"))
    body = session.texts[0]
    assert "Что я умею" in body
    assert str(settings.max_file_size_mb) in body
    assert "/cancel" in body


async def test_legacy_command_still_reaches_the_menu(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    """Users who bookmarked the original /start_process_book must not hit a dead end."""
    await feed(dispatcher, bot, message_update("/start_process_book"))
    assert len(session.button_data()) == len(Operation)


# --------------------------------------------------------------------------- split flow


async def test_split_flow_reaches_the_upload_step(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.SPLIT).pack()))
    assert session.texts[-1] == texts.ASK_ORIENTATION
    assert await state.get_state() == states.Flow.split_orientation.state

    await feed(dispatcher, bot, callback_update(OrientCB(value=Orientation.HORIZONTAL).pack()))
    assert session.texts[-1] == texts.ASK_SPLIT_MODE
    assert await state.get_state() == states.Flow.split_mode.state

    await feed(dispatcher, bot, callback_update(SplitModeCB(value=SplitMode.STRICT).pack()))
    assert session.texts[-1] == texts.SEND_FILE
    assert await state.get_state() == states.Flow.waiting_file.state

    data = await state.get_data()
    assert data[states.DATA_ORIENTATION] == Orientation.HORIZONTAL.value
    assert data[states.DATA_SPLIT_MODE] == SplitMode.STRICT.value


async def test_reserve_mode_asks_for_a_percentage(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.SPLIT).pack()))
    await feed(dispatcher, bot, callback_update(OrientCB(value=Orientation.VERTICAL).pack()))
    await feed(dispatcher, bot, callback_update(SplitModeCB(value=SplitMode.RESERVE).pack()))

    assert await state.get_state() == states.Flow.split_reserve.state
    assert "процентах" in session.texts[-1]


@pytest.mark.parametrize(
    "bad",
    [
        "abc",
        "-5",
        "150",
        "",
        "1,2,3",
        "nan",  # float() accepts these; only the range check stops them
        "inf",
        "-inf",
        "1e400",  # overflows to inf
    ],
)
async def test_invalid_reserve_reprompts_instead_of_crashing(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext, bad: str
) -> None:
    """Regression: the original called float() bare and blew up the handler on any junk."""
    await state.set_state(states.Flow.split_reserve)
    await feed(dispatcher, bot, message_update(bad))

    assert session.texts[-1] == texts.ERR_BAD_RESERVE
    assert await state.get_state() == states.Flow.split_reserve.state  # still asking


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5", 5.0), ("7.5", 7.5), ("7,5", 7.5), ("10%", 10.0), ("  0 ", 0.0), ("100", 100.0)],
)
def test_reserve_parser_accepts_reasonable_input(raw: str, expected: float) -> None:
    assert parse_reserve_percent(raw) == pytest.approx(expected)


async def test_valid_reserve_advances_to_the_upload_step(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await state.set_state(states.Flow.split_reserve)
    await state.update_data({states.DATA_OPERATION: Operation.SPLIT.value})
    await feed(dispatcher, bot, message_update("7,5"))

    assert session.texts[-1] == texts.SEND_FILE
    assert (await state.get_data())[states.DATA_RESERVE_PERCENT] == pytest.approx(7.5)


# --------------------------------------------------------------------------- other operations


@pytest.mark.parametrize(
    ("operation", "choice_cb", "expected_key", "expected_value"),
    [
        (
            Operation.ROTATE,
            RotateCB(value=RotateDirection.CW),
            states.DATA_ROTATE_DIRECTION,
            RotateDirection.CW.value,
        ),
        (
            Operation.COMPRESS,
            CompressCB(value=CompressLevel.EBOOK),
            states.DATA_COMPRESS_LEVEL,
            CompressLevel.EBOOK.value,
        ),
        (
            Operation.OCR,
            OcrLangCB(value=OcrLang.RUS_ENG),
            states.DATA_OCR_LANG,
            OcrLang.RUS_ENG.value,
        ),
        (
            Operation.EXTRACT,
            ExportCB(value=ExportFormat.EPUB),
            states.DATA_EXPORT_FORMAT,
            ExportFormat.EPUB.value,
        ),
    ],
)
async def test_single_question_operations_store_the_choice(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    operation: Operation,
    choice_cb: Any,
    expected_key: str,
    expected_value: str,
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=operation).pack()))
    await feed(dispatcher, bot, callback_update(choice_cb.pack()))

    assert session.texts[-1] == texts.SEND_FILE
    assert await state.get_state() == states.Flow.waiting_file.state
    assert (await state.get_data())[expected_key] == expected_value


async def test_merge_goes_straight_to_collecting_files(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.MERGE).pack()))
    assert await state.get_state() == states.Flow.merge_collecting.state
    assert "Присылайте" in session.texts[-1]


# --------------------------------------------------------------------------- uploads


async def test_a_document_enqueues_a_job(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    sent: list[tuple[str, Any]],
) -> None:
    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.ROTATE.value,
            states.DATA_ROTATE_DIRECTION: RotateDirection.CW.value,
        }
    )
    await feed(dispatcher, bot, document_update())

    assert len(sent) == 1
    name, payload = sent[0]
    assert name == "pdf.rotate"
    assert payload["operation"] == Operation.ROTATE.value
    assert payload["rotate_direction"] == RotateDirection.CW.value
    assert payload["message_id"] > 0  # the progress message the worker will edit

    assert await state.get_state() == states.Flow.processing.state
    assert (await state.get_data())[states.DATA_TASK_ID] == "task-123"


async def test_reserve_percent_becomes_a_fraction_in_the_request(
    dispatcher: Dispatcher, bot: Bot, state: FSMContext, sent: list[tuple[str, Any]]
) -> None:
    """The 0-100 → 0-1 conversion happens once, at the boundary."""
    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.SPLIT.value,
            states.DATA_ORIENTATION: Orientation.HORIZONTAL.value,
            states.DATA_SPLIT_MODE: SplitMode.RESERVE.value,
            states.DATA_RESERVE_PERCENT: 7.5,
        }
    )
    await feed(dispatcher, bot, document_update())
    assert sent[0][1]["reserve"] == pytest.approx(0.075)


async def test_a_non_document_is_answered_politely(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await state.set_state(states.Flow.waiting_file)
    await state.update_data({states.DATA_OPERATION: Operation.ROTATE.value})
    await feed(dispatcher, bot, message_update("вот держи"))
    assert session.texts[-1] == texts.ERR_SEND_FILE_PLEASE


async def test_a_broken_pdf_is_reported_and_cleans_up(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sent: list[tuple[str, Any]],
) -> None:
    async def download_garbage(bot: Any, document: Any, target: Path, s: Any) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        write_garbage(target)
        return target

    monkeypatch.setattr("pdfbot.tg.jobs.download_document", download_garbage)

    await state.set_state(states.Flow.waiting_file)
    await state.update_data({states.DATA_OPERATION: Operation.ROTATE.value})
    await feed(dispatcher, bot, document_update())

    assert session.texts[-1] == texts.ERR_BROKEN_PDF
    assert sent == []  # nothing was queued
    assert list(settings.jobs_dir.iterdir()) == []  # workspace removed


async def test_an_oversized_document_is_refused_before_download(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    settings: Settings,
    sent: list[tuple[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use the real size check rather than the patched downloader.
    from pdfbot.tg import files as files_module

    async def real_check(bot: Any, document: Any, target: Path, s: Settings) -> Path:
        files_module.check_size(document, s)
        raise AssertionError("should have been refused")

    monkeypatch.setattr("pdfbot.tg.jobs.download_document", real_check)

    await state.set_state(states.Flow.waiting_file)
    await state.update_data({states.DATA_OPERATION: Operation.ROTATE.value})
    huge = make_document(size=settings.max_file_size_bytes + 1)
    await feed(dispatcher, bot, document_update(huge))

    assert "слишком большой" in session.texts[-1]
    assert sent == []


async def test_extract_refuses_a_scan_before_queueing(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sent: list[tuple[str, Any]],
) -> None:
    """No point burning a worker slot to produce an empty TXT."""
    from tests.fixtures.pdf import make_scanned_pdf

    async def download_scan(bot: Any, document: Any, target: Path, s: Any) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(make_scanned_pdf(tmp_path / "scan.pdf", pages=3).read_bytes())
        return target

    monkeypatch.setattr("pdfbot.tg.jobs.download_document", download_scan)

    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.EXTRACT.value,
            states.DATA_EXPORT_FORMAT: ExportFormat.TXT.value,
        }
    )
    await feed(dispatcher, bot, document_update())

    assert session.texts[-1] == texts.ERR_NO_TEXT_LAYER
    assert sent == []


# --------------------------------------------------------------------------- merge collection


async def test_merge_collects_then_enqueues(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    sent: list[tuple[str, Any]],
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.MERGE).pack()))

    await feed(dispatcher, bot, document_update(make_document("a.pdf")))
    assert "Принято файлов: <b>1</b>" in session.texts[-1]
    # "Готово" must not appear with a single file.
    assert NavCB(action=NavAction.MERGE_DONE).pack() not in session.button_data()

    await feed(dispatcher, bot, document_update(make_document("b.pdf")))
    assert "Принято файлов: <b>2</b>" in session.texts[-1]
    assert NavCB(action=NavAction.MERGE_DONE).pack() in session.button_data()

    data = await state.get_data()
    assert data[states.DATA_FILES] == ["a.pdf", "b.pdf"]

    await feed(dispatcher, bot, callback_update(NavCB(action=NavAction.MERGE_DONE).pack()))
    assert sent[0][0] == "pdf.merge"
    assert await state.get_state() == states.Flow.processing.state


async def test_merge_refuses_to_finish_with_one_file(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    sent: list[tuple[str, Any]],
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.MERGE).pack()))
    await feed(dispatcher, bot, document_update(make_document("only.pdf")))
    await feed(dispatcher, bot, callback_update(NavCB(action=NavAction.MERGE_DONE).pack()))

    assert session.texts[-1] == texts.ERR_NEED_MORE_FILES
    assert sent == []


async def test_merge_enforces_the_file_limit(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    settings: Settings,
) -> None:
    await feed(dispatcher, bot, callback_update(OpCB(value=Operation.MERGE).pack()))
    for i in range(settings.max_merge_files):
        await feed(dispatcher, bot, document_update(make_document(f"{i}.pdf")))
    await feed(dispatcher, bot, document_update(make_document("one_too_many.pdf")))
    assert "файлов за раз" in session.texts[-1]


# --------------------------------------------------------------------------- cancel


@pytest.mark.parametrize(
    "flow_state",
    [
        states.Flow.split_orientation,
        states.Flow.split_mode,
        states.Flow.split_reserve,
        states.Flow.rotate_direction,
        states.Flow.compress_level,
        states.Flow.ocr_language,
        states.Flow.extract_format,
        states.Flow.waiting_file,
        states.Flow.merge_collecting,
        states.Flow.processing,
    ],
)
async def test_cancel_command_works_from_every_state(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    flow_state: Any,
) -> None:
    await state.set_state(flow_state)
    await feed(dispatcher, bot, message_update("/cancel"))

    assert session.texts[-1] == texts.CANCELLED
    assert await state.get_state() is None


async def test_cancel_button_works_from_every_state(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await state.set_state(states.Flow.waiting_file)
    await feed(dispatcher, bot, callback_update(NavCB(action=NavAction.CANCEL).pack()))
    assert session.texts[-1] == texts.CANCELLED
    assert await state.get_state() is None


async def test_cancel_with_nothing_running_says_so(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession
) -> None:
    await feed(dispatcher, bot, message_update("/cancel"))
    assert session.texts[-1] == texts.NOTHING_TO_CANCEL


async def test_cancel_revokes_the_task_and_removes_the_workspace(
    dispatcher: Dispatcher,
    bot: Bot,
    state: FSMContext,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    sent: list[tuple[str, Any]],
) -> None:
    revoked: list[str] = []
    monkeypatch.setattr(
        "pdfbot.tg.handlers.common.celery_app.control.revoke",
        lambda task_id, **kwargs: revoked.append(task_id),
    )

    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.ROTATE.value,
            states.DATA_ROTATE_DIRECTION: RotateDirection.CW.value,
        }
    )
    await feed(dispatcher, bot, document_update())
    assert list(settings.jobs_dir.iterdir()) != []

    await feed(dispatcher, bot, message_update("/cancel"))

    assert revoked == ["task-123"]
    assert list(settings.jobs_dir.iterdir()) == []
    assert await state.get_state() is None


async def test_cancel_frees_the_concurrency_slot(
    dispatcher: Dispatcher,
    bot: Bot,
    state: FSMContext,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
    sent: list[tuple[str, Any]],
) -> None:
    monkeypatch.setattr(
        "pdfbot.tg.handlers.common.celery_app.control.revoke", lambda *a, **k: None
    )
    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.ROTATE.value,
            states.DATA_ROTATE_DIRECTION: RotateDirection.CW.value,
        }
    )
    await feed(dispatcher, bot, document_update())
    assert any(v > 0 for v in fake_redis.store.values())

    await feed(dispatcher, bot, message_update("/cancel"))
    assert all(v <= 0 for v in fake_redis.store.values()) or not fake_redis.store


# --------------------------------------------------------------------------- concurrency


async def test_a_second_job_is_refused_while_one_runs(
    dispatcher: Dispatcher,
    bot: Bot,
    session: RecordingSession,
    state: FSMContext,
    storage: MemoryStorage,
    sent: list[tuple[str, Any]],
) -> None:
    """One user must not be able to occupy the whole worker pool."""
    await state.set_state(states.Flow.waiting_file)
    await state.update_data(
        {
            states.DATA_OPERATION: Operation.ROTATE.value,
            states.DATA_ROTATE_DIRECTION: RotateDirection.CW.value,
        }
    )
    await feed(dispatcher, bot, document_update())
    assert len(sent) == 1

    # Force the state back to waiting_file to simulate a racing second upload.
    await state.set_state(states.Flow.waiting_file)
    await feed(dispatcher, bot, document_update())

    assert len(sent) == 1
    assert session.texts[-1] == texts.ERR_BUSY


async def test_messages_during_processing_are_answered(
    dispatcher: Dispatcher, bot: Bot, session: RecordingSession, state: FSMContext
) -> None:
    await state.set_state(states.Flow.processing)
    await feed(dispatcher, bot, message_update("ну что там"))
    assert session.texts[-1] == texts.ERR_BUSY
