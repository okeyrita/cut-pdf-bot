"""Validate and describe a PDF before doing any real work.

Every entry point funnels through :func:`probe`, so a broken upload fails once, early, with a
specific error -- rather than blowing up deep inside a worker the way the original code did when
``PdfReader`` met a non-PDF.
"""

import logging
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pdfbot.domain.errors import (
    EncryptedPdfError,
    InvalidPdfError,
    TooLargeError,
    TooManyPagesError,
)
from pdfbot.domain.models import PdfInfo


logger = logging.getLogger(__name__)

#: Every PDF starts with this. Cheapest possible rejection of "user sent a .docx renamed to .pdf".
PDF_MAGIC = b"%PDF-"

#: How many pages to sample when guessing whether a text layer exists.
_TEXT_SAMPLE_PAGES = 5

#: Total stripped characters across sampled pages above which we call it a real text layer.
#: A scan usually yields 0; OCR'd or born-digital pages yield hundreds.
_TEXT_LAYER_THRESHOLD = 50


def has_pdf_magic(path: Path) -> bool:
    """True if the file begins with ``%PDF-``.

    Some generators emit junk before the header, so a false here is a strong signal but
    :func:`probe` still lets ``pypdf`` have the final say.
    """
    try:
        with path.open("rb") as fh:
            return fh.read(len(PDF_MAGIC)) == PDF_MAGIC
    except OSError:
        return False


def detect_text_layer(reader: PdfReader, sample_pages: int = _TEXT_SAMPLE_PAGES) -> bool:
    """Guess whether the document already carries extractable text.

    Samples pages spread across the document rather than the first few: title pages and scanned
    covers are often blank even in documents that do have text.
    """
    total = len(reader.pages)
    if total == 0:
        return False
    step = max(1, total // sample_pages)
    indices = list(range(0, total, step))[:sample_pages]

    chars = 0
    for index in indices:
        try:
            chars += len(reader.pages[index].extract_text().strip())
        except Exception:
            logger.debug("text extraction failed on page %d during probe", index, exc_info=True)
        if chars >= _TEXT_LAYER_THRESHOLD:
            return True
    return False


def open_reader(path: Path) -> PdfReader:
    """Open a PDF, normalising every failure mode into a domain error.

    Empty-password encrypted PDFs (very common -- owner password set, user password blank) are
    transparently decrypted, since they are readable in every viewer and the user would not
    describe them as "protected".
    """
    if not path.exists():
        raise InvalidPdfError("file does not exist")
    if path.stat().st_size == 0:
        raise InvalidPdfError("file is empty")

    try:
        reader = PdfReader(path, strict=False)
    except PdfReadError as exc:
        raise InvalidPdfError(str(exc)) from exc
    except Exception as exc:
        raise InvalidPdfError(f"{type(exc).__name__}: {exc}") from exc

    if reader.is_encrypted:
        try:
            opened = reader.decrypt("")
        except Exception as exc:
            raise EncryptedPdfError("cannot decrypt") from exc
        if not opened:
            raise EncryptedPdfError("password required")

    # Touching .pages forces the xref parse, so a structurally broken file fails here rather than
    # halfway through processing.
    try:
        _ = len(reader.pages)
    except Exception as exc:
        raise InvalidPdfError(f"unreadable page tree: {exc}") from exc

    return reader


def probe(
    path: Path,
    *,
    max_size_bytes: int | None = None,
    max_pages: int | None = None,
    check_text_layer: bool = True,
) -> PdfInfo:
    """Open, validate and describe a PDF.

    Args:
        path: File to inspect.
        max_size_bytes: Reject anything larger. ``None`` disables the check.
        max_pages: Reject anything longer. ``None`` disables the check.
        check_text_layer: Sample pages for extractable text. Costs a little time; skip it for
            operations that do not care (rotate, compress).

    Raises:
        InvalidPdfError, EncryptedPdfError, TooLargeError, TooManyPagesError
    """
    size = path.stat().st_size if path.exists() else 0
    if max_size_bytes is not None and size > max_size_bytes:
        raise TooLargeError(size, max_size_bytes)

    if not has_pdf_magic(path):
        logger.info("%s has no %%PDF- header; letting pypdf decide", path.name)

    reader = open_reader(path)
    pages = len(reader.pages)
    if pages == 0:
        raise InvalidPdfError("document has no pages")
    if max_pages is not None and pages > max_pages:
        raise TooManyPagesError(pages, max_pages)

    return PdfInfo(
        path=path,
        pages=pages,
        size_bytes=size,
        encrypted=reader.is_encrypted,
        has_text_layer=detect_text_layer(reader) if check_text_layer else False,
    )
