from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ElectionSystem(StrEnum):
    UNRESOLVED = "unresolved"
    PRESIDENTIAL_RUNOFF = "presidential_runoff"
    FPTP = "fptp"
    PROPORTIONAL = "proportional"
    MIXED_MEMBER = "mixed_member"
    ELECTORAL_COLLEGE = "electoral_college"
    INSTITUTIONAL = "institutional"


class QualityGrade(StrEnum):
    HIGH = "A"
    GOOD = "B"
    LIMITED = "C"
    STRUCTURAL = "D"


class CoverageStatus(StrEnum):
    FORECAST = "forecast"
    CALENDAR_ONLY = "calendar_only"
    MECHANICS_BLOCKED = "mechanics_blocked"


class SourceRef(BaseModel):
    source_id: str
    label: str
    url: str
    authority: str
    retrieved_at: datetime
    license: str
    license_url: str


class Jurisdiction(BaseModel):
    id: str
    name: str
    iso3: str | None = None
    region: str
    eligibility: str
    is_exception: bool = False
    forecast_enabled: bool = True
    coverage_status: CoverageStatus = CoverageStatus.MECHANICS_BLOCKED
    blocking_reasons: list[str] = Field(
        default_factory=lambda: [
            "No sourced national calendar and validated electoral-system pack are onboarded"
        ]
    )
    flag: str


class Contestant(BaseModel):
    id: str
    name: str
    short_name: str
    color: str
    leader: str | None = None
    incumbent: bool = False
    ideology: str | None = None


class Election(BaseModel):
    id: str
    jurisdiction_id: str
    name: str
    election_date: date | None
    date_confidence: str
    system: ElectionSystem
    seats_total: int | None = None
    majority: int | None = None
    threshold: float = Field(default=0, ge=0, lt=1)
    status: str
    last_updated: datetime
    contestants: list[Contestant]
    sources: list[SourceRef]


class DriverContribution(BaseModel):
    key: str
    label: str
    value: str
    contribution: float = Field(ge=-1, le=1)
    direction: str
    confidence: float = Field(ge=0, le=1)


class DriverSensitivity(BaseModel):
    driver_key: str
    label: str
    negative_scenario: float = Field(default=-1, ge=-1, le=1)
    observed_scenario: float = Field(ge=-1, le=1)
    positive_scenario: float = Field(default=1, ge=-1, le=1)
    negative_incumbent_share_shift: float = Field(ge=-1, le=1)
    observed_incumbent_share_shift: float = Field(ge=-1, le=1)
    positive_incumbent_share_shift: float = Field(ge=-1, le=1)
    confidence: float = Field(ge=0, le=1)
    clipped: bool
    method: str = "One-at-a-time structural perturbation; all other inputs held constant"


class ContestantForecast(BaseModel):
    contestant_id: str
    win_probability: float = Field(ge=0, le=1)
    projected_share: float = Field(ge=0, le=1)
    share_low: float = Field(ge=0, le=1)
    share_high: float = Field(ge=0, le=1)
    projected_seats: int | None = None
    seats_low: int | None = None
    seats_high: int | None = None


class CoalitionForecast(BaseModel):
    member_ids: list[str]
    majority_probability: float = Field(ge=0, le=1)
    seats_median: int
    seats_low: int
    seats_high: int


class ForecastSnapshot(BaseModel):
    id: str
    election_id: str
    as_of: datetime
    published_at: datetime
    model_version: str
    model_family: str
    selection_status: str
    simulation_count: int = Field(ge=1_000_000, le=1_000_000)
    seed: int
    data_quality: QualityGrade
    freshness: str
    missing_drivers: list[str]
    regional_forecast_supported: bool
    headline: str
    majority_probability: float = Field(ge=0, le=1)
    turnout_median: float = Field(ge=0, le=1)
    outcomes: list[ContestantForecast]
    coalition_outcomes: list[CoalitionForecast]
    drivers: list[DriverContribution]
    driver_sensitivity: list[DriverSensitivity] = Field(default_factory=list)
    methodology_url: str
    input_revision_ids: list[str] = Field(default_factory=list)
    input_provenance: list[SourceRef]
    provenance: list[SourceRef]


class BacktestMetrics(BaseModel):
    model_family: str
    folds: int
    brier_score: float = Field(ge=0)
    brier_ci_low: float = Field(ge=0)
    brier_ci_high: float = Field(ge=0)
    vote_share_rmse: float = Field(ge=0)
    interval_coverage: float = Field(ge=0, le=1)
    calibration_error: float = Field(ge=0, le=1)


class ModelComparison(BaseModel):
    election_id: str
    status: str
    winner: str | None
    historical_leader: str | None = None
    selection_rule: str
    metrics: list[BacktestMetrics]
    leakage_check: bool
    fold_count: int = 0
    held_out_election_count: int = 0
    simulation_count_per_model_fold: int = Field(default=0, ge=0)
    evaluated_horizon_min_days: int | None = None
    evaluated_horizon_max_days: int | None = None
    target_horizon_days: int | None = None
    evaluation_period_start: date | None = None
    evaluation_period_end: date | None = None
    dataset_sha256: str | None = None
    vintage_verified: bool = False
    message: str
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class SimulationSummary(BaseModel):
    snapshot_id: str
    election_id: str
    model_family: str
    simulation_count: int = Field(ge=1_000_000, le=1_000_000)
    seed: int
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    outcomes: list[ContestantForecast]
    provenance: list[SourceRef]


class DriverReport(BaseModel):
    election_id: str
    snapshot_id: str
    drivers: list[DriverContribution]
    sensitivity: list[DriverSensitivity] = Field(default_factory=list)
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class CoalitionReport(BaseModel):
    election_id: str
    snapshot_id: str
    majority: int
    coalitions: list[CoalitionForecast]
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class SourceLedger(BaseModel):
    election_id: str
    sources: list[SourceRef]
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class MapLayer(BaseModel):
    election_id: str
    supported: bool
    reason: str
    geojson: dict | None = None
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class ElectionMechanics(BaseModel):
    election_id: str
    system: ElectionSystem
    rules: dict
    source_adapters: list[dict]
    forecast_enabled: bool
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class OfficialResults(BaseModel):
    election_id: str
    feed_available: bool
    status: str
    reporting_fraction: float = Field(ge=0, le=1)
    results: list[dict]
    as_of: datetime
    published_at: datetime
    model_version: str
    data_quality: QualityGrade
    freshness: str
    provenance: list[SourceRef]


class ElectionDetail(BaseModel):
    jurisdiction: Jurisdiction
    election: Election
    forecast: ForecastSnapshot | None


class Health(BaseModel):
    status: str
    version: str
    timestamp: datetime
    dependencies: dict[str, str] = Field(default_factory=dict)


class CatalogStatus(BaseModel):
    schema_version: int
    generated_at: datetime
    eligibility_version: int
    eligibility_year: int
    eligibility_rule: str
    eligibility_snapshot_sha256: str
    eligible_jurisdictions: int
    total_jurisdictions: int
    forecast_ready: int
    calendar_only: int
    mechanics_blocked: int
    sourced_calendars: int
