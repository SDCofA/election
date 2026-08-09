from datetime import UTC, date, datetime

import pytest

from elexion_pipeline.adapters.official_calendar import (
    CalendarParseError,
    OfficialCalendarAdapter,
    OfficialCalendarConfig,
    parse_official_calendar,
)
from elexion_pipeline.checkpoint import MemoryCheckpointStore
from elexion_pipeline.domain import FetchResult, RawSnapshot


def _snapshot(digest: str = "a" * 64) -> RawSnapshot:
    return RawSnapshot(
        source_id="brazil_tse",
        source_url="https://www.tse.jus.br/calendar",
        retrieved_at=datetime(2026, 8, 9, tzinfo=UTC),
        sha256=digest,
        byte_count=100,
        content_type="text/html",
        object_key=f"raw/brazil_tse/{digest}.bin",
        object_uri=f"s3://fixture/{digest}",
        license_id="CC-BY-4.0",
        attribution="Tribunal Superior Eleitoral",
        usage_scope="Official calendar fixture",
    )


def _config() -> OfficialCalendarConfig:
    return OfficialCalendarConfig(
        source_id="brazil_tse",
        endpoint="/calendar",
        parser_version="calendar-v1",
        election_id="br-2026-president",
        election_date=date(2026, 10, 4),
        date_confidence="official",
        status="calendar only",
        released_at=datetime(2026, 2, 26, tzinfo=UTC),
        available_at=datetime(2026, 2, 26, tzinfo=UTC),
        required_markers=["4 de outubro de 2026", "Presidente e Vice-Presidente"],
    )


def test_calendar_parser_requires_every_authority_marker():
    batch = parse_official_calendar(
        b"<p>4 de outubro de 2026</p><b>Presidente e Vice-Presidente</b>",
        _snapshot(),
        _config(),
    )
    assert batch.election_date == date(2026, 10, 4)
    assert batch.parser_confidence == 1
    with pytest.raises(CalendarParseError, match="confidence"):
        parse_official_calendar(b"<p>4 de outubro de 2026</p>", _snapshot(), _config())


def test_calendar_adapter_uses_last_known_good_on_drift_without_republishing():
    class Fetcher:
        result = FetchResult(
            snapshot=_snapshot(),
            content=b"4 de outubro de 2026 Presidente e Vice-Presidente",
        )

        def fetch(self, *_args):
            return self.result

    fetcher = Fetcher()
    checkpoints = MemoryCheckpointStore()
    adapter = OfficialCalendarAdapter(fetcher, checkpoints)
    current = adapter.fetch(_config())
    assert current.fallback_used is False

    fetcher.result = FetchResult(snapshot=_snapshot("b" * 64), content=b"page changed")
    fallback = adapter.fetch(_config())
    assert fallback.fallback_used is True
    assert fallback.source_snapshot.sha256 == "a" * 64
    assert checkpoints.events[-1].failure_kind == "parser_drift"
