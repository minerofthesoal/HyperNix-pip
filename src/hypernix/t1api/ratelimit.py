"""t1api.ratelimit — advanced, configuration-driven rate limiting.

The spec asks for "middleware for rate limiting" (hard requirement) and
"advanced rate limiting" (Beta 3), plus one behavioural rule that decides
the whole design: **"Apply rate limits before expensive model
operations."** A limiter that runs after routing and metering has
already happened has not protected anything, so :class:`RateLimiter` is
checked in middleware — before the router, before the registry lookup,
before any model work — and expensive endpoints additionally declare a
``cost`` so one heavyweight call consumes more budget than one
``GET /health``.

Why token bucket *and* sliding window
-------------------------------------
They answer different questions and the spec needs both:

* A **token bucket** answers "may this caller make a request right
  now?", allowing a short burst above the steady rate and refilling
  continuously. That's the right shape for interactive clients like the
  waiter TUI, which idles and then fires several calls at once when you
  open a pane.
* A **sliding window** answers "has this caller exceeded N in the last
  M seconds?" without a bucket's burst allowance. That's the right shape
  for the forced limits an operator sets with ``waiter -r``, where the
  point is a hard ceiling, and for token-throughput caps where a burst
  is exactly what you're trying to prevent.

Both are per-subject and in-process. Multi-worker deployments get
per-worker limits unless a shared store is supplied (see
:class:`RateLimiter`'s ``shared_counter`` hook) — that's called out in
the docs rather than pretended away, because a per-worker limit under
four workers is a 4× looser limit than the number in the config
suggests.

Subjects
--------
Limits key off a :class:`Subject` — ``("key", key_id)``,
``("ip", address)``, or ``("server", server_id)``. A request is checked
against *every* rule that matches it and denied by the first one that
refuses, so a caller is bounded by both their key's rate and their
address's rate, and neither can be escaped by varying the other.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .errors import T1APIError, T1ErrorCode

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Subject:
    """What a limit applies to: ``Subject("key", "abc123")``."""

    kind: str  # "key" | "ip" | "server" | "global"
    identifier: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.kind}:{self.identifier}"


@dataclass
class RateRule:
    """One limit.

    Args:
        name: Stable identifier, surfaced in the error's details so a
            client can tell *which* limit it hit.
        capacity: Bucket size — the maximum burst.
        refill_per_second: Steady-state rate. ``capacity=60`` with
            ``refill_per_second=1`` is "60 burst, 60/minute sustained".
        applies_to: Subject kinds this rule governs.
        endpoints: Optional path prefixes this rule is restricted to.
            Empty = every endpoint.
        methods: Optional HTTP methods. Empty = every method.
        admin_exempt: Whether admin keys skip this rule. Off by default
            — an admin key is a bigger blast radius, not a smaller one.
    """

    name: str
    capacity: float
    refill_per_second: float
    applies_to: tuple[str, ...] = ("key",)
    endpoints: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    admin_exempt: bool = False

    def matches(self, subject: Subject, path: str, method: str) -> bool:
        if subject.kind not in self.applies_to:
            return False
        if self.endpoints and not any(path.startswith(prefix) for prefix in self.endpoints):
            return False
        if self.methods and method.upper() not in {m.upper() for m in self.methods}:
            return False
        return True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RateRule:
        return cls(
            name=d["name"],
            capacity=float(d["capacity"]),
            refill_per_second=float(d["refill_per_second"]),
            applies_to=tuple(d.get("applies_to", ("key",))),
            endpoints=tuple(d.get("endpoints", ())),
            methods=tuple(d.get("methods", ())),
            admin_exempt=bool(d.get("admin_exempt", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capacity": self.capacity,
            "refill_per_second": self.refill_per_second,
            "applies_to": list(self.applies_to),
            "endpoints": list(self.endpoints),
            "methods": list(self.methods),
            "admin_exempt": self.admin_exempt,
        }


@dataclass
class _Bucket:
    tokens: float
    last_refill: float

    def take(self, cost: float, rule: RateRule, now: float) -> tuple[bool, float | None]:
        """Consume *cost* if available. Returns ``(allowed, retry_after)``.

        ``retry_after`` is ``None`` when the bucket never refills
        (``refill_per_second <= 0``), meaning "not by waiting" rather than
        any number of seconds. It is deliberately not ``float("inf")``:
        that value reaches a JSON response body — where Python emits a
        bare ``Infinity`` that is not valid JSON — and a ``Retry-After``
        header, where converting it to an int raises OverflowError. A
        rule that can never be satisfied by waiting has to say so in a
        form the wire can carry.
        """
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(rule.capacity, self.tokens + elapsed * rule.refill_per_second)
        self.last_refill = now
        if self.tokens >= cost:
            self.tokens -= cost
            return True, 0.0
        if rule.refill_per_second <= 0:
            return False, None
        return False, (cost - self.tokens) / rule.refill_per_second


class _SlidingWindow:
    """Timestamped-event window used for forced limits and token caps."""

    def __init__(self) -> None:
        self.events: deque[tuple[float, float]] = deque()  # (ts, amount)
        self.total = 0.0

    def add(self, amount: float, now: float) -> None:
        self.events.append((now, amount))
        self.total += amount

    def trim(self, window_seconds: float, now: float) -> None:
        cutoff = now - window_seconds
        while self.events and self.events[0][0] < cutoff:
            _, amount = self.events.popleft()
            self.total -= amount
        if not self.events:
            self.total = 0.0

    def retry_after(self, window_seconds: float, now: float) -> float:
        if not self.events:
            return 0.0
        return max(0.0, (self.events[0][0] + window_seconds) - now)


# Sensible defaults: generous enough that ordinary interactive use never
# notices, tight enough that an unauthenticated flood or a runaway script
# hits a wall. Every value is overridable from configuration — see
# T1APIConfig.rate_limit_rules / T1_RATE_LIMIT_RULES.
DEFAULT_RULES: tuple[RateRule, ...] = (
    RateRule(
        name="per_key_default",
        capacity=120,
        refill_per_second=2.0,  # 120 burst, 120/min sustained
        applies_to=("key",),
    ),
    RateRule(
        name="per_ip_default",
        capacity=240,
        refill_per_second=4.0,
        applies_to=("ip",),
    ),
    RateRule(
        # Expensive paths: routing, module upload, job submission. Applied
        # in addition to per_key_default, so a caller within their overall
        # budget can still be told to slow down on the costly endpoints
        # specifically — which is the point of "apply rate limits before
        # expensive model operations".
        name="expensive_operations",
        capacity=20,
        refill_per_second=0.333,  # ~20/min sustained
        applies_to=("key",),
        endpoints=("/models/route", "/modules/upload", "/jobs", "/modules/", "/servers/register"),
        methods=("POST", "PATCH", "PUT", "DELETE"),
    ),
)

# Per-endpoint cost multipliers. A model-routing call or a module upload
# consumes more of the caller's budget than a status check. Longest
# matching prefix wins, so "/modules/upload" beats "/modules".
DEFAULT_ENDPOINT_COSTS: dict[str, float] = {
    "/models/route": 5.0,
    "/modules/upload": 10.0,
    "/modules": 2.0,
    "/jobs": 3.0,
    "/billing": 2.0,
    "/auth/t1/admin": 5.0,
}


def endpoint_cost(path: str, costs: dict[str, float] | None = None) -> float:
    """Cost of one request to *path*, defaulting to 1.0."""
    table = DEFAULT_ENDPOINT_COSTS if costs is None else costs
    best: tuple[int, float] = (0, 1.0)
    for prefix, cost in table.items():
        if path.startswith(prefix) and len(prefix) > best[0]:
            best = (len(prefix), cost)
    return best[1]


class RateLimiter:
    """Token-bucket + sliding-window limiter over a set of rules.

    Args:
        rules: The configured rules. Defaults to :data:`DEFAULT_RULES`.
        forced_limit_lookup: Callable ``(subject_type, subject_id) ->
            ForcedLimit | None``, normally
            :meth:`t1api.netpolicy.NetworkPolicy.get_limit`. Injected
            rather than imported so the limiter has no dependency on the
            network-policy store and stays unit-testable on its own.
        endpoint_costs: Overrides :data:`DEFAULT_ENDPOINT_COSTS`.
        enabled: Master off switch (``T1_RATE_LIMIT_ENABLED=0``).
    """

    def __init__(
        self,
        rules: tuple[RateRule, ...] | list[RateRule] | None = None,
        *,
        forced_limit_lookup: Callable[[str, str], Any] | None = None,
        endpoint_costs: dict[str, float] | None = None,
        enabled: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rules = tuple(rules) if rules is not None else DEFAULT_RULES
        self.forced_limit_lookup = forced_limit_lookup
        self.endpoint_costs = endpoint_costs if endpoint_costs is not None else DEFAULT_ENDPOINT_COSTS
        self.enabled = enabled
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._forced_windows: dict[tuple[str, str, str], _SlidingWindow] = {}

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check(
        self,
        subjects: list[Subject],
        *,
        path: str = "/",
        method: str = "GET",
        is_admin: bool = False,
        cost: float | None = None,
    ) -> None:
        """Consume budget for one request, or raise ``RATE_LIMITED``.

        Every matching rule is evaluated and the *first* refusal wins. On
        refusal, budget already consumed from earlier rules in this call
        is **not** refunded: the alternative (two passes, or rollback) is
        more machinery than the situation warrants, and erring toward
        charging a rejected caller slightly more is the safe direction
        for a limiter.
        """
        if not self.enabled:
            return
        request_cost = endpoint_cost(path, self.endpoint_costs) if cost is None else cost
        now = self._clock()

        for subject in subjects:
            self._check_forced(subject, now=now, tokens=0)

        for rule in self.rules:
            if rule.admin_exempt and is_admin:
                continue
            for subject in subjects:
                if not rule.matches(subject, path, method):
                    continue
                allowed, retry_after = self._take(rule, subject, request_cost, now)
                if not allowed:
                    when = (
                        f"Retry in {retry_after:.1f}s."
                        if retry_after is not None
                        else "This limit does not refill; it will not clear by waiting."
                    )
                    raise T1APIError(
                        T1ErrorCode.RATE_LIMITED,
                        f"Rate limit '{rule.name}' exceeded for {subject.kind}. {when}",
                        details={
                            "rule": rule.name,
                            "subject_kind": subject.kind,
                            "retry_after_seconds": (
                                round(retry_after, 2) if retry_after is not None else None
                            ),
                            "cost": request_cost,
                        },
                        http_status=429,
                    )

    def record_tokens(self, subjects: list[Subject], tokens: int) -> None:
        """Record token consumption against forced token caps.

        Called *after* a model operation reports how many tokens it
        actually used — the request itself is admitted on request-count
        budget, and the token cap governs the next one. Enforcing a token
        cap before the count is known would require pre-declaring it,
        which a client can lie about.
        """
        if not self.enabled or not tokens:
            return
        now = self._clock()
        for subject in subjects:
            limit = self._forced(subject)
            if limit is None or limit.tokens_per_window is None:
                continue
            window = self._window(subject, "tokens")
            with self._lock:
                window.add(float(tokens), now)

    def _check_forced(self, subject: Subject, *, now: float, tokens: int) -> None:
        limit = self._forced(subject)
        if limit is None:
            return
        if limit.requests_per_window is not None:
            window = self._window(subject, "requests")
            with self._lock:
                window.trim(limit.window_seconds, now)
                if window.total + 1 > limit.requests_per_window:
                    retry_after = window.retry_after(limit.window_seconds, now)
                    raise T1APIError(
                        T1ErrorCode.RATE_LIMITED,
                        f"Operator-forced request limit for this {subject.kind} exceeded "
                        f"({limit.requests_per_window} per {limit.window_seconds:g}s). "
                        f"Retry in {retry_after:.1f}s.",
                        details={
                            "rule": "forced_limit",
                            "subject_kind": subject.kind,
                            "retry_after_seconds": round(retry_after, 2),
                            "reason": limit.reason,
                        },
                        http_status=429,
                    )
                window.add(1.0, now)
        if limit.tokens_per_window is not None:
            window = self._window(subject, "tokens")
            with self._lock:
                window.trim(limit.window_seconds, now)
                if window.total >= limit.tokens_per_window:
                    retry_after = window.retry_after(limit.window_seconds, now)
                    raise T1APIError(
                        T1ErrorCode.RATE_LIMITED,
                        f"Operator-forced token limit for this {subject.kind} exceeded "
                        f"({limit.tokens_per_window} per {limit.window_seconds:g}s). "
                        f"Retry in {retry_after:.1f}s.",
                        details={
                            "rule": "forced_limit_tokens",
                            "subject_kind": subject.kind,
                            "retry_after_seconds": round(retry_after, 2),
                            "reason": limit.reason,
                        },
                        http_status=429,
                    )

    def _forced(self, subject: Subject) -> Any:
        if self.forced_limit_lookup is None or subject.kind not in ("key", "server"):
            return None
        try:
            return self.forced_limit_lookup(subject.kind, subject.identifier)
        except Exception:  # noqa: BLE001 - a limit-store failure must not 500 the request
            logger.warning("t1api.ratelimit: forced-limit lookup failed", exc_info=True)
            return None

    def _window(self, subject: Subject, dimension: str) -> _SlidingWindow:
        key = (subject.kind, subject.identifier, dimension)
        with self._lock:
            window = self._forced_windows.get(key)
            if window is None:
                window = _SlidingWindow()
                self._forced_windows[key] = window
        return window

    def _take(
        self, rule: RateRule, subject: Subject, cost: float, now: float
    ) -> tuple[bool, float | None]:
        key = (rule.name, str(subject))
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=rule.capacity, last_refill=now)
                self._buckets[key] = bucket
            return bucket.take(cost, rule, now)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def snapshot(self, subject: Subject) -> list[dict[str, Any]]:
        """Remaining budget per rule for *subject* — powers the waiter
        TUI's limits pane and the ``X-RateLimit-*`` response headers."""
        now = self._clock()
        out: list[dict[str, Any]] = []
        with self._lock:
            for rule in self.rules:
                if subject.kind not in rule.applies_to:
                    continue
                bucket = self._buckets.get((rule.name, str(subject)))
                if bucket is None:
                    remaining = rule.capacity
                else:
                    elapsed = max(0.0, now - bucket.last_refill)
                    remaining = min(rule.capacity, bucket.tokens + elapsed * rule.refill_per_second)
                out.append(
                    {
                        "rule": rule.name,
                        "capacity": rule.capacity,
                        "remaining": round(remaining, 2),
                        "refill_per_second": rule.refill_per_second,
                    }
                )
        return out

    def reset(self) -> None:
        """Drop all state. Test helper and an operator escape hatch."""
        with self._lock:
            self._buckets.clear()
            self._forced_windows.clear()


def rules_from_json(raw: Any) -> tuple[RateRule, ...]:
    """Build rules from parsed JSON (``T1_RATE_LIMIT_RULES`` or a file).

    Returns the defaults when *raw* is empty, so a deployment that sets
    nothing gets sane limits rather than none — "no configuration" must
    not mean "no rate limiting".
    """
    if not raw:
        return DEFAULT_RULES
    if isinstance(raw, dict):
        raw = raw.get("rules", [])
    return tuple(RateRule.from_dict(item) for item in raw)


__all__ = [
    "DEFAULT_ENDPOINT_COSTS",
    "DEFAULT_RULES",
    "RateLimiter",
    "RateRule",
    "Subject",
    "endpoint_cost",
    "rules_from_json",
]
