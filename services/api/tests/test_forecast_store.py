from datetime import UTC, datetime

from app.forecast_store import snapshot_from_record


def test_persisted_forecast_record_restores_immutable_public_contract():
    timestamp = datetime(2026, 8, 9, tzinfo=UTC)
    record = {
        "id": "snapshot-1",
        "election_id": "us-2028-president",
        "as_of": timestamp,
        "published_at": timestamp,
        "simulation_count": 1_000_000,
        "seed": 7,
        "data_quality": "D",
        "freshness": "structural-only",
        "headline": "Stored forecast",
        "majority_probability": 0.5,
        "turnout_median": 0.65,
        "source_manifest": {"input_provenance": [], "provenance": []},
        "model_version_id": "structural-ensemble-0.2.0:baseline_ensemble",
        "model_family": "baseline_ensemble",
        "validation": {
            "selection_status": "baseline retained",
            "regional_forecast_supported": False,
        },
        "feature_values": {
            "drivers": [],
            "missing_drivers": ["source-vintage polling"],
        },
        "outcomes": [
            {
                "contestant_id": "dem",
                "win_probability": 1.0,
                "projected_share": 1.0,
                "share_low": 0.9,
                "share_high": 1.0,
                "projected_seats": 538,
                "seats_low": 500,
                "seats_high": 538,
            }
        ],
        "coalition_outcomes": [],
    }
    snapshot = snapshot_from_record(record)
    assert snapshot.id == "snapshot-1"
    assert snapshot.model_version == "structural-ensemble-0.2.0"
    assert snapshot.simulation_count == 1_000_000
    assert snapshot.missing_drivers == ["source-vintage polling"]
