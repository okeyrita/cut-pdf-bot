"""Enums, callback payloads, labels and keyboards.

These are cheap tests guarding expensive-to-debug mistakes: a callback payload over Telegram's
64-byte limit is silently rejected by the client, and a missing label raises inside a handler.
"""

from enum import StrEnum

import pytest
from aiogram.filters.callback_data import CallbackData

from pdfbot import keyboards, texts
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


LABELLED_ENUMS: list[type[StrEnum]] = [
    Operation,
    Orientation,
    SplitMode,
    RotateDirection,
    CompressLevel,
    OcrLang,
    ExportFormat,
    NavAction,
]

ALL_CALLBACKS: list[tuple[type[CallbackData], type[StrEnum], str]] = [
    (OpCB, Operation, "value"),
    (OrientCB, Orientation, "value"),
    (SplitModeCB, SplitMode, "value"),
    (RotateCB, RotateDirection, "value"),
    (CompressCB, CompressLevel, "value"),
    (OcrLangCB, OcrLang, "value"),
    (ExportCB, ExportFormat, "value"),
    (NavCB, NavAction, "action"),
]


# --------------------------------------------------------------------------- labels


@pytest.mark.parametrize("enum_cls", LABELLED_ENUMS, ids=lambda e: e.__name__)
def test_every_member_has_a_label(enum_cls: type[StrEnum]) -> None:
    """Adding an enum variant without a caption must fail here, not in front of a user."""
    for member in enum_cls:
        assert texts.label(member), f"{enum_cls.__name__}.{member.name} has no label"


def test_labels_do_not_collide_across_enums() -> None:
    """Regression: StrEnum members hash as their string value.

    ``Orientation.HORIZONTAL`` and ``NavAction.HOME`` are both "h", so a single flat
    ``dict[StrEnum, str]`` silently loses one of them -- which is exactly what happened, leaving
    the orientation keyboard showing "В начало" instead of "Горизонтально".
    """
    assert texts.label(Orientation.HORIZONTAL) == "Горизонтально"
    assert texts.label(NavAction.HOME) == "🏠 В начало"
    assert Orientation.HORIZONTAL.value == NavAction.HOME.value == "h"  # the same string


# --------------------------------------------------------------------------- callbacks


@pytest.mark.parametrize(("cb_cls", "enum_cls", "field"), ALL_CALLBACKS, ids=lambda x: str(x))
def test_callbacks_round_trip(
    cb_cls: type[CallbackData], enum_cls: type[StrEnum], field: str
) -> None:
    for member in enum_cls:
        packed = cb_cls(**{field: member}).pack()
        restored = cb_cls.unpack(packed)
        assert getattr(restored, field) is member


@pytest.mark.parametrize(("cb_cls", "enum_cls", "field"), ALL_CALLBACKS, ids=lambda x: str(x))
def test_callbacks_fit_telegrams_64_byte_limit(
    cb_cls: type[CallbackData], enum_cls: type[StrEnum], field: str
) -> None:
    for member in enum_cls:
        packed = cb_cls(**{field: member}).pack()
        assert len(packed.encode("utf-8")) <= 64, f"{packed!r} is too long"


def test_callback_prefixes_are_unique() -> None:
    prefixes = [cb.__prefix__ for cb, _, _ in ALL_CALLBACKS]
    assert len(prefixes) == len(set(prefixes))


# --------------------------------------------------------------------------- keyboards


def test_main_menu_offers_every_operation() -> None:
    markup = keyboards.main_menu()
    payloads = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert len(payloads) == len(Operation)
    for operation in Operation:
        assert OpCB(value=operation).pack() in payloads


@pytest.mark.parametrize(
    "factory",
    [
        keyboards.orientation_kb,
        keyboards.split_mode_kb,
        keyboards.rotate_kb,
        keyboards.compress_kb,
        keyboards.ocr_lang_kb,
        keyboards.export_format_kb,
        keyboards.cancel_kb,
    ],
)
def test_every_choice_screen_offers_cancel(factory: object) -> None:
    """A user must never be stuck on a question with no way out."""
    markup = factory()  # type: ignore[operator]
    payloads = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert NavCB(action=NavAction.CANCEL).pack() in payloads


def test_orientation_keyboard_shows_both_axes() -> None:
    captions = [b.text for row in keyboards.orientation_kb().inline_keyboard for b in row]
    assert "Горизонтально" in captions
    assert "Вертикально" in captions


def test_merge_keyboard_hides_done_until_two_files() -> None:
    done = NavCB(action=NavAction.MERGE_DONE).pack()

    early = keyboards.merge_collecting_kb(can_finish=False)
    assert done not in [b.callback_data for row in early.inline_keyboard for b in row]

    ready = keyboards.merge_collecting_kb(can_finish=True)
    assert done in [b.callback_data for row in ready.inline_keyboard for b in row]


# --------------------------------------------------------------------------- enum behaviour


def test_rotation_degrees() -> None:
    assert RotateDirection.CW.degrees == 90
    assert RotateDirection.CCW.degrees == -90


def test_ghostscript_presets() -> None:
    assert CompressLevel.EBOOK.ghostscript_preset == "/ebook"
    assert CompressLevel.SCREEN.ghostscript_preset == "/screen"
    with pytest.raises(ValueError, match="does not run Ghostscript"):
        _ = CompressLevel.LOSSLESS.ghostscript_preset


def test_lossless_is_not_lossy() -> None:
    assert CompressLevel.LOSSLESS.is_lossy is False
    assert all(level.is_lossy for level in CompressLevel if level is not CompressLevel.LOSSLESS)


def test_ocr_language_splits_into_traineddata() -> None:
    assert OcrLang.RUS_ENG.traineddata == ("rus", "eng")
    assert OcrLang.RUS.traineddata == ("rus",)


def test_only_merge_is_multi_file() -> None:
    assert Operation.MERGE.is_multi_file is True
    assert not any(op.is_multi_file for op in Operation if op is not Operation.MERGE)


def test_export_suffixes() -> None:
    assert ExportFormat.TXT.suffix == ".txt"
    assert ExportFormat.EPUB.suffix == ".epub"
