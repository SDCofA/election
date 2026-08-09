from __future__ import annotations

import asyncio
from datetime import datetime

ALLOWED_EVENT_TYPES = {
    "alert",
    "calendar_change",
    "forecast_publication",
    "official_result_update",
}
REQUIRED_EVENT_FIELDS = {
    "id",
    "type",
    "as_of",
    "published_at",
    "model_version",
    "data_quality",
    "freshness",
    "provenance",
}


def validate_event(payload: dict) -> dict:
    missing = REQUIRED_EVENT_FIELDS - payload.keys()
    if missing:
        raise ValueError(f"Live event missing fields: {sorted(missing)}")
    if payload["type"] not in ALLOWED_EVENT_TYPES:
        raise ValueError(f"Unsupported live event type: {payload['type']}")
    if not isinstance(payload["id"], str) or not payload["id"]:
        raise ValueError("Live event ID is required")
    for field in ("as_of", "published_at"):
        datetime.fromisoformat(str(payload[field]))
    if not isinstance(payload["provenance"], list) or not payload["provenance"]:
        raise ValueError("Live events require provenance links")
    return payload


class EventHub:
    def __init__(self, queue_size: int = 100) -> None:
        self.queue_size = queue_size
        self.subscribers: set[asyncio.Queue[dict]] = set()
        self.dropped_events = 0

    def subscribe(self) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=self.queue_size)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict]) -> None:
        self.subscribers.discard(queue)

    def publish(self, payload: dict) -> None:
        event = validate_event(payload)
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
                self.dropped_events += 1
            queue.put_nowait(event)


event_hub = EventHub()
