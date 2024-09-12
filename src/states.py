from aiogram.fsm.state import State, StatesGroup


class SeparateDocument(StatesGroup):
    separate_page_orientation = State()
    separate_page_strongly = State()


class RotateDocument(StatesGroup):
    rotate_page_counterclockwise = State()
    rotate_page_counterclockwise = State()
