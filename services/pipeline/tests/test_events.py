import asyncio

from elexion_pipeline import definitions


class FakeNatsConnection:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []
        self.flushed = False
        self.drained = False

    async def publish(self, subject: str, payload: bytes) -> None:
        self.messages.append((subject, payload))

    async def flush(self, timeout: int) -> None:
        assert timeout == 5
        self.flushed = True

    async def drain(self) -> None:
        self.drained = True


def test_forecast_events_publish_to_typed_nats_subject(monkeypatch):
    connection = FakeNatsConnection()

    async def connect(**kwargs):
        assert kwargs["servers"] == ["nats://test:4222"]
        return connection

    monkeypatch.setattr(definitions.nats, "connect", connect)
    event = {
        "id": "forecast-1",
        "type": "forecast_publication",
        "as_of": "2026-08-09T12:00:00+00:00",
        "published_at": "2026-08-09T12:00:00+00:00",
        "model_version": "test-1",
        "data_quality": "A",
        "freshness": "fresh",
        "provenance": [{"url": "https://example.test/source"}],
    }
    asyncio.run(definitions._publish_nats_events([event], "nats://test:4222"))
    assert connection.messages[0][0] == "elexion.events.forecast_publication"
    assert connection.flushed is True
    assert connection.drained is True
