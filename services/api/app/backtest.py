from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import date
from itertools import pairwise
from pathlib import Path

import numpy as np

from .models import BacktestMetrics
from .simulation import _markov_shift

CHALLENGERS = ("gaussian_monte_carlo", "markov_momentum")
BASELINES = ("polls_only", "fundamentals_only", "previous_election")
FAMILIES = CHALLENGERS + BASELINES
BACKTEST_SIMULATION_COUNT = 1_000_000


@dataclass(frozen=True)
class HistoricalElection:
    election_id: str
    election_date: date
    actual_shares: tuple[float, ...]
    fundamentals_shares: tuple[float, ...]
    polling_snapshots: tuple[tuple[float, ...], ...]
    forecast_as_of: date
    fundamentals_available_at: date
    polling_snapshot_dates: tuple[date, ...]
    result_available_at: date
    fundamentals_revision_id: str | None = None
    polling_revision_ids: tuple[str, ...] = ()
    result_revision_id: str | None = None
    provenance_verified: bool = False


@dataclass(frozen=True)
class BacktestDataset:
    records: tuple[HistoricalElection, ...]
    dataset_sha256: str
    source_revision_ids: tuple[str, ...]
    provenance_verified: bool
    minimum_train_elections: int


@dataclass(frozen=True)
class BacktestFold:
    test_election_id: str
    train_election_ids: tuple[str, ...]
    train_forecast_as_of: tuple[date, ...]
    train_end: date
    test_date: date
    test_forecast_as_of: date
    predictions: dict[str, tuple[float, ...]]
    winner_probabilities: dict[str, tuple[float, ...]]
    share_intervals: dict[str, tuple[tuple[float, float], ...]]


@dataclass(frozen=True)
class BacktestReport:
    metrics: tuple[BacktestMetrics, ...]
    folds: tuple[BacktestFold, ...]
    winner: str | None
    reliable: bool
    promotion_status: str
    promotion_reasons: tuple[str, ...]
    evaluation_period_start: date | None
    evaluation_period_end: date | None
    simulation_count: int
    held_out_election_count: int
    evaluated_horizon_min_days: int | None
    evaluated_horizon_max_days: int | None
    target_horizon_days: int | None
    dataset_sha256: str | None = None
    markov_transition: tuple[tuple[float, ...], ...] = ()
    markov_step: float = 0.01


def _iso_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid {field}: {value!r}") from error


def load_backtest_dataset(path: Path) -> BacktestDataset:
    """Load source-vintage evidence; never silently accepts synthetic production data."""
    raw = path.read_bytes()
    payload = json.loads(raw)
    if payload.get("schema_version") != 3:
        raise ValueError("Backtest dataset schema_version must be 3")
    revisions = payload.get("source_revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ValueError("Backtest dataset requires source_revisions")
    revision_ids: set[str] = set()
    revision_evidence: dict[str, dict[str, date]] = {}
    revision_roles: dict[str, str] = {}
    minimum_train_elections = int(payload.get("minimum_train_elections", 5))
    if not 2 <= minimum_train_elections <= 10:
        raise ValueError("minimum_train_elections must be between 2 and 10")
    for revision in revisions:
        required = {
            "id",
            "source_url",
            "license",
            "license_url",
            "authority",
            "role",
            "observed_at",
            "released_at",
            "available_at",
            "retrieved_at",
            "sha256",
            "raw_path",
        }
        missing = required - set(revision)
        if missing:
            raise ValueError(f"Source revision missing fields: {sorted(missing)}")
        digest = str(revision["sha256"])
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"Invalid source revision sha256: {digest!r}")
        if not str(revision["source_url"]).startswith("https://"):
            raise ValueError("Backtest source URLs must use HTTPS")
        if not str(revision["license_url"]).startswith("https://"):
            raise ValueError("Backtest license URLs must use HTTPS")
        if not str(revision["license"]).strip() or not str(revision["authority"]).strip():
            raise ValueError("Backtest revisions require license and authority metadata")
        raw_root = path.parent.resolve()
        raw_path = (raw_root / str(revision["raw_path"])).resolve()
        if not raw_path.is_relative_to(raw_root):
            raise ValueError("Backtest raw snapshot path escapes the approved directory")
        if not raw_path.is_file():
            raise ValueError(f"Backtest raw snapshot is missing: {revision['raw_path']}")
        if hashlib.sha256(raw_path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Backtest raw snapshot hash mismatch: {revision['raw_path']}")
        if revision["role"] not in {"fundamentals", "poll", "result"}:
            raise ValueError("Backtest revision role must be fundamentals, poll, or result")
        revision_id = str(revision["id"])
        evidence = {
            field: _iso_date(str(revision[field])[:10], f"source {field}")
            for field in ("observed_at", "released_at", "available_at", "retrieved_at")
        }
        if not (
            evidence["observed_at"]
            <= evidence["released_at"]
            <= evidence["available_at"]
            <= evidence["retrieved_at"]
        ):
            raise ValueError(f"{revision_id}: source-vintage chronology is invalid")
        revision_ids.add(revision_id)
        revision_evidence[revision_id] = evidence
        revision_roles[revision_id] = str(revision["role"])
    if len(revision_ids) != len(revisions):
        raise ValueError("Source revision IDs must be unique")

    records = []
    referenced_revision_ids: set[str] = set()
    for item in payload.get("records", []):
        election_id = str(item.get("election_id", ""))
        if not election_id or election_id.lower().startswith(("synthetic", "fixture")):
            raise ValueError("Production backtest records cannot be synthetic fixtures")
        polling_snapshots = tuple(
            tuple(float(value) for value in snapshot) for snapshot in item["polling_snapshots"]
        )
        polling_revision_ids = tuple(str(value) for value in item["polling_revision_ids"])
        referenced = {
            str(item["fundamentals_revision_id"]),
            str(item["result_revision_id"]),
            *polling_revision_ids,
        }
        unknown = referenced - revision_ids
        if unknown:
            raise ValueError(f"{election_id}: unknown source revisions {sorted(unknown)}")
        referenced_revision_ids.update(referenced)
        forecast_as_of = _iso_date(item["forecast_as_of"], "forecast_as_of")
        fundamentals_available_at = _iso_date(
            item["fundamentals_available_at"], "fundamentals_available_at"
        )
        polling_snapshot_dates = tuple(
            _iso_date(value, "polling_snapshot_date") for value in item["polling_snapshot_dates"]
        )
        result_available_at = _iso_date(item["result_available_at"], "result_available_at")
        fundamentals_revision_id = str(item["fundamentals_revision_id"])
        fundamentals_revision = revision_evidence[fundamentals_revision_id]
        if revision_roles[fundamentals_revision_id] != "fundamentals":
            raise ValueError(f"{election_id}: fundamentals revision role mismatch")
        if fundamentals_revision["available_at"] != fundamentals_available_at:
            raise ValueError(f"{election_id}: fundamentals revision availability mismatch")
        if fundamentals_revision["available_at"] > forecast_as_of:
            raise ValueError(f"{election_id}: fundamentals revision was available after cutoff")
        for snapshot_date, revision_id in zip(
            polling_snapshot_dates, polling_revision_ids, strict=True
        ):
            evidence = revision_evidence[revision_id]
            if revision_roles[revision_id] != "poll":
                raise ValueError(f"{election_id}: polling revision role mismatch")
            if evidence["available_at"] != snapshot_date:
                raise ValueError(f"{election_id}: polling revision availability mismatch")
            if evidence["available_at"] > forecast_as_of:
                raise ValueError(f"{election_id}: polling revision was available after cutoff")
        result_revision_id = str(item["result_revision_id"])
        result_revision = revision_evidence[result_revision_id]
        if revision_roles[result_revision_id] != "result":
            raise ValueError(f"{election_id}: result revision role mismatch")
        if result_revision["available_at"] != result_available_at:
            raise ValueError(f"{election_id}: result revision availability mismatch")
        records.append(
            HistoricalElection(
                election_id=election_id,
                election_date=_iso_date(item["election_date"], "election_date"),
                actual_shares=tuple(float(value) for value in item["actual_shares"]),
                fundamentals_shares=tuple(float(value) for value in item["fundamentals_shares"]),
                polling_snapshots=polling_snapshots,
                forecast_as_of=forecast_as_of,
                fundamentals_available_at=fundamentals_available_at,
                polling_snapshot_dates=polling_snapshot_dates,
                result_available_at=result_available_at,
                fundamentals_revision_id=str(item["fundamentals_revision_id"]),
                polling_revision_ids=polling_revision_ids,
                result_revision_id=str(item["result_revision_id"]),
                provenance_verified=True,
            )
        )
    if not records:
        raise ValueError("Backtest dataset requires at least one historical election")
    unreferenced = revision_ids - referenced_revision_ids
    if unreferenced:
        raise ValueError(f"Backtest dataset has unreferenced revisions: {sorted(unreferenced)}")
    _validate_vintages(records)
    return BacktestDataset(
        records=tuple(records),
        dataset_sha256=hashlib.sha256(raw).hexdigest(),
        source_revision_ids=tuple(sorted(revision_ids)),
        provenance_verified=True,
        minimum_train_elections=minimum_train_elections,
    )


def backtest_engine_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_backtest_report(
    path: Path,
    *,
    dataset_sha256: str,
    target_horizon_days: int,
    expected_sha256: str,
) -> BacktestReport:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Backtest report hash mismatch")
    payload = json.loads(raw)
    if payload.get("schema_version") != 1:
        raise ValueError("Backtest report schema_version must be 1")
    if payload.get("engine_sha256") != backtest_engine_sha256():
        raise ValueError("Backtest report engine hash is stale")
    if payload.get("dataset_sha256") != dataset_sha256:
        raise ValueError("Backtest report dataset hash mismatch")
    if payload.get("target_horizon_days") != target_horizon_days:
        raise ValueError("Backtest report target horizon mismatch")
    if payload.get("simulation_count") != BACKTEST_SIMULATION_COUNT:
        raise ValueError("Backtest report must use exactly 1,000,000 simulations")
    folds = tuple(
        BacktestFold(
            test_election_id=item["test_election_id"],
            train_election_ids=tuple(item["train_election_ids"]),
            train_forecast_as_of=tuple(
                _iso_date(value, "train_forecast_as_of") for value in item["train_forecast_as_of"]
            ),
            train_end=_iso_date(item["train_end"], "train_end"),
            test_date=_iso_date(item["test_date"], "test_date"),
            test_forecast_as_of=_iso_date(item["test_forecast_as_of"], "test_forecast_as_of"),
            predictions={
                key: tuple(float(value) for value in values)
                for key, values in item["predictions"].items()
            },
            winner_probabilities={
                key: tuple(float(value) for value in values)
                for key, values in item["winner_probabilities"].items()
            },
            share_intervals={
                key: tuple((float(low), float(high)) for low, high in values)
                for key, values in item["share_intervals"].items()
            },
        )
        for item in payload["folds"]
    )
    return BacktestReport(
        metrics=tuple(BacktestMetrics.model_validate(item) for item in payload["metrics"]),
        folds=folds,
        winner=payload["winner"],
        reliable=bool(payload["reliable"]),
        promotion_status=payload["promotion_status"],
        promotion_reasons=tuple(payload["promotion_reasons"]),
        evaluation_period_start=(
            _iso_date(payload["evaluation_period_start"], "evaluation_period_start")
            if payload["evaluation_period_start"]
            else None
        ),
        evaluation_period_end=(
            _iso_date(payload["evaluation_period_end"], "evaluation_period_end")
            if payload["evaluation_period_end"]
            else None
        ),
        simulation_count=int(payload["simulation_count"]),
        held_out_election_count=int(payload["held_out_election_count"]),
        evaluated_horizon_min_days=payload["evaluated_horizon_min_days"],
        evaluated_horizon_max_days=payload["evaluated_horizon_max_days"],
        target_horizon_days=payload["target_horizon_days"],
        dataset_sha256=payload["dataset_sha256"],
        markov_transition=tuple(
            tuple(float(value) for value in row) for row in payload["markov_transition"]
        ),
        markov_step=float(payload["markov_step"]),
    )


def _normalize(values: np.ndarray) -> np.ndarray:
    clipped = np.maximum(values, 0.001)
    return clipped / clipped.sum()


def _base_prediction(record: HistoricalElection) -> np.ndarray:
    latest_poll = np.asarray(record.polling_snapshots[-1], dtype=np.float64)
    fundamentals = np.asarray(record.fundamentals_shares, dtype=np.float64)
    return _normalize(latest_poll * 0.72 + fundamentals * 0.28)


def _movement_state(previous: np.ndarray, current: np.ndarray, contestant_index: int) -> int:
    movement = current[contestant_index] - previous[contestant_index]
    if movement < -0.003:
        return 0
    if movement > 0.003:
        return 2
    return 1


def _fit_transition(records: list[HistoricalElection]) -> np.ndarray:
    counts = np.ones((3, 3), dtype=np.float64)  # Laplace smoothing prevents zero states.
    for record in records:
        snapshots = [np.asarray(item, dtype=np.float64) for item in record.polling_snapshots]
        for contestant_index in range(len(record.actual_shares)):
            states = [_movement_state(a, b, contestant_index) for a, b in pairwise(snapshots)]
            for previous, current in pairwise(states):
                counts[previous, current] += 1
    return counts / counts.sum(axis=1, keepdims=True)


def fit_markov_parameters(
    records: list[HistoricalElection],
) -> tuple[tuple[tuple[float, ...], ...], float]:
    unique_records = _collapse_election_origins(records)
    transition = _fit_transition(unique_records)
    historical_steps = [
        abs(b[index] - a[index])
        for item in unique_records
        for a, b in pairwise(item.polling_snapshots)
        for index in range(len(item.actual_shares))
    ]
    step = float(np.median(historical_steps)) if historical_steps else 0.01
    return tuple(tuple(float(value) for value in row) for row in transition), step


def _collapse_election_origins(
    records: list[HistoricalElection],
) -> list[HistoricalElection]:
    grouped: dict[str, list[HistoricalElection]] = {}
    for record in records:
        grouped.setdefault(record.election_id, []).append(record)
    collapsed = []
    for origins in grouped.values():
        snapshots: dict[date, tuple[tuple[float, ...], str | None]] = {}
        for origin in sorted(origins, key=lambda item: item.forecast_as_of):
            revision_ids: tuple[str | None, ...] = (
                origin.polling_revision_ids
                if origin.polling_revision_ids
                else (None,) * len(origin.polling_snapshots)
            )
            for snapshot_date, snapshot, revision_id in zip(
                origin.polling_snapshot_dates,
                origin.polling_snapshots,
                revision_ids,
                strict=True,
            ):
                snapshots.setdefault(snapshot_date, (snapshot, revision_id))
        template = max(origins, key=lambda item: item.forecast_as_of)
        ordered_snapshots = sorted(snapshots.items())
        revisions = tuple(value[1] for _, value in ordered_snapshots)
        collapsed.append(
            replace(
                template,
                polling_snapshot_dates=tuple(key for key, _ in ordered_snapshots),
                polling_snapshots=tuple(value[0] for _, value in ordered_snapshots),
                polling_revision_ids=(
                    tuple(str(value) for value in revisions)
                    if revisions and all(value is not None for value in revisions)
                    else ()
                ),
            )
        )
    return sorted(collapsed, key=lambda item: item.election_date)


def _predict(
    family: str,
    train: list[HistoricalElection],
    test: HistoricalElection,
) -> np.ndarray:
    base = _base_prediction(test)
    residuals = np.asarray(
        [np.asarray(item.actual_shares) - _base_prediction(item) for item in train]
    )
    bias = residuals.mean(axis=0) if len(residuals) else np.zeros_like(base)

    if family == "polls_only":
        return _normalize(np.asarray(test.polling_snapshots[-1], dtype=np.float64))
    if family == "fundamentals_only":
        return _normalize(np.asarray(test.fundamentals_shares, dtype=np.float64))
    if family == "previous_election":
        return _normalize(np.asarray(train[-1].actual_shares, dtype=np.float64))
    if family == "gaussian_monte_carlo":
        return _normalize(base + bias)

    transition, step = fit_markov_parameters(train)
    transition_array = np.asarray(transition)
    snapshots = [np.asarray(item, dtype=np.float64) for item in test.polling_snapshots]
    expected_states = np.asarray(
        [
            transition_array[_movement_state(snapshots[-2], snapshots[-1], contestant_index)]
            @ np.array([-1.0, 0.0, 1.0])
            for contestant_index in range(len(base))
        ]
    )
    momentum = (expected_states - expected_states.mean()) * step * 0.5
    return _normalize(base + bias + momentum)


@dataclass(frozen=True)
class PredictiveDistribution:
    mean_shares: np.ndarray
    winner_probabilities: np.ndarray
    share_low: np.ndarray
    share_high: np.ndarray


def _stable_fold_seed(
    family: str,
    train: list[HistoricalElection],
    test: HistoricalElection,
) -> int:
    lineage = ":".join(item.election_id for item in train)
    digest = hashlib.sha256(f"{family}:{lineage}:{test.election_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _rolling_residuals(
    family: str,
    train: list[HistoricalElection],
    dimensions: int,
) -> np.ndarray:
    residuals = []
    for index, record in enumerate(train):
        prior = train[:index]
        if family == "previous_election" and not prior:
            continue
        prediction = _predict(family, prior, record)
        residual = np.asarray(record.actual_shares, dtype=np.float64) - prediction
        residuals.append(residual - residual.mean())
    if not residuals:
        return np.empty((0, dimensions), dtype=np.float64)
    return np.asarray(residuals, dtype=np.float64)


def _residual_covariance(residuals: np.ndarray, dimensions: int) -> np.ndarray:
    projector = np.eye(dimensions) - np.ones((dimensions, dimensions)) / dimensions
    if len(residuals) < 2:
        covariance = np.eye(dimensions) * 0.03**2
    else:
        covariance = np.atleast_2d(np.cov(residuals, rowvar=False, ddof=1))
        average_variance = max(float(np.trace(covariance)) / dimensions, 0.005**2)
        covariance = 0.75 * covariance + 0.25 * np.eye(dimensions) * average_variance
    covariance = projector @ covariance @ projector
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    eigenvalues = np.maximum(eigenvalues, 0)
    return (eigenvectors * eigenvalues) @ eigenvectors.T


def _gaussian_draws(
    rng: np.random.Generator,
    count: int,
    covariance: np.ndarray,
) -> np.ndarray:
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    transform = eigenvectors * np.sqrt(np.maximum(eigenvalues, 0))
    standard = rng.normal(size=(count, covariance.shape[0])).astype(np.float32)
    return standard @ transform.T.astype(np.float32)


def _campaign_steps(record: HistoricalElection) -> int:
    intervals = [
        (current - previous).days
        for previous, current in pairwise(record.polling_snapshot_dates)
        if current > previous
    ]
    cadence = float(np.median(intervals)) if intervals else 7
    remaining = max(1, (record.election_date - record.forecast_as_of).days)
    return max(1, min(24, math.ceil(remaining / max(cadence, 1))))


def _predictive_distribution(
    family: str,
    train: list[HistoricalElection],
    test: HistoricalElection,
    simulation_count: int,
) -> PredictiveDistribution:
    if simulation_count < 1_000:
        raise ValueError("Probabilistic backtests require at least 1,000 draws")
    point = _predict(family, train, test)
    dimensions = len(point)
    residuals = _rolling_residuals(family, train, dimensions)
    covariance = _residual_covariance(residuals, dimensions)
    rng = np.random.default_rng(_stable_fold_seed(family, train, test))

    if family == "markov_momentum":
        transition, step = fit_markov_parameters(train)
        shocks = _markov_shift(
            rng,
            simulation_count,
            dimensions,
            volatility=max(float(np.sqrt(np.trace(covariance) / dimensions)), 0.005),
            steps=_campaign_steps(test),
            transition_values=transition,
            empirical_step=step,
        )
        shocks += _gaussian_draws(rng, simulation_count, covariance * 0.25)
    elif family == "gaussian_monte_carlo":
        shocks = _gaussian_draws(rng, simulation_count, covariance)
    else:
        if len(residuals):
            indices = rng.integers(0, len(residuals), size=simulation_count)
            centered = residuals - residuals.mean(axis=0, keepdims=True)
            shocks = centered[indices].astype(np.float32)
            shocks += _gaussian_draws(rng, simulation_count, covariance * 0.10)
        else:
            shocks = _gaussian_draws(rng, simulation_count, covariance)

    raw = point.astype(np.float32)[None, :] + shocks
    np.maximum(raw, 0.001, out=raw)
    shares = raw / raw.sum(axis=1, keepdims=True)
    winners = np.argmax(shares, axis=1)
    probabilities = np.bincount(winners, minlength=dimensions) / simulation_count
    low, high = np.quantile(shares, [0.05, 0.95], axis=0)
    return PredictiveDistribution(
        mean_shares=shares.mean(axis=0, dtype=np.float64),
        winner_probabilities=probabilities,
        share_low=low,
        share_high=high,
    )


def _validate_vintages(records: list[HistoricalElection]) -> None:
    origin_keys = {(item.election_id, item.forecast_as_of) for item in records}
    if len(origin_keys) != len(records):
        raise ValueError("Historical forecast origins must be unique")
    election_truth: dict[str, tuple[date, tuple[float, ...], date, str | None]] = {}
    for record in records:
        truth = (
            record.election_date,
            record.actual_shares,
            record.result_available_at,
            record.result_revision_id,
        )
        previous = election_truth.setdefault(record.election_id, truth)
        if previous != truth:
            raise ValueError(f"{record.election_id}: forecast origins disagree on election truth")
    dimensions = {len(item.actual_shares) for item in records}
    if len(dimensions) > 1:
        raise ValueError("Historical elections must use a stable contestant dimension")
    for record in records:
        if len(record.polling_snapshots) < 2 or len(record.polling_snapshots) != len(
            record.polling_snapshot_dates
        ):
            raise ValueError(
                f"{record.election_id}: at least two poll snapshots require vintage dates"
            )
        if record.polling_revision_ids and len(record.polling_revision_ids) != len(
            record.polling_snapshots
        ):
            raise ValueError(
                f"{record.election_id}: each poll snapshot requires one source revision"
            )
        if tuple(sorted(record.polling_snapshot_dates)) != record.polling_snapshot_dates:
            raise ValueError(f"{record.election_id}: poll vintages must be ordered")
        if record.forecast_as_of >= record.election_date:
            raise ValueError(f"{record.election_id}: forecast cutoff must precede election day")
        if record.fundamentals_available_at > record.forecast_as_of:
            raise ValueError(f"{record.election_id}: fundamentals were unavailable at cutoff")
        if any(item > record.forecast_as_of for item in record.polling_snapshot_dates):
            raise ValueError(f"{record.election_id}: poll vintage exceeds forecast cutoff")
        if record.result_available_at < record.election_date:
            raise ValueError(f"{record.election_id}: result availability predates election")
        lengths = {
            len(record.actual_shares),
            len(record.fundamentals_shares),
            *(len(item) for item in record.polling_snapshots),
        }
        if len(lengths) != 1:
            raise ValueError(f"{record.election_id}: contestant dimensions do not match")
        vectors = (
            record.actual_shares,
            record.fundamentals_shares,
            *record.polling_snapshots,
        )
        if any(
            any(value < 0 or value > 1 for value in vector)
            or not math.isclose(sum(vector), 1, abs_tol=0.001)
            for vector in vectors
        ):
            raise ValueError(f"{record.election_id}: vote-share vectors must be normalized")


def _mean_confidence_interval(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = np.random.default_rng(20260809)
    sample = np.asarray(values, dtype=np.float64)
    indices = rng.integers(0, len(sample), size=(5_000, len(sample)))
    means = sample[indices].mean(axis=1)
    low, high = np.quantile(means, [0.05, 0.95])
    return float(low), float(high)


def _cluster_means(values: list[float], groups: tuple[str, ...]) -> np.ndarray:
    if not groups:
        return np.asarray(values, dtype=np.float64)
    if len(values) != len(groups):
        raise ValueError("Cluster labels must align with backtest folds")
    clustered: dict[str, list[float]] = {}
    for value, group in zip(values, groups, strict=True):
        clustered.setdefault(group, []).append(value)
    return np.asarray(
        [float(np.mean(clustered[group])) for group in sorted(clustered)],
        dtype=np.float64,
    )


def _clustered_confidence_interval(
    values: list[float],
    groups: tuple[str, ...],
) -> tuple[float, float]:
    return _mean_confidence_interval(_cluster_means(values, groups).tolist())


def _clustered_average(values: list[float], groups: tuple[str, ...]) -> float:
    clustered = _cluster_means(values, groups)
    return float(clustered.mean()) if len(clustered) else 0.0


def _clustered_calibration_error(
    folds: list[list[tuple[float, float]]],
    groups: tuple[str, ...],
) -> float:
    if not folds:
        return 0.0
    if len(folds) != len(groups):
        raise ValueError("Calibration folds must align with election clusters")
    clustered: dict[str, list[tuple[float, float]]] = {}
    for pairs, group in zip(folds, groups, strict=True):
        clustered.setdefault(group, []).extend(pairs)
    return float(np.mean([_calibration_error(pairs) for pairs in clustered.values()]))


def _select_training_origins(
    records: list[HistoricalElection],
    test: HistoricalElection,
) -> list[HistoricalElection]:
    target_horizon = (test.election_date - test.forecast_as_of).days
    grouped: dict[str, list[HistoricalElection]] = {}
    for record in records:
        if (
            record.election_date < test.election_date
            and record.result_available_at <= test.forecast_as_of
        ):
            grouped.setdefault(record.election_id, []).append(record)
    selected = []
    for origins in grouped.values():
        selected.append(
            min(
                origins,
                key=lambda item: (
                    abs((item.election_date - item.forecast_as_of).days - target_horizon),
                    -item.forecast_as_of.toordinal(),
                ),
            )
        )
    return sorted(selected, key=lambda item: item.election_date)


def _calibration_error(values: list[tuple[float, float]]) -> float:
    if not values:
        return 0.0
    pairs = np.asarray(values)
    error = 0.0
    for low in np.linspace(0, 1, 11)[:-1]:
        high = low + 0.1
        mask = (pairs[:, 0] >= low) & (pairs[:, 0] < high if high < 1 else pairs[:, 0] <= 1)
        if np.any(mask):
            error += float(mask.mean()) * abs(
                float(pairs[mask, 0].mean()) - float(pairs[mask, 1].mean())
            )
    return error


def walk_forward_backtest(
    records: list[HistoricalElection],
    minimum_train: int = 5,
    dataset_sha256: str | None = None,
    simulation_count: int = BACKTEST_SIMULATION_COUNT,
    target_horizon_days: int | None = None,
) -> BacktestReport:
    ordered = sorted(records, key=lambda item: item.election_date)
    _validate_vintages(ordered)
    folds: list[BacktestFold] = []
    errors: dict[str, list[tuple[float, float, float, float, float]]] = {
        family: [] for family in FAMILIES
    }
    calibration_folds: dict[str, list[list[tuple[float, float]]]] = {
        family: [] for family in FAMILIES
    }

    for test in ordered:
        train = _select_training_origins(ordered, test)
        if len(train) < minimum_train:
            continue
        if any(item.election_date >= test.election_date for item in train):
            raise ValueError("Walk-forward leakage detected")
        distributions = {
            family: _predictive_distribution(
                family,
                train,
                test,
                simulation_count,
            )
            for family in FAMILIES
        }
        actual = np.asarray(test.actual_shares, dtype=np.float64)
        winner = int(np.argmax(actual))
        actual_one_hot = np.zeros(len(actual))
        actual_one_hot[winner] = 1.0
        for family, distribution in distributions.items():
            prediction = distribution.mean_shares
            probabilities = distribution.winner_probabilities
            brier = float(np.sum((probabilities - actual_one_hot) ** 2))
            rmse = float(math.sqrt(np.mean((prediction - actual) ** 2)))
            covered = float(
                np.mean((actual >= distribution.share_low) & (actual <= distribution.share_high))
            )
            predicted_winner = int(np.argmax(probabilities))
            calibration_folds[family].append(
                [
                    (float(probability), float(index == winner))
                    for index, probability in enumerate(probabilities)
                ]
            )
            errors[family].append(
                (
                    brier,
                    rmse,
                    covered,
                    float(probabilities[predicted_winner]),
                    float(predicted_winner == winner),
                )
            )
        folds.append(
            BacktestFold(
                test_election_id=test.election_id,
                train_election_ids=tuple(item.election_id for item in train),
                train_forecast_as_of=tuple(item.forecast_as_of for item in train),
                train_end=train[-1].election_date,
                test_date=test.election_date,
                test_forecast_as_of=test.forecast_as_of,
                predictions={
                    key: tuple(float(x) for x in value.mean_shares)
                    for key, value in distributions.items()
                },
                winner_probabilities={
                    key: tuple(float(x) for x in value.winner_probabilities)
                    for key, value in distributions.items()
                },
                share_intervals={
                    key: tuple(
                        (float(low), float(high))
                        for low, high in zip(value.share_low, value.share_high, strict=True)
                    )
                    for key, value in distributions.items()
                },
            )
        )

    metrics = []
    fold_groups = tuple(fold.test_election_id for fold in folds)
    for family, values in errors.items():
        brier_values = [item[0] for item in values]
        ci_low, ci_high = _clustered_confidence_interval(brier_values, fold_groups)
        metrics.append(
            BacktestMetrics(
                model_family=family,
                folds=len(values),
                brier_score=_clustered_average(brier_values, fold_groups),
                brier_ci_low=ci_low,
                brier_ci_high=ci_high,
                vote_share_rmse=_clustered_average([item[1] for item in values], fold_groups),
                interval_coverage=_clustered_average([item[2] for item in values], fold_groups),
                calibration_error=_clustered_calibration_error(
                    calibration_folds[family], fold_groups
                ),
            )
        )
    metric_tuple = tuple(metrics)
    period_start = folds[0].test_date if folds else None
    period_end = folds[-1].test_date if folds else None
    election_dates = sorted({item.election_date for item in ordered})
    history_span_years = (
        election_dates[-1].year - election_dates[0].year if len(election_dates) >= 2 else 0
    )
    evaluated_horizons = [(item.election_date - item.forecast_as_of).days for item in ordered]
    evaluated_horizon_min_days = min(evaluated_horizons) if evaluated_horizons else None
    evaluated_horizon_max_days = max(evaluated_horizons) if evaluated_horizons else None
    held_out_election_count = len(set(fold_groups))
    reliability_reasons = []
    if len(folds) < 8:
        reliability_reasons.append("At least eight out-of-sample folds are required")
    if held_out_election_count < 3:
        reliability_reasons.append("At least three distinct held-out elections are required")
    if history_span_years < 20:
        reliability_reasons.append(
            "Source-vintage election history must span at least twenty years"
        )
    if any(
        (current - previous).days / 365.2425 > 8 for previous, current in pairwise(election_dates)
    ):
        reliability_reasons.append("Election history contains a gap longer than eight years")
    if not ordered or not all(item.provenance_verified for item in ordered):
        reliability_reasons.append("Every fold requires verified source-revision provenance")
    if dataset_sha256 is None or len(dataset_sha256) != 64:
        reliability_reasons.append("A content-addressed production dataset is required")
    if (
        target_horizon_days is not None
        and evaluated_horizon_min_days is not None
        and evaluated_horizon_max_days is not None
        and not evaluated_horizon_min_days <= target_horizon_days <= evaluated_horizon_max_days
    ):
        reliability_reasons.append(
            "Production forecast horizon is outside the evaluated historical horizon range"
        )
    reliable = not reliability_reasons
    markov_transition, markov_step = fit_markov_parameters(ordered)
    winner, promotion_status, reasons = _promotion_decision(
        metric_tuple,
        errors,
        tuple(reliability_reasons),
        fold_groups,
    )
    return BacktestReport(
        metrics=metric_tuple,
        folds=tuple(folds),
        winner=winner,
        reliable=reliable,
        promotion_status=promotion_status,
        promotion_reasons=reasons,
        evaluation_period_start=period_start,
        evaluation_period_end=period_end,
        simulation_count=simulation_count,
        held_out_election_count=held_out_election_count,
        evaluated_horizon_min_days=evaluated_horizon_min_days,
        evaluated_horizon_max_days=evaluated_horizon_max_days,
        target_horizon_days=target_horizon_days,
        dataset_sha256=dataset_sha256,
        markov_transition=markov_transition,
        markov_step=markov_step,
    )


def _promotion_decision(
    metrics: tuple[BacktestMetrics, ...],
    fold_errors: dict[str, list[tuple[float, float, float, float, float]]],
    reliability_reasons: tuple[str, ...],
    fold_groups: tuple[str, ...] = (),
) -> tuple[str | None, str, tuple[str, ...]]:
    if reliability_reasons:
        return None, "insufficient_evidence", reliability_reasons

    by_family = {metric.model_family: metric for metric in metrics}
    best_baseline = min(
        (by_family[family] for family in BASELINES),
        key=lambda item: (item.brier_score, item.vote_share_rmse),
    )
    eligible = []
    rejected_reasons = []
    baseline_errors = np.asarray([item[0] for item in fold_errors[best_baseline.model_family]])
    for offset, family in enumerate(CHALLENGERS):
        challenger = by_family[family]
        reasons = []
        paired_difference = np.asarray([item[0] for item in fold_errors[family]]) - baseline_errors
        paired_clusters = _cluster_means(paired_difference.tolist(), fold_groups)
        rng = np.random.default_rng(20260809 + offset)
        indices = rng.integers(
            0,
            len(paired_clusters),
            size=(10_000, len(paired_clusters)),
        )
        superiority_upper = float(np.quantile(paired_clusters[indices].mean(axis=1), 0.95))
        if challenger.brier_score >= best_baseline.brier_score:
            reasons.append(
                f"Brier {challenger.brier_score:.4f} does not beat baseline "
                f"{best_baseline.brier_score:.4f}"
            )
        elif superiority_upper >= 0:
            reasons.append("paired bootstrap does not establish familywise 90% Brier superiority")
        if challenger.vote_share_rmse > best_baseline.vote_share_rmse * 1.05:
            reasons.append("vote-share RMSE exceeds baseline by more than 5%")
        if challenger.interval_coverage < 0.80:
            reasons.append("empirical 90% interval coverage is below 80%")
        if challenger.calibration_error > 0.10:
            reasons.append("winner-probability calibration error exceeds 10%")
        if challenger.calibration_error > best_baseline.calibration_error + 0.01:
            reasons.append("winner-probability calibration is materially worse than baseline")
        if reasons:
            rejected_reasons.extend(f"{family}: {reason}" for reason in reasons)
        else:
            eligible.append(challenger)
    if not eligible:
        return None, "baseline_retained", tuple(rejected_reasons)
    challenger = min(eligible, key=lambda item: (item.brier_score, item.vote_share_rmse))
    return (
        challenger.model_family,
        "challenger_promoted",
        (
            f"Beat {best_baseline.model_family} on Brier score",
            "Vote-share RMSE and interval coverage gates passed",
        ),
    )
