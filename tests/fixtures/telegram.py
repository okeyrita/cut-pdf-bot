"""Hand-rolled aiogram test doubles.

``aiogram-tests`` is effectively unmaintained, and it turns out not to be needed: aiogram's types
are plain pydantic models, so building an ``Update`` is just constructing one. Feeding it through a
real :class:`~aiogram.Dispatcher` exercises filters, FSM transitions and middlewares for real, and
the only thing that has to be faked is the HTTP session at the very edge.
"""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, Document, Message, Update, User


TEST_TOKEN = "42:TESTTOKEN"
USER_ID = 777
CHAT_ID = 777


def make_user(user_id: int = USER_ID) -> User:
    return User(id=user_id, is_bot=False, first_name="Тест", last_name="Тестов")


def make_chat(chat_id: int = CHAT_ID) -> Chat:
    return Chat(id=chat_id, type="private")


def make_message(
    text: str | None = "hi",
    *,
    message_id: int = 1,
    document: Document | None = None,
    user: User | None = None,
) -> Message:
    return Message(
        message_id=message_id,
        date=datetime.now(UTC),
        chat=make_chat(),
        from_user=user or make_user(),
        text=text,
        document=document,
    )


def make_document(
    file_name: str = "book.pdf", size: int = 1024, file_id: str = "FILEID"
) -> Document:
    return Document(
        file_id=file_id, file_unique_id=f"u{file_id}", file_name=file_name, file_size=size
    )


def message_update(text: str | None = "hi", **kwargs: Any) -> Update:
    return Update(update_id=next(_ids), message=make_message(text, **kwargs))


def document_update(document: Document | None = None) -> Update:
    return Update(
        update_id=next(_ids),
        message=make_message(None, document=document or make_document()),
    )


def callback_update(data: str, *, message_id: int = 1) -> Update:
    """A button press carrying packed ``callback_data``.

    The attached message is the bot's own, which is exactly how Telegram delivers it -- and why
    handlers must not read ``callback.message.from_user`` to identify the user.
    """
    return Update(
        update_id=next(_ids),
        callback_query=CallbackQuery(
            id=f"cb{next(_ids)}",
            from_user=make_user(),
            chat_instance="ci",
            data=data,
            message=make_message("prompt", message_id=message_id),
        ),
    )


def _counter() -> Any:
    n = 0
    while True:
        n += 1
        yield n


_ids = _counter()


class RecordingSession(BaseSession):
    """A session that records outgoing API calls instead of making them.

    Every aiogram method declares what it returns; this fabricates a plausible value of that shape
    so handler code that reads ``(await message.answer(...)).message_id`` keeps working.
    """

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    def calls(self, method_name: str) -> list[TelegramMethod[Any]]:
        return [r for r in self.requests if type(r).__name__ == method_name]

    @property
    def texts(self) -> list[str]:
        """Every message body the bot sent or edited, in order."""
        return [
            str(getattr(r, "text", ""))
            for r in self.requests
            if type(r).__name__ in {"SendMessage", "EditMessageText"}
        ]

    @property
    def last_markup(self) -> Any:
        for request in reversed(self.requests):
            markup = getattr(request, "reply_markup", None)
            if markup is not None:
                return markup
        return None

    def button_data(self) -> list[str]:
        """Packed callback_data of the most recent keyboard."""
        markup = self.last_markup
        if markup is None:
            return []
        return [b.callback_data for row in markup.inline_keyboard for b in row if b.callback_data]

    async def make_request(
        self, bot: Bot, method: TelegramMethod[TelegramType], timeout: int | None = None
    ) -> TelegramType:
        self.requests.append(method)
        name = type(method).__name__
        if name in {"SendMessage", "EditMessageText", "SendDocument"}:
            return make_message("sent", message_id=next(_ids))  # type: ignore[return-value]
        return True  # type: ignore[return-value]

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes]:
        yield b"%PDF-1.4\n"


class FakeRedis:
    """Just enough Redis for :class:`~pdfbot.tg.middlewares.concurrency.JobSlots`."""

    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def decr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) - 1
        return self.store[key]

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        value = self.store.get(key)
        return str(value) if value is not None else None

    async def delete(self, key: str) -> int:
        return int(self.store.pop(key, None) is not None)


def make_bot(session: RecordingSession | None = None) -> Bot:
    return Bot(token=TEST_TOKEN, session=session or RecordingSession())
