"""t1api.events — the event bus behind GET /events.

Framework-independent by design (same reasoning as the rest of ``t1api``'s
core): :class:`EventBus` is a plain in-process pub/sub primitive. The
FastAPI layer (Beta 2's HTTP wiring) turns a :class:`Subscriber` into a
Server-Sent-Events stream; :meth:`EventBus.recent` alone is enough to
implement a plain polling ``GET /events?since=<event_id>`` for clients
that don't want to hold a streaming connection open.

Every other Beta 2 subsystem (jobs, modules, servers) publishes onto one
shared bus so ``GET /events`` gives a unified timeline instead of one feed
per subsystem — wired at the ``t1api.app`` composition layer, same pattern
as the ``module_sync`` job handler.
"""
from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass
class Event:
    event_id: str
    type: str
    data: dict[str, Any]
    source: str
    ts: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "data": self.data,
            "source": self.source,
            "ts": self.ts,
        }


class Subscriber:
    """A live handle for one consumer of the event stream. Backed by a
    bounded ``queue.Queue`` — a slow consumer drops the oldest buffered
    events rather than applying backpressure to publishers (publishing
    must never block on a stalled SSE client)."""

    def __init__(self, maxsize: int = 256) -> None:
        self._queue: queue.Queue[Event] = queue.Queue(maxsize=maxsize)
        self.closed = False

    def _push(self, event: Event) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop the oldest to make room rather than blocking the
            # publisher — a live tail is allowed to lose backlog under
            # sustained overload; use recent()/since_id for backlog
            # recovery instead of relying on the live queue for that.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass

    def iter(self, *, timeout: float | None = None) -> Iterator[Event]:
        """Yield events as they arrive. With a *timeout*, stops yielding
        (returns) after that many seconds of silence — useful for an SSE
        handler that wants to send periodic keep-alives instead of
        blocking forever."""
        while not self.closed:
            try:
                yield self._queue.get(timeout=timeout)
            except queue.Empty:
                return

    def close(self) -> None:
        self.closed = True


class EventBus:
    """Thread-safe pub/sub with a bounded backlog for polling clients."""

    def __init__(self, *, history_size: int = 1000) -> None:
        self._lock = threading.Lock()
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: list[Subscriber] = []

    def publish(self, event_type: str, data: dict[str, Any], *, source: str = "") -> Event:
        event = Event(event_id=uuid.uuid4().hex, type=event_type, data=data, source=source, ts=time.time())
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
        for sub in subscribers:
            sub._push(event)
        return event

    def subscribe(self, *, maxsize: int = 256) -> Subscriber:
        sub = Subscriber(maxsize=maxsize)
        with self._lock:
            self._subscribers.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        sub.close()
        with self._lock:
            if sub in self._subscribers:
                self._subscribers.remove(sub)

    def recent(self, *, limit: int = 50, since_id: str | None = None, event_type: str | None = None) -> list[Event]:
        with self._lock:
            items = list(self._history)
        if since_id is not None:
            for i, e in enumerate(items):
                if e.event_id == since_id:
                    items = items[i + 1 :]
                    break
        if event_type is not None:
            items = [e for e in items if e.type == event_type]
        return items[-limit:]

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


__all__ = ["Event", "Subscriber", "EventBus"]
