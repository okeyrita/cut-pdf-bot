import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher, html, F
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, BufferedInputFile

from cutter import separate_pdf_tg_bot
from handlers.separate_pages import separate_pages_router
from keyboards import start_process_yes_button, start_process_no_button,\
    separate_pages_button, rotate_button
from states import SeparateDocument

# Bot token can be obtained via https://t.me/BotFather
TOKEN = ""


bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(separate_pages_router)


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


@dp.message(SeparateDocument.separate_page_strongly)
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
