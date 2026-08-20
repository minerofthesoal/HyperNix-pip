from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ..deps import get_event_bus, get_request_id
from ..events import EventBus
from ..schemas import EventItem, EventListResponse

router = APIRouter(prefix="/events", tags=["events"])


def _to_item(event) -> EventItem:
    return EventItem(**event.to_dict())


@router.get("", response_model=EventListResponse)
def list_events(
    limit: int = Query(default=50, ge=1, le=500),
    since_id: str | None = Query(default=None),
    event_type: str | None = Query(default=None, alias="type"),
    bus: EventBus = Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> EventListResponse:
    """Polling form of GET /events, matching the spec's endpoint list
    exactly. For a live tail, see GET /events/stream (an addition beyond
    the spec's list — see wiki/T1-API.md#events)."""
    events = bus.recent(limit=limit, since_id=since_id, event_type=event_type)
    return EventListResponse(events=[_to_item(e) for e in events], count=len(events), request_id=request_id)


@router.get("/stream")
async def stream_events(
    event_type: str | None = Query(default=None, alias="type"),
    bus: EventBus = Depends(get_event_bus),
) -> StreamingResponse:
    """Server-Sent-Events live tail. Not in the spec's original endpoint
    list — added because "event streaming" (the spec's own Beta 2 bullet)
    reads most naturally as a live stream, and GET /events alone can only
    be a poll. Kept as a separate endpoint rather than overloading GET
    /events so the polling contract stays exactly as specified.
    """
    subscriber = bus.subscribe()

    async def _gen():
        try:
            loop = asyncio.get_event_loop()
            while True:
                event = await loop.run_in_executor(None, lambda: next(subscriber.iter(timeout=15.0), None))
                if event is None:
                    yield ": keep-alive\n\n"
                    continue
                if event_type is not None and event.type != event_type:
                    continue
                yield f"event: {event.type}\ndata: {json.dumps(event.to_dict())}\n\n"
        finally:
            bus.unsubscribe(subscriber)

    return StreamingResponse(_gen(), media_type="text/event-stream")


__all__ = ["router"]
