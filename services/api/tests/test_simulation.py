import math

import numpy as np

from app.repository import MODEL_VERSION, get_repository, horizon_uncertainty_scale
from app.simulation import (
    SIMULATION_COUNT,
    SimulationInput,
    _markov_shift,
    _translate_seats,
    _zero_sum_gaussian_shift,
    run_simulation,
)


def test_simulations_are_deterministic_and_normalized():
    repo = get_repository()
    election = repo.elections["us-2028-president"]
    config = SimulationInput(
        election=election,
        base_shares=(0.493, 0.487, 0.02),
        volatility=0.032,
        turnout=0.655,
    )
    first = run_simulation(config, MODEL_VERSION)
    second = run_simulation(config, MODEL_VERSION)
    assert first == second
    assert sum(item.win_probability for item in first.outcomes) == 1
    assert math.isclose(sum(item.projected_share for item in first.outcomes), 1, abs_tol=0.001)
    assert all(item.seats_low is not None for item in first.outcomes)
    assert sum(item.projected_seats for item in first.outcomes) == election.seats_total
    assert SIMULATION_COUNT == 1_000_000


def test_all_public_g20_forecasts_produce_normalized_outcomes():
    repo = get_repository()
    assert {item.system for item in repo.elections.values()} == {
        "presidential_runoff",
        "presidential_plurality",
        "fptp",
        "mixed_member",
        "electoral_college",
        "institutional",
        "unresolved",
    }
    for snapshot in repo.forecasts.values():
        assert math.isclose(sum(item.win_probability for item in snapshot.outcomes), 1)
        assert math.isclose(
            sum(item.projected_share for item in snapshot.outcomes), 1, abs_tol=0.001
        )


def test_forecast_uncertainty_expands_with_horizon_and_is_bounded():
    assert horizon_uncertainty_scale(7) == 0.75
    assert math.isclose(horizon_uncertainty_scale(90), 1)
    assert horizon_uncertainty_scale(730) > horizon_uncertainty_scale(365) > 1
    assert horizon_uncertainty_scale(10_000) == 1.60


def test_turkiye_forecast_excludes_legally_blocked_candidate_scenario():
    snapshot = get_repository().forecasts["tr-next-president"]
    assert snapshot.forecast_horizon_days > 600
    assert snapshot.uncertainty_scale > 1
    assert 0.115 < snapshot.effective_volatility <= 0.18
    assert len(snapshot.scenario_outcomes) == 2
    assert {item.scenario_id for item in snapshot.scenario_outcomes} == {
        "erdogan-v-yavas",
        "erdogan-v-ozel",
    }
    assert math.isclose(sum(item.weight for item in snapshot.scenario_outcomes), 1)
    for scenario in snapshot.scenario_outcomes:
        assert scenario.source_ids == ["gundemar_may_2026"]
        assert math.isclose(sum(item.win_probability for item in scenario.outcomes), 1)
        assert math.isclose(
            sum(item.projected_share for item in scenario.outcomes), 1, abs_tol=0.001
        )
    government_probabilities = {
        item.scenario_id: item.outcomes[0].win_probability for item in snapshot.scenario_outcomes
    }
    assert government_probabilities["erdogan-v-ozel"] > government_probabilities["erdogan-v-yavas"]


def test_thresholded_seat_translation_preserves_every_seat():
    election = get_repository().elections["de-next-bundestag"]
    shares = np.asarray([[0.40, 0.30, 0.20, 0.07, 0.03]], dtype=np.float32)
    seats = _translate_seats(shares, election)
    assert int(seats.sum()) == election.seats_total
    assert seats[0, 4] == 0


def test_parliamentary_forecasts_keep_joint_coalition_distributions():
    repo = get_repository()
    snapshot = repo.forecasts["de-next-bundestag"]
    assert len(snapshot.coalition_outcomes) == 25
    assert all(
        item.seats_low <= item.seats_median <= item.seats_high
        for item in snapshot.coalition_outcomes
    )
    response = repo.coalition_report("de-next-bundestag")
    assert response is not None
    assert (
        response.coalitions[0].majority_probability >= response.coalitions[-1].majority_probability
    )


def test_markov_simulation_accepts_learned_transition_dynamics():
    transition = ((0.05, 0.05, 0.90), (0.05, 0.05, 0.90), (0.05, 0.05, 0.90))
    first = _markov_shift(
        np.random.default_rng(7), 20_000, 3, 0.03, 8, transition, empirical_step=0.01
    )
    second = _markov_shift(
        np.random.default_rng(7), 20_000, 3, 0.03, 8, transition, empirical_step=0.01
    )
    assert np.array_equal(first, second)
    assert first.shape == (20_000, 3)
    assert np.allclose(first.sum(axis=1), 0, atol=1e-7)
    assert float(first.std()) > 0.001


def test_gaussian_campaign_shocks_are_exchangeable_and_zero_sum():
    shifts = _zero_sum_gaussian_shift(np.random.default_rng(11), 100_000, 5, 0.03)
    assert shifts.shape == (100_000, 5)
    assert np.allclose(shifts.sum(axis=1), 0, atol=1e-7)
    assert np.allclose(shifts.std(axis=0), 0.03, atol=0.0003)
    covariance = np.cov(shifts, rowvar=False)
    assert np.all(covariance[np.triu_indices(5, 1)] < 0)


def test_unpromoted_alternative_is_never_labeled_as_public_champion():
    snapshot = get_repository().alternative("us-2028-president", "markov_momentum")
    assert snapshot is not None
    assert snapshot.selection_status == "experimental challenger; not publicly promoted"
