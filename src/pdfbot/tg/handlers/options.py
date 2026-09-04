"""One-question operations: rotate, compress, OCR, extract.

Each is the same shape -- store the chosen enum, then ask for the file -- so they share a module
rather than four near-identical files.
"""

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from pdfbot import states
from pdfbot.callbacks import CompressCB, ExportCB, OcrLangCB, RotateCB
from pdfbot.enums import Operation
from pdfbot.tg.jobs import ask_for_file


logger = logging.getLogger(__name__)


async def _store_and_ask(
    callback: CallbackQuery, state: FSMContext, key: str, value: str, operation: Operation
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.update_data({key: value})
    await ask_for_file(callback.message, state, operation)


async def choose_rotation(
    callback: CallbackQuery, callback_data: RotateCB, state: FSMContext
) -> None:
    await _store_and_ask(
        callback, state, states.DATA_ROTATE_DIRECTION, callback_data.value.value, Operation.ROTATE
    )


async def choose_compress_level(
    callback: CallbackQuery, callback_data: CompressCB, state: FSMContext
) -> None:
    await _store_and_ask(
        callback, state, states.DATA_COMPRESS_LEVEL, callback_data.value.value, Operation.COMPRESS
    )


async def choose_ocr_language(
    callback: CallbackQuery, callback_data: OcrLangCB, state: FSMContext
) -> None:
    await _store_and_ask(
        callback, state, states.DATA_OCR_LANG, callback_data.value.value, Operation.OCR
    )


async def choose_export_format(
    callback: CallbackQuery, callback_data: ExportCB, state: FSMContext
) -> None:
    await _store_and_ask(
        callback, state, states.DATA_EXPORT_FORMAT, callback_data.value.value, Operation.EXTRACT
    )


def build_router() -> Router:
    router = Router(name="options")
    router.callback_query.register(
        choose_rotation, RotateCB.filter(), states.Flow.rotate_direction
    )
    router.callback_query.register(
        choose_compress_level, CompressCB.filter(), states.Flow.compress_level
    )
    router.callback_query.register(
        choose_ocr_language, OcrLangCB.filter(), states.Flow.ocr_language
    )
    router.callback_query.register(
        choose_export_format, ExportCB.filter(), states.Flow.extract_format
    )
    return router
