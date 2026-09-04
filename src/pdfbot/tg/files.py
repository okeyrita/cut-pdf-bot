"""Getting an uploaded document onto the shared volume.

This is the one place that has to care whether we are talking to the cloud Bot API or a local
``telegram-bot-api`` server, because the two behave differently in a way that silently breaks code
written for the other:

* **Cloud API** -- ``getFile`` returns a relative path you download over HTTPS. ``bot.download()``
  handles it. Hard 20 MB limit.
* **Local server** -- ``getFile`` returns an **absolute path on the API server's filesystem**.
  There is nothing to download; the file is already on disk. ``bot.download()`` does not work.
  The bot container must mount the same volume as the API server, which is why
  ``local_bot_api_data_dir`` exists.

The local path is verified before use and the code falls back to an HTTP download if it is not
readable, so a half-configured deployment degrades instead of failing outright.
"""

import asyncio
import logging
import shutil
from pathlib import Path

from aiogram import Bot
from aiogram.types import Document

from pdfbot.config import Settings
from pdfbot.domain.errors import TooLargeError


logger = logging.getLogger(__name__)


def check_size(document: Document, settings: Settings) -> None:
    """Reject an oversized document before any bytes move.

    Raises:
        TooLargeError
    """
    size = document.file_size or 0
    if size > settings.max_file_size_bytes:
        raise TooLargeError(size, settings.max_file_size_bytes)


async def download_document(
    bot: Bot, document: Document, target: Path, settings: Settings
) -> Path:
    """Put ``document`` at ``target``, by copy or by download depending on the API mode."""
    check_size(document, settings)
    target.parent.mkdir(parents=True, exist_ok=True)

    if settings.use_local_bot_api:
        file = await bot.get_file(document.file_id)
        if file.file_path:
            local = Path(file.file_path)
            if local.is_file():
                # A copy, not a move: the API server owns that file and cleans it up itself.
                await asyncio.to_thread(shutil.copyfile, local, target)
                logger.debug("copied %s from local Bot API storage", local)
                return target
            logger.warning(
                "local Bot API returned %s but it is not readable from this container; "
                "is %s mounted? falling back to HTTP download",
                local,
                settings.local_bot_api_data_dir,
            )

    await bot.download(document, destination=target)
    return target


def suffix_for(document: Document) -> str:
    """File extension to store the upload under, defaulting to ``.pdf``."""
    name = document.file_name or ""
    suffix = Path(name).suffix.lower()
    return suffix if suffix else ".pdf"
