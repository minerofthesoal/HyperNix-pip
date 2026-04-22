"""coffee_maker — scheduled / repeated training runs.

A coffee maker brews on a schedule.  Same idea here: call a training
function on an interval (think nightly continuous-pretrain on fresh
data), keep a history of results, and let the caller stop the run at
any time via a sentinel.

This is intentionally lightweight — it's a cron replacement, not a
full scheduler.  For a real scheduler use systemd-timers / APScheduler
/ airflow; for a "run this five times and tell me how it went", use
``CoffeeMaker``.
"""
from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Brew:
    """One result from a single ``brew_fn()`` call."""

    cycle: int
    started_at: float
    duration_s: float
    ok: bool
    result: Any = None
    error: str | None = None


@dataclass
class CoffeeMaker:
    """Repeat ``brew_fn`` on an interval.

    ``brew_fn`` is a zero-arg callable.  Between calls the maker sleeps
    for ``interval_seconds`` (minus the time the brew already took, so
    the total cadence stays regular).  Exceptions in ``brew_fn`` are
    captured and recorded as failed :class:`Brew` entries — the next
    cycle still runs.  Call :meth:`run` to execute a fixed number of
    cycles or :meth:`serve` to run until ``stop()`` is called.
    """

    brew_fn: Callable[[], Any]
    interval_seconds: float = 60.0
    history: list[Brew] = field(default_factory=list)
    _stop: bool = field(default=False, init=False, repr=False)

    def brew_once(self, cycle: int = 0) -> Brew:
        started = time.time()
        t0 = time.monotonic()
        try:
            out = self.brew_fn()
            b = Brew(
                cycle=cycle, started_at=started,
                duration_s=time.monotonic() - t0,
                ok=True, result=out,
            )
        except Exception as exc:  # noqa: BLE001
            b = Brew(
                cycle=cycle, started_at=started,
                duration_s=time.monotonic() - t0,
                ok=False, error=f"{type(exc).__name__}: {exc}",
            )
        self.history.append(b)
        return b

    def run(self, cycles: int) -> list[Brew]:
        """Run exactly ``cycles`` brews (sleeping between them)."""
        self._stop = False
        for i in range(cycles):
            b = self.brew_once(cycle=i)
            if self._stop:
                break
            if i == cycles - 1:
                break
            # Sleep off the remainder of the interval.
            remaining = self.interval_seconds - b.duration_s
            if remaining > 0:
                time.sleep(remaining)
        return list(self.history)

    def serve(self, *, install_sigint: bool = True) -> list[Brew]:
        """Run until :meth:`stop` is called.  If ``install_sigint`` is
        True, Ctrl-C sets the stop flag cleanly instead of raising."""
        self._stop = False
        original_sigint = None
        if install_sigint:
            original_sigint = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGINT, lambda *_: self.stop())
        try:
            cycle = 0
            while not self._stop:
                b = self.brew_once(cycle=cycle)
                cycle += 1
                if self._stop:
                    break
                remaining = self.interval_seconds - b.duration_s
                if remaining > 0:
                    time.sleep(remaining)
        finally:
            if install_sigint and original_sigint is not None:
                signal.signal(signal.SIGINT, original_sigint)
        return list(self.history)

    def stop(self) -> None:
        """Cooperative cancel.  Finishes the current brew, then exits."""
        self._stop = True

    def summary(self) -> dict:
        total = len(self.history)
        failed = sum(1 for b in self.history if not b.ok)
        durations = [b.duration_s for b in self.history]
        return {
            "cycles": total,
            "failed": failed,
            "mean_duration_s": (sum(durations) / total) if total else 0.0,
            "last_ok": self.history[-1].ok if total else None,
        }


def coffee_maker(
    brew_fn: Callable[[], Any], *, interval_seconds: float = 60.0,
) -> CoffeeMaker:
    return CoffeeMaker(brew_fn=brew_fn, interval_seconds=interval_seconds)
