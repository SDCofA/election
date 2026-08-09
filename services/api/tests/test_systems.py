import numpy as np
import pytest

from app.models import Election, ElectionSystem
from app.repository import get_repository
from app.systems import (
    divisor_allocation,
    largest_remainder,
    mixed_member_compensatory,
    plurality_unit_seats,
    proportional_seats,
    validate_pack_rules,
)


def test_divisor_methods_match_known_golden_allocation():
    votes = np.asarray([100_000, 80_000, 30_000], dtype=np.float64)
    assert divisor_allocation(votes, 5, "dhondt").tolist() == [3, 2, 0]
    assert divisor_allocation(votes, 5, "sainte_lague").tolist() == [2, 2, 1]


def test_largest_remainder_and_threshold_preserve_chamber_size():
    shares = np.asarray([[0.48, 0.32, 0.16, 0.04]], dtype=np.float64)
    assert largest_remainder(shares, 10).tolist() == [[5, 3, 2, 0]]
    seats = proportional_seats(shares, 100, threshold=0.05)
    assert seats.tolist() == [[50, 33, 17, 0]]
    assert int(seats.sum()) == 100


def test_fptp_and_electoral_college_unit_translation_is_exact():
    unit_shares = np.asarray(
        [
            [[0.51, 0.49], [0.40, 0.60], [0.50, 0.50]],
            [[0.49, 0.51], [0.70, 0.30], [0.48, 0.52]],
        ]
    )
    seats = plurality_unit_seats(unit_shares, np.asarray([3, 5, 2]))
    assert seats.tolist() == [[5, 5], [5, 5]]


def test_fixed_size_mixed_member_entitlement_is_deterministic():
    shares = np.asarray([[0.42, 0.33, 0.20, 0.05]])
    districts = np.asarray([[28, 18, 4, 0]])
    first = mixed_member_compensatory(shares, districts, 100, 0.05)
    second = mixed_member_compensatory(shares, districts, 100, 0.05)
    assert np.array_equal(first, second)
    assert int(first.sum()) == 100


def test_every_pack_declares_consistent_engine_rules():
    repository = get_repository()
    for election_id, election in repository.elections.items():
        validate_pack_rules(election, repository.pack_data[election_id]["rules"])


def test_pack_validation_fails_closed_on_engine_mismatch():
    election: Election = get_repository().elections["gb-next-commons"]
    with pytest.raises(ValueError, match="does not match"):
        validate_pack_rules(election, {"engine": ElectionSystem.PROPORTIONAL.value, "seats": 650})


def test_unresolved_pack_requires_explicit_quality_state():
    election = get_repository().elections["arg-next-national"]
    with pytest.raises(ValueError, match="explicit quality state"):
        validate_pack_rules(election, {"engine": ElectionSystem.UNRESOLVED.value})


def test_unresolved_exploratory_proxy_requires_named_mode():
    election = get_repository().elections["arg-next-national"]
    with pytest.raises(ValueError, match="national-control scenario"):
        validate_pack_rules(
            election,
            {"engine": ElectionSystem.UNRESOLVED.value, "validation_status": "exploratory_proxy"},
        )
