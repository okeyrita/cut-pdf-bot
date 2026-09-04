"""Typed ``callback_data`` factories.

Telegram caps ``callback_data`` at 64 bytes, and aiogram packs these as ``prefix:field:field``.
Prefixes are therefore two characters and the payloads are enum wire values, which keeps every
packed callback well under the limit -- ``tests/unit/test_callbacks.py`` asserts that.
"""

from aiogram.filters.callback_data import CallbackData

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


class OpCB(CallbackData, prefix="op"):
    """Main menu: which operation to run."""

    value: Operation


class OrientCB(CallbackData, prefix="or"):
    value: Orientation


class SplitModeCB(CallbackData, prefix="sm"):
    value: SplitMode


class RotateCB(CallbackData, prefix="rt"):
    value: RotateDirection


class CompressCB(CallbackData, prefix="cp"):
    value: CompressLevel


class OcrLangCB(CallbackData, prefix="ol"):
    value: OcrLang


class ExportCB(CallbackData, prefix="ef"):
    value: ExportFormat


class NavCB(CallbackData, prefix="nv"):
    """Cancel / back / home / done-collecting-files."""

    action: NavAction
