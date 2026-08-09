from datetime import UTC, date, datetime

from app.fundamentals import FundamentalTrainingRow, HierarchicalFundamentalsModel


def _row(index: int, jurisdiction: str, archetype: str) -> FundamentalTrainingRow:
    year = 2000 + index
    growth = -1 + index * 0.2
    approval = 0.40 + index * 0.01
    return FundamentalTrainingRow(
        election_id=f"e-{index}",
        election_date=date(year, 6, 1),
        available_at=datetime(year, 5, 1, tzinfo=UTC),
        jurisdiction_id=jurisdiction,
        archetype=archetype,
        features=(growth, approval),
        actual_share=0.46 + index * 0.007 + (0.02 if jurisdiction == "a" else -0.01),
    )


def test_hierarchical_fundamentals_excludes_future_vintage_and_widens_unknowns():
    rows = [_row(i, "a" if i % 2 else "b", "advanced") for i in range(10)]
    rows.append(
        FundamentalTrainingRow(
            **{
                **_row(20, "a", "advanced").__dict__,
                "available_at": datetime(2035, 1, 1, tzinfo=UTC),
                "actual_share": 0.99,
            }
        )
    )
    model = HierarchicalFundamentalsModel()
    model.fit(rows, datetime(2020, 1, 1, tzinfo=UTC))
    known = model.predict((0.5, 0.5), "advanced", "a")
    unknown = model.predict((0.5, 0.5), "emerging", "z")
    assert known.training_count == 10
    assert 0 < known.low < known.share < known.high < 1
    assert unknown.posterior_std > known.posterior_std
    assert unknown.unseen_archetype is True
    assert unknown.unseen_jurisdiction is True


def test_hierarchical_model_partially_pools_country_effects():
    rows = [_row(i, "a" if i < 5 else "b", "advanced") for i in range(10)]
    model = HierarchicalFundamentalsModel(pooling_strength=4)
    model.fit(rows, datetime(2020, 1, 1, tzinfo=UTC))
    estimate_a = model.predict((0.2, 0.47), "advanced", "a")
    estimate_b = model.predict((0.2, 0.47), "advanced", "b")
    assert estimate_a.share > estimate_b.share
    assert abs(estimate_a.share - estimate_b.share) < 0.08
