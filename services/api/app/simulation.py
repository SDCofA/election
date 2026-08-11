from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .models import (
    CoalitionForecast,
    ContestantForecast,
    Election,
    ElectionSystem,
    ScenarioForecast,
)
from .systems import largest_remainder, national_proxy_seats

SIMULATION_COUNT = 1_000_000


@dataclass(frozen=True)
class ScenarioInput:
    scenario_id: str
    label: str
    weight: float
    base_shares: tuple[float, ...]
    assumption: str
    source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SimulationInput:
    election: Election
    base_shares: tuple[float, ...]
    volatility: float
    turnout: float
    model_family: str = "gaussian_monte_carlo"
    campaign_steps: int = 12
    incumbent_index: int | None = None
    fundamental_shift: float = 0
    security_volatility: float = 0
    house_effects: tuple[float, ...] = ()
    turnout_sensitivity: tuple[float, ...] = ()
    markov_transition: tuple[tuple[float, ...], ...] = ()
    markov_step: float | None = None
    scenarios: tuple[ScenarioInput, ...] = ()


@dataclass(frozen=True)
class SimulationResult:
    seed: int
    outcomes: list[ContestantForecast]
    majority_probability: float
    turnout_median: float
    scenario_outcomes: list[ScenarioForecast]
    coalition_outcomes: list[CoalitionForecast]


def stable_seed(election_id: str, model_version: str) -> int:
    digest = hashlib.sha256(f"{election_id}:{model_version}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _markov_shift(
    rng: np.random.Generator,
    count: int,
    candidate_count: int,
    volatility: float,
    steps: int,
    transition_values: tuple[tuple[float, ...], ...] = (),
    empirical_step: float | None = None,
) -> np.ndarray:
    """Sample persistent campaign momentum without looking beyond forecast time."""
    transition = np.asarray(
        transition_values or ((0.76, 0.20, 0.04), (0.15, 0.70, 0.15), (0.04, 0.20, 0.76)),
        dtype=np.float32,
    )
    if (
        transition.shape != (3, 3)
        or np.any(transition < 0)
        or not np.allclose(transition.sum(axis=1), 1, atol=1e-5)
    ):
        raise ValueError("Markov transition matrix must contain three normalized rows")
    if steps < 1:
        raise ValueError("Markov campaign steps must be positive")
    if candidate_count < 2:
        raise ValueError("Markov simulation requires at least two contestants")
    states = np.ones((count, candidate_count), dtype=np.int8)
    accumulated = np.zeros((count, candidate_count), dtype=np.float32)
    for _ in range(steps):
        for candidate_index in range(candidate_count):
            draws = rng.random(count)
            probabilities = transition[states[:, candidate_index]]
            next_state = (draws > probabilities[:, 0]).astype(np.int8)
            next_state += (draws > (probabilities[:, 0] + probabilities[:, 1])).astype(np.int8)
            states[:, candidate_index] = next_state
        accumulated += states.astype(np.float32) - 1.0
    accumulated -= accumulated.mean(axis=1, keepdims=True)
    step_size = empirical_step if empirical_step is not None else volatility * 0.45
    return accumulated * step_size * 0.5 / math.sqrt(steps)


def _zero_sum_gaussian_shift(
    rng: np.random.Generator,
    count: int,
    candidate_count: int,
    scale: float,
) -> np.ndarray:
    """Exchangeable multi-contestant shock; no contestant receives an order-based sign."""
    if candidate_count < 2:
        raise ValueError("Gaussian simulation requires at least two contestants")
    draws = rng.normal(0, scale, size=(count, candidate_count)).astype(np.float32)
    draws -= draws.mean(axis=1, keepdims=True)
    draws /= math.sqrt(1 - 1 / candidate_count)
    return draws


def _largest_remainder(probabilities: np.ndarray, seats: int) -> np.ndarray:
    return largest_remainder(probabilities, seats)


def _translate_seats(shares: np.ndarray, election: Election) -> np.ndarray:
    return national_proxy_seats(shares, election)


def _runoff_winners(rng: np.random.Generator, shares: np.ndarray) -> np.ndarray:
    if shares.shape[1] == 2:
        return np.argmax(shares, axis=1)
    finalists = np.argpartition(shares, -2, axis=1)[:, -2:]
    rows = np.arange(len(shares))
    finalist_shares = shares[rows[:, None], finalists]
    eliminated = 1 - finalist_shares.sum(axis=1)
    transfer_weights = finalist_shares / finalist_shares.sum(axis=1, keepdims=True)
    transfer_weights += rng.normal(0, 0.035, size=transfer_weights.shape).astype(np.float32)
    np.maximum(transfer_weights, 0.01, out=transfer_weights)
    transfer_weights /= transfer_weights.sum(axis=1, keepdims=True)
    runoff = np.zeros_like(shares)
    runoff[rows[:, None], finalists] = finalist_shares + eliminated[:, None] * transfer_weights
    return np.argmax(runoff, axis=1)


def run_simulation(config: SimulationInput, model_version: str) -> SimulationResult:
    if len(config.base_shares) != len(config.election.contestants):
        raise ValueError("Each contestant requires one base share")
    if not math.isclose(sum(config.base_shares), 1.0, abs_tol=0.001):
        raise ValueError("Base shares must sum to one")
    if config.scenarios:
        if not math.isclose(sum(item.weight for item in config.scenarios), 1.0, abs_tol=1e-6):
            raise ValueError("Scenario weights must sum to one")
        for scenario in config.scenarios:
            if scenario.weight <= 0:
                raise ValueError("Scenario weights must be positive")
            if len(scenario.base_shares) != len(config.election.contestants):
                raise ValueError("Scenario shares must match contestant count")
            if not math.isclose(sum(scenario.base_shares), 1.0, abs_tol=0.001):
                raise ValueError("Scenario shares must sum to one")

    seed = stable_seed(config.election.id, model_version)
    rng = np.random.default_rng(seed)
    candidate_count = len(config.base_shares)
    scenario_indexes: np.ndarray | None = None
    if config.scenarios:
        scenario_indexes = rng.choice(
            len(config.scenarios),
            size=SIMULATION_COUNT,
            p=np.asarray([item.weight for item in config.scenarios], dtype=np.float64),
        )
        scenario_bases = np.asarray(
            [item.base_shares for item in config.scenarios], dtype=np.float32
        )
        base = scenario_bases[scenario_indexes]
    else:
        base = np.asarray(config.base_shares, dtype=np.float32)
    if config.house_effects and len(config.house_effects) != candidate_count:
        raise ValueError("House effects must match contestant count")
    if config.turnout_sensitivity and len(config.turnout_sensitivity) != candidate_count:
        raise ValueError("Turnout sensitivities must match contestant count")

    if config.model_family == "markov_momentum":
        national_error = _markov_shift(
            rng,
            SIMULATION_COUNT,
            candidate_count,
            config.volatility,
            config.campaign_steps,
            config.markov_transition,
            config.markov_step,
        )
    elif config.model_family in {"gaussian_monte_carlo", "baseline_ensemble"}:
        scale = 0.45 if config.model_family == "gaussian_monte_carlo" else 0.60
        national_error = _zero_sum_gaussian_shift(
            rng,
            SIMULATION_COUNT,
            candidate_count,
            config.volatility * scale,
        )
    else:
        raise ValueError(f"Unknown model family: {config.model_family}")

    raw = np.broadcast_to(base, (SIMULATION_COUNT, candidate_count)).copy()
    raw += national_error
    idiosyncratic_error = rng.normal(
        0, config.volatility, size=(SIMULATION_COUNT, candidate_count)
    ).astype(np.float32)
    idiosyncratic_error -= idiosyncratic_error.mean(axis=1, keepdims=True)
    raw += idiosyncratic_error
    if config.house_effects:
        raw += np.asarray(config.house_effects, dtype=np.float32)

    if config.incumbent_index is not None:
        contrast = np.full(candidate_count, -1 / max(candidate_count - 1, 1), dtype=np.float32)
        contrast[config.incumbent_index] = 1
        economic_shock = rng.normal(0, config.volatility * 0.20, size=SIMULATION_COUNT).astype(
            np.float32
        )
        security_shock = rng.normal(0, config.security_volatility, size=SIMULATION_COUNT).astype(
            np.float32
        )
        raw += (config.fundamental_shift + economic_shock + security_shock)[:, None] * contrast

    turnout_samples = np.clip(
        rng.normal(config.turnout, 0.025, size=SIMULATION_COUNT), 0.35, 0.9
    ).astype(np.float32)
    if config.turnout_sensitivity:
        turnout_delta = turnout_samples - config.turnout
        raw += turnout_delta[:, None] * np.asarray(config.turnout_sensitivity, dtype=np.float32)
    np.maximum(raw, 0.003, out=raw)
    shares = raw / raw.sum(axis=1, keepdims=True)

    seat_matrix: np.ndarray | None = None
    if config.election.seats_total:
        seat_matrix = _translate_seats(shares, config.election)
        winners = np.argmax(seat_matrix, axis=1)
        majorities = (
            int(
                np.count_nonzero(
                    seat_matrix[np.arange(SIMULATION_COUNT), winners] >= config.election.majority
                )
            )
            if config.election.majority
            else 0
        )
    else:
        if config.election.system == ElectionSystem.PRESIDENTIAL_RUNOFF:
            winners = _runoff_winners(rng, shares)
        else:
            winners = np.argmax(shares, axis=1)
        first_round_winners = np.argmax(shares, axis=1)
        winning_shares = shares[np.arange(SIMULATION_COUNT), first_round_winners]
        majorities = int(np.count_nonzero(winning_shares >= 0.5))
    wins = np.bincount(winners, minlength=candidate_count)

    outcomes = []
    for i, contestant in enumerate(config.election.contestants):
        share_low, share_high = np.quantile(shares[:, i], [0.05, 0.95])
        seat_values = seat_matrix[:, i] if seat_matrix is not None else None
        seat_low, seat_high = (
            np.quantile(seat_values, [0.05, 0.95]) if seat_values is not None else (None, None)
        )
        outcomes.append(
            ContestantForecast(
                contestant_id=contestant.id,
                win_probability=float(wins[i] / SIMULATION_COUNT),
                projected_share=float(np.mean(shares[:, i])),
                share_low=float(share_low),
                share_high=float(share_high),
                projected_seats=round(float(np.mean(seat_values)))
                if seat_values is not None
                else None,
                seats_low=round(float(seat_low)) if seat_low is not None else None,
                seats_high=round(float(seat_high)) if seat_high is not None else None,
            )
        )

    scenario_outcomes = []
    if scenario_indexes is not None:
        for scenario_index, scenario in enumerate(config.scenarios):
            selected = scenario_indexes == scenario_index
            selected_count = int(np.count_nonzero(selected))
            if selected_count == 0:
                raise ValueError("Each scenario must receive at least one simulation")
            conditional_wins = np.bincount(winners[selected], minlength=candidate_count)
            conditional = []
            for contestant_index, contestant in enumerate(config.election.contestants):
                scenario_shares = shares[selected, contestant_index]
                share_low, share_high = np.quantile(scenario_shares, [0.05, 0.95])
                scenario_seats = (
                    seat_matrix[selected, contestant_index] if seat_matrix is not None else None
                )
                seat_low, seat_high = (
                    np.quantile(scenario_seats, [0.05, 0.95])
                    if scenario_seats is not None
                    else (None, None)
                )
                conditional.append(
                    ContestantForecast(
                        contestant_id=contestant.id,
                        win_probability=float(conditional_wins[contestant_index] / selected_count),
                        projected_share=float(np.mean(scenario_shares)),
                        share_low=float(share_low),
                        share_high=float(share_high),
                        projected_seats=(
                            round(float(np.mean(scenario_seats)))
                            if scenario_seats is not None
                            else None
                        ),
                        seats_low=round(float(seat_low)) if seat_low is not None else None,
                        seats_high=round(float(seat_high)) if seat_high is not None else None,
                    )
                )
            scenario_outcomes.append(
                ScenarioForecast(
                    scenario_id=scenario.scenario_id,
                    label=scenario.label,
                    weight=scenario.weight,
                    assumption=scenario.assumption,
                    source_ids=list(scenario.source_ids),
                    outcomes=conditional,
                )
            )

    coalition_outcomes = []
    parliamentary_systems = {
        ElectionSystem.FPTP,
        ElectionSystem.PROPORTIONAL,
        ElectionSystem.MIXED_MEMBER,
    }
    if (
        seat_matrix is not None
        and config.election.majority
        and config.election.system in parliamentary_systems
    ):
        for size in range(2, candidate_count):
            for member_indexes in combinations(range(candidate_count), size):
                coalition_seats = seat_matrix[:, member_indexes].sum(axis=1)
                low, median, high = np.quantile(coalition_seats, [0.05, 0.50, 0.95])
                coalition_outcomes.append(
                    CoalitionForecast(
                        member_ids=[
                            config.election.contestants[index].id for index in member_indexes
                        ],
                        majority_probability=float(
                            np.count_nonzero(coalition_seats >= config.election.majority)
                            / SIMULATION_COUNT
                        ),
                        seats_median=round(float(median)),
                        seats_low=round(float(low)),
                        seats_high=round(float(high)),
                    )
                )

    return SimulationResult(
        seed=seed,
        outcomes=outcomes,
        majority_probability=majorities / SIMULATION_COUNT,
        turnout_median=float(np.median(turnout_samples)),
        scenario_outcomes=scenario_outcomes,
        coalition_outcomes=coalition_outcomes,
    )
