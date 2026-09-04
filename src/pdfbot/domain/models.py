"""Value objects describing what to do to a PDF.

These are the contract between the Telegram handlers (which build them from FSM data) and the
domain functions (which consume them). They validate themselves on construction, so an impossible
request fails at the handler boundary rather than halfway through a worker job.
"""

from dataclasses import dataclass
from pathlib import Path

from pdfbot.enums import (
    CompressLevel,
    ExportFormat,
    OcrLang,
    Orientation,
    RotateDirection,
    SplitMode,
)


@dataclass(frozen=True, slots=True)
class PdfInfo:
    """What :func:`pdfbot.domain.pdf.inspect.probe` learned about a file."""

    path: Path
    pages: int
    size_bytes: int
    encrypted: bool
    has_text_layer: bool

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / 1024 / 1024, 2)


@dataclass(frozen=True, slots=True)
class SplitOptions:
    """How to cut each page in half.

    ``reserve`` is a *fraction* (0.05 = 5%), not a percentage: the conversion from the user's
    "5" happens once, at the handler boundary, so the geometry code never has to remember which
    unit it is in. That ambiguity is what the original ``0.01 * float(reserve_percent)`` got wrong.
    """

    orientation: Orientation
    mode: SplitMode
    reserve: float = 0.0

    def __post_init__(self) -> None:
        if self.mode is SplitMode.STRICT and self.reserve:
            raise ValueError("strict split cannot have a reserve")
        if not 0.0 <= self.reserve <= 1.0:
            raise ValueError(f"reserve must be a fraction in [0, 1], got {self.reserve}")

    @classmethod
    def from_percent(
        cls, orientation: Orientation, mode: SplitMode, percent: float = 0.0
    ) -> SplitOptions:
        """Build from the 0-100 number the user typed."""
        if not 0.0 <= percent <= 100.0:
            raise ValueError(f"percent must be in [0, 100], got {percent}")
        return cls(
            orientation=orientation,
            mode=mode,
            reserve=0.0 if mode is SplitMode.STRICT else percent / 100.0,
        )


@dataclass(frozen=True, slots=True)
class RotateOptions:
    direction: RotateDirection

    @property
    def degrees(self) -> int:
        return self.direction.degrees


@dataclass(frozen=True, slots=True)
class CompressOptions:
    level: CompressLevel

    #: Below this relative saving, returning the original is more honest than a "compressed" file.
    min_saving_ratio: float = 0.02


@dataclass(frozen=True, slots=True)
class OcrOptions:
    language: OcrLang
    chunk_pages: int = 10
    deskew: bool = True
    force: bool = False
    """Re-OCR pages that already carry a text layer instead of skipping them."""

    def __post_init__(self) -> None:
        if self.chunk_pages < 1:
            raise ValueError("chunk_pages must be >= 1")


@dataclass(frozen=True, slots=True)
class ExtractOptions:
    fmt: ExportFormat
    title: str = "Документ"
    pages_per_chapter: int = 20
    """EPUB only: how many PDF pages become one chapter."""

    def __post_init__(self) -> None:
        if self.pages_per_chapter < 1:
            raise ValueError("pages_per_chapter must be >= 1")


@dataclass(frozen=True, slots=True)
class CompressResult:
    """Returned by the compress task so the bot can report the real saving."""

    output: Path
    size_before: int
    size_after: int

    @property
    def saved_ratio(self) -> float:
        if self.size_before <= 0:
            return 0.0
        return max(0.0, 1.0 - self.size_after / self.size_before)

    @property
    def saved_percent(self) -> int:
        return round(self.saved_ratio * 100)

    @property
    def improved(self) -> bool:
        """False when compression was not worth it and :attr:`output` is the untouched original."""
        return self.size_after < self.size_before
