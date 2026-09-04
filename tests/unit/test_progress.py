"""Progress throttling.

Telegram allows roughly one message edit per second per chat. A 400-page book emitting one update
per page would be flood-limited within seconds, so the throttle is load-bearing, not cosmetic.

The clock is injected rather than slept on, which is the only way to assert this deterministically.
"""

import pytest

from pdfbot.domain.progress import ProgressReporter, render_bar


class FakeClock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_reporter(
    total: int, clock: FakeClock, **kwargs: float
) -> tuple[ProgressReporter, list[tuple[int, int]]]:
    seen: list[tuple[int, int]] = []
    reporter = ProgressReporter(
        total=total,
        emit=lambda done, tot: seen.append((done, tot)),
        clock=clock,
        **kwargs,
    )
    return reporter, seen


def test_time_alone_does_not_emit_without_progress() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(100, clock, min_interval=2.0, min_ratio=1.0)
    clock.advance(60)
    assert seen == []


def test_emits_once_the_interval_elapses() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(100, clock, min_interval=2.0, min_ratio=1.0)

    reporter.advance()
    assert seen == []  # too soon

    clock.advance(2.0)
    reporter.advance()
    assert seen == [(2, 100)]


def test_emits_on_volume_before_the_interval() -> None:
    """5% of 100 pages is 5, so the 5th page reports even though no time has passed."""
    clock = FakeClock()
    reporter, seen = make_reporter(100, clock, min_interval=999.0, min_ratio=0.05)
    for _ in range(5):
        reporter.advance()
    assert seen == [(5, 100)]


def test_a_long_book_produces_a_bounded_number_of_edits() -> None:
    """The whole point: 400 pages must not become 400 Telegram calls."""
    clock = FakeClock()
    reporter, seen = make_reporter(400, clock, min_interval=2.0, min_ratio=0.05)
    for _ in range(400):
        clock.advance(0.01)  # 4 seconds of work in total
        reporter.advance()
    # 5% steps -> 20 emits, plus a couple from the time trigger. Nowhere near 400.
    assert len(seen) <= 25
    assert seen[-1] == (400, 400)


def test_the_final_unit_always_emits() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(10, clock, min_interval=999.0, min_ratio=1.0)
    for _ in range(10):
        reporter.advance()
    assert seen[-1] == (10, 10)


def test_finish_is_idempotent() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(10, clock, min_interval=0.0)
    reporter.advance(10)
    reporter.finish()
    reporter.finish()
    assert seen.count((10, 10)) == 1


def test_start_shows_an_immediate_zero() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(50, clock, min_interval=999.0, min_ratio=1.0)
    reporter.start()
    assert seen == [(0, 50)]
    reporter.start()  # only once
    assert seen == [(0, 50)]


def test_advance_never_exceeds_total() -> None:
    clock = FakeClock()
    reporter, seen = make_reporter(5, clock, min_interval=0.0)
    reporter.advance(99)
    assert reporter.done == 5
    assert seen[-1] == (5, 5)


def test_zero_total_is_inert() -> None:
    """Compress and other stage-only operations construct a reporter with nothing to count."""
    clock = FakeClock()
    reporter, seen = make_reporter(0, clock)
    reporter.start()
    reporter.advance()
    reporter.finish()
    assert seen == []


@pytest.mark.parametrize(
    ("done", "total", "expected_pct"),
    [(0, 100, "0%"), (45, 120, "38%"), (100, 100, "100%"), (1, 3, "33%")],
)
def test_render_bar_percentage(done: int, total: int, expected_pct: str) -> None:
    bar = render_bar(done, total)
    assert bar.endswith(expected_pct)
    assert len(bar.split(" ")[0]) == 12


def test_render_bar_handles_zero_total() -> None:
    assert render_bar(0, 0).endswith("0%")
