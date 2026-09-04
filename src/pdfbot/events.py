"""The worker → bot return channel, over a Redis Stream.

Celery carries work *to* the workers. Results come back the other way through this stream, for two
reasons:

* Only the bot process holds a Telegram session, so all rate limiting and all API error handling
  live in exactly one place. A worker that called the Bot API itself would need its own Bot
  instance and its own copy of the local-API-server wiring.
* A **stream with a consumer group**, not pub/sub. Pub/sub is fire-and-forget: any event published
  while the bot is restarting is gone, and the user's progress message freezes at whatever it last
  showed. Stream entries survive, and the bot ``XACK``s only after the Telegram call succeeds, so a
  crash mid-edit is redelivered rather than lost.
"""

import logging
from collections.abc import Mapping
from enum import StrEnum, unique
from typing import Any, Self

from pydantic import BaseModel, Field
from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import ResponseError

from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    OcrLang,
    Operation,
    Orientation,
    RotateDirection,
    SplitMode,
)


logger = logging.getLogger(__name__)

#: Stream entries put the whole JSON payload under one field.
_PAYLOAD_FIELD = "data"


class JobRequest(BaseModel):
    """What the bot hands a Celery task.

    Deliberately only primitives and enums -- never file bytes. The PDF itself lives in the job's
    workspace on the shared volume, addressed by :attr:`job_id`.
    """

    job_id: str
    chat_id: int
    user_id: int
    message_id: int = Field(description="Progress message the worker's events will edit.")
    operation: Operation
    original_name: str = Field(default="document.pdf", description="For naming the result.")

    # split
    orientation: Orientation | None = None
    split_mode: SplitMode | None = None
    reserve: float = 0.0

    # rotate
    rotate_direction: RotateDirection | None = None

    # compress
    compress_level: CompressLevel | None = None

    # ocr
    ocr_lang: OcrLang | None = None

    # extract
    export_format: ExportFormat | None = None
    title: str = "Документ"


@unique
class EventKind(StrEnum):
    PROGRESS = "progress"
    """Countable work advanced: ``done``/``total`` pages."""

    STAGE = "stage"
    """An opaque step started (Ghostscript, OCR) where page counts are meaningless."""

    DONE = "done"
    ERROR = "error"


class JobEvent(BaseModel):
    """One message from a worker about a job.

    Carries the ids the bot needs to find the right chat and message, so the consumer is stateless
    and a restarted bot can pick up mid-job without consulting FSM storage.
    """

    job_id: str
    chat_id: int
    user_id: int
    message_id: int = Field(description="The progress message to edit in place.")
    kind: EventKind

    done: int = 0
    total: int = 0
    stage: str | None = None

    result_path: str | None = None
    result_name: str | None = Field(default=None, description="Filename shown to the user.")
    caption: str | None = None

    error_code: str | None = Field(
        default=None, description="Domain exception class name; the bot maps it to Russian text."
    )
    error_detail: str | None = None

    def to_fields(self) -> dict[Any, Any]:
        return {_PAYLOAD_FIELD: self.model_dump_json()}

    @classmethod
    def from_fields(cls, fields: Mapping[Any, Any]) -> Self:
        raw = fields.get(_PAYLOAD_FIELD) or fields.get(_PAYLOAD_FIELD.encode())
        if raw is None:
            raise ValueError("stream entry has no payload field")
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return cls.model_validate_json(raw)


def publish(client: Redis, stream: str, event: JobEvent, *, maxlen: int = 10_000) -> str:
    """Append an event to the stream (worker side, synchronous).

    Trimmed approximately, so a stalled bot cannot grow the stream without bound. Publishing is
    best-effort: a Redis hiccup must not fail an otherwise successful PDF job, so failures are
    logged and swallowed.
    """
    try:
        return str(client.xadd(stream, event.to_fields(), maxlen=maxlen, approximate=True))
    except Exception:
        logger.warning(
            "could not publish %s event for job %s", event.kind, event.job_id, exc_info=True
        )
        return ""


async def ensure_group(client: AsyncRedis, stream: str, group: str) -> None:
    """Create the consumer group, tolerating "already exists".

    ``mkstream`` means the bot can start before any worker has ever published.
    """
    try:
        await client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        logger.info("created consumer group %s on %s", group, stream)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
