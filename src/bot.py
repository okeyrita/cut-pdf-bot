import asyncio
import logging
import sys
from os import getenv
import io

from aiogram import Bot, Dispatcher, html, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InputFile, BufferedInputFile

from cutter import separate_pdf_tg_bot

# Bot token can be obtained via https://t.me/BotFather
TOKEN = "7497738699:AAFRh3ULzapyhDw7KfhKZbUl8PGcMhXAAcE"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


class SeparateDocument(StatesGroup):
    separate_page_orientation = State()
    separate_page_strongly = State()


class FormDocument(StatesGroup):
    separate_file_orientation = State()
    separate_file_strongly = State()


start_process_yes_button = KeyboardButton(text="Да, запустить")
continue_process_button = KeyboardButton(text="Продолжить обработку")
start_process_no_button = KeyboardButton(text="Нет")
complete_process_button = KeyboardButton(text="Завершить обработку")

separate_pages_button = KeyboardButton(text="Разделить страницы книги")
rotate_button = KeyboardButton(text="Повернуть страницы книги")

separate_vertical_button = KeyboardButton(text="горизонтально")
separate_horizontal_button = KeyboardButton(text="Вертикально")

separate_strongly_button = KeyboardButton(text="строго")
separate_with_reserve_button = KeyboardButton(text="с запасом")


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
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите обработать pdf книгу?',
        reply_markup=keyboard
    )


@dp.message(F.text.casefold() == start_process_yes_button.text.casefold())
async def accept_button(message: Message):
    keyboard = [[separate_pages_button, rotate_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        "Как хотите обработать файл?",
        reply_markup=keyboard
    )


@dp.message(F.text.casefold() == separate_pages_button.text.casefold())
async def separate_pages_file(message: Message, state: FSMContext):
    await state.set_state(SeparateDocument.separate_page_orientation)
    keyboard = [[separate_vertical_button, separate_horizontal_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы вертикально или горизонтально?',
        reply_markup=keyboard
    )


@dp.message(SeparateDocument.separate_page_orientation, F.text.casefold() == separate_vertical_button.text.casefold())
@dp.message(SeparateDocument.separate_page_orientation, F.text.casefold() == separate_horizontal_button.text.casefold())
async def separate_file_strongly(message: Message, state: FSMContext):
    await state.set_state(SeparateDocument.separate_page_strongly)
    keyboard = [[separate_strongly_button, separate_with_reserve_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы строго пополам или с запасом?',
        reply_markup=keyboard
    )


@dp.message(SeparateDocument.separate_page_strongly, F.text.casefold() == separate_strongly_button.text.casefold())
async def separate_pages_strongly(message: Message, state: FSMContext):
    await message.answer(
        'Отправьте документ'
    )


@dp.message(F.document)
async def process_file(message: Message, state: FSMContext):
    # get document
    destination = f"doc.pdf"
    await bot.download(
        message.document,
        destination=destination
    )
    # process document
    new = separate_pdf_tg_bot(destination)
    result = BufferedInputFile(new.getbuffer().tobytes(), 'new.pdf')
    await message.reply_document(result)
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
