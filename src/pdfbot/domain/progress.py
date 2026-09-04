"""Throttled progress reporting.

A 400-page book would otherwise emit 400 Telegram edits, and Telegram allows roughly one edit per
second per chat. :class:`ProgressReporter` collapses that to a handful: it emits when enough time
has passed *or* enough work has happened, and always on the final unit.

The clock is injected so tests can assert throttling behaviour without sleeping.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


#: How many filled cells the rendered bar has.
BAR_WIDTH = 12


def render_bar(done: int, total: int, width: int = BAR_WIDTH) -> str:
    """Unicode progress bar, e.g. ``████████░░░░ 67%``."""
    if total <= 0:
        return "░" * width + "   0%"
    ratio = min(max(done / total, 0.0), 1.0)
    filled = round(ratio * width)
    return f"{'█' * filled}{'░' * (width - filled)} {round(ratio * 100)}%"


@dataclass(slots=True)
class ProgressReporter:
    """Calls ``emit(done, total)`` at a bounded rate as work advances.

    Args:
        total: Total units of work (pages, files, chunks). ``0`` disables reporting.
        emit: Sink for an allowed update. Must not raise; progress is strictly best-effort.
        min_interval: Minimum seconds between emits.
        min_ratio: Also emit once this fraction of ``total`` has accumulated since the last emit.
        clock: Monotonic time source. Injected for tests.
    """

    total: int
    emit: Callable[[int, int], None]
    min_interval: float = 2.0
    min_ratio: float = 0.05
    clock: Callable[[], float] = time.monotonic

    done: int = field(default=0, init=False)
    _last_emit_at: float = field(default=0.0, init=False)
    _last_emit_done: int = field(default=0, init=False)
    _started: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self._last_emit_at = self.clock()

    @property
    def _step(self) -> int:
        """Units that must accumulate before an emit is allowed on volume alone."""
        return max(1, int(self.total * self.min_ratio))

    def start(self) -> None:
        """Emit an initial 0/total so the user sees a bar immediately."""
        if self.total > 0 and not self._started:
            self._started = True
            self._fire()

    def advance(self, n: int = 1) -> None:
        """Record ``n`` completed units and emit if the throttle allows."""
        if self.total <= 0:
            return
        self.done = min(self.done + n, self.total)
        if self._should_emit():
            self._fire()

    def finish(self) -> None:
        """Force a final 100% emit, regardless of throttling."""
        if self.total > 0 and self._last_emit_done != self.total:
            self.done = self.total
            self._fire()

    def _should_emit(self) -> bool:
        if self.done >= self.total:
            return True  # the last unit always reports
        elapsed = self.clock() - self._last_emit_at
        return elapsed >= self.min_interval or (self.done - self._last_emit_done) >= self._step

    def _fire(self) -> None:
        self._last_emit_at = self.clock()
        self._last_emit_done = self.done
        self.emit(self.done, self.total)


def noop_reporter(total: int = 0) -> ProgressReporter:
    """A reporter that discards everything -- convenient default in tests and CLI use."""
    return ProgressReporter(total=total, emit=lambda _done, _total: None)
