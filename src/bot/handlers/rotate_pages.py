from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, BufferedInputFile

from util.pdf_transform import rotate_pdf
from keyboards import rotate_button, rotate_clockwise_button,\
    rotate_counterclockwise_button
from states import RotatePageDocument

rotate_pages_router: Router = Router()


@rotate_pages_router.message(F.text.casefold() == rotate_button.text.casefold())
async def rotate_page_file(message: Message, state: FSMContext):
    await state.set_state(RotatePageDocument.rotate_direction)
    keyboard = [[rotate_clockwise_button, rotate_counterclockwise_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    await message.answer(
        'Хотите повернуть страницы по часовой стрелке или против часовой стрелки?',
        reply_markup=keyboard
    )
