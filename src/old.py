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

from cutter import separate_pdf_tg_bot

# Bot token can be obtained via https://t.me/BotFather
TOKEN = "7497738699:AAFRh3ULzapyhDw7KfhKZbUl8PGcMhXAAcE"

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


class FormDocument(StatesGroup):
    separate_file_orientation = State()
    separate_file_strongly = State()


start_process_yes_button = KeyboardButton(text="Да, запустить")
continue_process_button = KeyboardButton(text="Продолжить обработку")
start_process_no_button = KeyboardButton(text="Нет")
complete_process_button = KeyboardButton(text="Завершить обработку")

separate_file_button = KeyboardButton(text="Разделить страницы книги")
rotate_button = KeyboardButton(text="Повернуть страницы книги")

vertical_button = KeyboardButton(text="горизонтально")
horizontal_button = KeyboardButton(text="Вертикально")

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
async def accept_button(message: Message, state: FSMContext):
    await state.set_state(FormDocument.get_file)
    await message.answer("Отправьте файл для обработки")


#@dp.message(F.text.casefold() == continue_process_button.text.casefold())
@dp.message(FormDocument.get_file)
async def file_recieved(message: Message, state: FSMContext):


    '''
    message.document
    print(type(FormDocument.get_file))
    with io.BytesIO() as file_in_io:
        await FormDocument.get_file.download(destination_file=file_in_io)
        file_in_io.seek(0)
    new = separate_pdf_tg_bot(FormDocument.get_file)
    await message.reply_document(new)
    '''
    # документ получен
    #keyboard = [[separate_file_button, rotate_button]]
    #keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    #await message.answer(
    #    'Как хотите обработать файл?',
    #    reply_markup=keyboard
    #)


@dp.message(F.text.casefold() == separate_file_button.text.casefold())
async def separate_file(message: Message, state: FSMContext):
    keyboard = [[vertical_button, horizontal_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы вертикально или горизонтально?',
        reply_markup=keyboard
    )


@dp.message(F.text.casefold() == horizontal_button.text.casefold())
async def separate_file_stringly(message: Message, state: FSMContext):
    keyboard = [[separate_strongly_button, separate_with_reserve_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Хотите разделить страницы строго пополам или с запасом?',
        reply_markup=keyboard
    )


@dp.message(F.text.casefold() == separate_strongly_button.text.casefold())
async def process_separation_pages_file(message: Message, state: FSMContext):
    # TODO: обработка файла
    async with io.BytesIO() as file_in_io:
        await message.photo[-1].download(destination_file=file_in_io)
        file_in_io.seek(0)
    new = separate_pdf_tg_bot(file_in_io)
    await message.reply_document(new)

    keyboard = [[continue_process_button, complete_process_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Файл обработан. Хотите его обработать как то еще?',
        reply_markup=keyboard
    )

@dp.message(F.text.casefold() == complete_process_button.text.casefold())
async def complete_process(message: Message, state: FSMContext):
    # TODO: отправить файл
    keyboard = [[continue_process_button, complete_process_button]]
    keyboard = ReplyKeyboardMarkup(keyboard=keyboard)
    await message.answer(
        'Готово!',
        reply_markup=start_process_book()
    )


async def main() -> None:
    # Initialize Bot instance with default bot properties which will be passed to all API calls

    # And the run events dispatching
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
