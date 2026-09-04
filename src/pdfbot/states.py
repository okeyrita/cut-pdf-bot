"""FSM states.

Deliberately one flat :class:`~aiogram.fsm.state.StatesGroup` rather than one group per operation:
``/cancel`` and the "which step am I on" middleware both need to reason about every state at once,
and the chosen :class:`~pdfbot.enums.Operation` lives in FSM *data* rather than in the state name.
"""

from aiogram.fsm.state import State, StatesGroup


class Flow(StatesGroup):
    """Every step of every operation."""

    choosing_operation = State()

    # split
    split_orientation = State()
    split_mode = State()
    split_reserve = State()

    # rotate
    rotate_direction = State()

    # compress
    compress_level = State()

    # ocr
    ocr_language = State()

    # extract
    extract_format = State()

    # shared tail
    waiting_file = State()
    """Single-document operations park here until a valid PDF arrives."""

    merge_collecting = State()
    """Merge parks here, accumulating documents, until the user presses "готово"."""

    processing = State()
    """A Celery job is in flight. Only ``/cancel`` is accepted."""


#: Keys written into FSM data. Collected here so handlers and tests agree on spelling.
DATA_OPERATION = "operation"
DATA_TASK_ID = "task_id"
DATA_JOB_ID = "job_id"
DATA_PROGRESS_MESSAGE_ID = "progress_message_id"
DATA_FILES = "files"
DATA_ORIENTATION = "orientation"
DATA_SPLIT_MODE = "split_mode"
DATA_RESERVE_PERCENT = "reserve_percent"
DATA_ROTATE_DIRECTION = "rotate_direction"
DATA_COMPRESS_LEVEL = "compress_level"
DATA_OCR_LANG = "ocr_lang"
DATA_EXPORT_FORMAT = "export_format"
