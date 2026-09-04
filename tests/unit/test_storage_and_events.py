"""Job workspaces, the bot↔worker contract, and option validation."""

import time
from pathlib import Path

import pytest

from pdfbot.domain.models import (
    CompressResult,
    ExtractOptions,
    OcrOptions,
    SplitOptions,
)
from pdfbot.enums import ExportFormat, OcrLang, Operation, Orientation, SplitMode
from pdfbot.events import EventKind, JobEvent, JobRequest
from pdfbot.storage import JobWorkspace, UnsafeJobIdError, new_job_id, sweep_stale


# --------------------------------------------------------------------------- workspaces


def test_create_and_attach_round_trip(tmp_path: Path) -> None:
    created = JobWorkspace.create(tmp_path)
    attached = JobWorkspace.attach(tmp_path, created.job_id)
    assert attached.root == created.root
    assert attached.root.is_dir()


def test_attach_rejects_a_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        JobWorkspace.attach(tmp_path, new_job_id())


@pytest.mark.parametrize(
    "job_id",
    ["../../etc", "..", "a/b", "", "not-hex", "/absolute", "0" * 31, "0" * 33, "../" + "0" * 30],
)
def test_attach_rejects_path_traversal(tmp_path: Path, job_id: str) -> None:
    """Job ids come back from the broker as strings, so they are re-validated before path joins."""
    with pytest.raises(UnsafeJobIdError):
        JobWorkspace.attach(tmp_path, job_id)


def test_inputs_are_returned_in_upload_order(tmp_path: Path) -> None:
    ws = JobWorkspace.create(tmp_path)
    for index in range(12):
        ws.input_path(index).write_bytes(b"%PDF-")
    names = [p.name for p in ws.inputs()]
    # Zero-padded names, so lexical sort is upload order even past nine files.
    assert names == [f"input_{i:03d}.pdf" for i in range(12)]


def test_cleanup_is_idempotent(tmp_path: Path) -> None:
    ws = JobWorkspace.create(tmp_path)
    ws.input_path().write_bytes(b"%PDF-")
    ws.cleanup()
    ws.cleanup()
    assert not ws.root.exists()


def test_output_path_honours_the_suffix(tmp_path: Path) -> None:
    ws = JobWorkspace.create(tmp_path)
    assert ws.output_path().name == "output.pdf"
    assert ws.output_path(".epub").name == "output.epub"


def test_sweep_removes_only_stale_workspaces(tmp_path: Path) -> None:
    fresh = JobWorkspace.create(tmp_path)
    stale = JobWorkspace.create(tmp_path)
    old = time.time() - 7200
    import os

    os.utime(stale.root, (old, old))

    removed = sweep_stale(tmp_path, ttl_seconds=3600)
    assert removed == 1
    assert fresh.root.exists()
    assert not stale.root.exists()


def test_sweep_tolerates_a_missing_directory(tmp_path: Path) -> None:
    assert sweep_stale(tmp_path / "nope", ttl_seconds=1) == 0


# --------------------------------------------------------------------------- events


def test_job_event_survives_the_stream_round_trip() -> None:
    event = JobEvent(
        job_id=new_job_id(),
        chat_id=-100,
        user_id=7,
        message_id=42,
        kind=EventKind.PROGRESS,
        done=45,
        total=120,
    )
    restored = JobEvent.from_fields(event.to_fields())
    assert restored == event


def test_job_event_accepts_bytes_from_redis() -> None:
    """redis-py returns bytes unless decode_responses is set; both must work."""
    event = JobEvent(job_id=new_job_id(), chat_id=1, user_id=2, message_id=3, kind=EventKind.DONE)
    raw = {k.encode(): v.encode() for k, v in event.to_fields().items()}
    assert JobEvent.from_fields(raw) == event


def test_job_event_rejects_a_payload_free_entry() -> None:
    with pytest.raises(ValueError, match="no payload"):
        JobEvent.from_fields({"something": "else"})


def test_job_request_is_json_serialisable() -> None:
    """Celery serialises with JSON, so enums must survive model_dump(mode="json")."""
    request = JobRequest(
        job_id=new_job_id(),
        chat_id=1,
        user_id=2,
        message_id=3,
        operation=Operation.SPLIT,
        orientation=Orientation.HORIZONTAL,
        split_mode=SplitMode.RESERVE,
        reserve=0.05,
    )
    payload = request.model_dump(mode="json")
    assert payload["operation"] == "split"
    assert payload["orientation"] == "h"
    assert JobRequest.model_validate(payload) == request


def test_job_request_defaults_are_none_for_other_operations() -> None:
    request = JobRequest(
        job_id=new_job_id(), chat_id=1, user_id=2, message_id=3, operation=Operation.ROTATE
    )
    assert request.orientation is None
    assert request.ocr_lang is None
    assert request.reserve == 0.0


# --------------------------------------------------------------------------- options


def test_split_options_convert_percent_to_fraction() -> None:
    options = SplitOptions.from_percent(Orientation.VERTICAL, SplitMode.RESERVE, 7.5)
    assert options.reserve == pytest.approx(0.075)


def test_strict_split_ignores_any_percent() -> None:
    options = SplitOptions.from_percent(Orientation.VERTICAL, SplitMode.STRICT, 50)
    assert options.reserve == 0.0


def test_strict_split_rejects_an_explicit_reserve() -> None:
    with pytest.raises(ValueError, match="strict split"):
        SplitOptions(Orientation.VERTICAL, SplitMode.STRICT, reserve=0.1)


@pytest.mark.parametrize("percent", [-1, 101, 1000])
def test_split_options_reject_out_of_range_percentages(percent: float) -> None:
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        SplitOptions.from_percent(Orientation.VERTICAL, SplitMode.RESERVE, percent)


def test_ocr_options_reject_a_zero_chunk() -> None:
    with pytest.raises(ValueError, match="chunk_pages"):
        OcrOptions(OcrLang.RUS, chunk_pages=0)


def test_extract_options_reject_a_zero_chapter_size() -> None:
    with pytest.raises(ValueError, match="pages_per_chapter"):
        ExtractOptions(ExportFormat.EPUB, pages_per_chapter=0)


def test_compress_result_reports_the_saving() -> None:
    result = CompressResult(output=Path("o.pdf"), size_before=1000, size_after=250)
    assert result.saved_percent == 75
    assert result.improved is True


def test_compress_result_with_no_saving() -> None:
    result = CompressResult(output=Path("o.pdf"), size_before=1000, size_after=1000)
    assert result.saved_percent == 0
    assert result.improved is False


def test_compress_result_handles_a_zero_byte_input() -> None:
    result = CompressResult(output=Path("o.pdf"), size_before=0, size_after=0)
    assert result.saved_ratio == 0.0
