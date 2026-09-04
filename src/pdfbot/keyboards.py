"""Inline keyboard builders.

Every button carries a packed :mod:`pdfbot.callbacks` payload. There are no reply keyboards, no
text-matching filters anywhere in the bot. Captions come from :data:`pdfbot.texts.LABELS`, so this
module is the only place that joins a wire value to something a human reads.
"""

from collections.abc import Iterable, Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from pdfbot.callbacks import (
    CompressCB,
    ExportCB,
    NavCB,
    OcrLangCB,
    OpCB,
    OrientCB,
    RotateCB,
    SplitModeCB,
)
from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    NavAction,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)
from pdfbot.texts import label


def _build(
    rows: Iterable[Sequence[tuple[str, CallbackData]]],
    *,
    nav: Sequence[NavAction] = (NavAction.CANCEL,),
) -> InlineKeyboardMarkup:
    """Assemble a keyboard from explicit rows, appending a navigation row.

    Rows are laid out exactly as given rather than through ``adjust()`` so that captions of very
    different lengths do not end up sharing a row.
    """
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=text, callback_data=cb.pack()) for text, cb in row]
        for row in rows
    ]
    if nav:
        keyboard.append(
            [
                InlineKeyboardButton(text=label(action), callback_data=NavCB(action=action).pack())
                for action in nav
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def main_menu() -> InlineKeyboardMarkup:
    """The six operations, one per row."""
    return _build(
        [[(label(op), OpCB(value=op))] for op in Operation],
        nav=(),
    )


def orientation_kb() -> InlineKeyboardMarkup:
    return _build(
        [
            [
                (label(Orientation.HORIZONTAL), OrientCB(value=Orientation.HORIZONTAL)),
                (label(Orientation.VERTICAL), OrientCB(value=Orientation.VERTICAL)),
            ]
        ]
    )


def split_mode_kb() -> InlineKeyboardMarkup:
    return _build(
        [
            [
                (label(SplitMode.STRICT), SplitModeCB(value=SplitMode.STRICT)),
                (label(SplitMode.RESERVE), SplitModeCB(value=SplitMode.RESERVE)),
            ]
        ]
    )


def rotate_kb() -> InlineKeyboardMarkup:
    return _build(
        [
            [(label(RotateDirection.CW), RotateCB(value=RotateDirection.CW))],
            [(label(RotateDirection.CCW), RotateCB(value=RotateDirection.CCW))],
        ]
    )


def compress_kb() -> InlineKeyboardMarkup:
    return _build([[(label(level), CompressCB(value=level))] for level in CompressLevel])


def ocr_lang_kb() -> InlineKeyboardMarkup:
    return _build([[(label(lang), OcrLangCB(value=lang))] for lang in OcrLang])


def export_format_kb() -> InlineKeyboardMarkup:
    return _build(
        [
            [
                (label(ExportFormat.TXT), ExportCB(value=ExportFormat.TXT)),
                (label(ExportFormat.EPUB), ExportCB(value=ExportFormat.EPUB)),
            ]
        ]
    )


def cancel_kb() -> InlineKeyboardMarkup:
    """Shown while waiting for a file or while a job runs."""
    return _build([], nav=(NavAction.CANCEL,))


def merge_collecting_kb(*, can_finish: bool) -> InlineKeyboardMarkup:
    """Merge screen: "готово" only appears once enough files have arrived."""
    nav = (NavAction.MERGE_DONE, NavAction.CANCEL) if can_finish else (NavAction.CANCEL,)
    return _build([], nav=nav)
