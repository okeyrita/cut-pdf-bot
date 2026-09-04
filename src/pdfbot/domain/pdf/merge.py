"""Concatenate several PDFs into one."""

import logging
from collections.abc import Sequence
from pathlib import Path

from pypdf import PdfWriter

from pdfbot.domain.errors import NotEnoughFilesError, TooManyFilesError
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.progress import ProgressReporter


logger = logging.getLogger(__name__)


def merge_pdfs(
    sources: Sequence[Path],
    output: Path,
    *,
    max_files: int | None = None,
    reporter: ProgressReporter | None = None,
) -> Path:
    """Append ``sources`` into a single PDF, preserving the given order.

    Order is the order the user sent the files in; the caller is responsible for keeping that
    stable, since it is the only thing the user can control about the result.

    Raises:
        NotEnoughFilesError: fewer than two inputs.
        TooManyFilesError: more than ``max_files`` inputs.
    """
    if len(sources) < 2:
        raise NotEnoughFilesError(f"need at least 2 files, got {len(sources)}")
    if max_files is not None and len(sources) > max_files:
        raise TooManyFilesError(len(sources), max_files)

    writer = PdfWriter()
    total_pages = 0

    for source in sources:
        reader = open_reader(source)  # re-validates each input at merge time
        for page in reader.pages:
            writer.add_page(page)
            total_pages += 1
        reader.close()
        if reporter is not None:
            reporter.advance()

    logger.info("merged %d files into %d pages", len(sources), total_pages)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    writer.close()

    if reporter is not None:
        reporter.finish()
    return output
