"""Validation of incoming files.

The original bot had no validation at all: a non-PDF raised deep inside ``PdfReader`` and the user
saw nothing. Every rejection path below exists to turn that into a specific message.
"""

from pathlib import Path

import pytest

from pdfbot.domain.errors import (
    EncryptedPdfError,
    InvalidPdfError,
    TooLargeError,
    TooManyPagesError,
)
from pdfbot.domain.pdf.inspect import has_pdf_magic, open_reader, probe
from tests.fixtures.pdf import (
    make_encrypted_pdf,
    make_pdf,
    make_scanned_pdf,
    write_garbage,
)


def test_probe_describes_a_normal_pdf(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=9)
    info = probe(src)
    assert info.pages == 9
    assert info.encrypted is False
    assert info.has_text_layer is True
    assert info.size_bytes > 0
    assert info.size_mb == pytest.approx(info.size_bytes / 1024 / 1024, abs=0.01)


def test_probe_detects_a_missing_text_layer(tmp_path: Path) -> None:
    scan = make_scanned_pdf(tmp_path / "scan.pdf", pages=4)
    assert probe(scan).has_text_layer is False


def test_probe_can_skip_the_text_layer_check(tmp_path: Path) -> None:
    """Rotate and compress do not care, and the check costs a full parse pass."""
    src = make_pdf(tmp_path / "s.pdf", pages=3)
    assert probe(src, check_text_layer=False).has_text_layer is False


def test_rejects_a_non_pdf(tmp_path: Path) -> None:
    junk = write_garbage(tmp_path / "not.pdf")
    assert has_pdf_magic(junk) is False
    with pytest.raises(InvalidPdfError):
        probe(junk)


def test_rejects_an_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(InvalidPdfError):
        probe(empty)


def test_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidPdfError):
        probe(tmp_path / "nope.pdf")


def test_rejects_a_truncated_pdf(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=3)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(src.read_bytes()[:120])
    with pytest.raises(InvalidPdfError):
        probe(broken)


def test_rejects_a_password_protected_pdf(tmp_path: Path) -> None:
    locked = make_encrypted_pdf(tmp_path / "locked.pdf", password="hunter2")
    with pytest.raises(EncryptedPdfError):
        probe(locked)


def test_opens_an_empty_password_pdf(tmp_path: Path) -> None:
    """Owner-password-only PDFs open in every viewer; users would not call them protected."""
    src = make_encrypted_pdf(tmp_path / "open.pdf", password="")
    reader = open_reader(src)
    assert len(reader.pages) >= 1


def test_enforces_the_size_limit(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=3)
    with pytest.raises(TooLargeError) as excinfo:
        probe(src, max_size_bytes=10)
    assert excinfo.value.limit_bytes == 10
    assert excinfo.value.size_bytes == src.stat().st_size


def test_enforces_the_page_limit(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=12)
    with pytest.raises(TooManyPagesError) as excinfo:
        probe(src, max_pages=5)
    assert (excinfo.value.pages, excinfo.value.limit) == (12, 5)


def test_size_check_runs_before_parsing(tmp_path: Path) -> None:
    """A huge file must be rejected without pypdf ever opening it."""
    junk = write_garbage(tmp_path / "big.pdf", b"x" * 5000)
    with pytest.raises(TooLargeError):
        probe(junk, max_size_bytes=100)


def test_accepts_a_single_page_document(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "one.pdf", pages=1)
    assert probe(src).pages == 1


def test_accepts_a_long_document(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "long.pdf", pages=200)
    assert probe(src, max_pages=500).pages == 200
