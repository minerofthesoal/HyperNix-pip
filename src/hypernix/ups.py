"""ups — uninterruptible-power-supply mode for training.

Watches two real-world signals and triggers a "checkpoint
panic" when either fires:

1.  **Weather** — heavy rain, severe thunderstorms, or any other
    WMO weather code in :data:`SEVERE_WEATHER_CODES`.  Queries
    open-meteo.com (free, no API key) at the configured
    coordinates.
2.  **Scheduled power outage** — pluggable callback.  Most US /
    European utilities don't expose a public API, so the user
    supplies an ``outage_check_fn(address) -> bool`` that returns
    ``True`` when the utility website lists a scheduled outage
    covering the configured address / window.

When either signal is positive, the UPS:

* **forces** an immediate snapshot via the user-supplied
  ``snapshot_fn``,
* **multiplies** the trainer's checkpoint cadence (default ``3×``)
  via :meth:`adjusted_save_every`,
* **records** every threat in :attr:`history` so a downstream
  log can show the user "we sped up checkpoint cadence at
  17:42:11 because of incoming thunderstorms".

Quick use::

    from hypernix.ups import UPS

    ups = UPS(latitude=47.61, longitude=-122.33)  # Seattle

    save_every = ups.adjusted_save_every(base_save_every=500)
    if ups.threat_active():
        print("UPS:", ups.last_status.summary)

The threat check itself is HTTP — set ``offline=True`` on
construction (or HYPERNIX_UPS_OFFLINE=1) to skip the network
call and only consult the user-supplied ``outage_check_fn``.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: WMO weather codes considered "force checkpoint now" severe.
#:
#: 65 = heavy rain                    95 = thunderstorm
#: 66, 67 = freezing rain (heavy)     96 = thunderstorm + slight hail
#: 75 = heavy snow                    99 = thunderstorm + heavy hail
#: 82 = violent rain showers
SEVERE_WEATHER_CODES: frozenset[int] = frozenset({
    65, 66, 67,
    75, 77,
    82,
    95, 96, 99,
})

#: WMO codes treated as "elevated risk" (forces checkpoint but
#: doesn't 3× the cadence).
ELEVATED_WEATHER_CODES: frozenset[int] = frozenset({
    61, 63,    # rain (light, moderate)
    71, 73,    # snow
    80, 81,    # rain showers
})


@dataclass
class ThreatStatus:
    timestamp: float
    weather_code: int | None = None
    weather_severe: bool = False
    weather_elevated: bool = False
    scheduled_outage: bool = False
    summary: str = ""

    @property
    def active(self) -> bool:
        return self.weather_severe or self.weather_elevated or self.scheduled_outage

    @property
    def panic(self) -> bool:
        """Severe weather or a scheduled outage — force an immediate
        checkpoint and 3× the cadence."""
        return self.weather_severe or self.scheduled_outage


# ---------------------------------------------------------------------------
# Weather backend (open-meteo, no key)
# ---------------------------------------------------------------------------

def _query_open_meteo(
    latitude: float, longitude: float, *, timeout: float = 5.0,
) -> dict[str, Any] | None:
    """Return open-meteo's ``current`` block, or ``None`` on any
    error.  Pure stdlib HTTP."""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,weather_code,precipitation,wind_speed_10m"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None
    return data.get("current") if isinstance(data, dict) else None


def _autodetect_coords(timeout: float = 5.0) -> tuple[float, float] | None:
    """Best-effort IP-geolocation via ipapi.co (free, no key)."""
    try:
        with urllib.request.urlopen(
            "https://ipapi.co/json/", timeout=timeout,
        ) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    lat = data.get("latitude")
    lon = data.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
        return float(lat), float(lon)
    return None


# ---------------------------------------------------------------------------
# UPS
# ---------------------------------------------------------------------------

@dataclass
class UPS:
    """Uninterruptible-power-supply guard.

    Args:
        latitude / longitude: Coordinates used for the weather
            query.  When ``None``, :class:`UPS` tries IP-based
            geolocation via ipapi.co; if that also fails the
            weather check becomes a no-op.
        outage_check_fn: Optional ``(address: str | None) -> bool``
            returning ``True`` when the user's utility lists a
            scheduled outage covering the configured ``address``
            / current time.  When ``None``, scheduled-outage
            detection is disabled.
        address: Free-form address string passed to
            ``outage_check_fn``.
        offline: Skip every network call (or set
            ``HYPERNIX_UPS_OFFLINE=1`` in the env).
        cadence_multiplier: Multiplier applied to the trainer's
            ``save_every`` when a panic is active.  Default 3 →
            "save 3× more often".
        check_interval_seconds: Minimum seconds between weather
            HTTP calls (so a tight training loop doesn't hammer
            open-meteo).  Default 300 (5 minutes).
        snapshot_fn: Optional callable invoked once the moment a
            new panic begins, so the trainer can dump a snapshot
            before the lights go out.
    """

    latitude: float | None = None
    longitude: float | None = None
    outage_check_fn: Callable[[str | None], bool] | None = None
    address: str | None = None
    offline: bool = False
    cadence_multiplier: int = 3
    check_interval_seconds: float = 300.0
    snapshot_fn: Callable[[], None] | None = None

    last_status: ThreatStatus | None = field(default=None, init=False)
    history: list[ThreatStatus] = field(default_factory=list, init=False, repr=False)
    _last_check_at: float = field(default=0.0, init=False, repr=False)

    _coords_resolved: bool = field(default=False, init=False, repr=False)
    _bg_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _cached_status: ThreatStatus | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cadence_multiplier < 1:
            raise ValueError("cadence_multiplier must be >= 1")
        if os.environ.get("HYPERNIX_UPS_OFFLINE") == "1":
            self.offline = True
        # Patch (0.61.1): IP-geolocation is *lazy* — defer until the
        # first :meth:`check` so constructing a UPS doesn't block on
        # a 5s HTTPS round-trip.  Tests / quick scripts that pass
        # ``offline=True`` or explicit coords pay no network cost.

    def _ensure_coords(self) -> None:
        if self._coords_resolved:
            return
        self._coords_resolved = True
        if self.offline:
            return
        if self.latitude is not None and self.longitude is not None:
            return
        coords = _autodetect_coords()
        if coords is not None:
            self.latitude, self.longitude = coords

    # ------------------------------------------------------------------
    # Threat polling
    # ------------------------------------------------------------------

    def check(self, *, force: bool = False) -> ThreatStatus:
        """Sample both signals (or return cached status)."""
        now = time.time()
        
        with self._lock:
            if (
                not force
                and self.last_status is not None
                and now - self._last_check_at < self.check_interval_seconds
            ):
                return self.last_status

        # If not already polling in background, start the thread
        if not self.offline and self._bg_thread is None:
            self._start_bg_thread()

        # If we have a cached status from the background thread, use it
        with self._lock:
            if self._cached_status is not None and not force:
                status = self._cached_status
            else:
                # Fallback to sync check if no background status available yet
                status = self._perform_sync_check(now)

            # Handle panic transition
            was_panic = self.last_status is not None and self.last_status.panic
            if status.panic and not was_panic and self.snapshot_fn is not None:
                try:
                    # Async snapshotting
                    threading.Thread(target=self.snapshot_fn, daemon=True).start()
                except Exception as exc:  # noqa: BLE001
                    status.summary += f" (snapshot_fn async trigger failed: {exc})"

            self.last_status = status
            self._last_check_at = now
            if status.active and (not self.history or self.history[-1].timestamp != status.timestamp):
                self.history.append(status)
            return status

    def _start_bg_thread(self) -> None:
        with self._lock:
            if self._bg_thread is not None:
                return
            self._bg_thread = threading.Thread(target=self._bg_loop, daemon=True)
            self._bg_thread.start()

    def _bg_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.time()
            status = self._perform_sync_check(now)
            with self._lock:
                self._cached_status = status
            self._stop_event.wait(self.check_interval_seconds)

    def _perform_sync_check(self, now: float) -> ThreatStatus:
        status = ThreatStatus(timestamp=now)
        # 0.61.1: lazy IP-geolocation on the first check.
        self._ensure_coords()
        # 1. Weather
        if (
            not self.offline
            and self.latitude is not None
            and self.longitude is not None
        ):
            current = _query_open_meteo(self.latitude, self.longitude)
            if current is not None:
                wc = current.get("weather_code")
                if isinstance(wc, int):
                    status.weather_code = wc
                    status.weather_severe = wc in SEVERE_WEATHER_CODES
                    status.weather_elevated = wc in ELEVATED_WEATHER_CODES
        # 2. Scheduled outage hook
        if self.outage_check_fn is not None:
            try:
                status.scheduled_outage = bool(self.outage_check_fn(self.address))
            except Exception:  # noqa: BLE001
                status.scheduled_outage = False

        status.summary = self._summarise(status)
        return status

    def _summarise(self, s: ThreatStatus) -> str:
        bits: list[str] = []
        if s.weather_severe:
            bits.append(f"SEVERE WEATHER (wmo={s.weather_code})")
        elif s.weather_elevated:
            bits.append(f"elevated weather (wmo={s.weather_code})")
        elif s.weather_code is not None:
            bits.append(f"weather=clear (wmo={s.weather_code})")
        if s.scheduled_outage:
            bits.append("SCHEDULED OUTAGE")
        if not bits:
            bits.append("no signal")
        return " ; ".join(bits)

    # ------------------------------------------------------------------
    # Trainer-facing helpers
    # ------------------------------------------------------------------

    def threat_active(self) -> bool:
        s = self.check()
        return s.active

    def panic(self) -> bool:
        s = self.check()
        return s.panic

    def adjusted_save_every(self, base_save_every: int) -> int:
        """Return the effective ``save_every`` given the current
        threat level.  Under panic, divides ``base_save_every`` by
        :attr:`cadence_multiplier` (so the trainer saves N× more
        often).  Floors at 1."""
        if base_save_every <= 0:
            return base_save_every
        if self.panic():
            return max(1, base_save_every // self.cadence_multiplier)
        return base_save_every

    def force_snapshot(self) -> None:
        """Manually fire the configured ``snapshot_fn`` (no-op if
        unset).  Useful for "I'm shutting the laptop now" buttons."""
        if self.snapshot_fn is not None:
            self.snapshot_fn()


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def ups(
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    outage_check_fn: Callable[[str | None], bool] | None = None,
    address: str | None = None,
    offline: bool = False,
    cadence_multiplier: int = 3,
) -> UPS:
    return UPS(
        latitude=latitude, longitude=longitude,
        outage_check_fn=outage_check_fn, address=address,
        offline=offline, cadence_multiplier=cadence_multiplier,
    )


def threat_now(
    latitude: float | None = None, longitude: float | None = None,
) -> ThreatStatus:
    """One-shot weather check; offline-fallback returns an inactive status."""
    return UPS(latitude=latitude, longitude=longitude).check(force=True)


__all__ = [
    "ELEVATED_WEATHER_CODES",
    "SEVERE_WEATHER_CODES",
    "ThreatStatus",
    "UPS",
    "threat_now",
    "ups",
]
