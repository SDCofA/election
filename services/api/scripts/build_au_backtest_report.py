from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.backtest import (
    BACKTEST_SIMULATION_COUNT,
    backtest_engine_sha256,
    load_backtest_dataset,
    walk_forward_backtest,
)

BACKTESTS_ROOT = Path(__file__).resolve().parents[1] / "app" / "backtests"
DATASET_PATH = BACKTESTS_ROOT / "au-federal-tpp-2004-2025-v2.json"
OUTPUT_PATH = BACKTESTS_ROOT / "au-federal-tpp-2004-2025-v2-report.json"
TARGET_HORIZON_DAYS = 648


def build() -> tuple[Path, str]:
    dataset = load_backtest_dataset(DATASET_PATH)
    report = walk_forward_backtest(
        list(dataset.records),
        minimum_train=dataset.minimum_train_elections,
        dataset_sha256=dataset.dataset_sha256,
        simulation_count=BACKTEST_SIMULATION_COUNT,
        target_horizon_days=TARGET_HORIZON_DAYS,
    )
    payload = {
        "schema_version": 1,
        "engine_sha256": backtest_engine_sha256(),
        "dataset_sha256": report.dataset_sha256,
        "provenance_verified": report.provenance_verified,
        "target_horizon_days": report.target_horizon_days,
        "simulation_count": report.simulation_count,
        "winner": report.winner,
        "reliable": report.reliable,
        "promotion_status": report.promotion_status,
        "promotion_reasons": list(report.promotion_reasons),
        "evaluation_period_start": (
            report.evaluation_period_start.isoformat() if report.evaluation_period_start else None
        ),
        "evaluation_period_end": (
            report.evaluation_period_end.isoformat() if report.evaluation_period_end else None
        ),
        "held_out_election_count": report.held_out_election_count,
        "evaluated_horizon_min_days": report.evaluated_horizon_min_days,
        "evaluated_horizon_max_days": report.evaluated_horizon_max_days,
        "poll_weight": report.poll_weight,
        "markov_transition": report.markov_transition,
        "markov_step": report.markov_step,
        "metrics": [item.model_dump(mode="json") for item in report.metrics],
        "folds": [
            {
                "test_election_id": fold.test_election_id,
                "train_election_ids": fold.train_election_ids,
                "train_forecast_as_of": [item.isoformat() for item in fold.train_forecast_as_of],
                "train_end": fold.train_end.isoformat(),
                "test_date": fold.test_date.isoformat(),
                "test_forecast_as_of": fold.test_forecast_as_of.isoformat(),
                "poll_weight": fold.poll_weight,
                "predictions": fold.predictions,
                "winner_probabilities": fold.winner_probabilities,
                "share_intervals": fold.share_intervals,
            }
            for fold in report.folds
        ],
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    OUTPUT_PATH.write_bytes(raw)
    return OUTPUT_PATH, hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    path, digest = build()
    print(f"path={path}")
    print(f"sha256={digest}")
