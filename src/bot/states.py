from aiogram.fsm.state import State, StatesGroup


class SeparatePageDocument(StatesGroup):
    separate_orientation = State()
    separate_strongly = State()
    reserve_percent = State()
    get_file = State()


class RotatePageDocument(StatesGroup):
    rotate_direction = State()
    get_file = State()
