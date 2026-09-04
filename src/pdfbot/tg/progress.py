"""Consumes worker events and drives the Telegram side of a job.

One long-lived task owns this. It is the only place that edits progress messages or uploads
results, which keeps every Telegram rate-limit concern in a single file.

Delivery guarantees: entries are read through a consumer group and ``XACK``ed only after the
Telegram call has been attempted, so a bot that dies mid-edit re-reads the entry on restart rather
than leaving the user staring at a stalled bar. :meth:`ProgressConsumer.reclaim` picks up whatever
the previous process left pending.
"""

import asyncio
import contextlib
import logging
from collections.abc import Mapping
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.types import FSInputFile
from redis.asyncio import Redis as AsyncRedis

from pdfbot import keyboards, texts
from pdfbot.config import Settings
from pdfbot.domain.progress import render_bar
from pdfbot.events import EventKind, JobEvent, ensure_group
from pdfbot.storage import JobWorkspace, UnsafeJobIdError
from pdfbot.tg.error_text import message_for_code
from pdfbot.tg.middlewares.concurrency import JobSlots


logger = logging.getLogger(__name__)

#: Russian captions for the opaque stages that have no page count.
_STAGE_TEXT = {
    "compressing": texts.STAGE_COMPRESSING,
    "ocr": texts.STAGE_OCR,
    "building": texts.STAGE_BUILDING,
}

#: How long XREADGROUP blocks before looping. Long enough to be cheap, short enough to shut down
#: promptly on cancellation.
_BLOCK_MS = 5000


class ProgressConsumer:
    """Reads job events and reflects them into the user's chat."""

    def __init__(
        self,
        bot: Bot,
        redis: AsyncRedis,
        settings: Settings,
        storage: BaseStorage,
        consumer_name: str = "bot-1",
    ) -> None:
        self._bot = bot
        self._redis = redis
        self._settings = settings
        self._storage = storage
        self._consumer = consumer_name

    # ------------------------------------------------------------------ lifecycle

    async def run(self) -> None:
        """Main loop. Cancel the task to stop it."""
        await ensure_group(self._redis, self._settings.events_stream, self._settings.events_group)
        await self.reclaim()
        logger.info("progress consumer started on %s", self._settings.events_stream)

        while True:
            try:
                batch = await self._redis.xreadgroup(
                    groupname=self._settings.events_group,
                    consumername=self._consumer,
                    streams={self._settings.events_stream: ">"},
                    count=20,
                    block=_BLOCK_MS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("event read failed; retrying", exc_info=True)
                await asyncio.sleep(1)
                continue

            for _stream, entries in batch or []:
                for entry_id, fields in entries:
                    await self._process(entry_id, fields)

    async def reclaim(self) -> None:
        """Take over entries a previous bot process read but never acknowledged."""
        try:
            _cursor, entries, _deleted = await self._redis.xautoclaim(
                name=self._settings.events_stream,
                groupname=self._settings.events_group,
                consumername=self._consumer,
                min_idle_time=60_000,
                count=100,
            )
        except Exception:
            logger.warning("could not reclaim pending events", exc_info=True)
            return

        if entries:
            logger.info("reclaimed %d pending events", len(entries))
        for entry_id, fields in entries:
            await self._process(entry_id, fields)

    async def _process(self, entry_id: str, fields: Mapping[str, str]) -> None:
        """Handle one entry, acknowledging it whatever happens.

        A poisonous entry that always fails would otherwise be redelivered forever, so the ack is
        unconditional and failures are logged instead.
        """
        try:
            event = JobEvent.from_fields(fields)
        except Exception:
            logger.warning("dropping malformed event %s", entry_id, exc_info=True)
        else:
            try:
                await self.handle(event)
            except Exception:
                logger.exception("failed to handle %s event for job %s", event.kind, event.job_id)
        finally:
            with contextlib.suppress(Exception):
                await self._redis.xack(
                    self._settings.events_stream, self._settings.events_group, entry_id
                )

    # ------------------------------------------------------------------ event handling

    async def handle(self, event: JobEvent) -> None:
        match event.kind:
            case EventKind.PROGRESS:
                await self._edit(
                    event,
                    texts.PROGRESS.format(
                        bar=render_bar(event.done, event.total),
                        done=event.done,
                        total=event.total,
                    ),
                )
            case EventKind.STAGE:
                await self._edit(
                    event,
                    texts.PROGRESS_STAGE.format(
                        bar="⏳", stage=_STAGE_TEXT.get(event.stage or "", event.stage or "")
                    ),
                )
            case EventKind.DONE:
                await self._finish(event)
            case EventKind.ERROR:
                await self._fail(event)

    async def _edit(self, event: JobEvent, text: str) -> None:
        """Update the progress message, tolerating the two errors Telegram routinely returns."""
        try:
            await self._bot.edit_message_text(
                text=text,
                chat_id=event.chat_id,
                message_id=event.message_id,
                reply_markup=keyboards.cancel_kb(),
            )
        except TelegramRetryAfter as exc:
            # Flood control. One retry; progress is not worth queueing up behind.
            logger.info("rate limited, retrying edit in %ss", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
                await self._bot.edit_message_text(
                    text=text, chat_id=event.chat_id, message_id=event.message_id
                )
        except TelegramBadRequest as exc:
            # "message is not modified" is expected: two consecutive throttled emits can land on
            # the same page count. Anything else is worth a line in the log.
            if "not modified" not in str(exc):
                logger.info("could not edit progress message: %s", exc)

    async def _finish(self, event: JobEvent) -> None:
        """Upload the result, then tear the job down."""
        path = Path(event.result_path or "")
        if not path.is_file():
            logger.error("job %s finished but %s is missing", event.job_id, path)
            await self._fail(event.model_copy(update={"error_code": "UnexpectedError"}))
            return

        await self._delete_progress(event)
        await self._bot.send_document(
            chat_id=event.chat_id,
            document=FSInputFile(path, filename=event.result_name or path.name),
            caption=event.caption,
        )
        await self._bot.send_message(
            chat_id=event.chat_id, text=texts.DONE, reply_markup=keyboards.main_menu()
        )
        await self._teardown(event)

    async def _fail(self, event: JobEvent) -> None:
        await self._delete_progress(event)
        await self._bot.send_message(
            chat_id=event.chat_id,
            text=message_for_code(event.error_code),
            reply_markup=keyboards.main_menu(),
        )
        await self._teardown(event)

    async def _delete_progress(self, event: JobEvent) -> None:
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await self._bot.delete_message(chat_id=event.chat_id, message_id=event.message_id)

    async def _teardown(self, event: JobEvent) -> None:
        """Release the user's job slot, clear their FSM state and delete the workspace."""
        slots = JobSlots(
            self._redis,
            self._settings.max_concurrent_jobs_per_user,
            self._settings.task_time_limit,
        )
        await slots.release(event.user_id)

        key = StorageKey(bot_id=self._bot.id, chat_id=event.chat_id, user_id=event.user_id)
        with contextlib.suppress(Exception):
            await self._storage.set_state(key, None)
            await self._storage.set_data(key, {})

        with contextlib.suppress(FileNotFoundError, UnsafeJobIdError):
            JobWorkspace.attach(self._settings.jobs_dir, event.job_id).cleanup()
