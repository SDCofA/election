from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np


@dataclass(frozen=True)
class FundamentalTrainingRow:
    election_id: str
    election_date: date
    available_at: datetime
    jurisdiction_id: str
    archetype: str
    features: tuple[float, ...]
    actual_share: float


@dataclass(frozen=True)
class FundamentalEstimate:
    share: float
    low: float
    high: float
    posterior_std: float
    training_count: int
    latest_training_date: date
    unseen_jurisdiction: bool
    unseen_archetype: bool


def _logit(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, 0.01, 0.99)
    return np.log(clipped / (1 - clipped))


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))


class HierarchicalFundamentalsModel:
    """Gaussian-prior empirical Bayes model with archetype and country partial pooling."""

    def __init__(self, ridge: float = 4, pooling_strength: float = 5) -> None:
        if ridge <= 0 or pooling_strength <= 0:
            raise ValueError("Prior strengths must be positive")
        self.ridge = ridge
        self.pooling_strength = pooling_strength

    def fit(self, rows: list[FundamentalTrainingRow], cutoff: datetime) -> None:
        training = [
            row for row in rows if row.available_at <= cutoff and row.election_date < cutoff.date()
        ]
        if len(training) < 5:
            raise ValueError("At least five source-vintage training elections are required")
        dimensions = {len(row.features) for row in training}
        if len(dimensions) != 1 or 0 in dimensions:
            raise ValueError("Fundamental feature dimensions do not match")
        if any(not 0 < row.actual_share < 1 for row in training):
            raise ValueError("Actual shares must lie strictly between zero and one")

        features = np.asarray([row.features for row in training], dtype=np.float64)
        self.feature_mean = features.mean(axis=0)
        self.feature_std = features.std(axis=0)
        self.feature_std[self.feature_std < 1e-8] = 1
        standardized = (features - self.feature_mean) / self.feature_std
        design = np.column_stack([np.ones(len(training)), standardized])
        target = _logit(np.asarray([row.actual_share for row in training]))
        penalty = np.eye(design.shape[1]) * self.ridge
        penalty[0, 0] = 0
        self.coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ target)

        global_residuals = target - design @ self.coefficients
        self.archetype_offsets = self._pooled_offsets(
            [row.archetype for row in training], global_residuals
        )
        after_archetype = np.asarray(
            [
                residual - self.archetype_offsets[row.archetype]
                for row, residual in zip(training, global_residuals, strict=True)
            ]
        )
        self.jurisdiction_offsets = self._pooled_offsets(
            [row.jurisdiction_id for row in training], after_archetype
        )
        final_residuals = np.asarray(
            [
                residual - self.jurisdiction_offsets[row.jurisdiction_id]
                for row, residual in zip(training, after_archetype, strict=True)
            ]
        )
        self.residual_std = max(0.08, float(np.std(final_residuals, ddof=1)))
        self.training_count = len(training)
        self.latest_training_date = max(row.election_date for row in training)

    def _pooled_offsets(self, labels: list[str], residuals: np.ndarray) -> dict[str, float]:
        offsets = {}
        for label in sorted(set(labels)):
            values = residuals[np.asarray(labels) == label]
            shrinkage = len(values) / (len(values) + self.pooling_strength)
            offsets[label] = float(values.mean() * shrinkage)
        return offsets

    def predict(
        self,
        features: tuple[float, ...],
        archetype: str,
        jurisdiction_id: str,
    ) -> FundamentalEstimate:
        if not hasattr(self, "coefficients"):
            raise ValueError("Model must be fitted before prediction")
        values = np.asarray(features, dtype=np.float64)
        if len(values) != len(self.feature_mean):
            raise ValueError("Prediction feature dimension does not match training")
        standardized = (values - self.feature_mean) / self.feature_std
        linear = float(np.r_[1, standardized] @ self.coefficients)
        unseen_archetype = archetype not in self.archetype_offsets
        unseen_jurisdiction = jurisdiction_id not in self.jurisdiction_offsets
        linear += self.archetype_offsets.get(archetype, 0)
        linear += self.jurisdiction_offsets.get(jurisdiction_id, 0)
        uncertainty_multiplier = 1 + 0.20 * unseen_archetype + 0.15 * unseen_jurisdiction
        posterior_std = self.residual_std * uncertainty_multiplier
        return FundamentalEstimate(
            share=_sigmoid(linear),
            low=_sigmoid(linear - 1.645 * posterior_std),
            high=_sigmoid(linear + 1.645 * posterior_std),
            posterior_std=posterior_std,
            training_count=self.training_count,
            latest_training_date=self.latest_training_date,
            unseen_jurisdiction=unseen_jurisdiction,
            unseen_archetype=unseen_archetype,
        )
