from datetime import UTC, date, datetime

import numpy as np
import pytest

from app.polling import PollObservation, aggregate_polls


def _poll(
    poll_id: str,
    pollster: str,
    day: int,
    available_day: int,
    shares: tuple[float, ...],
) -> PollObservation:
    return PollObservation(
        poll_id=poll_id,
        pollster=pollster,
        fieldwork_end=date(2028, 10, day),
        available_at=datetime(2028, 10, available_day, 12, tzinfo=UTC),
        sample_size=1_000,
        shares=shares,
        mode="live_phone",
    )


def test_poll_aggregation_excludes_future_vintages_and_corrects_house_effects():
    polls = [
        _poll("old", "A", 1, 2, (0.54, 0.46)),
        _poll("new", "B", 20, 21, (0.48, 0.52)),
        _poll("future", "C", 22, 26, (0.10, 0.90)),
    ]
    cutoff = datetime(2028, 10, 24, tzinfo=UTC)
    result = aggregate_polls(
        polls,
        cutoff,
        house_effects={"A": (0.02, -0.02)},
    )
    assert result.poll_ids == ("old", "new")
    assert result.omitted_future_vintages == 1
    assert result.poll_count == 2
    assert result.latest_available_at == datetime(2028, 10, 21, 12, tzinfo=UTC)
    assert np.isclose(sum(result.shares), 1)
    assert result.shares[0] < 0.52
    assert np.all(np.linalg.eigvalsh(np.asarray(result.covariance)) > 0)


def test_poll_aggregation_fails_closed_without_available_poll():
    future = _poll("future", "A", 20, 21, (0.5, 0.5))
    with pytest.raises(ValueError, match="No polls"):
        aggregate_polls([future], datetime(2028, 10, 19, tzinfo=UTC))
