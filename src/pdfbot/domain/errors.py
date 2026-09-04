"""Domain error hierarchy.

Every failure a user could plausibly cause gets its own class, so the Telegram layer maps it to a
specific Russian message instead of showing a generic apology. Anything not derived from
:class:`PdfBotError` is a bug and is logged with a traceback.

Each subclass carries the data its message template needs (``size_mb``, ``pages``, ...) rather than
a pre-rendered string, which keeps display text out of the domain.
"""


class PdfBotError(Exception):
    """Base class for expected, user-facing failures."""


class InvalidPdfError(PdfBotError):
    """Bytes are not a PDF at all, or the file is too damaged for pypdf to open."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(reason or "not a readable PDF")
        self.reason = reason


class EncryptedPdfError(PdfBotError):
    """PDF is password-protected and the empty password did not open it."""


class TooLargeError(PdfBotError):
    def __init__(self, size_bytes: int, limit_bytes: int) -> None:
        super().__init__(f"{size_bytes} bytes exceeds limit {limit_bytes}")
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / 1024 / 1024, 1)

    @property
    def limit_mb(self) -> int:
        return self.limit_bytes // 1024 // 1024


class TooManyPagesError(PdfBotError):
    def __init__(self, pages: int, limit: int) -> None:
        super().__init__(f"{pages} pages exceeds limit {limit}")
        self.pages = pages
        self.limit = limit


class TooManyFilesError(PdfBotError):
    def __init__(self, count: int, limit: int) -> None:
        super().__init__(f"{count} files exceeds limit {limit}")
        self.count = count
        self.limit = limit


class NotEnoughFilesError(PdfBotError):
    """Merge needs at least two documents."""


class NoTextLayerError(PdfBotError):
    """Text extraction was asked for on what looks like a scan."""


class ProcessingFailedError(PdfBotError):
    """An external tool (Ghostscript, tesseract) failed or produced nothing usable."""

    def __init__(self, tool: str, detail: str = "") -> None:
        super().__init__(f"{tool} failed: {detail}" if detail else f"{tool} failed")
        self.tool = tool
        self.detail = detail


class OperationCancelledError(PdfBotError):
    """Raised inside a worker when the user cancelled mid-job."""
