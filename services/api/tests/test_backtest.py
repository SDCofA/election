import hashlib
import json
import runpy
from datetime import date, timedelta
from pathlib import Path

from app.backtest import (
    BACKTEST_SIMULATION_COUNT,
    FAMILIES,
    HistoricalElection,
    _predictive_distribution,
    _promotion_decision,
    load_backtest_dataset,
    load_backtest_report,
    walk_forward_backtest,
)
from app.models import BacktestMetrics


def _record(year: int, drift: float) -> HistoricalElection:
    election_day = date(year, 11, 1)
    forecast_as_of = election_day - timedelta(days=7)
    snapshots = (
        (0.48 + drift, 0.52 - drift),
        (0.49 + drift, 0.51 - drift),
        (0.50 + drift, 0.50 - drift),
        (0.51 + drift, 0.49 - drift),
    )
    return HistoricalElection(
        election_id=f"synthetic-{year}",
        election_date=election_day,
        actual_shares=(0.52 + drift, 0.48 - drift),
        fundamentals_shares=(0.505 + drift, 0.495 - drift),
        polling_snapshots=snapshots,
        forecast_as_of=forecast_as_of,
        fundamentals_available_at=forecast_as_of - timedelta(days=30),
        polling_snapshot_dates=tuple(
            forecast_as_of - timedelta(days=21 - index * 7) for index in range(4)
        ),
        result_available_at=election_day + timedelta(days=14),
        fundamentals_revision_id=f"fundamentals-{year}",
        polling_revision_ids=tuple(f"poll-{year}-{index}" for index in range(4)),
        result_revision_id=f"result-{year}",
        provenance_verified=True,
    )


def _origin(record: HistoricalElection, horizon_days: int) -> HistoricalElection:
    cutoff = record.election_date - timedelta(days=horizon_days)
    return HistoricalElection(
        **{
            **record.__dict__,
            "polling_snapshots": (
                record.polling_snapshots[0],
                record.polling_snapshots[-1],
            ),
            "forecast_as_of": cutoff,
            "fundamentals_available_at": cutoff - timedelta(days=30),
            "polling_snapshot_dates": (
                cutoff - timedelta(days=14),
                cutoff - timedelta(days=1),
            ),
            "polling_revision_ids": (
                f"poll-{record.election_id}-{horizon_days}-early",
                f"poll-{record.election_id}-{horizon_days}-late",
            ),
        }
    )


def test_walk_forward_is_strict_and_reports_both_challengers():
    records = [_record(year, ((year % 3) - 1) * 0.004) for year in range(1990, 2027, 2)]
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
    )
    assert report.reliable is True
    assert report.winner in {None, "gaussian_monte_carlo", "markov_momentum"}
    assert {metric.model_family for metric in report.metrics} == {
        "gaussian_monte_carlo",
        "markov_momentum",
        "baseline_ensemble",
        "polls_only",
        "fundamentals_only",
        "previous_election",
    }
    assert all(fold.train_end < fold.test_date for fold in report.folds)
    assert all(
        metric.brier_ci_low <= metric.brier_score <= metric.brier_ci_high
        for metric in report.metrics
    )
    assert all(0 <= metric.calibration_error <= 1 for metric in report.metrics)
    assert report.promotion_status in {"challenger_promoted", "baseline_retained"}
    assert report.simulation_count == 5_000
    assert report.evaluation_period_start == date(2000, 11, 1)
    assert report.evaluation_period_end == date(2026, 11, 1)
    assert BACKTEST_SIMULATION_COUNT == 1_000_000
    assert all(
        abs(sum(probabilities) - 1) < 1e-9
        for fold in report.folds
        for probabilities in fold.winner_probabilities.values()
    )


def test_backtest_refuses_to_select_with_too_few_folds():
    records = [_record(year, 0.0) for year in range(2000, 2008)]
    report = walk_forward_backtest(records, minimum_train=5, simulation_count=5_000)
    assert report.reliable is False
    assert report.winner is None
    assert report.promotion_status == "insufficient_evidence"


def test_training_history_cannot_masquerade_as_long_out_of_sample_evaluation():
    years = [1980, 1984, 1988, 1992, 1996, *range(2020, 2028)]
    records = [_record(year, 0.0) for year in years]
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
    )
    assert len(report.folds) == 8
    assert report.reliable is False
    assert "gap longer" in " ".join(report.promotion_reasons)


def test_multiple_forecast_origins_are_horizon_matched_without_same_election_leakage():
    records = [
        _origin(_record(year, 0.0), horizon) for year in range(1988, 2025, 4) for horizon in (90, 7)
    ]
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
    )
    assert report.reliable is True
    assert len(report.folds) == 10
    assert report.held_out_election_count == 5
    election_dates = {record.election_id: record.election_date for record in records}
    for fold in report.folds:
        test_horizon = (fold.test_date - fold.test_forecast_as_of).days
        assert fold.test_election_id not in fold.train_election_ids
        assert all(
            (election_dates[election_id] - cutoff).days == test_horizon
            for election_id, cutoff in zip(
                fold.train_election_ids,
                fold.train_forecast_as_of,
                strict=True,
            )
        )


def test_noncomparable_training_horizons_are_excluded_from_walk_forward_folds():
    records = [_origin(_record(year, 0.0), 7) for year in range(1988, 2025, 4)]
    records.append(_origin(_record(2024, 0.0), 90))
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
    )
    assert all((fold.test_date - fold.test_forecast_as_of).days == 7 for fold in report.folds)


def test_target_horizon_must_be_near_an_evaluated_fold_not_merely_inside_range():
    records = [
        _origin(_record(year, 0.0), horizon)
        for year in range(1988, 2025, 4)
        for horizon in (7, 821)
    ]
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
        target_horizon_days=365,
    )
    assert report.evaluated_horizon_min_days == 7
    assert report.evaluated_horizon_max_days == 821
    assert report.reliable is False
    assert "outside the evaluated" in " ".join(report.promotion_reasons)


def test_gaussian_and_markov_predictive_distributions_are_distinct_and_reproducible():
    records = [_record(year, 0.0) for year in range(1990, 2002, 2)]
    train, test = records[:-1], records[-1]
    gaussian = _predictive_distribution("gaussian_monte_carlo", train, test, 5_000)
    markov = _predictive_distribution("markov_momentum", train, test, 5_000)
    replay = _predictive_distribution("markov_momentum", train, test, 5_000)
    assert (markov.mean_shares == replay.mean_shares).all()
    assert (markov.share_low == replay.share_low).all()
    assert abs(markov.winner_probabilities.sum() - 1) < 1e-12
    assert not (gaussian.share_low == markov.share_low).all()


def test_public_baseline_is_scored_and_wider_than_gaussian_challenger():
    records = [_record(year, 0.0) for year in range(1990, 2002, 2)]
    train, test = records[:-1], records[-1]
    baseline = _predictive_distribution("baseline_ensemble", train, test, 5_000)
    gaussian = _predictive_distribution("gaussian_monte_carlo", train, test, 5_000)
    baseline_width = baseline.share_high - baseline.share_low
    gaussian_width = gaussian.share_high - gaussian.share_low
    assert (baseline_width > gaussian_width).all()
    assert abs(baseline.winner_probabilities.sum() - 1) < 1e-12


def test_backtest_rejects_future_vintage():
    records = [_record(year, 0.0) for year in range(1990, 2027, 2)]
    invalid = records[-1]
    records[-1] = HistoricalElection(
        **{
            **invalid.__dict__,
            "fundamentals_available_at": invalid.election_date + timedelta(days=1),
        }
    )
    try:
        walk_forward_backtest(records, simulation_count=5_000)
    except ValueError as error:
        assert "unavailable at cutoff" in str(error)
    else:
        raise AssertionError("future-vintage fundamentals must fail closed")


def test_unavailable_prior_result_is_excluded_from_training():
    records = [_record(year, 0.0) for year in range(1990, 2027, 2)]
    delayed = records[7]
    records[7] = HistoricalElection(
        **{
            **delayed.__dict__,
            "result_available_at": date(2100, 1, 1),
        }
    )
    report = walk_forward_backtest(records, minimum_train=5, simulation_count=5_000)
    later_folds = [fold for fold in report.folds if fold.test_date > delayed.election_date]
    assert later_folds
    assert all(delayed.election_id not in fold.train_election_ids for fold in later_folds)


def test_unverified_provenance_cannot_promote_model():
    records = [_record(year, 0.0) for year in range(1990, 2027, 2)]
    record = records[-1]
    records[-1] = HistoricalElection(**{**record.__dict__, "provenance_verified": False})
    report = walk_forward_backtest(records, simulation_count=5_000)
    assert report.reliable is False
    assert report.winner is None
    assert "contemporaneous archived poll" in " ".join(report.promotion_reasons)


def test_source_revision_dataset_loader(tmp_path):
    availability = {
        "fundamentals": ("2000-08-31", "2000-09-01"),
        "poll-1": ("2000-09-30", "2000-10-01"),
        "poll-2": ("2000-10-19", "2000-10-20"),
        "result": ("2000-11-01", "2000-11-10"),
    }
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    digests = {}
    for revision_id in availability:
        raw = revision_id.encode()
        (raw_dir / f"{revision_id}.json").write_bytes(raw)
        digests[revision_id] = hashlib.sha256(raw).hexdigest()
    revisions = [
        {
            "id": revision_id,
            "source_url": f"https://example.test/{revision_id}",
            "license": "CC-BY-4.0",
            "license_url": "https://example.test/license",
            "authority": "official",
            "role": (
                "fundamentals"
                if revision_id == "fundamentals"
                else "result"
                if revision_id == "result"
                else "poll"
            ),
            "observed_at": dates[0],
            "released_at": dates[1],
            "available_at": dates[1],
            "retrieved_at": dates[1],
            "sha256": digests[revision_id],
            "raw_path": f"raw/{revision_id}.json",
            "vintage_proof": (
                "contemporaneous_archive" if revision_id.startswith("poll-") else "official_release"
            ),
        }
        for revision_id, dates in availability.items()
    ]
    payload = {
        "schema_version": 4,
        "source_revisions": revisions,
        "records": [
            {
                "election_id": "verified-2000",
                "election_date": "2000-11-01",
                "actual_shares": [0.52, 0.48],
                "fundamentals_shares": [0.51, 0.49],
                "polling_snapshots": [[0.49, 0.51], [0.51, 0.49]],
                "forecast_as_of": "2000-10-25",
                "fundamentals_available_at": "2000-09-01",
                "polling_snapshot_dates": ["2000-10-01", "2000-10-20"],
                "result_available_at": "2000-11-10",
                "fundamentals_revision_id": "fundamentals",
                "polling_revision_ids": ["poll-1", "poll-2"],
                "result_revision_id": "result",
            }
        ],
    }
    path = tmp_path / "verified.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    dataset = load_backtest_dataset(path)
    assert dataset.provenance_verified is True
    assert len(dataset.dataset_sha256) == 64
    assert dataset.records[0].provenance_verified is True

    for revision in payload["source_revisions"]:
        if revision["role"] == "poll":
            revision["vintage_proof"] = "retrospective_compilation"
    path.write_text(json.dumps(payload), encoding="utf-8")
    retrospective = load_backtest_dataset(path)
    assert retrospective.provenance_verified is False
    assert retrospective.records[0].provenance_verified is False


def test_source_revision_loader_rejects_tampered_raw_snapshot(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw = b"verified"
    snapshot = raw_dir / "source.json"
    snapshot.write_bytes(raw)
    revision = {
        "id": "source",
        "source_url": "https://example.test/source",
        "license": "CC-BY-4.0",
        "license_url": "https://example.test/license",
        "authority": "official",
        "role": "poll",
        "observed_at": "2000-10-01",
        "released_at": "2000-10-01",
        "available_at": "2000-10-01",
        "retrieved_at": "2000-10-01",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw_path": "raw/source.json",
        "vintage_proof": "contemporaneous_archive",
    }
    payload = {"schema_version": 4, "source_revisions": [revision], "records": []}
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot.write_bytes(b"tampered")
    try:
        load_backtest_dataset(path)
    except ValueError as error:
        assert "raw snapshot hash mismatch" in str(error)
    else:
        raise AssertionError("tampered raw evidence must fail closed")


def test_target_horizon_outside_evidence_domain_blocks_promotion():
    records = [_record(year, 0.0) for year in range(1990, 2027, 2)]
    report = walk_forward_backtest(
        records,
        minimum_train=5,
        dataset_sha256="a" * 64,
        simulation_count=5_000,
        target_horizon_days=365,
    )
    assert report.evaluated_horizon_min_days == report.evaluated_horizon_max_days == 7
    assert report.target_horizon_days == 365
    assert report.reliable is False
    assert report.winner is None
    assert report.promotion_status == "insufficient_evidence"
    assert "outside the evaluated" in " ".join(report.promotion_reasons)


def test_packaged_million_draw_report_is_bound_to_dataset_engine_and_target():
    root = Path(__file__).parents[1] / "app" / "backtests"
    dataset = load_backtest_dataset(root / "us-presidential-2000-2020-v3.json")
    report_path = root / "us-presidential-2000-2020-v3-report.json"
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    report = load_backtest_report(
        report_path,
        dataset_sha256=dataset.dataset_sha256,
        target_horizon_days=821,
        expected_sha256=digest,
    )
    assert report.simulation_count == 1_000_000
    assert len(report.folds) == 12
    assert report.held_out_election_count == 3
    assert report.winner is None
    assert dataset.provenance_verified is False
    assert report.provenance_verified is False
    assert "contemporaneous archived poll" in " ".join(report.promotion_reasons)


def test_packaged_turkiye_report_uses_archived_origins_without_overclaiming():
    root = Path(__file__).parents[1] / "app" / "backtests"
    dataset = load_backtest_dataset(root / "tr-presidential-2014-2023-v1.json")
    report_path = root / "tr-presidential-2014-2023-v1-report.json"
    report = load_backtest_report(
        report_path,
        dataset_sha256=dataset.dataset_sha256,
        target_horizon_days=637,
        expected_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
    )
    assert len(dataset.records) == 9
    assert dataset.provenance_verified is True
    assert report.provenance_verified is True
    assert report.simulation_count == 1_000_000
    assert len(report.folds) == 3
    assert report.held_out_election_count == 1
    assert report.reliable is False
    assert report.winner is None
    assert "three distinct held-out elections" in " ".join(report.promotion_reasons)


def test_turkiye_archive_vectors_recompute_from_pinned_wikitext():
    api_root = Path(__file__).parents[1]
    builder = runpy.run_path(api_root / "scripts" / "build_tr_presidential_backtest.py")
    parser = builder["poll_vector_from_wikitext"]
    snapshots = builder["POLL_SNAPSHOTS"]
    raw_root = api_root / "app" / "backtests" / "raw" / "tr"
    for year, origins in snapshots.items():
        for oldid, _, expected in origins:
            raw = (raw_root / f"wikipedia-oldid-{oldid}.wikitext").read_text(encoding="utf-8")
            computed = parser(raw, year)
            assert all(
                abs(actual - target) <= 0.000002 for actual, target in zip(computed, expected)
            )


def test_packaged_australia_report_has_three_archive_verified_holdouts():
    root = Path(__file__).parents[1] / "app" / "backtests"
    dataset = load_backtest_dataset(root / "au-federal-tpp-2010-2025-v1.json")
    report_path = root / "au-federal-tpp-2010-2025-v1-report.json"
    report = load_backtest_report(
        report_path,
        dataset_sha256=dataset.dataset_sha256,
        target_horizon_days=648,
        expected_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
    )
    assert len(dataset.records) == 18
    assert dataset.provenance_verified is True
    assert report.provenance_verified is True
    assert report.simulation_count == 1_000_000
    assert len(report.folds) == 9
    assert report.held_out_election_count == 3
    assert report.evaluated_horizon_min_days == 7
    assert report.evaluated_horizon_max_days == 28
    assert report.reliable is False
    assert report.winner is None
    assert "twenty years" in " ".join(report.promotion_reasons)


def test_australia_archive_vectors_recompute_from_pinned_wikitext():
    api_root = Path(__file__).parents[1]
    builder = runpy.run_path(api_root / "scripts" / "build_au_federal_backtest.py")
    parser = builder["poll_vector_from_wikitext"]
    revisions = builder["POLL_REVISIONS"]
    expected_vectors = builder["EXPECTED_POLL_VECTORS"]
    raw_root = api_root / "app" / "backtests" / "raw" / "au"
    for year, origins in revisions.items():
        for (oldid, _), expected in zip(origins, expected_vectors[year], strict=True):
            raw = (raw_root / f"wikipedia-oldid-{oldid}.wikitext").read_text(encoding="utf-8")
            computed = parser(raw)
            assert all(
                abs(actual - target) <= 0.000002
                for actual, target in zip(computed, expected, strict=True)
            )


def test_cached_report_rejects_wrong_target_horizon():
    root = Path(__file__).parents[1] / "app" / "backtests"
    dataset = load_backtest_dataset(root / "us-presidential-2000-2020-v3.json")
    report_path = root / "us-presidential-2000-2020-v3-report.json"
    try:
        load_backtest_report(
            report_path,
            dataset_sha256=dataset.dataset_sha256,
            target_horizon_days=820,
            expected_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
        )
    except ValueError as error:
        assert "target horizon mismatch" in str(error)
    else:
        raise AssertionError("a cached report for another deployment horizon must fail closed")


def test_source_revision_loader_rejects_cutoff_mismatch(tmp_path):
    availability = {
        "fundamentals": ("2000-08-31", "2000-09-01"),
        "poll-1": ("2000-09-30", "2000-10-01"),
        "poll-2": ("2000-10-19", "2000-10-26"),
        "result": ("2000-11-01", "2000-11-10"),
    }
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    digests = {}
    for revision_id in availability:
        raw = revision_id.encode()
        (raw_dir / f"{revision_id}.json").write_bytes(raw)
        digests[revision_id] = hashlib.sha256(raw).hexdigest()
    revisions = [
        {
            "id": revision_id,
            "source_url": f"https://example.test/{revision_id}",
            "license": "CC-BY-4.0",
            "license_url": "https://example.test/license",
            "authority": "official",
            "role": (
                "fundamentals"
                if revision_id == "fundamentals"
                else "result"
                if revision_id == "result"
                else "poll"
            ),
            "observed_at": dates[0],
            "released_at": dates[1],
            "available_at": dates[1],
            "retrieved_at": dates[1],
            "sha256": digests[revision_id],
            "raw_path": f"raw/{revision_id}.json",
            "vintage_proof": (
                "contemporaneous_archive" if revision_id.startswith("poll-") else "official_release"
            ),
        }
        for revision_id, dates in availability.items()
    ]
    payload = {
        "schema_version": 4,
        "source_revisions": revisions,
        "records": [
            {
                "election_id": "verified-2000",
                "election_date": "2000-11-01",
                "actual_shares": [0.52, 0.48],
                "fundamentals_shares": [0.51, 0.49],
                "polling_snapshots": [[0.49, 0.51], [0.51, 0.49]],
                "forecast_as_of": "2000-10-25",
                "fundamentals_available_at": "2000-09-01",
                "polling_snapshot_dates": ["2000-10-01", "2000-10-20"],
                "result_available_at": "2000-11-10",
                "fundamentals_revision_id": "fundamentals",
                "polling_revision_ids": ["poll-1", "poll-2"],
                "result_revision_id": "result",
            }
        ],
    }
    path = tmp_path / "future-vintage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        load_backtest_dataset(path)
    except ValueError as error:
        assert "polling revision availability mismatch" in str(error)
    else:
        raise AssertionError("revision metadata after the declared snapshot must fail closed")


def test_promotion_gate_rejects_miscalibrated_challenger():
    metrics = tuple(
        BacktestMetrics(
            model_family=family,
            folds=8,
            brier_score=0.10 if family == "markov_momentum" else 0.20,
            brier_ci_low=0.08,
            brier_ci_high=0.22,
            vote_share_rmse=0.02,
            interval_coverage=0.9,
            calibration_error=0.20 if family == "markov_momentum" else 0.05,
        )
        for family in FAMILIES
    )
    errors = {
        family: [(0.10 if family == "markov_momentum" else 0.20, 0.02, 0.9, 0.7, 1.0)] * 8
        for family in FAMILIES
    }
    winner, status, reasons = _promotion_decision(metrics, errors, ())
    assert winner is None
    assert status == "baseline_retained"
    assert "calibration" in " ".join(reasons).lower()
