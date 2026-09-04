"""Domain vocabulary.

Every user choice is an enum with a short, stable wire value. These values travel inside Telegram
``callback_data`` (hard 64-byte limit) and inside Celery task payloads, so they are deliberately
terse and must never change without a migration. Human-readable Russian labels live in
:mod:`pdfbot.texts` -- nothing in the domain layer ever compares against display text.
"""

from enum import StrEnum, unique


@unique
class Operation(StrEnum):
    """Top-level thing the user wants done to a PDF."""

    SPLIT = "split"
    ROTATE = "rot"
    MERGE = "mrg"
    COMPRESS = "cmp"
    OCR = "ocr"
    EXTRACT = "ext"

    @property
    def is_multi_file(self) -> bool:
        """Whether this operation collects several documents before running."""
        return self is Operation.MERGE


@unique
class Orientation(StrEnum):
    """Axis along which a page is cut in half."""

    HORIZONTAL = "h"
    """Cut across the page: produces a top half and a bottom half."""

    VERTICAL = "v"
    """Cut down the page: produces a left half and a right half."""


@unique
class SplitMode(StrEnum):
    """Whether the two halves overlap."""

    STRICT = "s"
    """Cut exactly at the midpoint; the halves do not overlap."""

    RESERVE = "r"
    """Extend each half past the midpoint by a percentage, so nothing is clipped mid-line."""


@unique
class RotateDirection(StrEnum):
    """Direction of a 90-degree page rotation."""

    CW = "cw"
    CCW = "ccw"

    @property
    def degrees(self) -> int:
        """Angle to hand to ``pypdf``'s ``PageObject.rotate``."""
        return 90 if self is RotateDirection.CW else -90


@unique
class CompressLevel(StrEnum):
    """How aggressively to shrink a PDF.

    ``LOSSLESS`` is a pure pikepdf re-save (object streams + stream compression) and never touches
    image data. The other two downsample images through Ghostscript and do lose quality.
    """

    LOSSLESS = "ll"
    EBOOK = "eb"
    SCREEN = "sc"

    @property
    def is_lossy(self) -> bool:
        return self is not CompressLevel.LOSSLESS

    @property
    def ghostscript_preset(self) -> str:
        """Value for Ghostscript's ``-dPDFSETTINGS``. Only meaningful when :attr:`is_lossy`."""
        match self:
            case CompressLevel.EBOOK:
                return "/ebook"
            case CompressLevel.SCREEN:
                return "/screen"
            case CompressLevel.LOSSLESS:
                raise ValueError("LOSSLESS compression does not run Ghostscript")


@unique
class OcrLang(StrEnum):
    """Tesseract language selection.

    Values are literal tesseract codes, so they pass straight to ``ocrmypdf(language=...)``
    and each one implies a ``tesseract-ocr-<lang>`` system package in the image.
    """

    RUS = "rus"
    ENG = "eng"
    RUS_ENG = "rus+eng"

    @property
    def traineddata(self) -> tuple[str, ...]:
        """Individual tesseract models this selection needs installed."""
        return tuple(self.value.split("+"))


@unique
class ExportFormat(StrEnum):
    """Target format when extracting a PDF's text."""

    TXT = "txt"
    EPUB = "epub"

    @property
    def suffix(self) -> str:
        return f".{self.value}"


@unique
class NavAction(StrEnum):
    """Navigation buttons that are not an operation choice."""

    CANCEL = "x"
    BACK = "b"
    HOME = "h"
    MERGE_DONE = "d"
