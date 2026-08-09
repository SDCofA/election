from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .adapters.official_results import ResultParserConfig
from .registry import SourceRegistry


class LiveWindow(BaseModel):
    opens_at: datetime
    closes_at: datetime

    @field_validator("opens_at", "closes_at")
    @classmethod
    def timestamps_require_timezones(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Official-result live windows require timezones")
        return value

    @model_validator(mode="after")
    def closes_after_open(self) -> LiveWindow:
        if self.closes_at <= self.opens_at:
            raise ValueError("Official-result live window must close after it opens")
        return self


class OfficialResultFeedConfig(BaseModel):
    source_id: str
    endpoint: str
    format: Literal["json", "csv"]
    parser_version: str
    live_window: LiveWindow
    unit_field: str = "reporting_unit_id"
    contestant_field: str = "contestant_id"
    votes_field: str = "votes"
    reporting_field: str = "reporting_fraction"
    reported_at_field: str = "reported_at"
    certified_field: str = "is_certified"
    json_list_field: str = "results"
    minimum_confidence: float = Field(default=0.98, ge=0.98, le=1)

    def parser_config(self, election_id: str) -> ResultParserConfig:
        return ResultParserConfig(
            format=self.format,
            parser_version=self.parser_version,
            election_id=election_id,
            unit_field=self.unit_field,
            contestant_field=self.contestant_field,
            votes_field=self.votes_field,
            reporting_field=self.reporting_field,
            reported_at_field=self.reported_at_field,
            certified_field=self.certified_field,
            json_list_field=self.json_list_field,
            minimum_confidence=self.minimum_confidence,
        )


def validated_feed_config(pack: dict, registry: SourceRegistry) -> OfficialResultFeedConfig | None:
    raw = pack.get("official_results")
    if raw is None:
        return None
    status = raw.get("status")
    if status == "unavailable":
        if not str(raw.get("reason", "")).strip():
            raise ValueError("Unavailable official-result feed requires a reason")
        return None
    if status != "approved":
        raise ValueError("Official-result feed status must be approved or unavailable")
    config = OfficialResultFeedConfig.model_validate(
        {key: value for key, value in raw.items() if key != "status"}
    )
    adapters = {item["source_id"]: item for item in pack["source_adapters"]}
    adapter = adapters.get(config.source_id)
    if adapter is None or adapter.get("status") != "approved":
        raise ValueError("Official-result feed must use an approved pack adapter")
    registry.require_approved(config.source_id)
    citations = {item["source_id"] for item in pack["election"]["sources"]}
    if config.source_id not in citations:
        raise ValueError("Official-result feed must have election provenance")
    units = pack.get("reporting_units", [])
    if not units:
        raise ValueError("Approved official-result feed requires reporting units")
    unit_ids = {item.get("id") for item in units}
    if None in unit_ids or len(unit_ids) != len(units):
        raise ValueError("Official-result reporting-unit IDs must be present and unique")
    for unit in units:
        if not {"id", "name", "level"}.issubset(unit):
            raise ValueError("Official-result reporting units require id, name, and level")
        if unit.get("parent_id") is not None and unit["parent_id"] not in unit_ids:
            raise ValueError("Official-result reporting-unit parent is unknown")
    return config


def is_live_window(config: OfficialResultFeedConfig, now: datetime) -> bool:
    if now.tzinfo is None:
        raise ValueError("Live-result poll time requires a timezone")
    return config.live_window.opens_at <= now <= config.live_window.closes_at


def select_active_feeds(
    packs: list[dict], registry: SourceRegistry, now: datetime
) -> tuple[int, list[tuple[dict, OfficialResultFeedConfig]]]:
    configured_count = 0
    active = []
    for pack in packs:
        config = validated_feed_config(pack, registry)
        if config is None:
            continue
        configured_count += 1
        if is_live_window(config, now):
            active.append((pack, config))
    return configured_count, active
