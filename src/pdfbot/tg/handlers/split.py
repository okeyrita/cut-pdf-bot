"""Split flow: orientation → strict/reserve → (reserve %) → file."""

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from pdfbot import keyboards, states, texts
from pdfbot.callbacks import OrientCB, SplitModeCB
from pdfbot.enums import Operation, SplitMode
from pdfbot.tg.jobs import ask_for_file


logger = logging.getLogger(__name__)


def parse_reserve_percent(raw: str) -> float:
    """Parse the user's reserve percentage.

    Accepts a comma as the decimal separator, which is what a Russian-locale keyboard offers.

    Raises:
        ValueError: not a number, or outside 0-100. The original code called ``float()`` bare and
            crashed the handler on any non-numeric input.
    """
    value = float(raw.strip().replace(",", ".").replace("%", ""))
    if not 0.0 <= value <= 100.0:
        raise ValueError(f"{value} is outside [0, 100]")
    return value


async def choose_orientation(
    callback: CallbackQuery, callback_data: OrientCB, state: FSMContext
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    await state.update_data({states.DATA_ORIENTATION: callback_data.value.value})
    await state.set_state(states.Flow.split_mode)
    await callback.message.answer(texts.ASK_SPLIT_MODE, reply_markup=keyboards.split_mode_kb())


async def choose_mode(
    callback: CallbackQuery, callback_data: SplitModeCB, state: FSMContext
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return

    mode = callback_data.value
    await state.update_data({states.DATA_SPLIT_MODE: mode.value})

    if mode is SplitMode.RESERVE:
        await state.set_state(states.Flow.split_reserve)
        await callback.message.answer(texts.ASK_RESERVE, reply_markup=keyboards.cancel_kb())
        return

    await state.update_data({states.DATA_RESERVE_PERCENT: 0.0})
    await ask_for_file(callback.message, state, Operation.SPLIT)


async def enter_reserve(message: Message, state: FSMContext) -> None:
    """The only free-text step in the whole bot."""
    try:
        percent = parse_reserve_percent(message.text or "")
    except ValueError:
        await message.answer(texts.ERR_BAD_RESERVE, reply_markup=keyboards.cancel_kb())
        return

    await state.update_data({states.DATA_RESERVE_PERCENT: percent})
    await ask_for_file(message, state, Operation.SPLIT)


def build_router() -> Router:
    router = Router(name="split")
    router.callback_query.register(
        choose_orientation, OrientCB.filter(), states.Flow.split_orientation
    )
    router.callback_query.register(choose_mode, SplitModeCB.filter(), states.Flow.split_mode)
    router.message.register(enter_reserve, states.Flow.split_reserve)
    return router
