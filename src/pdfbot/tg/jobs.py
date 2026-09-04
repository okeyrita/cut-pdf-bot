"""Accepting a document and handing it to a worker.

The transition every operation funnels through: validate the upload, land it on the shared volume,
post the message the worker will edit into a progress bar, then enqueue.
"""

import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Document, Message
from redis.asyncio import Redis as AsyncRedis

from pdfbot import keyboards, states, texts
from pdfbot.config import Settings
from pdfbot.domain.models import PdfInfo
from pdfbot.domain.pdf.inspect import probe
from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)
from pdfbot.events import JobRequest
from pdfbot.storage import JobWorkspace
from pdfbot.tg.files import download_document, suffix_for
from pdfbot.tg.middlewares.concurrency import JobSlots
from pdfbot.worker.celery_app import app as celery_app
from pdfbot.worker.tasks import TASK_BY_OPERATION


logger = logging.getLogger(__name__)


async def ask_for_file(message: Message, state: FSMContext, operation: Operation) -> None:
    """Park the conversation in ``waiting_file`` (or ``merge_collecting``) and prompt."""
    await state.update_data({states.DATA_OPERATION: operation.value})
    if operation.is_multi_file:
        await state.set_state(states.Flow.merge_collecting)
        await message.answer(
            texts.SEND_FILES_TO_MERGE, reply_markup=keyboards.merge_collecting_kb(can_finish=False)
        )
    else:
        await state.set_state(states.Flow.waiting_file)
        await message.answer(texts.SEND_FILE, reply_markup=keyboards.cancel_kb())


async def receive_document(
    bot: Bot,
    document: Document,
    workspace: JobWorkspace,
    settings: Settings,
    index: int = 0,
    *,
    check_text_layer: bool = False,
) -> PdfInfo:
    """Download and validate one upload into the workspace.

    Probing runs in a thread: it parses the whole xref table, which on a large book is long enough
    to stall the event loop and delay every other user's updates.

    Raises:
        TooLargeError, InvalidPdfError, EncryptedPdfError, TooManyPagesError
    """
    target = workspace.input_path(index, suffix_for(document))
    await download_document(bot, document, target, settings)
    return await asyncio.to_thread(
        probe,
        target,
        max_size_bytes=settings.max_file_size_bytes,
        max_pages=settings.max_pages,
        check_text_layer=check_text_layer,
    )


def _percent_to_fraction(raw: object) -> float:
    """FSM data comes back from Redis untyped; normalise 0-100 into a 0-1 fraction."""
    if raw is None or raw == "":
        return 0.0
    return float(str(raw)) / 100.0


def build_request(
    *,
    job_id: str,
    chat_id: int,
    user_id: int,
    message_id: int,
    operation: Operation,
    original_name: str,
    data: dict[str, object],
) -> JobRequest:
    """Assemble a :class:`JobRequest` from FSM data.

    FSM data holds bare wire strings (that is what Redis stores), so each field is re-parsed back
    into its enum here. Doing it in one place means the worker can trust the request it receives.
    """

    def enum_or_none[T](cls: type[T], key: str) -> T | None:
        raw = data.get(key)
        return cls(raw) if raw is not None else None  # type: ignore[call-arg]

    return JobRequest(
        job_id=job_id,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        operation=operation,
        original_name=original_name,
        orientation=enum_or_none(Orientation, states.DATA_ORIENTATION),
        split_mode=enum_or_none(SplitMode, states.DATA_SPLIT_MODE),
        reserve=_percent_to_fraction(data.get(states.DATA_RESERVE_PERCENT)),
        rotate_direction=enum_or_none(RotateDirection, states.DATA_ROTATE_DIRECTION),
        compress_level=enum_or_none(CompressLevel, states.DATA_COMPRESS_LEVEL),
        ocr_lang=enum_or_none(OcrLang, states.DATA_OCR_LANG),
        export_format=enum_or_none(ExportFormat, states.DATA_EXPORT_FORMAT),
        title=Path(original_name).stem or "Документ",
    )


async def enqueue(
    message: Message,
    user_id: int,
    state: FSMContext,
    settings: Settings,
    redis: AsyncRedis,
    workspace: JobWorkspace,
    operation: Operation,
    original_name: str,
) -> bool:
    """Post the progress message and dispatch the Celery task.

    ``message`` is only used to reply into the right chat -- the user id is passed separately
    because the merge flow finishes from a callback, whose ``message`` was sent by the bot and
    therefore carries the bot as its ``from_user``.

    Returns False (and cleans up) when the user is already at their concurrent-job limit.
    """
    slots = JobSlots(redis, settings.max_concurrent_jobs_per_user, settings.task_time_limit)
    if not await slots.acquire(user_id):
        workspace.cleanup()
        await message.answer(texts.ERR_BUSY)
        return False

    progress = await message.answer(texts.QUEUED, reply_markup=keyboards.cancel_kb())
    data = await state.get_data()
    request = build_request(
        job_id=workspace.job_id,
        chat_id=message.chat.id,
        user_id=user_id,
        message_id=progress.message_id,
        operation=operation,
        original_name=original_name,
        data=data,
    )

    result = celery_app.send_task(
        TASK_BY_OPERATION[operation], args=[request.model_dump(mode="json")]
    )

    await state.set_state(states.Flow.processing)
    await state.update_data(
        {
            states.DATA_JOB_ID: workspace.job_id,
            states.DATA_TASK_ID: result.id,
            states.DATA_PROGRESS_MESSAGE_ID: progress.message_id,
        }
    )
    logger.info(
        "job queued",
        extra={
            "job_id": workspace.job_id,
            "task_id": result.id,
            "op": operation.value,
            "user_id": user_id,
        },
    )
    return True
