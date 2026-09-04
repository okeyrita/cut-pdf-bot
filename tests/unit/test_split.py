"""Split geometry.

The original implementation had two defects this file pins down permanently:

1. The caller passed ``separate_orientation`` into the ``separate_strongly`` slot, so the
   horizontal branch was unreachable and *every* split came out vertical.
2. Geometry assumed the mediabox started at ``(0, 0)``, which is false for cropped or imposed PDFs.
"""

from pathlib import Path

import pytest
from pypdf import PdfReader

from pdfbot.domain.models import SplitOptions
from pdfbot.domain.pdf.split import halves, split_pdf
from pdfbot.domain.progress import ProgressReporter
from pdfbot.enums import Orientation, SplitMode
from tests.fixtures.pdf import A4, make_offset_mediabox_pdf, make_pdf


def _boxes(path: Path) -> list[tuple[float, float, float, float]]:
    return [
        (
            float(p.mediabox.left),
            float(p.mediabox.bottom),
            float(p.mediabox.right),
            float(p.mediabox.top),
        )
        for p in PdfReader(path).pages
    ]


def test_doubles_the_page_count(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=7)
    out = split_pdf(src, tmp_path / "o.pdf", SplitOptions(Orientation.VERTICAL, SplitMode.STRICT))
    assert len(PdfReader(out).pages) == 14


def test_horizontal_split_is_reachable_and_cuts_height(tmp_path: Path) -> None:
    """Regression: the horizontal branch was dead code in the original."""
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    width, height = A4
    out = split_pdf(
        src, tmp_path / "o.pdf", SplitOptions(Orientation.HORIZONTAL, SplitMode.STRICT)
    )

    upper, lower = _boxes(out)
    assert upper == pytest.approx((0, height / 2, width, height))
    assert lower == pytest.approx((0, 0, width, height / 2))


def test_vertical_split_cuts_width(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    width, height = A4
    out = split_pdf(src, tmp_path / "o.pdf", SplitOptions(Orientation.VERTICAL, SplitMode.STRICT))

    left, right = _boxes(out)
    assert left == pytest.approx((0, 0, width / 2, height))
    assert right == pytest.approx((width / 2, 0, width, height))


def test_orientations_produce_different_output(tmp_path: Path) -> None:
    """Directly guards the swapped-argument bug: the two orientations must not coincide."""
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    h = split_pdf(src, tmp_path / "h.pdf", SplitOptions(Orientation.HORIZONTAL, SplitMode.STRICT))
    v = split_pdf(src, tmp_path / "v.pdf", SplitOptions(Orientation.VERTICAL, SplitMode.STRICT))
    assert _boxes(h) != _boxes(v)


@pytest.mark.parametrize("orientation", list(Orientation))
def test_reserve_makes_halves_overlap(tmp_path: Path, orientation: Orientation) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    strict = split_pdf(src, tmp_path / "strict.pdf", SplitOptions(orientation, SplitMode.STRICT))
    loose = split_pdf(
        src,
        tmp_path / "loose.pdf",
        SplitOptions.from_percent(orientation, SplitMode.RESERVE, 10),
    )

    def area(path: Path) -> float:
        left, bottom, right, top = _boxes(path)[0]
        return (right - left) * (top - bottom)

    assert area(loose) > area(strict)


def test_cropbox_follows_mediabox(tmp_path: Path) -> None:
    """A viewer honouring the cropbox would otherwise render the uncut original page."""
    src = make_pdf(tmp_path / "s.pdf", pages=2)
    out = split_pdf(
        src, tmp_path / "o.pdf", SplitOptions(Orientation.HORIZONTAL, SplitMode.STRICT)
    )
    for page in PdfReader(out).pages:
        assert tuple(map(float, page.cropbox)) == tuple(map(float, page.mediabox))


def test_respects_a_non_zero_origin(tmp_path: Path) -> None:
    """Regression: cropped/imposed PDFs do not start at (0, 0)."""
    offset = 50.0
    src = make_offset_mediabox_pdf(tmp_path / "s.pdf", pages=1, offset=offset)
    width, height = A4
    out = split_pdf(
        src, tmp_path / "o.pdf", SplitOptions(Orientation.HORIZONTAL, SplitMode.STRICT)
    )

    upper, lower = _boxes(out)
    mid = offset + height / 2
    assert upper == pytest.approx((offset, mid, offset + width, offset + height))
    assert lower == pytest.approx((offset, offset, offset + width, mid))


def test_halves_is_pure_and_symmetric() -> None:
    """The two halves must exactly tile the page when there is no reserve."""
    options = SplitOptions(Orientation.HORIZONTAL, SplitMode.STRICT)
    upper, lower = halves(0, 0, 100, 200, options)
    assert upper == pytest.approx((0, 100, 100, 200))
    assert lower == pytest.approx((0, 0, 100, 100))
    # No reserve: the halves tile the page exactly, with no gap and no overlap.
    assert upper[1] == pytest.approx(lower[3])


def test_reporter_ticks_once_per_source_page(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=5)
    seen: list[tuple[int, int]] = []
    reporter = ProgressReporter(total=5, emit=lambda d, t: seen.append((d, t)), min_interval=0)
    split_pdf(
        src, tmp_path / "o.pdf", SplitOptions(Orientation.VERTICAL, SplitMode.STRICT), reporter
    )
    assert reporter.done == 5
    assert seen[-1] == (5, 5)
