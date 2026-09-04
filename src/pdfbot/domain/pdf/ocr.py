"""Add a searchable text layer to a scanned PDF, via ocrmypdf + tesseract.

**Why this is chunked.** ``ocrmypdf`` exposes no per-page callback -- it is one long opaque call.
Running a 300-page scan through it in a single pass means showing the user a spinner for twenty
minutes with no idea whether anything is happening. So the document is cut into fixed-size chunks,
each chunk is OCR'd, and the results are concatenated. Progress then reflects real completed pages.

The trade-off is honest and worth naming: per-chunk runs cannot optimise across the whole document,
so the output is slightly larger than a single-pass run would be.
"""

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import ocrmypdf
from pypdf import PdfWriter

from pdfbot.domain.errors import EncryptedPdfError, ProcessingFailedError
from pdfbot.domain.models import OcrOptions
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.pdf.merge import merge_pdfs
from pdfbot.domain.progress import ProgressReporter


logger = logging.getLogger(__name__)

StageCallback = Callable[[str], None]


def tesseract_available() -> bool:
    """Whether the tesseract binary is on PATH."""
    return shutil.which("tesseract") is not None


def installed_languages() -> frozenset[str]:
    """Language models tesseract can actually load.

    A missing ``rus`` model is the classic OCR deployment failure: the image builds fine and only
    blows up when a user sends a Russian scan. Checking up front turns that into a clear error.
    """
    if not tesseract_available():
        return frozenset()
    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return frozenset()
    lines = result.stdout.splitlines()[1:]  # first line is a header
    return frozenset(line.strip() for line in lines if line.strip())


def chunk_ranges(total_pages: int, chunk_size: int) -> Iterator[tuple[int, int]]:
    """Yield half-open ``[start, end)`` page-index ranges covering the document."""
    for start in range(0, total_pages, chunk_size):
        yield start, min(start + chunk_size, total_pages)


def _write_page_range(source: Path, target: Path, start: int, end: int) -> Path:
    """Extract pages ``[start, end)`` of ``source`` into a standalone PDF."""
    reader = open_reader(source)
    writer = PdfWriter()
    try:
        for index in range(start, end):
            writer.add_page(reader.pages[index])
        with target.open("wb") as fh:
            writer.write(fh)
    finally:
        writer.close()
        reader.close()
    return target


def _run_ocrmypdf(source: Path, target: Path, options: OcrOptions) -> None:
    """One ocrmypdf invocation, with its exceptions mapped to domain errors."""
    try:
        ocrmypdf.ocr(
            source,
            target,
            # ocrmypdf wants the codes as a sequence; "rus+eng" is tesseract CLI syntax.
            language=list(options.language.traineddata),
            deskew=options.deskew,
            # Pages that already have text are left alone unless the user insists, so re-running a
            # partially-OCR'd book is cheap and non-destructive.
            skip_text=not options.force,
            force_ocr=options.force,
            progress_bar=False,
            optimize=1,
        )
    except ocrmypdf.exceptions.EncryptedPdfError as exc:
        raise EncryptedPdfError("ocrmypdf refused an encrypted PDF") from exc
    except ocrmypdf.exceptions.MissingDependencyError as exc:
        raise ProcessingFailedError("ocrmypdf", f"missing dependency: {exc}") from exc
    except ocrmypdf.exceptions.PriorOcrFoundError as exc:
        raise ProcessingFailedError("ocrmypdf", "document already has OCR") from exc
    except Exception as exc:
        raise ProcessingFailedError("ocrmypdf", f"{type(exc).__name__}: {exc}") from exc


def ocr_pdf(
    source: Path,
    output: Path,
    options: OcrOptions,
    reporter: ProgressReporter | None = None,
    on_stage: StageCallback | None = None,
) -> Path:
    """Produce a copy of ``source`` with a searchable text layer.

    Raises:
        ProcessingFailedError: tesseract missing, a required language model absent, or an
            ocrmypdf failure.
    """
    if not tesseract_available():
        raise ProcessingFailedError("tesseract", "binary not found on PATH")

    available = installed_languages()
    missing = [lang for lang in options.language.traineddata if lang not in available]
    if available and missing:
        raise ProcessingFailedError("tesseract", f"missing language data: {', '.join(missing)}")

    reader = open_reader(source)
    total_pages = len(reader.pages)
    reader.close()

    output.parent.mkdir(parents=True, exist_ok=True)
    if on_stage is not None:
        on_stage("ocr")

    # Short documents finish fast enough that chunking only costs quality.
    if total_pages <= options.chunk_pages:
        _run_ocrmypdf(source, output, options)
        if reporter is not None:
            reporter.finish()
        return output

    with tempfile.TemporaryDirectory(prefix="pdfbot-ocr-") as tmpdir:
        tmp = Path(tmpdir)
        chunk_outputs: list[Path] = []
        for index, (start, end) in enumerate(chunk_ranges(total_pages, options.chunk_pages)):
            chunk_in = _write_page_range(source, tmp / f"in_{index:04d}.pdf", start, end)
            chunk_out = tmp / f"out_{index:04d}.pdf"
            _run_ocrmypdf(chunk_in, chunk_out, options)
            chunk_outputs.append(chunk_out)
            if reporter is not None:
                reporter.advance(end - start)

        logger.info("OCR'd %s in %d chunks", source.name, len(chunk_outputs))
        if on_stage is not None:
            on_stage("building")
        merge_pdfs(chunk_outputs, output)

    if reporter is not None:
        reporter.finish()
    return output
