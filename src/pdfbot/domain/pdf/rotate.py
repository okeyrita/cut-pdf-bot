"""Rotate every page by 90 degrees."""

import logging
from pathlib import Path

from pypdf import PdfWriter

from pdfbot.domain.models import RotateOptions
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.progress import ProgressReporter


logger = logging.getLogger(__name__)


def rotate_pdf(
    source: Path,
    output: Path,
    options: RotateOptions,
    reporter: ProgressReporter | None = None,
) -> Path:
    """Write a copy of ``source`` with every page rotated.

    Rotation is metadata (``/Rotate``), not a content transform, so this is fast and lossless
    regardless of page count.
    """
    reader = open_reader(source)
    writer = PdfWriter()
    degrees = options.degrees

    logger.info("rotating %s (%d pages) by %d°", source.name, len(reader.pages), degrees)

    for page in reader.pages:
        writer.add_page(page).rotate(degrees)
        if reporter is not None:
            reporter.advance()

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)
    writer.close()
    reader.close()

    if reporter is not None:
        reporter.finish()
    return output
