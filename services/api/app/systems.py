from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .models import Election, ElectionSystem


@dataclass(frozen=True)
class RegionalUnit:
    id: str
    seats: int
    base_shares: tuple[float, ...]


def largest_remainder(shares: np.ndarray, seats: int) -> np.ndarray:
    """Allocate every seat with deterministic index-order tie breaking."""
    if shares.ndim != 2 or seats < 1:
        raise ValueError("Largest-remainder input must be a matrix and seats must be positive")
    totals = shares.sum(axis=1, keepdims=True)
    if np.any(shares < 0) or np.any(totals <= 0):
        raise ValueError("Seat shares must be non-negative with a positive row total")
    quotas = shares / totals * seats
    allocations = np.floor(quotas).astype(np.int32)
    remaining = seats - allocations.sum(axis=1)
    order = np.argsort(-(quotas - allocations), axis=1, kind="stable")
    rows = np.arange(len(shares))
    for rank in range(shares.shape[1]):
        eligible = remaining > rank
        allocations[rows[eligible], order[eligible, rank]] += 1
    return allocations


def divisor_allocation(votes: np.ndarray, seats: int, method: str = "dhondt") -> np.ndarray:
    """Exact single-contest D'Hondt or Sainte-Laguë allocation."""
    values = np.asarray(votes, dtype=np.float64)
    if values.ndim != 1 or seats < 1 or np.any(values < 0) or values.sum() <= 0:
        raise ValueError("Divisor allocation requires non-negative one-dimensional votes")
    if method == "dhondt":
        divisors = np.arange(1, seats + 1, dtype=np.float64)
    elif method == "sainte_lague":
        divisors = np.arange(1, seats * 2, 2, dtype=np.float64)
    else:
        raise ValueError(f"Unsupported divisor method: {method}")
    quotients = values[:, None] / divisors[None, :]
    winners = np.argsort(-quotients, axis=None, kind="stable")[:seats] // seats
    return np.bincount(winners, minlength=len(values)).astype(np.int32)


def proportional_seats(
    shares: np.ndarray,
    seats: int,
    threshold: float = 0,
) -> np.ndarray:
    if not 0 <= threshold < 1:
        raise ValueError("Threshold must be between zero and one")
    eligible = np.where(shares >= threshold, shares, 0)
    empty = eligible.sum(axis=1) == 0
    eligible[empty] = shares[empty]
    return largest_remainder(eligible, seats)


def plurality_unit_seats(unit_shares: np.ndarray, unit_seats: np.ndarray) -> np.ndarray:
    """Translate FPTP/block-vote unit shares into simulation-level seats."""
    if unit_shares.ndim != 3:
        raise ValueError("Unit shares must have simulation, unit, contestant dimensions")
    weights = np.asarray(unit_seats, dtype=np.int32)
    if len(weights) != unit_shares.shape[1] or np.any(weights < 1):
        raise ValueError("Each regional unit requires a positive seat weight")
    winners = np.argmax(unit_shares, axis=2)
    result = np.zeros((unit_shares.shape[0], unit_shares.shape[2]), dtype=np.int32)
    for unit_index, weight in enumerate(weights):
        result[np.arange(len(result)), winners[:, unit_index]] += weight
    return result


def mixed_member_compensatory(
    list_shares: np.ndarray,
    district_seats: np.ndarray,
    seats: int,
    threshold: float,
) -> np.ndarray:
    """Return fixed-size party entitlement for a compensatory chamber."""
    if district_seats.shape != list_shares.shape:
        raise ValueError("District and list matrices must have matching dimensions")
    if np.any(district_seats < 0):
        raise ValueError("District seats cannot be negative")
    entitlement = proportional_seats(list_shares, seats, threshold)
    if np.any(district_seats.sum(axis=1) > seats):
        raise ValueError("District seats exceed chamber size")
    return entitlement


def validate_pack_rules(election: Election, rules: dict) -> None:
    if rules.get("engine") != election.system.value:
        raise ValueError(f"{election.id}: rules engine does not match election system")
    if election.system == ElectionSystem.UNRESOLVED:
        status = rules.get("validation_status")
        if status not in {"mechanics_blocked", "exploratory_proxy"}:
            raise ValueError(
                f"{election.id}: unresolved mechanics require an explicit quality state"
            )
        if (
            status == "exploratory_proxy"
            and rules.get("forecast_mode") != "national_control_scenario"
        ):
            raise ValueError(
                f"{election.id}: exploratory proxy requires a national-control scenario"
            )
        return
    if election.system in {
        ElectionSystem.FPTP,
        ElectionSystem.PROPORTIONAL,
        ElectionSystem.MIXED_MEMBER,
        ElectionSystem.ELECTORAL_COLLEGE,
    }:
        declared = rules.get("seats", rules.get("electoral_votes"))
        if election.seats_total is None or declared != election.seats_total:
            raise ValueError(f"{election.id}: pack seat total is missing or inconsistent")
    if election.system == ElectionSystem.PRESIDENTIAL_RUNOFF:
        threshold = rules.get("first_round_threshold")
        if rules.get("rounds") != 2 or threshold is None or not 0.5 <= threshold <= 1:
            raise ValueError(f"{election.id}: invalid presidential runoff rules")
    if (
        election.system == ElectionSystem.PRESIDENTIAL_PLURALITY
        and rules.get("winner_rule") != "plurality"
    ):
        raise ValueError(f"{election.id}: presidential plurality requires a plurality rule")
    if election.system == ElectionSystem.INSTITUTIONAL and not (
        rules.get("calendar_only") or rules.get("exploratory_scenario")
    ):
        raise ValueError(
            f"{election.id}: institutional selection requires calendar-only or exploratory status"
        )


def national_proxy_seats(shares: np.ndarray, election: Election) -> np.ndarray:
    """Explicit low-grade proxy used only when validated regional inputs are absent."""
    if election.seats_total is None:
        raise ValueError("Seat translation requires seats_total")
    weighted = np.where(shares >= election.threshold, shares, 0)
    empty = weighted.sum(axis=1) == 0
    weighted[empty] = shares[empty]
    if election.system == ElectionSystem.FPTP:
        weighted = np.power(weighted, 3)
    elif election.system == ElectionSystem.ELECTORAL_COLLEGE:
        weighted = np.power(weighted, 4)
    return largest_remainder(weighted, election.seats_total)
