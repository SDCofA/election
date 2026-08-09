from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from typing import Literal

from pydantic import BaseModel, Field
from pypdf import PdfReader

from ..checkpoint import AdapterCheckpoint, CheckpointStore
from ..domain import RawSnapshot
from .http import HttpSnapshotFetcher


class CalendarParseError(ValueError):
    pass


class ElectionCalendarRecord(BaseModel):
    election_id: str
    jurisdiction_id: str
    name: str
    election_date: date
    status: str
    available_at: datetime
    source_snapshot_sha256: str
    source_url: str
    parser_version: str
    parser_confidence: float = Field(ge=0, le=1)
    fallback_used: bool = False
    freshness_warning: str | None = None


@dataclass(frozen=True)
class CalendarParserConfig:
    format: Literal["json", "csv", "ics", "html", "pdf"]
    parser_version: str
    jurisdiction_id: str
    id_field: str = "id"
    name_field: str = "name"
    date_field: str = "date"
    status_field: str = "status"
    json_list_field: str | None = "elections"
    date_formats: tuple[str, ...] = ("%Y-%m-%d", "%Y%m%d")
    minimum_confidence: float = 0.90
    pdf_row_pattern: str | None = None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _unfold_ics(text: str) -> list[str]:
    lines = text.replace("\r\n", "\n").split("\n")
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def _parse_ics(content: bytes) -> list[dict[str, str]]:
    records = []
    current: dict[str, str] | None = None
    for line in _unfold_ics(content.decode("utf-8-sig")):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            records.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0].upper()] = value
    return [
        {
            "id": item.get("UID", ""),
            "name": item.get("SUMMARY", ""),
            "date": item.get("DTSTART", "")[:8],
            "status": item.get("STATUS", "scheduled").lower(),
        }
        for item in records
    ]


def _parse_html(content: bytes) -> list[dict[str, str]]:
    parser = _TableParser()
    parser.feed(content.decode("utf-8-sig"))
    if len(parser.rows) < 2:
        return []
    headers = [item.strip().lower() for item in parser.rows[0]]
    return [dict(zip(headers, row, strict=False)) for row in parser.rows[1:]]


def _parse_pdf(content: bytes, pattern: str | None) -> list[dict[str, str]]:
    if not pattern:
        raise CalendarParseError("PDF adapters require a configured named-group row pattern")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    expression = re.compile(pattern, re.MULTILINE)
    required_groups = {"id", "name", "date", "status"}
    if not required_groups <= expression.groupindex.keys():
        raise CalendarParseError("PDF row pattern requires id, name, date, and status groups")
    return [match.groupdict() for match in expression.finditer(text)]


def _raw_records(content: bytes, config: CalendarParserConfig) -> list[dict]:
    if config.format == "json":
        payload = json.loads(content)
        if isinstance(payload, list):
            return payload
        if config.json_list_field and isinstance(payload.get(config.json_list_field), list):
            return payload[config.json_list_field]
        return []
    if config.format == "csv":
        return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    if config.format == "ics":
        return _parse_ics(content)
    if config.format == "html":
        return _parse_html(content)
    return _parse_pdf(content, config.pdf_row_pattern)


def _parse_date(value: str, formats: tuple[str, ...]) -> date:
    for date_format in formats:
        try:
            return datetime.strptime(value.strip(), date_format).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported election date: {value}")


def parse_calendar(
    content: bytes,
    snapshot: RawSnapshot,
    config: CalendarParserConfig,
) -> tuple[list[ElectionCalendarRecord], float]:
    raw = _raw_records(content, config)
    if not raw:
        raise CalendarParseError("No election records found")
    parsed = []
    for item in raw:
        try:
            record = ElectionCalendarRecord(
                election_id=str(item[config.id_field]).strip(),
                jurisdiction_id=config.jurisdiction_id,
                name=str(item[config.name_field]).strip(),
                election_date=_parse_date(str(item[config.date_field]), config.date_formats),
                status=str(item.get(config.status_field, "scheduled")).strip().lower(),
                available_at=snapshot.retrieved_at,
                source_snapshot_sha256=snapshot.sha256,
                source_url=snapshot.source_url,
                parser_version=config.parser_version,
                parser_confidence=1,
            )
            if not record.election_id or not record.name:
                raise ValueError("Election ID and name are required")
            parsed.append(record)
        except (KeyError, TypeError, ValueError):
            continue
    confidence = len(parsed) / len(raw)
    for index, record in enumerate(parsed):
        parsed[index] = record.model_copy(update={"parser_confidence": confidence})
    return parsed, confidence


class OfficialElectionAdapter:
    def __init__(
        self,
        fetcher: HttpSnapshotFetcher,
        checkpoints: CheckpointStore | None = None,
    ) -> None:
        self.fetcher = fetcher
        self.checkpoints = checkpoints
        self._last_known_good: dict[tuple[str, str], list[ElectionCalendarRecord]] = {}

    def fetch_calendar(
        self,
        source_id: str,
        endpoint: str,
        config: CalendarParserConfig,
    ) -> list[ElectionCalendarRecord]:
        key = (source_id, config.jurisdiction_id)
        fetched = self.fetcher.fetch(source_id, endpoint)
        if fetched is None:
            return self._fallback(
                key,
                "Source returned not-modified without a cached parse",
                "source_unavailable",
            )
        try:
            records, confidence = parse_calendar(fetched.content, fetched.snapshot, config)
            if confidence < config.minimum_confidence:
                raise CalendarParseError(
                    f"Parser confidence {confidence:.3f} is below {config.minimum_confidence:.3f}"
                )
        except (CalendarParseError, UnicodeError, json.JSONDecodeError) as error:
            return self._fallback(key, str(error), "parser_drift")
        self._last_known_good[key] = records
        if self.checkpoints is not None:
            self.checkpoints.save(
                AdapterCheckpoint(
                    adapter_id="official_calendar",
                    scope_id=f"{source_id}:{config.jurisdiction_id}",
                    parser_version=config.parser_version,
                    source_snapshot_sha256=fetched.snapshot.sha256,
                    payload={"records": [record.model_dump(mode="json") for record in records]},
                )
            )
        return records

    def _fallback(
        self,
        key: tuple[str, str],
        warning: str,
        failure_kind: str,
    ) -> list[ElectionCalendarRecord]:
        if self.checkpoints is not None:
            self.checkpoints.record_failure(
                "official_calendar",
                f"{key[0]}:{key[1]}",
                failure_kind,
                warning,
            )
        records = self._last_known_good.get(key)
        if records is None and self.checkpoints is not None:
            checkpoint = self.checkpoints.load("official_calendar", f"{key[0]}:{key[1]}")
            if checkpoint is not None:
                records = [
                    ElectionCalendarRecord.model_validate(record)
                    for record in checkpoint.payload.get("records", [])
                ]
                if not records:
                    records = None
        if records is None:
            raise CalendarParseError(
                f"Calendar parse failed and no last-known-good exists: {warning}"
            )
        now = datetime.now(UTC)
        return [
            item.model_copy(
                update={
                    "fallback_used": True,
                    "freshness_warning": warning,
                    "available_at": now,
                }
            )
            for item in records
        ]
