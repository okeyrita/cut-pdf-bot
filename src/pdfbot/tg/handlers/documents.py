"""Receiving uploads: one document for most operations, many for merge."""

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis as AsyncRedis

from pdfbot import keyboards, states, texts
from pdfbot.callbacks import NavCB
from pdfbot.config import Settings
from pdfbot.domain.errors import NotEnoughFilesError, NoTextLayerError, TooManyFilesError
from pdfbot.enums import NavAction, Operation
from pdfbot.storage import JobWorkspace, UnsafeJobIdError
from pdfbot.tg.jobs import enqueue, receive_document


logger = logging.getLogger(__name__)


def _operation(data: dict[str, object]) -> Operation:
    return Operation(str(data.get(states.DATA_OPERATION, Operation.SPLIT.value)))


async def receive_single(
    message: Message, state: FSMContext, bot: Bot, settings: Settings, redis: AsyncRedis
) -> None:
    """The upload step for every single-file operation."""
    document = message.document
    if document is None:
        return

    data = await state.get_data()
    operation = _operation(data)
    workspace = JobWorkspace.create(settings.jobs_dir)

    try:
        # Only text extraction needs to know about a text layer, and the check costs a parse pass.
        info = await receive_document(
            bot,
            document,
            workspace,
            settings,
            check_text_layer=operation is Operation.EXTRACT,
        )
        if operation is Operation.EXTRACT and not info.has_text_layer:
            # Producing an empty TXT would be worse than refusing: the user would think their book
            # simply had no text, rather than learning they need OCR first.
            raise NoTextLayerError("no text layer; OCR required first")
    except Exception:
        workspace.cleanup()
        raise  # the errors middleware turns this into a specific Russian message

    await enqueue(
        message,
        message.from_user.id if message.from_user else 0,
        state,
        settings,
        redis,
        workspace,
        operation,
        document.file_name or "document.pdf",
    )


async def collect_for_merge(
    message: Message, state: FSMContext, bot: Bot, settings: Settings
) -> None:
    """Accumulate documents into one workspace until the user presses "готово"."""
    document = message.document
    if document is None:
        return

    data = await state.get_data()
    collected = list(data.get(states.DATA_FILES, []))
    if len(collected) >= settings.max_merge_files:
        raise TooManyFilesError(len(collected) + 1, settings.max_merge_files)

    job_id = data.get(states.DATA_JOB_ID)
    try:
        workspace = (
            JobWorkspace.attach(settings.jobs_dir, str(job_id))
            if job_id
            else JobWorkspace.create(settings.jobs_dir)
        )
    except FileNotFoundError, UnsafeJobIdError:
        # The workspace was swept or cancelled between uploads; start a fresh one.
        workspace = JobWorkspace.create(settings.jobs_dir)
        collected = []

    info = await receive_document(bot, document, workspace, settings, index=len(collected))
    collected.append(document.file_name or f"file_{len(collected) + 1}.pdf")

    total_pages = int(data.get("merge_pages", 0)) + info.pages
    await state.update_data(
        {
            states.DATA_JOB_ID: workspace.job_id,
            states.DATA_FILES: collected,
            "merge_pages": total_pages,
        }
    )
    await message.answer(
        texts.MERGE_COLLECTED.format(count=len(collected), pages=total_pages),
        reply_markup=keyboards.merge_collecting_kb(can_finish=len(collected) >= 2),
    )


async def finish_merge(
    callback: CallbackQuery,
    state: FSMContext,
    settings: Settings,
    redis: AsyncRedis,
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    data = await state.get_data()
    collected = list(data.get(states.DATA_FILES, []))
    if len(collected) < 2:
        raise NotEnoughFilesError(f"only {len(collected)} collected")

    workspace = JobWorkspace.attach(settings.jobs_dir, str(data[states.DATA_JOB_ID]))
    await enqueue(
        callback.message,
        callback.from_user.id,
        state,
        settings,
        redis,
        workspace,
        Operation.MERGE,
        str(collected[0]),
    )


async def not_a_document(message: Message) -> None:
    """Text, photo or sticker sent where a PDF was expected."""
    await message.answer(texts.ERR_SEND_FILE_PLEASE)


def build_router() -> Router:
    """Upload handling.

    Order matters: the document handlers must be registered before the catch-alls, which exist to
    answer anything that is not a PDF.
    """
    router = Router(name="documents")
    router.message.register(receive_single, states.Flow.waiting_file, F.document)
    router.message.register(collect_for_merge, states.Flow.merge_collecting, F.document)
    router.callback_query.register(
        finish_merge,
        NavCB.filter(F.action == NavAction.MERGE_DONE),
        states.Flow.merge_collecting,
    )
    router.message.register(not_a_document, states.Flow.waiting_file)
    router.message.register(not_a_document, states.Flow.merge_collecting)
    return router
