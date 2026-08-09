from datetime import UTC, date, datetime
from threading import Lock

from app import calendar_store
from app import repository as repository_module
from app.calendar_store import CalendarRevision
from app.models import Election
from app.repository import CatalogRepository


class _Rows:
    def fetchall(self):
        return [
            {
                "election_id": "br-2026-president",
                "election_date": date(2026, 10, 4),
                "date_confidence": "official",
                "status": "calendar only",
                "available_at": datetime(2026, 2, 26, tzinfo=UTC),
                "retrieved_at": datetime(2026, 8, 9, tzinfo=UTC),
                "source_revision_id": "00000000-0000-0000-0000-000000000001",
            }
        ]


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, query):
        assert "DISTINCT ON (calendar.election_id)" in query
        assert "source.retrieved_at <= now()" in query
        return _Rows()


def test_latest_calendar_store_returns_exact_source_revision(monkeypatch):
    monkeypatch.setattr(
        calendar_store.psycopg,
        "connect",
        lambda *_args, **_kwargs: _Connection(),
    )
    revisions = calendar_store.load_latest_calendars("dsn")
    revision = revisions["br-2026-president"]
    assert revision.election_date == date(2026, 10, 4)
    assert revision.source_revision_id == "00000000-0000-0000-0000-000000000001"


def test_repository_refreshes_calendar_without_mutating_published_snapshot(monkeypatch):
    repo = CatalogRepository.__new__(CatalogRepository)
    election = Election.model_validate(
        {
            "id": "br-2026-president",
            "jurisdiction_id": "bra",
            "name": "Brazil",
            "election_date": "2026-10-04",
            "date_confidence": "official",
            "system": "presidential_runoff",
            "status": "calendar only",
            "last_updated": "2026-08-09T00:00:00Z",
            "contestants": [],
            "sources": [],
        }
    )
    published = object()
    repo.elections = {election.id: election}
    repo.forecasts = {election.id: published}
    repo.candidates = {(election.id, "baseline_ensemble", "old"): object()}
    repo.alternatives = {(election.id, "markov_momentum"): object()}
    repo.calendar_store_status = "not_configured"
    repo._calendar_refresh_at = 0
    repo._calendar_lock = Lock()
    revision = CalendarRevision(
        election_id=election.id,
        election_date=date(2026, 10, 5),
        date_confidence="official correction",
        status="calendar corrected",
        available_at=datetime(2026, 8, 10, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 10, tzinfo=UTC),
        source_revision_id="00000000-0000-0000-0000-000000000002",
    )
    monkeypatch.setenv("DATABASE_URL", "dsn")
    monkeypatch.setattr(
        repository_module, "load_latest_calendars", lambda _dsn: {election.id: revision}
    )

    repo.refresh_calendars(force=True)

    assert repo.elections[election.id].election_date == date(2026, 10, 5)
    assert repo.candidates == {}
    assert repo.alternatives == {}
    assert repo.forecasts[election.id] is published
