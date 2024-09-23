import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, html, F
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, BufferedInputFile

from handlers.separate_pages import separate_pages_router
from handlers.rotate_pages import rotate_pages_router
from keyboards import start_process_yes_button, start_process_no_button,\
    separate_pages_button, rotate_button, separate_strongly_button
from states import SeparatePageDocument, RotatePageDocument
from util.pdf_transform import separate_pdf, rotate_pdf

# Bot token can be obtained via https://t.me/BotFather
TOKEN = "7497738699:AAFRh3ULzapyhDw7KfhKZbUl8PGcMhXAAcE"


bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(separate_pages_router)
dp.include_router(rotate_pages_router)


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    """
    This handler receives messages with `/start` command
    """
    await message.answer(f"Привет, {html.bold(message.from_user.full_name)}! \n ")


@dp.message(Command('start_process_book'))
async def start_process_book(message: Message):
    """
    """
    keyboard = [[start_process_yes_button, start_process_no_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    await message.answer(
        'Хотите обработать pdf книгу?',
        reply_markup=keyboard
    )


@dp.message(F.text.casefold() == start_process_yes_button.text.casefold())
async def accept_button(message: Message):
    keyboard = [[separate_pages_button, rotate_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
    await message.answer(
        "Как хотите обработать файл?",
        reply_markup=keyboard
    )


@separate_pages_router.message(
    SeparatePageDocument.separate_strongly,
    F.text.casefold() == separate_strongly_button.text.casefold())
@dp.message(RotatePageDocument.rotate_direction)
@dp.message(SeparatePageDocument.reserve_percent)
async def separate_pages_strongly(message: Message, state: FSMContext):
    current_state = await state.get_state()
    stategroup_state_name = current_state.split(':')
    state_group, state_name = stategroup_state_name[0], stategroup_state_name[1]
    await state.update_data({state_name: message.text})
    print(await state.get_data())
    if state_group == 'SeparatePageDocument':
        await state.set_state(SeparatePageDocument.get_file)
    else:
        await state.set_state(RotatePageDocument.get_file)
    await message.answer(
        'Отправьте документ'
    )


@dp.message(SeparatePageDocument.get_file, F.document)
async def process_separate_file(message: Message, state: FSMContext):
    pdf_file = await bot.download(message.document)
    fsm_data = await state.get_data()
    new = separate_pdf(
        pdf_file, fsm_data['separate_orientation'],
        fsm_data['separate_strongly'], fsm_data.get('reserve_percent', 0))

    result = BufferedInputFile(new.getbuffer().tobytes(), 'new.pdf')
    await message.reply_document(result)
    state.clear()
    await message.answer(
        'Готово!'
    )


@dp.message(RotatePageDocument.get_file, F.document)
async def process_file(message: Message, state: FSMContext):
    pdf_file = await bot.download(message.document)
    fsm_data = await state.get_data()
    new = rotate_pdf(pdf_file, fsm_data['rotate_direction'])

    result = BufferedInputFile(new.getbuffer().tobytes(), 'new.pdf')
    await message.reply_document(result)
    state.clear()
    await message.answer(
        'Готово!'
    )


async def main() -> None:
    # Initialize Bot instance with default bot properties which will be passed to all API calls
    # And the run events dispatching
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
