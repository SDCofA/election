from datetime import UTC, datetime

import pytest

from app import model_inputs

FEATURE_REVISION = "00000000-0000-0000-0000-000000000001"
POLL_REVISION = "00000000-0000-0000-0000-000000000002"


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, unresolved=False):
        self.unresolved = unresolved

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, query, _params):
        cutoff = datetime(2026, 8, 9, tzinfo=UTC)
        if "FROM feature_snapshots" in query:
            return _Rows(
                [
                    {
                        "as_of": cutoff,
                        "values": {
                            "features": {"inflation": {"value": 2.0}},
                            "missing_features": ["unemployment"],
                        },
                        "source_revision_ids": [FEATURE_REVISION],
                        "content_sha256": "a" * 64,
                    }
                ]
            )
        if "FROM latest" in query:
            base = {
                "id": POLL_REVISION,
                "poll_key": "poll-1",
                "pollster": "Example",
                "fieldwork_end": cutoff,
                "available_at": cutoff,
                "sample_size": 1_000,
                "mode": "online",
            }
            return _Rows(
                [
                    {**base, "contestant_id": "a", "share": 0.55},
                    {**base, "contestant_id": "b", "share": 0.45},
                ]
            )
        rows = [
            {
                "revision_id": revision_id,
                "source_key": "source",
                "label": "Source",
                "url": "https://example.test/data",
                "authority": "official",
                "retrieved_at": cutoff,
                "license": "CC-BY-4.0",
                "license_url": "https://creativecommons.org/licenses/by/4.0/",
            }
            for revision_id in (FEATURE_REVISION, POLL_REVISION)
        ]
        return _Rows(rows[:1] if self.unresolved else rows)


def test_load_model_evidence_combines_exact_macro_and_poll_revisions(monkeypatch):
    monkeypatch.setattr(model_inputs.psycopg, "connect", lambda *_args, **_kwargs: _Connection())
    evidence = model_inputs.load_model_evidence("dsn", "election", ["a", "b"])
    assert evidence is not None
    assert evidence.source_revision_ids == (FEATURE_REVISION, POLL_REVISION)
    assert evidence.poll_aggregate is not None
    assert evidence.poll_aggregate.shares == pytest.approx((0.55, 0.45))
    assert evidence.missing_macro_features == ("unemployment",)
    assert len(evidence.provenance) == 2
    assert len(evidence.content_sha256) == 64


def test_load_model_evidence_rejects_unresolved_revision(monkeypatch):
    monkeypatch.setattr(
        model_inputs.psycopg,
        "connect",
        lambda *_args, **_kwargs: _Connection(unresolved=True),
    )
    with pytest.raises(ValueError, match="unresolved source revisions"):
        model_inputs.load_model_evidence("dsn", "election", ["a", "b"])
