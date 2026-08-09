from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np


@dataclass(frozen=True)
class PollObservation:
    poll_id: str
    pollster: str
    fieldwork_end: date
    available_at: datetime
    sample_size: int
    shares: tuple[float, ...]
    mode: str = "mixed"


@dataclass(frozen=True)
class PollAggregate:
    as_of: datetime
    latest_available_at: datetime
    shares: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    poll_count: int
    effective_sample_size: float
    omitted_future_vintages: int
    poll_ids: tuple[str, ...]


MODE_QUALITY = {"live_phone": 1.0, "mixed": 0.95, "online": 0.90, "ivr": 0.82}


def _normalize(values: np.ndarray) -> np.ndarray:
    clipped = np.maximum(values, 0.001)
    return clipped / clipped.sum()


def aggregate_polls(
    polls: list[PollObservation],
    cutoff: datetime,
    *,
    half_life_days: float = 21,
    house_effects: dict[str, tuple[float, ...]] | None = None,
) -> PollAggregate:
    if half_life_days <= 0:
        raise ValueError("Poll half-life must be positive")
    eligible = [
        item
        for item in polls
        if item.available_at <= cutoff and item.fieldwork_end <= cutoff.date()
    ]
    if not eligible:
        raise ValueError("No polls were available at the forecast cutoff")
    dimensions = {len(item.shares) for item in eligible}
    if len(dimensions) != 1 or 0 in dimensions:
        raise ValueError("Poll contestant dimensions do not match")
    if any(item.sample_size <= 0 for item in eligible):
        raise ValueError("Poll sample size must be positive")

    effects = house_effects or {}
    adjusted = []
    weights = []
    for item in eligible:
        shares = np.asarray(item.shares, dtype=np.float64)
        effect = np.asarray(effects.get(item.pollster, (0,) * len(shares)), dtype=np.float64)
        if len(effect) != len(shares):
            raise ValueError(f"House effect dimension mismatch for {item.pollster}")
        adjusted.append(_normalize(shares - effect))
        age = max(0, (cutoff.date() - item.fieldwork_end).days)
        decay = math.exp(-math.log(2) * age / half_life_days)
        weights.append(math.sqrt(item.sample_size) * decay * MODE_QUALITY.get(item.mode, 0.85))

    matrix = np.asarray(adjusted)
    weight_vector = np.asarray(weights)
    mean = np.average(matrix, axis=0, weights=weight_vector)
    centered = matrix - mean
    if len(matrix) > 1:
        covariance = (centered * weight_vector[:, None]).T @ centered / weight_vector.sum()
    else:
        sampling_variance = mean * (1 - mean) / eligible[0].sample_size
        covariance = np.diag(sampling_variance)
    covariance += np.eye(len(mean)) * 1e-6
    effective_sample = sum(
        item.sample_size
        * math.exp(
            -math.log(2) * max(0, (cutoff.date() - item.fieldwork_end).days) / half_life_days
        )
        for item in eligible
    )
    return PollAggregate(
        as_of=cutoff,
        latest_available_at=max(item.available_at for item in eligible),
        shares=tuple(float(item) for item in mean),
        covariance=tuple(tuple(float(value) for value in row) for row in covariance),
        poll_count=len(eligible),
        effective_sample_size=float(effective_sample),
        omitted_future_vintages=len(polls) - len(eligible),
        poll_ids=tuple(item.poll_id for item in eligible),
    )
