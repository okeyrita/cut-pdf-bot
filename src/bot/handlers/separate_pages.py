from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, BufferedInputFile

from util.pdf_transform import separate_pdf
from keyboards import separate_pages_button, separate_vertical_button,\
    separate_horizontal_button, separate_strongly_button,\
    separate_with_reserve_button
from states import SeparatePageDocument

separate_pages_router: Router = Router()


@separate_pages_router.message(
    F.text.casefold() == separate_pages_button.text.casefold())
async def separate_pages_file(message: Message, state: FSMContext):
    await state.set_state(SeparatePageDocument.separate_orientation)
    keyboard = [[separate_vertical_button, separate_horizontal_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    await message.answer(
        'Хотите разделить страницы вертикально или горизонтально?',
        reply_markup=keyboard
    )


@separate_pages_router.message(SeparatePageDocument.separate_orientation)
async def ask_separate_file_strongly(message: Message, state: FSMContext):
    await state.update_data(separate_orientation=message.text)
    await state.set_state(SeparatePageDocument.separate_strongly)
    keyboard = [[separate_strongly_button, separate_with_reserve_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    await message.answer(
        'Хотите разделить страницы строго пополам или с запасом?',
        reply_markup=keyboard
    )


@separate_pages_router.message(
    SeparatePageDocument.separate_strongly,
    F.text.casefold() == separate_with_reserve_button.text.casefold())
async def separate_file_strongly(message: Message, state: FSMContext):
    await state.update_data(separate_strongly=message.text)
    await state.set_state(SeparatePageDocument.reserve_percent)
    await message.answer(
        'Отправьте целое или дробное число от 0 до 100 с разделителем точка.'
    )
