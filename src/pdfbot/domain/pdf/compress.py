"""Shrink a PDF.

Two very different mechanisms behind one option:

* ``LOSSLESS`` -- a pikepdf re-save. Rewrites the object structure with object streams and
  compressed streams, drops orphaned objects. Image data is untouched, so quality is identical.
  On a well-produced PDF this often saves nothing at all.
* ``EBOOK`` / ``SCREEN`` -- Ghostscript re-distills the file and downsamples images. This is where
  the real savings are, and it does lose quality.

Neither tool reports per-page progress, so callers get stage callbacks rather than a page counter.
Pretending otherwise would mean showing a fake bar.
"""

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pikepdf

from pdfbot.domain.errors import ProcessingFailedError
from pdfbot.domain.models import CompressOptions, CompressResult
from pdfbot.enums import CompressLevel


logger = logging.getLogger(__name__)

#: Ghostscript binary. Overridden in tests.
GHOSTSCRIPT = "gs"

#: Hard ceiling on a Ghostscript run; the Celery soft time limit is the real backstop.
_GS_TIMEOUT_SECONDS = 1800

StageCallback = Callable[[str], None]


def ghostscript_available(binary: str = GHOSTSCRIPT) -> bool:
    """Whether Ghostscript can be executed. Used to fail fast with a clear message."""
    return shutil.which(binary) is not None


def _compress_lossless(source: Path, target: Path) -> None:
    """Structural re-save via pikepdf. Never touches image data."""
    try:
        with pikepdf.open(source) as pdf:
            pdf.save(
                target,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
                linearize=True,
                recompress_flate=True,
            )
    except pikepdf.PdfError as exc:
        raise ProcessingFailedError("pikepdf", str(exc)) from exc


def _compress_ghostscript(source: Path, target: Path, level: CompressLevel) -> None:
    """Re-distill through Ghostscript at the given quality preset."""
    if not ghostscript_available():
        raise ProcessingFailedError("ghostscript", "binary not found on PATH")

    command = [
        GHOSTSCRIPT,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS={level.ghostscript_preset}",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dSAFER",
        f"-sOutputFile={target}",
        str(source),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_GS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessingFailedError("ghostscript", "timed out") from exc

    if result.returncode != 0:
        raise ProcessingFailedError("ghostscript", result.stderr.strip()[:400])
    if not target.exists() or target.stat().st_size == 0:
        raise ProcessingFailedError("ghostscript", "produced an empty file")


def compress_pdf(
    source: Path,
    output: Path,
    options: CompressOptions,
    on_stage: StageCallback | None = None,
) -> CompressResult:
    """Compress ``source``, falling back to the original when the saving is negligible.

    A "compressed" file the same size as, or larger than, the input is worse than useless:
    it costs the user an upload and quality for nothing. When the saving is below
    ``options.min_saving_ratio`` the result points back at ``source`` and
    :attr:`~pdfbot.domain.models.CompressResult.improved` is ``False``, so the caller can send the
    original and say so.
    """
    size_before = source.stat().st_size
    if on_stage is not None:
        on_stage("compressing")

    output.parent.mkdir(parents=True, exist_ok=True)
    scratch = output.with_suffix(".tmp.pdf")

    try:
        if options.level is CompressLevel.LOSSLESS:
            _compress_lossless(source, scratch)
        else:
            _compress_ghostscript(source, scratch, options.level)

        size_after = scratch.stat().st_size
        saving = 1.0 - (size_after / size_before) if size_before else 0.0
        logger.info(
            "compress %s level=%s: %d -> %d bytes (%.1f%%)",
            source.name,
            options.level.name,
            size_before,
            size_after,
            saving * 100,
        )

        if saving < options.min_saving_ratio:
            return CompressResult(output=source, size_before=size_before, size_after=size_before)

        scratch.replace(output)
        return CompressResult(output=output, size_before=size_before, size_after=size_after)
    finally:
        scratch.unlink(missing_ok=True)
