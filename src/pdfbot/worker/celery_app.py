"""Celery application.

RabbitMQ carries the tasks; Redis stores task state. Results are small dicts -- the actual output
PDF stays on the shared volume and is announced through the event stream in :mod:`pdfbot.events`.
"""

from celery import Celery

from pdfbot.config import get_settings
from pdfbot.logging_conf import configure_logging


settings = get_settings()

app = Celery(
    "pdfbot",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["pdfbot.worker.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # A PDF job is long and not idempotent-safe to run twice concurrently, but it IS safe to redo
    # after a crash: the workspace is re-read from scratch. acks_late + prefetch 1 therefore gives
    # us "redeliver on worker death" without a worker hoarding queued jobs it cannot start.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=settings.task_time_limit,
    task_soft_time_limit=settings.task_soft_time_limit,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    worker_hijack_root_logger=False,
    control_queue_durable=True,
    control_queue_exclusive=False,
    event_queue_durable=True,
    event_queue_exclusive=False,
)


@app.on_after_configure.connect
def _setup_logging(**_kwargs: object) -> None:
    configure_logging(settings)
