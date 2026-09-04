"""Router assembly.

Order is load-bearing:

1. cancel -- ``/cancel`` and the cancel button must win from every state, including while a job is
   running.
2. common -- /start, /help, the main menu, and the "you are busy" catch-all.
3. operation routers -- each only matches its own FSM state.
4. documents -- last, because its final handlers are catch-alls for the upload states.

Every router is built by a factory rather than being a module-level singleton: aiogram refuses to
attach the same Router twice, so singletons would make a second Dispatcher (and every test after
the first) fail.
"""

from aiogram import Router

from pdfbot.tg.handlers import documents, options, split
from pdfbot.tg.handlers.common import build_cancel_router, build_common_router


def build_root_router() -> Router:
    """One fresh router holding every handler, in priority order."""
    root = Router(name="root")
    root.include_router(build_cancel_router())
    root.include_router(build_common_router())
    root.include_router(split.build_router())
    root.include_router(options.build_router())
    root.include_router(documents.build_router())
    return root
