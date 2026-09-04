"""PDF builders for tests.

Fixtures are generated at test time rather than checked in as binaries: a 3-page A4 PDF is two
lines of reportlab, and generating it keeps page count, page size and text content as explicit
parameters of each test instead of properties of an opaque blob.
"""

import random
from pathlib import Path

from pypdf import PdfWriter
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


__all__ = [
    "A4",
    "letter",
    "make_encrypted_pdf",
    "make_offset_mediabox_pdf",
    "make_pdf",
    "make_scanned_pdf",
    "write_garbage",
]


def make_pdf(
    path: Path,
    pages: int = 3,
    *,
    pagesize: tuple[float, float] = A4,
    text: str = "Page {n}",
    landscape: bool = False,
) -> Path:
    """A born-digital PDF with real, extractable text on every page.

    Text is drawn in both the top and bottom half so that split tests can tell the halves apart.
    """
    size = (pagesize[1], pagesize[0]) if landscape else pagesize
    width, height = size
    pdf = canvas.Canvas(str(path), pagesize=size)
    for n in range(1, pages + 1):
        pdf.setFont("Helvetica", 14)
        pdf.drawString(20 * mm, height - 30 * mm, f"TOP {text.format(n=n)}")
        pdf.drawString(20 * mm, height / 2 + 10 * mm, f"UPPER-MIDDLE {n}")
        pdf.drawString(20 * mm, height / 2 - 15 * mm, f"LOWER-MIDDLE {n}")
        pdf.drawString(20 * mm, 20 * mm, f"BOTTOM {text.format(n=n)}")
        pdf.drawString(width / 2 + 10 * mm, height / 2, f"RIGHT {n}")
        pdf.showPage()
    pdf.save()
    return path


def make_scanned_pdf(path: Path, pages: int = 2, *, pagesize: tuple[float, float] = A4) -> Path:
    """A PDF with no text layer -- only vector marks, the way a scan behaves.

    Real scans embed a raster image; drawing random lines is far cheaper and is indistinguishable
    for our purposes, since what matters is that ``extract_text()`` comes back empty.
    """
    width, height = pagesize
    rng = random.Random(1234)
    pdf = canvas.Canvas(str(path), pagesize=pagesize)
    for _ in range(pages):
        for _ in range(60):
            x = rng.uniform(20, width - 20)
            y = rng.uniform(20, height - 20)
            pdf.line(x, y, x + rng.uniform(5, 40), y)
        pdf.showPage()
    pdf.save()
    return path


def make_encrypted_pdf(path: Path, password: str = "secret", pages: int = 1) -> Path:
    """A password-protected PDF, for the EncryptedPdfError path."""
    plain = path.with_name(f"_plain_{path.name}")
    make_pdf(plain, pages)
    writer = PdfWriter(clone_from=plain)
    writer.encrypt(password)
    with path.open("wb") as fh:
        writer.write(fh)
    writer.close()
    plain.unlink()
    return path


def make_offset_mediabox_pdf(
    path: Path, pages: int = 1, *, offset: float = 50.0, pagesize: tuple[float, float] = A4
) -> Path:
    """A PDF whose mediabox does not start at (0, 0).

    Imposed and cropped books look like this, and the original implementation assumed an origin of
    (0, 0) -- so this fixture guards the regression directly.
    """
    make_pdf(path, pages, pagesize=pagesize)
    writer = PdfWriter(clone_from=path)
    for page in writer.pages:
        box = page.mediabox
        box.lower_left = (float(box.left) + offset, float(box.bottom) + offset)
        box.upper_right = (float(box.right) + offset, float(box.top) + offset)
    with path.open("wb") as fh:
        writer.write(fh)
    writer.close()
    return path


def write_garbage(path: Path, data: bytes = b"this is definitely not a pdf\n" * 10) -> Path:
    """A file that is not a PDF at all."""
    path.write_bytes(data)
    return path
