"""/start, /help, /cancel, the main menu, and the operation dispatch."""

import asyncio
import contextlib
import logging

from aiogram import F, Router, html
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis as AsyncRedis

from pdfbot import keyboards, states, texts
from pdfbot.callbacks import NavCB, OpCB
from pdfbot.config import Settings
from pdfbot.enums import NavAction, Operation
from pdfbot.storage import JobWorkspace, UnsafeJobIdError
from pdfbot.tg.jobs import ask_for_file
from pdfbot.tg.middlewares.concurrency import JobSlots
from pdfbot.worker.celery_app import app as celery_app


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- cancel


async def _abort(state: FSMContext, settings: Settings, redis: AsyncRedis, user_id: int) -> bool:
    """Tear down whatever the user had in flight. Returns True if there was anything.

    Order matters: revoke first so the worker stops before its workspace disappears underneath it.
    """
    data = await state.get_data()
    had_work = bool(await state.get_state())

    task_id = data.get(states.DATA_TASK_ID)
    if task_id:
        # revoke() talks to the broker; it is synchronous and must not block the event loop.
        await asyncio.to_thread(
            celery_app.control.revoke, str(task_id), terminate=True, signal="SIGTERM"
        )
        logger.info("revoked task %s", task_id)

    job_id = data.get(states.DATA_JOB_ID)
    if job_id:
        with contextlib.suppress(FileNotFoundError, UnsafeJobIdError):
            JobWorkspace.attach(settings.jobs_dir, str(job_id)).cleanup()

    if task_id:
        slots = JobSlots(redis, settings.max_concurrent_jobs_per_user, settings.task_time_limit)
        await slots.release(user_id)

    await state.clear()
    return had_work


async def cancel_command(
    message: Message, state: FSMContext, settings: Settings, redis: AsyncRedis
) -> None:
    user_id = message.from_user.id if message.from_user else 0
    had_work = await _abort(state, settings, redis, user_id)
    await message.answer(
        texts.CANCELLED if had_work else texts.NOTHING_TO_CANCEL,
        reply_markup=keyboards.main_menu(),
    )


async def cancel_button(
    callback: CallbackQuery, state: FSMContext, settings: Settings, redis: AsyncRedis
) -> None:
    await callback.answer()
    user_id = callback.from_user.id
    await _abort(state, settings, redis, user_id)
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.CANCELLED, reply_markup=keyboards.main_menu())


# --------------------------------------------------------------------------- entry points


async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(states.Flow.choosing_operation)
    name = html.bold(message.from_user.full_name) if message.from_user else "друг"
    await message.answer(texts.START.format(name=name), reply_markup=keyboards.main_menu())


async def start_process_book(message: Message, state: FSMContext) -> None:
    """Alias kept for users who bookmarked the original command."""
    await state.clear()
    await state.set_state(states.Flow.choosing_operation)
    await message.answer(texts.CHOOSE_OPERATION, reply_markup=keyboards.main_menu())


async def help_command(message: Message, settings: Settings) -> None:
    await message.answer(
        texts.HELP.format(
            max_size=settings.max_file_size_mb,
            max_pages=settings.max_pages,
            max_merge=settings.max_merge_files,
        )
    )


async def go_home(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await state.set_state(states.Flow.choosing_operation)
    if isinstance(callback.message, Message):
        await callback.message.answer(texts.CHOOSE_OPERATION, reply_markup=keyboards.main_menu())


# --------------------------------------------------------------------------- operation dispatch

#: First question of each operation: (prompt, keyboard factory, state to enter).
_FIRST_STEP = {
    Operation.SPLIT: (
        texts.ASK_ORIENTATION,
        keyboards.orientation_kb,
        states.Flow.split_orientation,
    ),
    Operation.ROTATE: (
        texts.ASK_ROTATE_DIRECTION,
        keyboards.rotate_kb,
        states.Flow.rotate_direction,
    ),
    Operation.COMPRESS: (
        texts.ASK_COMPRESS_LEVEL,
        keyboards.compress_kb,
        states.Flow.compress_level,
    ),
    Operation.OCR: (texts.ASK_OCR_LANG, keyboards.ocr_lang_kb, states.Flow.ocr_language),
    Operation.EXTRACT: (
        texts.ASK_EXPORT_FORMAT,
        keyboards.export_format_kb,
        states.Flow.extract_format,
    ),
}


async def choose_operation(
    callback: CallbackQuery, callback_data: OpCB, state: FSMContext
) -> None:
    """Main menu selection: remember the operation and ask its first question."""
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    operation = callback_data.value
    await state.set_data({states.DATA_OPERATION: operation.value})

    # Merge is the one operation with no options -- it goes straight to collecting files.
    if operation.is_multi_file:
        await ask_for_file(callback.message, state, operation)
        return

    prompt, keyboard, next_state = _FIRST_STEP[operation]
    await state.set_state(next_state)
    await callback.message.answer(prompt, reply_markup=keyboard())


async def busy(message: Message) -> None:
    """Anything sent while a job runs. Tell the user rather than silently ignoring it."""
    await message.answer(texts.ERR_BUSY)


def build_cancel_router() -> Router:
    """Cancellation only. Included first, so it wins from every state -- including `processing`."""
    router = Router(name="cancel")
    router.message.register(cancel_command, Command("cancel"), StateFilter("*"))
    router.callback_query.register(
        cancel_button, NavCB.filter(F.action == NavAction.CANCEL), StateFilter("*")
    )
    return router


def build_common_router() -> Router:
    """Entry points and the main-menu dispatch.

    Registration order is match order: the `processing` catch-all goes last so it cannot shadow
    the commands above it.
    """
    router = Router(name="common")
    router.message.register(start, CommandStart(), StateFilter("*"))
    router.message.register(start_process_book, Command("start_process_book"), StateFilter("*"))
    router.message.register(help_command, Command("help"), StateFilter("*"))
    router.callback_query.register(
        go_home, NavCB.filter(F.action == NavAction.HOME), StateFilter("*")
    )
    router.callback_query.register(choose_operation, OpCB.filter(), StateFilter("*"))
    router.message.register(busy, states.Flow.processing)
    return router
