"""Pull a PDF's text out into TXT or EPUB.

Only works on documents that already carry a text layer -- born-digital, or previously run through
:mod:`pdfbot.domain.pdf.ocr`. A scan produces empty pages, so the caller is told to OCR first
rather than being handed a 0-byte file.
"""

import html
import logging
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

from ebooklib import epub

from pdfbot.domain.errors import NoTextLayerError
from pdfbot.domain.models import ExtractOptions
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.progress import ProgressReporter
from pdfbot.enums import ExportFormat


logger = logging.getLogger(__name__)

#: Below this many characters across the whole document we call it a scan, not a text PDF.
_MIN_TOTAL_CHARS = 100

#: Two or more newlines separate paragraphs; a single newline is usually just a line wrap.
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")

#: Runs of whitespace inside a paragraph collapse to a single space.
_WHITESPACE = re.compile(r"\s+")


def iter_page_text(source: Path, reporter: ProgressReporter | None = None) -> Iterator[str]:
    """Yield the text of each page in order.

    A page that fails to parse yields an empty string rather than aborting the whole document --
    one malformed page in a 500-page book should not cost the user the other 499.
    """
    reader = open_reader(source)
    try:
        for number, page in enumerate(reader.pages, start=1):
            try:
                yield page.extract_text() or ""
            except Exception:
                logger.warning("could not extract text from page %d of %s", number, source.name)
                yield ""
            if reporter is not None:
                reporter.advance()
    finally:
        reader.close()


def _clean_paragraphs(text: str) -> list[str]:
    """Split a page's text into tidy paragraphs."""
    paragraphs = []
    for chunk in _PARAGRAPH_SPLIT.split(text):
        collapsed = _WHITESPACE.sub(" ", chunk).strip()
        if collapsed:
            paragraphs.append(collapsed)
    return paragraphs


def extract_to_txt(source: Path, output: Path, reporter: ProgressReporter | None = None) -> Path:
    """Write the document's text to a UTF-8 ``.txt``, one form feed between pages."""
    pages = list(iter_page_text(source, reporter))
    total_chars = sum(len(p.strip()) for p in pages)
    if total_chars < _MIN_TOTAL_CHARS:
        raise NoTextLayerError(f"only {total_chars} characters found")

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        for number, text in enumerate(pages, start=1):
            fh.write(f"\n\n--- Страница {number} ---\n\n")
            fh.write(text.strip())
    if reporter is not None:
        reporter.finish()
    return output


def extract_to_epub(
    source: Path,
    output: Path,
    options: ExtractOptions,
    reporter: ProgressReporter | None = None,
) -> Path:
    """Build an EPUB, grouping ``options.pages_per_chapter`` PDF pages into each chapter.

    PDFs carry no chapter structure, so any chaptering is a guess; fixed-size groups at least give
    e-readers usable navigation points instead of one enormous document.
    """
    pages = list(iter_page_text(source, reporter))
    total_chars = sum(len(p.strip()) for p in pages)
    if total_chars < _MIN_TOTAL_CHARS:
        raise NoTextLayerError(f"only {total_chars} characters found")

    book = epub.EpubBook()
    book.set_identifier(f"pdfbot-{uuid.uuid4()}")
    book.set_title(options.title)
    book.set_language("ru")

    chapters = []
    for start in range(0, len(pages), options.pages_per_chapter):
        group = pages[start : start + options.pages_per_chapter]
        first_page = start + 1
        last_page = start + len(group)
        title = (
            f"Страницы {first_page}–{last_page}"
            if last_page > first_page
            else f"Страница {first_page}"
        )

        body = [f"<h2>{html.escape(title)}</h2>"]
        for text in group:
            body.extend(f"<p>{html.escape(p)}</p>" for p in _clean_paragraphs(text))

        chapter = epub.EpubHtml(
            title=title,
            file_name=f"chap_{first_page:05d}.xhtml",
            lang="ru",
        )
        chapter.content = "".join(body)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *chapters]

    output.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(output), book)
    logger.info("built EPUB %s with %d chapters", output.name, len(chapters))

    if reporter is not None:
        reporter.finish()
    return output


def extract_text(
    source: Path,
    output: Path,
    options: ExtractOptions,
    reporter: ProgressReporter | None = None,
) -> Path:
    """Dispatch to the TXT or EPUB writer based on ``options.fmt``."""
    if options.fmt is ExportFormat.TXT:
        return extract_to_txt(source, output, reporter)
    return extract_to_epub(source, output, options, reporter)
