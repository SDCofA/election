from __future__ import annotations

import json
import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from threading import Lock
from time import monotonic

from .backtest import (
    BacktestReport,
    load_backtest_dataset,
    load_backtest_report,
    walk_forward_backtest,
)
from .calendar_store import CalendarRevision, CalendarStoreUnavailable, load_latest_calendars
from .forecast_store import load_published_forecasts
from .model_inputs import ModelEvidence, load_model_evidence
from .models import (
    CatalogStatus,
    CoalitionReport,
    CoverageStatus,
    DriverContribution,
    DriverReport,
    DriverSensitivity,
    Election,
    ElectionDetail,
    ElectionMechanics,
    ForecastSnapshot,
    Jurisdiction,
    MapLayer,
    ModelComparison,
    OfficialResults,
    QualityGrade,
    SimulationSummary,
    SourceLedger,
)
from .official_result_store import OfficialResultStoreUnavailable, load_official_results
from .simulation import SIMULATION_COUNT, ScenarioInput, SimulationInput, run_simulation
from .systems import validate_pack_rules

PACKS_DIR = Path(__file__).parent / "packs"
BACKTESTS_DIR = Path(__file__).parent / "backtests"
CATALOG_PATH = Path(__file__).parent / "catalog" / "vdem-v16.json"
MODEL_VERSION = "structural-ensemble-0.5.0"
G20_COUNTRY_IDS = frozenset(
    {
        "arg",
        "aus",
        "bra",
        "can",
        "chn",
        "deu",
        "fra",
        "gbr",
        "idn",
        "ind",
        "ita",
        "jpn",
        "kor",
        "mex",
        "rus",
        "sau",
        "tur",
        "usa",
        "zaf",
    }
)


def horizon_uncertainty_scale(horizon_days: int, reference_days: int = 90) -> float:
    """Widen structural forecast error with time, with conservative stability caps."""
    if reference_days < 1:
        raise ValueError("Volatility reference horizon must be positive")
    effective_horizon = max(horizon_days, 7)
    return min(1.60, max(0.75, (effective_horizon / reference_days) ** 0.18))


class CatalogRepository:
    def __init__(self) -> None:
        self.jurisdictions: dict[str, Jurisdiction] = {}
        self.elections: dict[str, Election] = {}
        self.forecasts: dict[str, ForecastSnapshot] = {}
        self.pack_data: dict[str, dict] = {}
        self.alternatives: dict[tuple[str, str], ForecastSnapshot] = {}
        self.candidates: dict[tuple[str, str, str], ForecastSnapshot] = {}
        self.snapshots: dict[str, ForecastSnapshot] = {}
        self.published_snapshots: dict[str, ForecastSnapshot] = {}
        self.comparisons: dict[str, ModelComparison] = {}
        self.backtest_reports: dict[str, BacktestReport] = {}
        self.catalog_payload: dict = {}
        self.forecast_store_status = "not_configured"
        self.calendar_store_status = "not_configured"
        self._calendar_refresh_at = 0.0
        self._calendar_lock = Lock()
        self._load()

    def _load(self) -> None:
        self.catalog_payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        self.jurisdictions = {
            item["id"]: Jurisdiction.model_validate(item)
            for item in self.catalog_payload["jurisdictions"]
            if item["id"] in G20_COUNTRY_IDS
        }
        calendar_revisions: dict[str, CalendarRevision] = {}
        if dsn := os.getenv("DATABASE_URL"):
            try:
                calendar_revisions = load_latest_calendars(dsn)
                self.calendar_store_status = f"connected:{len(calendar_revisions)}"
            except CalendarStoreUnavailable:
                self.calendar_store_status = "unavailable"
            self._calendar_refresh_at = monotonic()
        for path in sorted(PACKS_DIR.rglob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            jurisdiction = Jurisdiction.model_validate(data["jurisdiction"])
            if jurisdiction.id not in G20_COUNTRY_IDS:
                continue
            managed = self.jurisdictions.get(jurisdiction.id)
            if managed and jurisdiction.eligibility.startswith("v-dem:"):
                jurisdiction = jurisdiction.model_copy(
                    update={
                        "eligibility": managed.eligibility,
                        "region": managed.region,
                        "flag": managed.flag,
                    }
                )
            coverage_status = (
                CoverageStatus.FORECAST
                if jurisdiction.forecast_enabled
                else CoverageStatus(
                    data["jurisdiction"].get("coverage_status", "mechanics_blocked")
                )
            )
            jurisdiction = jurisdiction.model_copy(
                update={
                    "coverage_status": coverage_status,
                    "blocking_reasons": (
                        []
                        if coverage_status == CoverageStatus.FORECAST
                        else data["jurisdiction"].get(
                            "blocking_reasons",
                            ["Forecast publication requirements remain unresolved"],
                        )
                    ),
                }
            )
            election = Election.model_validate(data["election"])
            if not election.potential_candidates:
                election = election.model_copy(
                    update={
                        "potential_candidates": [
                            contestant.model_copy(
                                update={
                                    "ballot_status": (
                                        contestant.ballot_status
                                        if contestant.ballot_status != "official"
                                        else "modeled"
                                    ),
                                    "basis": contestant.basis
                                    or "Modeled current field; the final official ballot remains authoritative.",
                                }
                            )
                            for contestant in election.contestants
                        ]
                    }
                )
            if revision := calendar_revisions.get(election.id):
                election = self._calendar_override(election, revision)
            if election.jurisdiction_id != jurisdiction.id:
                raise ValueError(f"Jurisdiction mismatch in {path.name}")
            validate_pack_rules(election, data["rules"])
            if jurisdiction.forecast_enabled and election.election_date is None:
                raise ValueError(f"{election.id}: forecast-enabled election requires a date")
            self.jurisdictions[jurisdiction.id] = jurisdiction
            self.elections[election.id] = election
            self.pack_data[election.id] = data

            if jurisdiction.forecast_enabled:
                report = self._backtest_report(data, election)
                selected_family = (
                    report.winner
                    if report is not None
                    and report.promotion_status == "challenger_promoted"
                    and report.winner is not None
                    else "baseline_ensemble"
                )
                snapshot = self._build_forecast(election, data, selected_family, report)
                self.forecasts[election.id] = snapshot
                self.snapshots[snapshot.id] = snapshot
                self.published_snapshots[snapshot.id] = snapshot
                self.comparisons[election.id] = self._model_comparison(
                    election, snapshot, report, data
                )
                if report is not None:
                    self.backtest_reports[election.id] = report
        self._load_persisted_forecasts()

    @staticmethod
    def _calendar_override(election: Election, revision: CalendarRevision) -> Election:
        return election.model_copy(
            update={
                "election_date": revision.election_date,
                "date_confidence": revision.date_confidence,
                "status": revision.status,
                "last_updated": revision.retrieved_at,
            }
        )

    def refresh_calendars(self, *, force: bool = False) -> None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn or (not force and monotonic() - self._calendar_refresh_at < 60):
            return
        with self._calendar_lock:
            if not force and monotonic() - self._calendar_refresh_at < 60:
                return
            try:
                revisions = load_latest_calendars(dsn)
            except CalendarStoreUnavailable:
                self.calendar_store_status = "unavailable"
                self._calendar_refresh_at = monotonic()
                return
            changed = set()
            for election_id, revision in revisions.items():
                election = self.elections.get(election_id)
                if election is None:
                    continue
                updated = self._calendar_override(election, revision)
                if updated != election:
                    self.elections[election_id] = updated
                    changed.add(election_id)
            if changed:
                self.candidates = {
                    key: value for key, value in self.candidates.items() if key[0] not in changed
                }
                self.alternatives = {
                    key: value for key, value in self.alternatives.items() if key[0] not in changed
                }
            self.calendar_store_status = f"connected:{len(revisions)}"
            self._calendar_refresh_at = monotonic()

    def _load_persisted_forecasts(self) -> None:
        dsn = os.getenv("DATABASE_URL")
        if not dsn:
            return
        persisted = load_published_forecasts(dsn)
        self.forecast_store_status = f"connected:{len(persisted)}"
        for snapshot in persisted:
            if snapshot.election_id not in self.elections:
                raise ValueError(
                    f"Persisted forecast references unknown election: {snapshot.election_id}"
                )
            self.snapshots[snapshot.id] = snapshot
            self.published_snapshots[snapshot.id] = snapshot
            current = self.forecasts.get(snapshot.election_id)
            if current is None or (snapshot.published_at, snapshot.id) > (
                current.published_at,
                current.id,
            ):
                self.forecasts[snapshot.election_id] = snapshot

    @staticmethod
    def _backtest_report(data: dict, election: Election) -> BacktestReport | None:
        relative_path = data.get("backtest_dataset")
        if not relative_path:
            return None
        root = BACKTESTS_DIR.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Backtest dataset path escapes the approved directory")
        dataset = load_backtest_dataset(path)
        if election.election_date is None:
            raise ValueError(f"{election.id}: dated backtest target is required")
        forecast_as_of = date.fromisoformat(data["election"]["last_updated"][:10])
        target_horizon_days = max(1, (election.election_date - forecast_as_of).days)
        if relative_report := data.get("backtest_report"):
            report_path = (root / relative_report).resolve()
            if not report_path.is_relative_to(root):
                raise ValueError("Backtest report path escapes the approved directory")
            return load_backtest_report(
                report_path,
                dataset_sha256=dataset.dataset_sha256,
                target_horizon_days=target_horizon_days,
                expected_sha256=data["backtest_report_sha256"],
            )
        return walk_forward_backtest(
            list(dataset.records),
            minimum_train=dataset.minimum_train_elections,
            dataset_sha256=dataset.dataset_sha256,
            target_horizon_days=target_horizon_days,
        )

    @staticmethod
    def _model_comparison(
        election: Election,
        snapshot: ForecastSnapshot,
        report: BacktestReport | None,
        data: dict,
    ) -> ModelComparison:
        if report is None:
            feasibility = data.get("backtest_feasibility", {})
            constraints = list(feasibility.get("validation_constraints", []))
            return ModelComparison(
                election_id=election.id,
                status="insufficient_historical_vintages",
                winner=None,
                selection_rule=(
                    "public baseline plus challengers under strict multi-origin source-vintage "
                    "walk-forward; election-clustered "
                    "paired-bootstrap Brier superiority; RMSE and empirical "
                    "interval-coverage gates"
                ),
                metrics=[],
                leakage_check=True,
                historical_election_count=int(feasibility.get("historical_election_count", 0)),
                historical_span_years=int(feasibility.get("historical_span_years", 0)),
                maximum_held_out_elections=int(feasibility.get("maximum_held_out_elections", 0)),
                validation_constraints=constraints,
                message=(
                    feasibility.get("message")
                    or "No champion declared: no approved historical source-vintage dataset is "
                    "attached to this jurisdiction pack."
                ),
                **CatalogRepository._snapshot_metadata(snapshot),
            )
        challenger_metrics = [
            metric
            for metric in report.metrics
            if metric.model_family in {"gaussian_monte_carlo", "markov_momentum"}
        ]
        historical_leader = (
            min(
                challenger_metrics,
                key=lambda item: (item.brier_score, item.vote_share_rmse),
            ).model_family
            if challenger_metrics
            else None
        )
        return ModelComparison(
            election_id=election.id,
            status=report.promotion_status,
            winner=report.winner,
            historical_leader=historical_leader,
            selection_rule=(
                "public baseline and challengers; minimum eight strict forecast-origin folds "
                "across three held-out elections "
                "and twenty years of source-vintage history; contemporaneously archived "
                "poll vintages and verified source revisions; "
                "election-clustered paired-bootstrap Brier superiority; RMSE and "
                "interval-coverage gates"
            ),
            metrics=list(report.metrics),
            leakage_check=True,
            fold_count=len(report.folds),
            held_out_election_count=report.held_out_election_count,
            simulation_count_per_model_fold=report.simulation_count,
            evaluated_horizon_min_days=report.evaluated_horizon_min_days,
            evaluated_horizon_max_days=report.evaluated_horizon_max_days,
            target_horizon_days=report.target_horizon_days,
            evaluation_period_start=report.evaluation_period_start,
            evaluation_period_end=report.evaluation_period_end,
            dataset_sha256=report.dataset_sha256,
            vintage_verified=report.provenance_verified,
            historical_election_count=int(
                data.get("backtest_feasibility", {}).get("historical_election_count", 0)
            ),
            historical_span_years=int(
                data.get("backtest_feasibility", {}).get("historical_span_years", 0)
            ),
            maximum_held_out_elections=int(
                data.get("backtest_feasibility", {}).get("maximum_held_out_elections", 0)
            ),
            validation_constraints=list(
                data.get("backtest_feasibility", {}).get("validation_constraints", [])
            ),
            message="; ".join(report.promotion_reasons),
            **CatalogRepository._snapshot_metadata(snapshot),
        )

    def _build_forecast(
        self,
        election: Election,
        data: dict,
        model_family: str,
        backtest_report: BacktestReport | None = None,
        evidence: ModelEvidence | None = None,
    ) -> ForecastSnapshot:
        version = f"{MODEL_VERSION}:{model_family}"
        incumbent_index = next(
            (index for index, item in enumerate(election.contestants) if item.incumbent), None
        )
        candidate_count = len(election.contestants)
        default_turnout_sensitivity = tuple(
            0.12 if index == incumbent_index else -0.12 / max(candidate_count - 1, 1)
            for index in range(candidate_count)
        )
        base_shares = tuple(data["model"]["base_shares"])
        volatility = float(data["model"]["volatility"])
        poll_count = 0
        poll_age_days: int | None = None
        forecast_as_of = (
            evidence.as_of.date() if evidence is not None else election.last_updated.date()
        )
        horizon_days = max(0, (election.election_date - forecast_as_of).days)
        uncertainty_scale = horizon_uncertainty_scale(
            horizon_days,
            int(data["model"].get("volatility_reference_days", 90)),
        )
        volatility *= uncertainty_scale
        if evidence is not None and evidence.poll_aggregate is not None:
            poll_age_days = max(
                0,
                (evidence.as_of.date() - evidence.poll_aggregate.latest_available_at.date()).days,
            )
            horizon_weight = max(
                0.25,
                min(0.72, 0.72 * math.exp(-max(0, horizon_days - 60) / 730)),
            )
            poll_weight = horizon_weight * math.exp(-poll_age_days / 90)
            blended = [
                (1 - poll_weight) * prior + poll_weight * poll
                for prior, poll in zip(base_shares, evidence.poll_aggregate.shares, strict=True)
            ]
            total = sum(blended)
            base_shares = tuple(value / total for value in blended)
            poll_count = evidence.poll_aggregate.poll_count
            poll_dispersion = max(
                math.sqrt(max(row[index], 0))
                for index, row in enumerate(evidence.poll_aggregate.covariance)
            )
            volatility = max(volatility, poll_dispersion)
        volatility = min(0.18, volatility)
        # Qualitative pack drivers are reporting context, not fitted causal effects.
        # They cannot move a forecast until a source-vintage coefficient model passes
        # the same country-specific walk-forward promotion gates as every challenger.
        base_fundamental_shift = 0.0
        driver_sensitivity: list[DriverSensitivity] = []
        simulation = run_simulation(
            SimulationInput(
                election=election,
                base_shares=base_shares,
                volatility=volatility,
                turnout=data["model"]["turnout"],
                model_family=model_family,
                campaign_steps=max(1, min(24, math.ceil(horizon_days / 7))),
                incumbent_index=incumbent_index,
                fundamental_shift=base_fundamental_shift,
                security_volatility=0.0,
                house_effects=tuple(data["model"].get("house_effects", [0] * candidate_count)),
                turnout_sensitivity=tuple(
                    data["model"].get("turnout_sensitivity", default_turnout_sensitivity)
                ),
                markov_transition=(
                    backtest_report.markov_transition if backtest_report is not None else ()
                ),
                markov_step=(backtest_report.markov_step if backtest_report is not None else None),
                scenarios=tuple(
                    ScenarioInput(
                        scenario_id=item["id"],
                        label=item["label"],
                        weight=float(item["weight"]),
                        base_shares=tuple(item["base_shares"]),
                        assumption=item["assumption"],
                        source_ids=tuple(item.get("source_ids", [])),
                    )
                    for item in data["model"].get("scenarios", [])
                ),
            ),
            version,
        )
        input_provenance = list(evidence.provenance) if evidence is not None else []
        input_revision_ids = list(evidence.source_revision_ids) if evidence is not None else []
        has_vintage_inputs = bool(input_revision_ids and input_provenance)
        evidence_complete = bool(
            evidence is not None
            and not evidence.missing_macro_features
            and evidence.poll_aggregate is not None
            and poll_age_days is not None
            and poll_age_days <= 45
        )
        configured_quality = QualityGrade(data["model"]["data_quality"])
        promoted = (
            backtest_report is not None
            and backtest_report.promotion_status == "challenger_promoted"
            and backtest_report.winner == model_family
        )
        return ForecastSnapshot(
            id=(
                f"{election.id}-{MODEL_VERSION}-{model_family}-"
                f"{(evidence.as_of if evidence else election.last_updated):%Y%m%dT%H%M%SZ}-"
                f"{evidence.content_sha256[:12] if evidence else 'structural'}"
            ),
            election_id=election.id,
            as_of=evidence.as_of if evidence else election.last_updated,
            published_at=evidence.as_of if evidence else election.last_updated,
            model_version=MODEL_VERSION,
            model_family=model_family,
            selection_status=(
                "baseline retained until reliable walk-forward promotion evidence"
                if model_family == "baseline_ensemble"
                else (
                    "automatically promoted by strict source-vintage backtest gates"
                    if promoted
                    else "experimental challenger; not publicly promoted"
                )
            ),
            simulation_count=SIMULATION_COUNT,
            seed=simulation.seed,
            data_quality=(
                configured_quality
                if has_vintage_inputs and evidence_complete
                else QualityGrade.STRUCTURAL
            ),
            freshness=(
                f"{poll_count} source-vintage polls; latest is {poll_age_days} days old"
                if has_vintage_inputs and evidence_complete
                else (
                    f"source-vintage inputs incomplete or stale; latest poll is {poll_age_days} days old"
                    if has_vintage_inputs and poll_age_days is not None
                    else "structural-only; no source-vintage feature snapshot"
                )
            ),
            missing_drivers=(
                [item["label"] for item in data["drivers"] if item["confidence"] < 0.20]
                + (
                    [f"Macro: {item}" for item in evidence.missing_macro_features]
                    if evidence is not None
                    else ["Source-vintage polling and fundamentals"]
                )
                + (
                    []
                    if (
                        evidence is not None
                        and evidence.poll_aggregate is not None
                        and poll_age_days is not None
                        and poll_age_days <= 45
                    )
                    else ["Source-vintage polling"]
                )
                + (
                    ["Validated historical release-vintage backtest", "Subnational model"]
                    if configured_quality == QualityGrade.STRUCTURAL or not evidence_complete
                    else []
                )
            ),
            regional_forecast_supported=False,
            headline=data["model"].get(
                "headline",
                "Structural signals remain provisional; uncertainty is explicitly widened.",
            ),
            majority_probability=simulation.majority_probability,
            turnout_median=simulation.turnout_median,
            forecast_horizon_days=horizon_days,
            uncertainty_scale=uncertainty_scale,
            effective_volatility=volatility,
            outcomes=simulation.outcomes,
            scenario_outcomes=simulation.scenario_outcomes,
            coalition_outcomes=simulation.coalition_outcomes,
            drivers=[DriverContribution.model_validate(item) for item in data["drivers"]],
            driver_sensitivity=driver_sensitivity,
            methodology_url="/methodology",
            input_revision_ids=input_revision_ids,
            input_provenance=input_provenance,
            provenance=[*election.sources, *input_provenance],
        )

    def candidate(self, election_id: str, model_family: str) -> ForecastSnapshot | None:
        self.refresh_calendars()
        if model_family not in {
            "baseline_ensemble",
            "gaussian_monte_carlo",
            "markov_momentum",
        }:
            return None
        election = self.elections.get(election_id)
        data = self.pack_data.get(election_id)
        if (
            election is None
            or data is None
            or not self.jurisdictions[election.jurisdiction_id].forecast_enabled
        ):
            return None
        dsn = os.getenv("DATABASE_URL")
        evidence = (
            load_model_evidence(
                dsn,
                election_id,
                [contestant.id for contestant in election.contestants],
            )
            if dsn
            else None
        )
        evidence_key = evidence.content_sha256 if evidence is not None else "structural"
        key = (election_id, model_family, evidence_key)
        if key not in self.candidates:
            self.candidates[key] = self._build_forecast(
                election,
                data,
                model_family,
                self.backtest_reports.get(election_id),
                evidence,
            )
        return self.candidates[key]

    def alternative(self, election_id: str, model_family: str) -> ForecastSnapshot | None:
        if model_family not in {"gaussian_monte_carlo", "markov_momentum"}:
            return None
        public = self.forecasts.get(election_id)
        if public is not None and public.model_family == model_family:
            return public
        election = self.elections.get(election_id)
        data = self.pack_data.get(election_id)
        if (
            election is None
            or data is None
            or not self.jurisdictions[election.jurisdiction_id].forecast_enabled
        ):
            return None
        key = (election_id, model_family)
        if key not in self.alternatives:
            self.alternatives[key] = self._build_forecast(
                election, data, model_family, self.backtest_reports.get(election_id)
            )
            self.snapshots[self.alternatives[key].id] = self.alternatives[key]
        return self.alternatives[key]

    def forecast_history(self, election_id: str) -> list[ForecastSnapshot]:
        return sorted(
            (item for item in self.published_snapshots.values() if item.election_id == election_id),
            key=lambda item: (item.published_at, item.model_family),
            reverse=True,
        )

    def comparison(self, election_id: str) -> ModelComparison | None:
        return self.comparisons.get(election_id)

    def simulation_summary(self, election_id: str) -> SimulationSummary | None:
        snapshot = self.forecasts.get(election_id)
        if snapshot is None:
            return None
        return SimulationSummary(
            snapshot_id=snapshot.id,
            election_id=election_id,
            model_family=snapshot.model_family,
            simulation_count=snapshot.simulation_count,
            seed=snapshot.seed,
            outcomes=snapshot.outcomes,
            **self._snapshot_metadata(snapshot),
        )

    def driver_report(self, election_id: str) -> DriverReport | None:
        snapshot = self.forecasts.get(election_id)
        if snapshot is None:
            return None
        return DriverReport(
            election_id=election_id,
            snapshot_id=snapshot.id,
            drivers=snapshot.drivers,
            sensitivity=snapshot.driver_sensitivity,
            **self._snapshot_metadata(snapshot),
        )

    def coalition_report(self, election_id: str) -> CoalitionReport | None:
        snapshot = self.forecasts.get(election_id)
        election = self.elections.get(election_id)
        if (
            snapshot is None
            or election is None
            or election.majority is None
            or not snapshot.coalition_outcomes
        ):
            return None
        return CoalitionReport(
            election_id=election_id,
            snapshot_id=snapshot.id,
            majority=election.majority,
            coalitions=sorted(
                snapshot.coalition_outcomes,
                key=lambda item: item.majority_probability,
                reverse=True,
            ),
            **self._snapshot_metadata(snapshot),
        )

    def source_ledger(self, election_id: str) -> SourceLedger | None:
        self.refresh_calendars()
        election = self.elections.get(election_id)
        if election is None:
            return None
        snapshot = self.forecasts.get(election_id)
        return SourceLedger(
            election_id=election_id,
            sources=election.sources,
            **(
                self._snapshot_metadata(snapshot) if snapshot else self._calendar_metadata(election)
            ),
        )

    def map_layer(self, election_id: str) -> MapLayer | None:
        self.refresh_calendars()
        election = self.elections.get(election_id)
        if election is None:
            return None
        snapshot = self.forecasts.get(election_id)
        return MapLayer(
            election_id=election_id,
            supported=False,
            reason="Regional forecast suppressed: no validated boundary-level model is available.",
            **(
                self._snapshot_metadata(snapshot) if snapshot else self._calendar_metadata(election)
            ),
        )

    def mechanics(self, election_id: str) -> ElectionMechanics | None:
        self.refresh_calendars()
        election = self.elections.get(election_id)
        data = self.pack_data.get(election_id)
        if election is None or data is None:
            return None
        snapshot = self.forecasts.get(election_id)
        return ElectionMechanics(
            election_id=election_id,
            system=election.system,
            rules=data["rules"],
            source_adapters=data["source_adapters"],
            forecast_enabled=self.jurisdictions[election.jurisdiction_id].forecast_enabled,
            **(
                self._snapshot_metadata(snapshot) if snapshot else self._calendar_metadata(election)
            ),
        )

    def official_results(self, election_id: str) -> OfficialResults | None:
        self.refresh_calendars()
        election = self.elections.get(election_id)
        if election is None:
            return None
        snapshot = self.forecasts.get(election_id)
        if dsn := os.getenv("DATABASE_URL"):
            try:
                persisted = load_official_results(dsn, election_id)
            except OfficialResultStoreUnavailable:
                return OfficialResults(
                    election_id=election_id,
                    feed_available=False,
                    status="results store unavailable",
                    reporting_fraction=0,
                    results=[],
                    **(
                        self._snapshot_metadata(snapshot)
                        if snapshot
                        else self._calendar_metadata(election)
                    ),
                )
            if persisted is not None:
                return OfficialResults.model_validate(persisted)
        return OfficialResults(
            election_id=election_id,
            feed_available=False,
            status="results feed unavailable",
            reporting_fraction=0,
            results=[],
            **(
                self._snapshot_metadata(snapshot) if snapshot else self._calendar_metadata(election)
            ),
        )

    @staticmethod
    def _snapshot_metadata(snapshot: ForecastSnapshot) -> dict:
        return {
            "as_of": snapshot.as_of,
            "published_at": snapshot.published_at,
            "model_version": snapshot.model_version,
            "data_quality": snapshot.data_quality,
            "freshness": snapshot.freshness,
            "provenance": snapshot.provenance,
        }

    @staticmethod
    def _calendar_metadata(election: Election) -> dict:
        return {
            "as_of": election.last_updated,
            "published_at": election.last_updated,
            "model_version": "calendar-0.1.0",
            "data_quality": QualityGrade.STRUCTURAL,
            "freshness": election.status,
            "provenance": election.sources,
        }

    def catalog_status(self) -> CatalogStatus:
        eligibility = self.catalog_payload["eligibility"]
        return CatalogStatus(
            schema_version=self.catalog_payload["schema_version"],
            generated_at=self.catalog_payload["generated_at"],
            eligibility_version=eligibility["version"],
            eligibility_year=eligibility["year"],
            eligibility_rule=eligibility["rule"],
            eligibility_snapshot_sha256=eligibility["snapshot_sha256"],
            eligible_jurisdictions=sum(
                item["id"] in G20_COUNTRY_IDS and item["eligibility"].startswith("v-dem:")
                for item in self.catalog_payload["jurisdictions"]
            ),
            total_jurisdictions=len(self.jurisdictions),
            forecast_ready=sum(item.forecast_enabled for item in self.jurisdictions.values()),
            calendar_only=sum(
                item.coverage_status == CoverageStatus.CALENDAR_ONLY
                for item in self.jurisdictions.values()
            ),
            mechanics_blocked=sum(
                item.coverage_status == CoverageStatus.MECHANICS_BLOCKED
                for item in self.jurisdictions.values()
            ),
            sourced_calendars=len(self.elections),
        )

    def detail(self, election_id: str) -> ElectionDetail | None:
        self.refresh_calendars()
        election = self.elections.get(election_id)
        if election is None:
            return None
        return ElectionDetail(
            jurisdiction=self.jurisdictions[election.jurisdiction_id],
            election=election,
            forecast=self.forecasts.get(election_id),
        )


@lru_cache(maxsize=1)
def get_repository() -> CatalogRepository:
    return CatalogRepository()
