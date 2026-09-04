"""End-to-end: bot enqueues → RabbitMQ → worker → Redis stream → bot consumes."""

import time
from collections.abc import Awaitable, Iterator
from typing import Any

import pytest
from pypdf import PdfReader
from redis import Redis

from pdfbot.events import JobEvent
from tests.fixtures.pdf import make_pdf


pytestmark = pytest.mark.integration


@pytest.fixture
def celery_worker(worker_env: dict[str, str]) -> Iterator[Any]:
    """A real Celery worker consuming from the real broker."""
    from celery.contrib.testing.worker import start_worker

    from pdfbot.worker.celery_app import app

    app.conf.broker_url = worker_env["CELERY_BROKER_URL"]
    app.conf.result_backend = worker_env["CELERY_RESULT_BACKEND"]

    import pdfbot.worker.tasks  # noqa: F401  - registers the tasks on the app

    with start_worker(app, perform_ping_check=False, shutdown_timeout=30) as worker:
        yield worker


def _drain(client: Redis, stream: str, *, timeout: float = 60.0) -> list[JobEvent]:
    """Read stream entries until a terminal event arrives or the timeout expires."""
    from pdfbot.events import EventKind

    collected: list[JobEvent] = []
    last_id = "0"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        batch = client.xread({stream: last_id}, count=50, block=1000)
        assert not isinstance(batch, Awaitable)  # sync client
        for _name, entries in batch or []:
            for entry_id, fields in entries:
                last_id = entry_id
                collected.append(JobEvent.from_fields(fields))
        if any(e.kind in {EventKind.DONE, EventKind.ERROR} for e in collected):
            break
    return collected


def test_split_job_round_trips_through_the_real_stack(
    celery_worker: Any, worker_env: dict[str, str]
) -> None:
    from pdfbot.config import get_settings
    from pdfbot.enums import Operation, Orientation, SplitMode
    from pdfbot.events import EventKind, JobRequest
    from pdfbot.storage import JobWorkspace
    from pdfbot.worker.tasks import TASK_BY_OPERATION

    settings = get_settings()
    client = Redis.from_url(settings.redis_url, decode_responses=True)

    workspace = JobWorkspace.create(settings.jobs_dir)
    make_pdf(workspace.input_path(), pages=20)

    request = JobRequest(
        job_id=workspace.job_id,
        chat_id=1,
        user_id=2,
        message_id=3,
        operation=Operation.SPLIT,
        original_name="book.pdf",
        orientation=Orientation.HORIZONTAL,
        split_mode=SplitMode.STRICT,
    )

    from pdfbot.worker.celery_app import app

    result = app.send_task(
        TASK_BY_OPERATION[Operation.SPLIT], args=[request.model_dump(mode="json")]
    )
    payload = result.get(timeout=90)
    assert payload["status"] == "ok"

    events = _drain(client, settings.events_stream)
    kinds = [e.kind for e in events]
    assert EventKind.PROGRESS in kinds, "no progress reported over the real stream"
    assert kinds[-1] is EventKind.DONE

    done = events[-1]
    assert done.result_name == "book_split.pdf"
    assert len(PdfReader(done.result_path or "").pages) == 40

    progress = [e for e in events if e.kind is EventKind.PROGRESS]
    assert [e.done for e in progress] == sorted(e.done for e in progress)
    assert progress[-1].done == 20


def test_a_failing_job_publishes_an_error(celery_worker: Any, worker_env: dict[str, str]) -> None:
    from pdfbot.config import get_settings
    from pdfbot.enums import Operation, RotateDirection
    from pdfbot.events import EventKind, JobRequest
    from pdfbot.storage import JobWorkspace
    from pdfbot.worker.celery_app import app
    from pdfbot.worker.tasks import TASK_BY_OPERATION
    from tests.fixtures.pdf import write_garbage

    settings = get_settings()
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    client.delete(settings.events_stream)

    workspace = JobWorkspace.create(settings.jobs_dir)
    write_garbage(workspace.input_path())

    request = JobRequest(
        job_id=workspace.job_id,
        chat_id=1,
        user_id=2,
        message_id=3,
        operation=Operation.ROTATE,
        rotate_direction=RotateDirection.CW,
    )
    app.send_task(TASK_BY_OPERATION[Operation.ROTATE], args=[request.model_dump(mode="json")]).get(
        timeout=60
    )

    events = _drain(client, settings.events_stream)
    assert events[-1].kind is EventKind.ERROR
    assert events[-1].error_code == "InvalidPdfError"
