"""The Redis Stream consumer against a real Redis.

Consumer groups, ``XACK`` and ``XAUTOCLAIM`` are exactly the parts a fake cannot validate: their
semantics live in the server. This is where the "a restarted bot picks a job back up" claim is
actually proven.
"""

from typing import Any

import pytest
from aiogram.fsm.storage.memory import MemoryStorage
from redis import Redis
from redis.asyncio import Redis as AsyncRedis

from pdfbot.config import Settings
from pdfbot.events import EventKind, JobEvent, ensure_group, publish
from pdfbot.tg.progress import ProgressConsumer
from tests.fixtures.telegram import RecordingSession, make_bot


pytestmark = pytest.mark.integration


@pytest.fixture
def stream_settings(worker_env: dict[str, str], settings: Settings) -> Settings:
    """Test settings pointed at the real Redis container, with a per-test stream name."""
    import uuid

    return settings.model_copy(
        update={
            "redis_url": worker_env["REDIS_URL"],
            "events_stream": f"test:events:{uuid.uuid4().hex}",
            "events_group": "test-group",
        }
    )


def make_event(kind: EventKind, **kwargs: Any) -> JobEvent:
    return JobEvent(job_id="0" * 32, chat_id=1, user_id=2, message_id=3, kind=kind, **kwargs)


async def test_consumer_group_reads_and_acknowledges(stream_settings: Settings) -> None:
    sync = Redis.from_url(stream_settings.redis_url, decode_responses=True)
    client: AsyncRedis = AsyncRedis.from_url(stream_settings.redis_url, decode_responses=True)
    session = RecordingSession()
    bot = make_bot(session)

    await ensure_group(client, stream_settings.events_stream, stream_settings.events_group)
    publish(sync, stream_settings.events_stream, make_event(EventKind.PROGRESS, done=5, total=10))

    consumer = ProgressConsumer(bot, client, stream_settings, MemoryStorage())
    batch = await client.xreadgroup(
        groupname=stream_settings.events_group,
        consumername="test-1",
        streams={stream_settings.events_stream: ">"},
        count=10,
        block=2000,
    )
    assert batch, "consumer group returned nothing"

    for _name, entries in batch:
        for entry_id, fields in entries:
            await consumer._process(entry_id, fields)

    # Everything acknowledged: nothing left pending for this group.
    pending = await client.xpending(stream_settings.events_stream, stream_settings.events_group)
    assert pending["pending"] == 0
    assert "5/10 стр." in session.texts[0]

    await client.aclose()


async def test_unacknowledged_entries_are_reclaimed(stream_settings: Settings) -> None:
    """The restart guarantee: an entry read but never acked comes back to the next consumer."""
    sync = Redis.from_url(stream_settings.redis_url, decode_responses=True)
    client: AsyncRedis = AsyncRedis.from_url(stream_settings.redis_url, decode_responses=True)

    await ensure_group(client, stream_settings.events_stream, stream_settings.events_group)
    publish(sync, stream_settings.events_stream, make_event(EventKind.PROGRESS, done=1, total=4))

    # A "crashed" bot: reads the entry, never acknowledges it.
    await client.xreadgroup(
        groupname=stream_settings.events_group,
        consumername="dead-bot",
        streams={stream_settings.events_stream: ">"},
        count=10,
    )
    pending = await client.xpending(stream_settings.events_stream, stream_settings.events_group)
    assert pending["pending"] == 1

    session = RecordingSession()
    consumer = ProgressConsumer(
        make_bot(session), client, stream_settings, MemoryStorage(), consumer_name="fresh-bot"
    )
    # min_idle_time is 60s in production; reclaim immediately here.
    cursor, entries, _ = await client.xautoclaim(
        name=stream_settings.events_stream,
        groupname=stream_settings.events_group,
        consumername="fresh-bot",
        min_idle_time=0,
        count=10,
    )
    assert len(entries) == 1
    for entry_id, fields in entries:
        await consumer._process(entry_id, fields)

    pending = await client.xpending(stream_settings.events_stream, stream_settings.events_group)
    assert pending["pending"] == 0
    assert "1/4 стр." in session.texts[0]

    await client.aclose()


async def test_ensure_group_is_idempotent(stream_settings: Settings) -> None:
    """The bot calls this on every start; BUSYGROUP must not be fatal."""
    client: AsyncRedis = AsyncRedis.from_url(stream_settings.redis_url, decode_responses=True)
    await ensure_group(client, stream_settings.events_stream, stream_settings.events_group)
    await ensure_group(client, stream_settings.events_stream, stream_settings.events_group)
    await client.aclose()


async def test_stream_is_trimmed(stream_settings: Settings) -> None:
    """A stalled bot must not let the stream grow without bound."""
    sync = Redis.from_url(stream_settings.redis_url, decode_responses=True)
    for index in range(50):
        publish(
            sync,
            stream_settings.events_stream,
            make_event(EventKind.PROGRESS, done=index, total=50),
            maxlen=10,
        )
    # maxlen is approximate, so assert the order of magnitude rather than an exact count.
    length = sync.xlen(stream_settings.events_stream)
    assert isinstance(length, int)
    assert length < 50
