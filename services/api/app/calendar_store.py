from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import psycopg
from psycopg.rows import dict_row


class CalendarStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CalendarRevision:
    election_id: str
    election_date: date
    date_confidence: str
    status: str
    available_at: datetime
    retrieved_at: datetime
    source_revision_id: str


def load_latest_calendars(dsn: str) -> dict[str, CalendarRevision]:
    try:
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=2) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT ON (calendar.election_id)
                  calendar.election_id, calendar.election_date, calendar.date_confidence,
                  calendar.status, calendar.available_at, source.retrieved_at,
                  calendar.id AS source_revision_id
                FROM calendar_revisions calendar
                JOIN source_revisions revision ON revision.id = calendar.id
                JOIN sources source ON source.id = revision.source_id
                WHERE calendar.available_at <= now()
                  AND source.retrieved_at <= now()
                ORDER BY calendar.election_id, calendar.revision DESC
                """
            ).fetchall()
    except psycopg.Error as error:
        raise CalendarStoreUnavailable from error
    return {
        row["election_id"]: CalendarRevision(
            election_id=row["election_id"],
            election_date=row["election_date"],
            date_confidence=row["date_confidence"],
            status=row["status"],
            available_at=row["available_at"],
            retrieved_at=row["retrieved_at"],
            source_revision_id=str(row["source_revision_id"]),
        )
        for row in rows
    }
