from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from elexion_pipeline.features import FeatureObservation, FeatureSpec, build_feature_snapshot
from elexion_pipeline.persistence import validate_source_vintage_feature


def _observation(
    metric: str,
    value: float,
    available_at: datetime,
    revision: int = 0,
) -> FeatureObservation:
    return FeatureObservation(
        metric=metric,
        value=value,
        unit="percent",
        observed_at=available_at - timedelta(days=30),
        released_at=available_at,
        available_at=available_at,
        revision=revision,
        source_revision_id=str(uuid4()),
        source_key="official-statistics",
        source_url="https://data.example.test/series",
        license="CC-BY-4.0",
    )


def test_feature_builder_excludes_future_vintages_and_keeps_exact_lineage():
    cutoff = datetime(2026, 8, 9, tzinfo=UTC)
    old = _observation("primary", 2.0, cutoff - timedelta(days=2))
    current = _observation("alternate", 2.2, cutoff - timedelta(days=1), revision=1)
    future = _observation("primary", 99.0, cutoff + timedelta(seconds=1), revision=2)
    projection = FeatureObservation(
        **{
            **_observation("primary", 88.0, cutoff - timedelta(days=1), revision=3).__dict__,
            "observed_at": cutoff + timedelta(days=30),
        }
    )
    snapshot = build_feature_snapshot(
        "election-1",
        "jurisdiction-1",
        cutoff,
        [old, current, future, projection],
        (
            FeatureSpec("inflation", ("primary", "alternate")),
            FeatureSpec("growth", ("growth",)),
        ),
    )
    feature = snapshot["values"]["features"]["inflation"]
    assert feature["value"] == 2.2
    assert feature["source_revision_id"] == current.source_revision_id
    assert future.source_revision_id not in snapshot["source_revision_ids"]
    assert projection.source_revision_id not in snapshot["source_revision_ids"]
    assert snapshot["values"]["missing_features"] == ["growth"]
    assert snapshot["values"]["completeness"] == 0.5
    assert len(snapshot["content_sha256"]) == 64
    assert all(UUID(value) for value in snapshot["source_revision_ids"])


def test_feature_snapshot_hash_is_deterministic_across_input_order():
    cutoff = datetime(2026, 8, 9, tzinfo=UTC)
    first = _observation("inflation", 2.0, cutoff - timedelta(days=2))
    second = _observation("growth", 1.0, cutoff - timedelta(days=1))
    specs = (
        FeatureSpec("inflation", ("inflation",)),
        FeatureSpec("growth", ("growth",)),
    )
    left = build_feature_snapshot("e", "j", cutoff, [first, second], specs)
    right = build_feature_snapshot("e", "j", cutoff, [second, first], specs)
    assert left == right
    assert validate_source_vintage_feature(left)
    left["values"]["features"]["growth"]["value"] = 999
    with pytest.raises(ValueError, match="content hash mismatch"):
        validate_source_vintage_feature(left)
