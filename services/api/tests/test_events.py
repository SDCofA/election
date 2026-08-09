from datetime import UTC, datetime

import pytest

from app.events import EventHub, validate_event


def _event(identifier: str = "event-1") -> dict:
    timestamp = datetime.now(UTC).isoformat()
    return {
        "id": identifier,
        "type": "official_result_update",
        "as_of": timestamp,
        "published_at": timestamp,
        "model_version": "results-1",
        "data_quality": "A",
        "freshness": "live",
        "provenance": [{"url": "https://authority.example/results"}],
    }


def test_event_contract_requires_metadata_and_known_type():
    assert validate_event(_event())["id"] == "event-1"
    invalid = _event()
    invalid["type"] = "rumor"
    with pytest.raises(ValueError, match="Unsupported"):
        validate_event(invalid)
    invalid = _event()
    invalid.pop("provenance")
    with pytest.raises(ValueError, match="missing fields"):
        validate_event(invalid)


def test_slow_subscriber_queue_is_bounded_and_keeps_latest_event():
    hub = EventHub(queue_size=2)
    queue = hub.subscribe()
    hub.publish(_event("one"))
    hub.publish(_event("two"))
    hub.publish(_event("three"))
    assert hub.dropped_events == 1
    assert queue.get_nowait()["id"] == "two"
    assert queue.get_nowait()["id"] == "three"
    hub.unsubscribe(queue)
    assert not hub.subscribers
