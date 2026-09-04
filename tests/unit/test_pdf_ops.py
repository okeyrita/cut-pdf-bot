"""Rotate, merge, compress, extract and OCR chunking."""

import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdfbot.domain.errors import (
    NotEnoughFilesError,
    NoTextLayerError,
    ProcessingFailedError,
    TooManyFilesError,
)
from pdfbot.domain.models import (
    CompressOptions,
    ExtractOptions,
    OcrOptions,
    RotateOptions,
)
from pdfbot.domain.pdf.compress import compress_pdf, ghostscript_available
from pdfbot.domain.pdf.extract import extract_text, iter_page_text
from pdfbot.domain.pdf.merge import merge_pdfs
from pdfbot.domain.pdf.ocr import chunk_ranges, ocr_pdf
from pdfbot.domain.pdf.rotate import rotate_pdf
from pdfbot.domain.progress import ProgressReporter
from pdfbot.enums import CompressLevel, ExportFormat, OcrLang, RotateDirection
from tests.fixtures.pdf import make_pdf, make_scanned_pdf


# --------------------------------------------------------------------------- rotate


@pytest.mark.parametrize(
    ("direction", "expected"), [(RotateDirection.CW, 90), (RotateDirection.CCW, -90)]
)
def test_rotate_sets_the_angle(tmp_path: Path, direction: RotateDirection, expected: int) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=3)
    out = rotate_pdf(src, tmp_path / "o.pdf", RotateOptions(direction))
    pages = PdfReader(out).pages
    assert len(pages) == 3
    assert all(p.get("/Rotate") == expected for p in pages)


def test_rotate_preserves_page_count_and_size(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=4)
    before = PdfReader(src).pages[0].mediabox
    out = rotate_pdf(src, tmp_path / "o.pdf", RotateOptions(RotateDirection.CW))
    after = PdfReader(out).pages[0].mediabox
    # /Rotate is metadata: the box itself must be untouched.
    assert tuple(map(float, before)) == tuple(map(float, after))


# --------------------------------------------------------------------------- merge


def test_merge_concatenates_in_order(tmp_path: Path) -> None:
    a = make_pdf(tmp_path / "a.pdf", pages=2, text="AAA {n}")
    b = make_pdf(tmp_path / "b.pdf", pages=3, text="BBB {n}")
    out = merge_pdfs([a, b], tmp_path / "o.pdf")

    pages = PdfReader(out).pages
    assert len(pages) == 5
    assert "AAA" in pages[0].extract_text()
    assert "BBB" in pages[2].extract_text()


def test_merge_rejects_a_single_file(tmp_path: Path) -> None:
    a = make_pdf(tmp_path / "a.pdf", pages=1)
    with pytest.raises(NotEnoughFilesError):
        merge_pdfs([a], tmp_path / "o.pdf")


def test_merge_enforces_the_file_limit(tmp_path: Path) -> None:
    files = [make_pdf(tmp_path / f"{i}.pdf", pages=1) for i in range(4)]
    with pytest.raises(TooManyFilesError) as excinfo:
        merge_pdfs(files, tmp_path / "o.pdf", max_files=3)
    assert excinfo.value.limit == 3


# --------------------------------------------------------------------------- compress


@pytest.mark.parametrize("level", list(CompressLevel))
def test_compress_produces_a_valid_pdf(tmp_path: Path, level: CompressLevel) -> None:
    if level.is_lossy and not ghostscript_available():
        pytest.skip("ghostscript not installed")
    src = make_pdf(tmp_path / "s.pdf", pages=30)
    result = compress_pdf(src, tmp_path / "o.pdf", CompressOptions(level))
    assert len(PdfReader(result.output).pages) == 30
    assert result.size_after <= result.size_before


def test_compress_returns_the_original_when_it_cannot_help(tmp_path: Path) -> None:
    """An output no smaller than the input must not be passed off as compressed."""
    src = make_pdf(tmp_path / "s.pdf", pages=2)
    # An impossible saving threshold forces the fallback branch deterministically.
    result = compress_pdf(
        src, tmp_path / "o.pdf", CompressOptions(CompressLevel.LOSSLESS, min_saving_ratio=0.999)
    )
    assert result.output == src
    assert result.improved is False
    assert result.saved_percent == 0


def test_compress_reports_stages(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=2)
    stages: list[str] = []
    compress_pdf(
        src, tmp_path / "o.pdf", CompressOptions(CompressLevel.LOSSLESS), on_stage=stages.append
    )
    assert stages == ["compressing"]


# --------------------------------------------------------------------------- extract


def test_extract_txt_has_every_page(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=12)
    out = extract_text(src, tmp_path / "o.txt", ExtractOptions(ExportFormat.TXT))
    body = out.read_text(encoding="utf-8")
    assert body.count("--- Страница") == 12
    assert "TOP Page 1" in body


def test_extract_epub_is_a_readable_zip_with_chapters(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=25)
    out = extract_text(
        src,
        tmp_path / "o.epub",
        ExtractOptions(ExportFormat.EPUB, title="Книга", pages_per_chapter=10),
    )
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
    # 25 pages / 10 per chapter -> 3 chapters
    assert len([n for n in names if "chap_" in n]) == 3
    assert any("nav" in n for n in names)


@pytest.mark.parametrize("fmt", list(ExportFormat))
def test_extract_refuses_a_scan(tmp_path: Path, fmt: ExportFormat) -> None:
    """Handing back an empty file would hide the real problem: the book needs OCR first."""
    scan = make_scanned_pdf(tmp_path / "scan.pdf", pages=3)
    with pytest.raises(NoTextLayerError):
        extract_text(scan, tmp_path / f"o{fmt.suffix}", ExtractOptions(fmt))


def test_extract_escapes_html_in_epub(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=2, text="<script>alert({n})</script>")
    out = extract_text(src, tmp_path / "o.epub", ExtractOptions(ExportFormat.EPUB))
    with zipfile.ZipFile(out) as archive:
        chapter = next(n for n in archive.namelist() if "chap_" in n)
        content = archive.read(chapter).decode()
    assert "<script>" not in content
    assert "&lt;script&gt;" in content


def test_iter_page_text_yields_one_entry_per_page(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=6)
    assert len(list(iter_page_text(src))) == 6


def test_extract_ticks_progress(tmp_path: Path) -> None:
    src = make_pdf(tmp_path / "s.pdf", pages=8)
    reporter = ProgressReporter(total=8, emit=lambda d, t: None, min_interval=0)
    extract_text(src, tmp_path / "o.txt", ExtractOptions(ExportFormat.TXT), reporter)
    assert reporter.done == 8


# --------------------------------------------------------------------------- ocr


@pytest.mark.parametrize(
    ("total", "size", "expected"),
    [
        (25, 10, [(0, 10), (10, 20), (20, 25)]),
        (10, 10, [(0, 10)]),
        (1, 10, [(0, 1)]),
        (0, 10, []),
        (3, 1, [(0, 1), (1, 2), (2, 3)]),
    ],
)
def test_chunk_ranges_tile_the_document(
    total: int, size: int, expected: list[tuple[int, int]]
) -> None:
    ranges = list(chunk_ranges(total, size))
    assert ranges == expected
    # Whatever the split, every page must be covered exactly once.
    assert sum(end - start for start, end in ranges) == total


def test_ocr_fails_clearly_without_tesseract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.tesseract_available", lambda: False)
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    with pytest.raises(ProcessingFailedError) as excinfo:
        ocr_pdf(src, tmp_path / "o.pdf", OcrOptions(OcrLang.RUS))
    assert excinfo.value.tool == "tesseract"


def test_ocr_fails_clearly_on_a_missing_language_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The classic deployment bug: image builds fine, then dies on the first Russian scan."""
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.tesseract_available", lambda: True)
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.installed_languages", lambda: frozenset({"eng"}))
    src = make_pdf(tmp_path / "s.pdf", pages=1)
    with pytest.raises(ProcessingFailedError) as excinfo:
        ocr_pdf(src, tmp_path / "o.pdf", OcrOptions(OcrLang.RUS))
    assert "rus" in excinfo.value.detail


def test_ocr_chunks_long_documents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 25-page book at 10 pages/chunk must call ocrmypdf three times, ticking progress each time.

    ocrmypdf itself is stubbed: what is under test is our chunking and progress accounting, not
    tesseract's accuracy.
    """
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.tesseract_available", lambda: True)
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.installed_languages", lambda: frozenset({"rus"}))

    calls: list[tuple[Path, Path]] = []

    def fake_run(source: Path, target: Path, options: OcrOptions) -> None:
        calls.append((source, target))
        target.write_bytes(source.read_bytes())  # pass the pages through unchanged

    monkeypatch.setattr("pdfbot.domain.pdf.ocr._run_ocrmypdf", fake_run)

    src = make_pdf(tmp_path / "s.pdf", pages=25)
    ticks: list[tuple[int, int]] = []
    reporter = ProgressReporter(total=25, emit=lambda d, t: ticks.append((d, t)), min_interval=0)
    stages: list[str] = []

    out = ocr_pdf(
        src,
        tmp_path / "o.pdf",
        OcrOptions(OcrLang.RUS, chunk_pages=10),
        reporter=reporter,
        on_stage=stages.append,
    )

    assert len(calls) == 3
    assert len(PdfReader(out).pages) == 25  # chunks reassembled without losing pages
    assert ticks[-1] == (25, 25)
    assert stages == ["ocr", "building"]


def test_ocr_skips_chunking_for_short_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.tesseract_available", lambda: True)
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.installed_languages", lambda: frozenset({"rus"}))
    calls: list[Path] = []

    def fake_run(source: Path, target: Path, options: OcrOptions) -> None:
        calls.append(source)
        target.write_bytes(source.read_bytes())

    monkeypatch.setattr("pdfbot.domain.pdf.ocr._run_ocrmypdf", fake_run)

    src = make_pdf(tmp_path / "s.pdf", pages=4)
    ocr_pdf(src, tmp_path / "o.pdf", OcrOptions(OcrLang.RUS, chunk_pages=10))
    assert calls == [src]
