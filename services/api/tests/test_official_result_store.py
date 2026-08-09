from datetime import UTC, datetime

from app.official_result_store import load_official_results


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, *_):
        return _Cursor(self.rows)


def test_official_result_store_builds_metadata_complete_latest_snapshot(monkeypatch):
    reported_at = datetime(2026, 8, 9, 10, tzinfo=UTC)
    retrieved_at = datetime(2026, 8, 9, 10, 0, 5, tzinfo=UTC)
    rows = [
        {
            "reporting_unit_id": "national",
            "reporting_unit_name": "National",
            "contestant_id": "a",
            "contestant_name": "Candidate A",
            "votes": 100,
            "reporting_fraction": 0.25,
            "reported_at": reported_at,
            "is_certified": False,
            "source_key": "official",
            "label": "Election authority",
            "url": "https://results.example.test/results.json",
            "authority": "official",
            "retrieved_at": retrieved_at,
            "license": "PUBLIC",
            "license_url": "https://results.example.test/license",
            "parser_version": "v1",
            "content_sha256": "a" * 64,
        }
    ]
    monkeypatch.setattr(
        "app.official_result_store.psycopg.connect", lambda *_, **__: _Connection(rows)
    )
    result = load_official_results("postgresql://fixture", "x-1")
    assert result is not None
    assert result["feed_available"] is True
    assert result["reporting_fraction"] == 0.25
    assert result["model_version"] == "official-results:v1"
    assert result["provenance"][0]["source_id"] == "official"
    assert result["results"][0]["source_snapshot_sha256"] == "a" * 64
