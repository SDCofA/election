from __future__ import annotations

from datetime import UTC, datetime

import pytest

from elexion_pipeline.definitions import minute_official_result_refresh
from elexion_pipeline.domain import SourceDefinition
from elexion_pipeline.live_results import select_active_feeds, validated_feed_config
from elexion_pipeline.registry import SourceRegistry


def _registry(approved: bool = True) -> SourceRegistry:
    return SourceRegistry(
        [
            SourceDefinition(
                id="official",
                name="Official authority",
                base_url="https://results.example.test/",
                allowed_hosts=["results.example.test"],
                authority="official",
                license_id="PUBLIC",
                license_name="Public",
                license_url="https://results.example.test/license",
                attribution="Official authority",
                approved=approved,
                max_bytes=1_000_000,
                freshness_hours=1,
                content_types=["application/json"],
            )
        ]
    )


def _pack(status: str = "approved") -> dict:
    feed = {
        "status": status,
        "source_id": "official",
        "endpoint": "results.json",
        "format": "json",
        "parser_version": "fixture-v1",
        "live_window": {
            "opens_at": "2026-08-09T10:00:00Z",
            "closes_at": "2026-08-09T12:00:00Z",
        },
    }
    if status == "unavailable":
        feed = {"status": "unavailable", "reason": "No licensed machine-readable feed"}
    return {
        "source_adapters": [{"source_id": "official", "status": "approved"}],
        "reporting_units": [{"id": "national", "name": "National", "level": "national"}],
        "election": {
            "id": "x-1",
            "sources": [
                {
                    "source_id": "official",
                    "label": "Official authority",
                    "url": "https://results.example.test/",
                }
            ],
        },
        "official_results": feed,
    }


def test_missing_or_unavailable_feed_is_explicitly_inactive():
    pack = _pack("unavailable")
    assert validated_feed_config(pack, _registry()) is None
    pack.pop("official_results")
    assert validated_feed_config(pack, _registry()) is None


def test_feed_selection_never_activates_outside_declared_window():
    configured, active = select_active_feeds(
        [_pack()], _registry(), datetime(2026, 8, 9, 9, 59, tzinfo=UTC)
    )
    assert configured == 1
    assert active == []
    _, active = select_active_feeds([_pack()], _registry(), datetime(2026, 8, 9, 10, 0, tzinfo=UTC))
    assert len(active) == 1


def test_feed_rejects_unapproved_source_before_polling():
    with pytest.raises(PermissionError):
        validated_feed_config(_pack(), _registry(approved=False))


def test_feed_requires_reporting_units_and_provenance():
    pack = _pack()
    pack["reporting_units"] = []
    with pytest.raises(ValueError, match="requires reporting units"):
        validated_feed_config(pack, _registry())


def test_official_result_schedule_runs_every_minute():
    assert minute_official_result_refresh.cron_schedule == "* * * * *"
