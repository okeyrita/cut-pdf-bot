"""Logging setup shared by the bot and the workers."""

import json
import logging
import logging.config
import sys
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from pdfbot.config import Settings


#: Attributes LogRecord always has; anything else was added by the caller and is worth emitting.
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any ``extra=`` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Install handlers. Idempotent, so calling it from several entry points is safe."""
    formatter: logging.Formatter = (
        JsonFormatter()
        if settings.log_json
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # These are chatty at INFO and say nothing useful about our own behaviour.
    for noisy in ("aiogram.event", "aiohttp.access", "pikepdf", "PIL", "ocrmypdf._pipeline"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
