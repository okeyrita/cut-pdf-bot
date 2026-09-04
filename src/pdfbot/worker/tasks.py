"""Celery tasks.

Each task is a thin shell: rehydrate the request, open the workspace, call one pure domain
function, publish the outcome. All the interesting logic lives in :mod:`pdfbot.domain`, which knows
nothing about Celery and is tested without it.
"""

import logging
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from celery.exceptions import SoftTimeLimitExceeded
from redis import Redis

from pdfbot.config import Settings, get_settings
from pdfbot.domain.errors import PdfBotError
from pdfbot.domain.models import (
    CompressOptions,
    ExtractOptions,
    OcrOptions,
    RotateOptions,
    SplitOptions,
)
from pdfbot.domain.pdf.compress import compress_pdf
from pdfbot.domain.pdf.extract import extract_text
from pdfbot.domain.pdf.inspect import open_reader
from pdfbot.domain.pdf.merge import merge_pdfs
from pdfbot.domain.pdf.ocr import ocr_pdf
from pdfbot.domain.pdf.rotate import rotate_pdf
from pdfbot.domain.pdf.split import split_pdf
from pdfbot.domain.progress import ProgressReporter
from pdfbot.enums import Operation
from pdfbot.events import EventKind, JobEvent, JobRequest, publish
from pdfbot.storage import JobWorkspace, sweep_stale
from pdfbot.worker.celery_app import app


logger = logging.getLogger(__name__)

#: What a handler returns: the produced file, plus an optional extra line for the user.
HandlerResult = tuple[Path, str | None]


def _require[T](value: T | None, field: str) -> T:
    """Unwrap an operation-specific field the handler cannot run without.

    A missing value means the bot enqueued a malformed request -- a bug, not user error. Raised
    rather than ``assert``ed so it still fires under ``python -O``.
    """
    if value is None:
        raise ValueError(f"job request is missing required field {field!r}")
    return value


@lru_cache(maxsize=1)
def _redis(url: str) -> Redis:
    """One synchronous Redis connection per worker process, reused across tasks."""
    return Redis.from_url(url, decode_responses=True)


class _Emitter:
    """Publishes progress, stage and terminal events for one job."""

    def __init__(self, request: JobRequest, settings: Settings) -> None:
        self._request = request
        self._settings = settings
        self._client = _redis(settings.redis_url)

    def _send(self, **fields: object) -> None:
        event = JobEvent(
            job_id=self._request.job_id,
            chat_id=self._request.chat_id,
            user_id=self._request.user_id,
            message_id=self._request.message_id,
            **fields,
        )
        publish(self._client, self._settings.events_stream, event)

    def progress(self, done: int, total: int) -> None:
        self._send(kind=EventKind.PROGRESS, done=done, total=total)

    def stage(self, name: str) -> None:
        self._send(kind=EventKind.STAGE, stage=name)

    def done(self, path: Path, name: str, caption: str | None = None) -> None:
        self._send(kind=EventKind.DONE, result_path=str(path), result_name=name, caption=caption)

    def error(self, code: str, detail: str = "") -> None:
        self._send(kind=EventKind.ERROR, error_code=code, error_detail=detail)

    def reporter(self, total: int) -> ProgressReporter:
        return ProgressReporter(
            total=total,
            emit=self.progress,
            min_interval=self._settings.progress_min_interval,
            min_ratio=self._settings.progress_min_ratio,
        )


def page_count(path: Path) -> int:
    reader = open_reader(path)
    try:
        return len(reader.pages)
    finally:
        reader.close()


def _result_name(original: str, suffix: str, tag: str) -> str:
    """Name the output after the input, so a user with several books can tell them apart."""
    stem = Path(original).stem[:60] or "document"
    return f"{stem}_{tag}{suffix}"


def _run(
    payload: dict[str, object],
    handler: Callable[[JobRequest, JobWorkspace, _Emitter], HandlerResult],
) -> dict[str, object]:
    """Shared task body: rehydrate, execute, publish, translate failures into ERROR events."""
    settings = get_settings()
    request = JobRequest.model_validate(payload)
    emitter = _Emitter(request, settings)

    logger.info(
        "job start",
        extra={
            "job_id": request.job_id,
            "op": request.operation.value,
            "user_id": request.user_id,
        },
    )

    try:
        workspace = JobWorkspace.attach(settings.jobs_dir, request.job_id)
    except (FileNotFoundError, ValueError) as exc:
        # Almost always means the user cancelled while the job sat in the queue. Nothing to report.
        logger.info("workspace gone for job %s (%s); dropping", request.job_id, exc)
        return {"job_id": request.job_id, "status": "abandoned"}

    try:
        output, caption = handler(request, workspace, emitter)
    except SoftTimeLimitExceeded:
        logger.warning("job %s hit the soft time limit", request.job_id)
        emitter.error("TimeoutError")
        return {"job_id": request.job_id, "status": "timeout"}
    except PdfBotError as exc:
        logger.info("job %s failed: %s", request.job_id, exc)
        emitter.error(type(exc).__name__, str(exc))
        return {"job_id": request.job_id, "status": "failed", "error": type(exc).__name__}
    except Exception as exc:
        logger.exception("job %s crashed", request.job_id)
        emitter.error("UnexpectedError", f"{type(exc).__name__}: {exc}")
        return {"job_id": request.job_id, "status": "crashed"}

    emitter.done(output, _output_filename(request, output), caption)
    logger.info("job done", extra={"job_id": request.job_id, "bytes": output.stat().st_size})
    return {"job_id": request.job_id, "status": "ok", "output": str(output)}


def _output_filename(request: JobRequest, output: Path) -> str:
    return _result_name(request.original_name, output.suffix, _FILENAME_TAGS[request.operation])


#: Suffix added to the output filename, per operation.
_FILENAME_TAGS: dict[Operation, str] = {
    Operation.SPLIT: "split",
    Operation.ROTATE: "rotated",
    Operation.MERGE: "merged",
    Operation.COMPRESS: "compressed",
    Operation.OCR: "ocr",
    Operation.EXTRACT: "text",
}


# --------------------------------------------------------------------------- handlers


def _handle_split(
    request: JobRequest, workspace: JobWorkspace, emitter: _Emitter
) -> HandlerResult:
    orientation = _require(request.orientation, "orientation")
    mode = _require(request.split_mode, "split_mode")
    source = workspace.input_path()
    total = page_count(source)
    reporter = emitter.reporter(total)
    reporter.start()
    options = SplitOptions(orientation=orientation, mode=mode, reserve=request.reserve)
    output = split_pdf(source, workspace.output_path(), options, reporter)
    return output, f"Страниц было: {total}, стало: {total * 2}."


def _handle_rotate(
    request: JobRequest, workspace: JobWorkspace, emitter: _Emitter
) -> HandlerResult:
    direction = _require(request.rotate_direction, "rotate_direction")
    source = workspace.input_path()
    reporter = emitter.reporter(page_count(source))
    reporter.start()
    output = rotate_pdf(source, workspace.output_path(), RotateOptions(direction))
    return output, None


def _handle_merge(
    request: JobRequest,  # noqa: ARG001 - unused here, but all handlers share one signature
    workspace: JobWorkspace,
    emitter: _Emitter,
) -> HandlerResult:
    settings = get_settings()
    sources = workspace.inputs()
    reporter = emitter.reporter(len(sources))
    reporter.start()
    output = merge_pdfs(
        sources, workspace.output_path(), max_files=settings.max_merge_files, reporter=reporter
    )
    return output, f"Объединено файлов: {len(sources)}, страниц: {page_count(output)}."


def _handle_compress(
    request: JobRequest, workspace: JobWorkspace, emitter: _Emitter
) -> HandlerResult:
    level = _require(request.compress_level, "compress_level")
    source = workspace.input_path()
    result = compress_pdf(
        source,
        workspace.output_path(),
        CompressOptions(level=level),
        on_stage=emitter.stage,
    )
    if not result.improved:
        caption = (
            "Сжать заметно не получилось — файл уже хорошо упакован. "
            "Возвращаю исходник без изменений."
        )
    else:
        caption = (
            f"Было: {result.size_before / 1024 / 1024:.2f} МБ → "
            f"стало: {result.size_after / 1024 / 1024:.2f} МБ (−{result.saved_percent}%)."
        )
    return result.output, caption


def _handle_ocr(request: JobRequest, workspace: JobWorkspace, emitter: _Emitter) -> HandlerResult:
    language = _require(request.ocr_lang, "ocr_lang")
    settings = get_settings()
    source = workspace.input_path()
    total = page_count(source)
    reporter = emitter.reporter(total)
    reporter.start()
    output = ocr_pdf(
        source,
        workspace.output_path(),
        OcrOptions(language=language, chunk_pages=settings.ocr_chunk_pages),
        reporter=reporter,
        on_stage=emitter.stage,
    )
    return output, f"Распознано страниц: {total}. Теперь по книге можно искать текст."


def _handle_extract(
    request: JobRequest, workspace: JobWorkspace, emitter: _Emitter
) -> HandlerResult:
    fmt = _require(request.export_format, "export_format")
    source = workspace.input_path()
    reporter = emitter.reporter(page_count(source))
    reporter.start()
    output = extract_text(
        source,
        workspace.output_path(fmt.suffix),
        ExtractOptions(fmt=fmt, title=request.title),
        reporter,
    )
    return output, None


# --------------------------------------------------------------------------- tasks
#
# One task per operation rather than a single dispatcher, so heavy work can be routed to its own
# queue later (`task_routes`) without touching handler code -- OCR in particular deserves its own
# worker pool.


@app.task(name="pdf.split")
def split_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_split)


@app.task(name="pdf.rotate")
def rotate_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_rotate)


@app.task(name="pdf.merge")
def merge_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_merge)


@app.task(name="pdf.compress")
def compress_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_compress)


@app.task(name="pdf.ocr")
def ocr_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_ocr)


@app.task(name="pdf.extract")
def extract_task(payload: dict[str, object]) -> dict[str, object]:
    return _run(payload, _handle_extract)


#: Maps an operation to its registered task name, so the bot does not need a six-way ``if``.
TASK_BY_OPERATION: dict[Operation, str] = {
    Operation.SPLIT: "pdf.split",
    Operation.ROTATE: "pdf.rotate",
    Operation.MERGE: "pdf.merge",
    Operation.COMPRESS: "pdf.compress",
    Operation.OCR: "pdf.ocr",
    Operation.EXTRACT: "pdf.extract",
}


@app.task(name="maintenance.sweep_workspaces")
def sweep_workspaces() -> int:
    """Delete abandoned job directories. Wire to a beat schedule if you run one."""
    settings = get_settings()
    return sweep_stale(settings.jobs_dir, settings.workspace_ttl_seconds)
