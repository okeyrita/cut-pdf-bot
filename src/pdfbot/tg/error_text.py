"""Turn a domain error into the Russian sentence the user sees.

Used from two directions: the error middleware catches exceptions raised in handlers, while the
progress consumer receives a failure from a worker as a class *name* on the event stream. Both go
through here so the wording is identical either way.
"""

from pdfbot import texts
from pdfbot.domain.errors import (
    EncryptedPdfError,
    InvalidPdfError,
    NotEnoughFilesError,
    NoTextLayerError,
    PdfBotError,
    ProcessingFailedError,
    TooLargeError,
    TooManyFilesError,
    TooManyPagesError,
)


def message_for_error(exc: BaseException) -> str:
    """Message for an exception instance, filling in its own numbers where it has them."""
    match exc:
        case TooLargeError():
            return texts.ERR_TOO_LARGE.format(size=exc.size_mb, limit=exc.limit_mb)
        case TooManyPagesError():
            return texts.ERR_TOO_MANY_PAGES.format(pages=exc.pages, limit=exc.limit)
        case TooManyFilesError():
            return texts.ERR_TOO_MANY_FILES.format(limit=exc.limit)
        case EncryptedPdfError():
            return texts.ERR_ENCRYPTED
        case NoTextLayerError():
            return texts.ERR_NO_TEXT_LAYER
        case NotEnoughFilesError():
            return texts.ERR_NEED_MORE_FILES
        case InvalidPdfError():
            return texts.ERR_BROKEN_PDF
        case ProcessingFailedError():
            return texts.ERR_PROCESSING_FAILED
        case PdfBotError():
            return texts.ERR_PROCESSING_FAILED
        case _:
            return texts.ERR_UNEXPECTED


#: Codes a worker can put on the event stream. Workers send a class name because the exception
#: itself cannot cross the wire, so numbers (page counts, sizes) are lost -- these messages are
#: therefore the generic wording of their counterparts above.
_BY_CODE: dict[str, str] = {
    "InvalidPdfError": texts.ERR_BROKEN_PDF,
    "EncryptedPdfError": texts.ERR_ENCRYPTED,
    "NoTextLayerError": texts.ERR_NO_TEXT_LAYER,
    "NotEnoughFilesError": texts.ERR_NEED_MORE_FILES,
    "TooManyFilesError": texts.ERR_PROCESSING_FAILED,
    "TooLargeError": texts.ERR_PROCESSING_FAILED,
    "TooManyPagesError": texts.ERR_PROCESSING_FAILED,
    "ProcessingFailedError": texts.ERR_PROCESSING_FAILED,
    "TimeoutError": texts.ERR_TIMEOUT,
    "UnexpectedError": texts.ERR_UNEXPECTED,
}


def message_for_code(code: str | None) -> str:
    """Message for an error code that arrived over the event stream."""
    return _BY_CODE.get(code or "", texts.ERR_UNEXPECTED)
