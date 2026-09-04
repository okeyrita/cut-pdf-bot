"""Cut every page in half.

This is the bot's original reason to exist: a book typeset for A4 spreads is unreadable on a phone,
but each half-page on its own is fine.

Geometry note: the halves are produced by narrowing each page's **boxes**, not by re-rasterising.
Both copies still reference the same content stream, so the output has twice as many pages and is
roughly the size of the input -- splitting never shrinks a file.
"""

import logging
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import RectangleObject

from pdfbot.domain.models import SplitOptions
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.progress import ProgressReporter
from pdfbot.enums import Orientation


logger = logging.getLogger(__name__)


def _set_box(page: object, rect: tuple[float, float, float, float]) -> None:
    """Point both mediabox and cropbox at ``rect``.

    Setting only the mediabox (as the original code did) is not enough: any viewer that honours
    the cropbox keeps rendering the full original page, so the "split" appears to do nothing.
    """
    box = RectangleObject(rect)
    page.mediabox = box  # type: ignore[attr-defined]
    page.cropbox = RectangleObject(rect)  # type: ignore[attr-defined]


def halves(
    left: float, bottom: float, right: float, top: float, options: SplitOptions
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Return the two half-page rectangles, in reading order.

    Rectangles are ``(llx, lly, urx, ury)``. ``reserve`` pushes each half *past* the midpoint by
    that fraction of the page's height (horizontal cut) or width (vertical cut), so a line of text
    sitting exactly on the seam appears complete on both halves instead of being sliced.

    Works off the real box corners rather than assuming an origin at ``(0, 0)`` -- cropped or
    imposed PDFs frequently have a non-zero lower-left corner, which the original code ignored.
    """
    width = right - left
    height = top - bottom

    if options.orientation is Orientation.HORIZONTAL:
        mid = bottom + height / 2
        margin = height * options.reserve
        upper = (left, mid - margin, right, top)
        lower = (left, bottom, right, mid + margin)
        return upper, lower

    mid = left + width / 2
    margin = width * options.reserve
    left_half = (left, bottom, mid + margin, top)
    right_half = (mid - margin, bottom, right, top)
    return left_half, right_half


def split_pdf(
    source: Path,
    output: Path,
    options: SplitOptions,
    reporter: ProgressReporter | None = None,
) -> Path:
    """Write a copy of ``source`` with every page cut in half.

    Args:
        source: Input PDF. Must already have passed :func:`~pdfbot.domain.pdf.inspect.probe`.
        output: Destination path; overwritten if present.
        options: Orientation, mode and reserve fraction.
        reporter: Optional progress sink, ticked once per *source* page.

    Returns:
        ``output``, for chaining.
    """
    reader = open_reader(source)
    writer = PdfWriter()

    logger.info(
        "splitting %s (%d pages) %s reserve=%.3f",
        source.name,
        len(reader.pages),
        options.orientation.name,
        options.reserve,
    )

    for page in reader.pages:
        box = page.mediabox
        first_rect, second_rect = halves(
            float(box.left), float(box.bottom), float(box.right), float(box.top), options
        )
        # add_page deep-copies into the writer, so the two halves are independent objects and we
        # avoid an explicit deepcopy of the page tree per half.
        _set_box(writer.add_page(page), first_rect)
        _set_box(writer.add_page(page), second_rect)
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
