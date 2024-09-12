from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup

from keyboards import separate_pages_button, separate_vertical_button,\
    separate_horizontal_button, separate_strongly_button,\
    separate_with_reserve_button
from states import SeparateDocument

separate_pages_router: Router = Router()


@separate_pages_router.message(F.text.casefold() == separate_pages_button.text.casefold())
async def separate_pages_file(message: Message, state: FSMContext):
    await state.set_state(SeparateDocument.separate_page_orientation)
    keyboard = [[separate_vertical_button, separate_horizontal_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы вертикально или горизонтально?',
        reply_markup=keyboard
    )


@separate_pages_router.message(SeparateDocument.separate_page_orientation)
async def separate_file_strongly(message: Message, state: FSMContext):
    await state.set_state(SeparateDocument.separate_page_strongly)
    keyboard = [[separate_strongly_button, separate_with_reserve_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы строго пополам или с запасом?',
        reply_markup=keyboard
    )
