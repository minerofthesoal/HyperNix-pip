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

import json
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
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


# ---------------------------------------------------------------------------
# Tier 2 — FrenchPressMaker (batch brew)
# ---------------------------------------------------------------------------

@dataclass
class FrenchPressMaker:
    """Batch brew: takes a list of callables, runs them all once,
    returns results in order.

    Unlike :class:`CoffeeMaker`, the French press doesn't loop on a
    schedule — it's a "here's a pot, steep it, pour one serving per
    guest" operation.  Useful for running an ensemble of evaluators,
    training a handful of LoRAs in sequence, or any other "N
    independent jobs" pattern.
    """

    brews: list[Callable[[], Any]]
    history: list[Brew] = field(default_factory=list)

    def plunge(self) -> list[Brew]:
        for i, fn in enumerate(self.brews):
            started = time.time()
            t0 = time.monotonic()
            try:
                out = fn()
                b = Brew(cycle=i, started_at=started,
                         duration_s=time.monotonic() - t0, ok=True, result=out)
            except Exception as exc:  # noqa: BLE001
                b = Brew(cycle=i, started_at=started,
                         duration_s=time.monotonic() - t0,
                         ok=False, error=f"{type(exc).__name__}: {exc}")
            self.history.append(b)
        return list(self.history)


def french_press(brews: list[Callable[[], Any]]) -> FrenchPressMaker:
    return FrenchPressMaker(brews=list(brews))


# ---------------------------------------------------------------------------
# Tier 3 — PercolatorMaker (cyclic / refinement)
# ---------------------------------------------------------------------------

@dataclass
class PercolatorMaker:
    """Cyclic brew: the output of cycle N is passed as the input to
    cycle N+1.  Think of it as a fixed-point iteration — great for
    iterative refinement loops (e.g. "draft, critique, revise, …"
    with a judge model).

    ``brew_fn`` takes the previous cycle's result and returns the
    next.  The initial input is ``seed_input``.
    """

    brew_fn: Callable[[Any], Any]
    seed_input: Any = None
    max_cycles: int = 5
    convergence: Callable[[Any, Any], bool] | None = None
    history: list[Brew] = field(default_factory=list)

    def percolate(self) -> Any:
        current = self.seed_input
        for i in range(self.max_cycles):
            started = time.time()
            t0 = time.monotonic()
            try:
                out = self.brew_fn(current)
                b = Brew(cycle=i, started_at=started,
                         duration_s=time.monotonic() - t0,
                         ok=True, result=out)
                self.history.append(b)
                if self.convergence is not None and self.convergence(current, out):
                    current = out
                    break
                current = out
            except Exception as exc:  # noqa: BLE001
                self.history.append(Brew(
                    cycle=i, started_at=started,
                    duration_s=time.monotonic() - t0,
                    ok=False, error=f"{type(exc).__name__}: {exc}",
                ))
                break
        return current


def percolator(
    brew_fn: Callable[[Any], Any],
    seed_input: Any = None,
    *,
    max_cycles: int = 5,
    convergence: Callable[[Any, Any], bool] | None = None,
) -> PercolatorMaker:
    return PercolatorMaker(
        brew_fn=brew_fn, seed_input=seed_input,
        max_cycles=max_cycles, convergence=convergence,
    )


# ---------------------------------------------------------------------------
# New type — ColdBrewMaker (long slow patient brew with disk checkpoints)
# ---------------------------------------------------------------------------

@dataclass
class ColdBrewMaker:
    """Long-running single brew with mandatory disk checkpoints.

    Unlike the other three which are short-or-repeating, cold brew is
    "set it and forget it" — one ``brew_fn`` call that may take hours
    or days.  The maker writes a ``checkpoint_path`` JSON file after
    each internal phase so that a crashed / killed run can be
    resumed.

    ``brew_fn`` is called with ``(checkpoint_dict, phase)`` where
    ``checkpoint_dict`` is whatever was last persisted (or an empty
    dict on the first call) and ``phase`` is the 0-based phase index.
    It must return a dict that will be written back to disk before
    the next phase runs.
    """

    brew_fn: Callable[[dict, int], dict]
    phases: int = 24
    checkpoint_path: Path | str = "cold_brew.json"
    phase_interval_seconds: float = 0.0
    history: list[Brew] = field(default_factory=list)

    def _load(self) -> tuple[dict, int]:
        p = Path(self.checkpoint_path)
        if not p.exists():
            return {}, 0
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("state", {}), int(data.get("next_phase", 0))

    def _save(self, state: dict, next_phase: int) -> None:
        p = Path(self.checkpoint_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"state": state, "next_phase": next_phase},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def brew(self) -> dict:
        state, start = self._load()
        for phase in range(start, self.phases):
            started = time.time()
            t0 = time.monotonic()
            try:
                state = self.brew_fn(state, phase)
                self._save(state, phase + 1)
                self.history.append(Brew(
                    cycle=phase, started_at=started,
                    duration_s=time.monotonic() - t0, ok=True, result=state,
                ))
            except Exception as exc:  # noqa: BLE001
                self.history.append(Brew(
                    cycle=phase, started_at=started,
                    duration_s=time.monotonic() - t0,
                    ok=False, error=f"{type(exc).__name__}: {exc}",
                ))
                raise
            if phase < self.phases - 1 and self.phase_interval_seconds > 0:
                time.sleep(self.phase_interval_seconds)
        return state


def cold_brew(
    brew_fn: Callable[[dict, int], dict],
    *,
    phases: int = 24,
    checkpoint_path: Path | str = "cold_brew.json",
    phase_interval_seconds: float = 0.0,
) -> ColdBrewMaker:
    return ColdBrewMaker(
        brew_fn=brew_fn, phases=phases,
        checkpoint_path=checkpoint_path,
        phase_interval_seconds=phase_interval_seconds,
    )


# All tiers / types by short name — useful for runtime selection.
TIERS: dict[str, type] = {
    "drip": CoffeeMaker,
    "french-press": FrenchPressMaker,
    "percolator": PercolatorMaker,
    "cold-brew": ColdBrewMaker,
}
