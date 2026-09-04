"""Celery task bodies, exercised directly.

Calling the task functions rather than dispatching them keeps this fast and broker-free while still
covering everything that is genuinely worker-side: workspace handling, the domain call, the events
published, and how failures are translated. The broker itself is covered in
``tests/integration/``.
"""

from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfReader

from pdfbot.config import Settings
from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)
from pdfbot.events import EventKind, JobEvent, JobRequest
from pdfbot.storage import JobWorkspace
from pdfbot.worker import tasks
from pdfbot.worker.celery_app import app as celery_app
from tests.fixtures.pdf import make_pdf, make_scanned_pdf, write_garbage


class FakeStreamRedis:
    """Captures everything published to the event stream."""

    def __init__(self) -> None:
        self.events: list[JobEvent] = []

    def xadd(self, stream: str, fields: dict[str, str], **kwargs: Any) -> str:
        self.events.append(JobEvent.from_fields(fields))
        return "1-0"

    def kinds(self) -> list[EventKind]:
        return [e.kind for e in self.events]

    def last(self) -> JobEvent:
        return self.events[-1]


@pytest.fixture
def stream(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> FakeStreamRedis:
    fake = FakeStreamRedis()
    monkeypatch.setattr(tasks, "_redis", lambda url: fake)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    return fake


@pytest.fixture
def workspace(settings: Settings) -> JobWorkspace:
    return JobWorkspace.create(settings.jobs_dir)


def payload_for(workspace: JobWorkspace, operation: Operation, **kwargs: Any) -> dict[str, object]:
    return JobRequest(
        job_id=workspace.job_id,
        chat_id=1,
        user_id=USER,
        message_id=99,
        operation=operation,
        original_name="Мояя книга.pdf",
        **kwargs,
    ).model_dump(mode="json")


USER = 555


# --------------------------------------------------------------------------- happy paths


def test_split_task_writes_output_and_reports_progress(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    make_pdf(workspace.input_path(), pages=10)
    result = tasks.split_task(
        payload_for(
            workspace,
            Operation.SPLIT,
            orientation=Orientation.HORIZONTAL,
            split_mode=SplitMode.STRICT,
        )
    )

    assert result["status"] == "ok"
    output = Path(str(result["output"]))
    assert len(PdfReader(output).pages) == 20

    assert EventKind.PROGRESS in stream.kinds()
    assert stream.last().kind is EventKind.DONE
    assert stream.last().result_path == str(output)
    # Output is named after the input so a user with several books can tell them apart.
    assert stream.last().result_name == "Мояя книга_split.pdf"


def test_progress_events_are_monotonic_and_end_at_total(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    make_pdf(workspace.input_path(), pages=40)
    tasks.split_task(
        payload_for(
            workspace,
            Operation.SPLIT,
            orientation=Orientation.VERTICAL,
            split_mode=SplitMode.STRICT,
        )
    )
    progress = [e for e in stream.events if e.kind is EventKind.PROGRESS]
    assert progress, "no progress reported"
    assert [e.done for e in progress] == sorted(e.done for e in progress)
    assert progress[-1].done == progress[-1].total == 40
    # Throttling must keep this well below one event per page.
    assert len(progress) < 40


def test_rotate_task(workspace: JobWorkspace, stream: FakeStreamRedis) -> None:
    make_pdf(workspace.input_path(), pages=3)
    result = tasks.rotate_task(
        payload_for(workspace, Operation.ROTATE, rotate_direction=RotateDirection.CCW)
    )
    assert result["status"] == "ok"
    assert all(p.get("/Rotate") == -90 for p in PdfReader(Path(str(result["output"]))).pages)


def test_merge_task_uses_every_input(workspace: JobWorkspace, stream: FakeStreamRedis) -> None:
    make_pdf(workspace.input_path(0), pages=2)
    make_pdf(workspace.input_path(1), pages=3)
    result = tasks.merge_task(payload_for(workspace, Operation.MERGE))
    assert len(PdfReader(Path(str(result["output"]))).pages) == 5
    assert "Объединено файлов: 2" in (stream.last().caption or "")


def test_compress_task_reports_the_saving(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    make_pdf(workspace.input_path(), pages=30)
    result = tasks.compress_task(
        payload_for(workspace, Operation.COMPRESS, compress_level=CompressLevel.LOSSLESS)
    )
    assert result["status"] == "ok"
    caption = stream.last().caption or ""
    assert "МБ" in caption
    assert EventKind.STAGE in stream.kinds()  # compression reports stages, not page counts


def test_extract_task_produces_a_txt(workspace: JobWorkspace, stream: FakeStreamRedis) -> None:
    make_pdf(workspace.input_path(), pages=6)
    result = tasks.extract_task(
        payload_for(workspace, Operation.EXTRACT, export_format=ExportFormat.TXT)
    )
    output = Path(str(result["output"]))
    assert output.suffix == ".txt"
    assert "--- Страница" in output.read_text(encoding="utf-8")
    assert stream.last().result_name == "Мояя книга_text.txt"


def test_extract_task_produces_an_epub(workspace: JobWorkspace, stream: FakeStreamRedis) -> None:
    make_pdf(workspace.input_path(), pages=6)
    result = tasks.extract_task(
        payload_for(workspace, Operation.EXTRACT, export_format=ExportFormat.EPUB)
    )
    assert Path(str(result["output"])).suffix == ".epub"


# --------------------------------------------------------------------------- failure paths


def test_a_broken_input_publishes_a_specific_error(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    write_garbage(workspace.input_path())
    result = tasks.rotate_task(
        payload_for(workspace, Operation.ROTATE, rotate_direction=RotateDirection.CW)
    )
    assert result["status"] == "failed"
    assert stream.last().kind is EventKind.ERROR
    assert stream.last().error_code == "InvalidPdfError"


def test_extracting_from_a_scan_publishes_no_text_layer(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    make_scanned_pdf(workspace.input_path(), pages=3)
    result = tasks.extract_task(
        payload_for(workspace, Operation.EXTRACT, export_format=ExportFormat.TXT)
    )
    assert result["status"] == "failed"
    assert stream.last().error_code == "NoTextLayerError"


def test_an_unexpected_crash_still_tells_the_user(
    workspace: JobWorkspace, stream: FakeStreamRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker bug must surface as a message, not as silence."""
    make_pdf(workspace.input_path(), pages=2)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tasks, "rotate_pdf", boom)
    result = tasks.rotate_task(
        payload_for(workspace, Operation.ROTATE, rotate_direction=RotateDirection.CW)
    )
    assert result["status"] == "crashed"
    assert stream.last().error_code == "UnexpectedError"


def test_a_cancelled_job_is_dropped_silently(settings: Settings, stream: FakeStreamRedis) -> None:
    """/cancel deletes the workspace; a queued task then has nothing to do and must not report."""
    ghost = JobWorkspace.create(settings.jobs_dir)
    payload = payload_for(ghost, Operation.ROTATE, rotate_direction=RotateDirection.CW)
    ghost.cleanup()

    result = tasks.rotate_task(payload)
    assert result["status"] == "abandoned"
    assert stream.events == []  # nothing published: the user already knows they cancelled


def test_a_malformed_job_id_is_rejected(stream: FakeStreamRedis) -> None:
    payload = JobRequest(
        job_id="../../../etc/passwd",
        chat_id=1,
        user_id=USER,
        message_id=1,
        operation=Operation.ROTATE,
        rotate_direction=RotateDirection.CW,
    ).model_dump(mode="json")
    assert tasks.rotate_task(payload)["status"] == "abandoned"


def test_a_missing_operation_field_is_a_crash_not_a_hang(
    workspace: JobWorkspace, stream: FakeStreamRedis
) -> None:
    """Enqueuing without the required option is a bug; the user still gets told."""
    make_pdf(workspace.input_path(), pages=1)
    result = tasks.rotate_task(payload_for(workspace, Operation.ROTATE))  # no direction
    assert result["status"] == "crashed"
    assert stream.last().kind is EventKind.ERROR


def test_ocr_task_surfaces_a_missing_tesseract(
    workspace: JobWorkspace, stream: FakeStreamRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("pdfbot.domain.pdf.ocr.tesseract_available", lambda: False)
    make_pdf(workspace.input_path(), pages=2)
    result = tasks.ocr_task(payload_for(workspace, Operation.OCR, ocr_lang=OcrLang.RUS))
    assert result["status"] == "failed"
    assert stream.last().error_code == "ProcessingFailedError"


def test_every_operation_has_a_task(settings: Settings) -> None:
    for operation in Operation:
        assert operation in tasks.TASK_BY_OPERATION
        assert tasks.TASK_BY_OPERATION[operation] in celery_app.tasks


def test_sweep_task_removes_stale_workspaces(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import time

    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    stale = JobWorkspace.create(settings.jobs_dir)
    old = time.time() - settings.workspace_ttl_seconds - 60
    os.utime(stale.root, (old, old))

    assert tasks.sweep_workspaces() == 1
    assert not stale.root.exists()
