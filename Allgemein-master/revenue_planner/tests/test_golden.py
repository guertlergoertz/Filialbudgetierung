"""Golden regression test for the full engine run.

Golden values — change deliberately only when calculation logic intentionally
changes. Any unintended drift (> 0.5 EUR per branch-year) means a behavior
change in the planning engine and MUST be investigated before adjusting these
constants.

Computed on 2026-06-11 (fixture includes a -40% dip during Osterferien BW
2025 so eff_ferien is exercised) from the deterministic fixture in conftest.py
(planjahr 2026, stichtag 2026-01-01, 3% growth in all months).
"""
from collections import defaultdict

from .conftest import BRANCH_FACTORS

GOLDEN_ANNUAL_BUDGET = {
    "0001": 419106.96,
    "0002": 620082.35,
    "0003": 330710.56,
}


def test_golden_annual_budget(engine):
    plans = engine.run(list(BRANCH_FACTORS.keys()))
    totals = defaultdict(float)
    for p in plans:
        totals[p.fil_nr] += p.budget
    assert set(totals) == set(GOLDEN_ANNUAL_BUDGET)
    for fil_nr, expected in GOLDEN_ANNUAL_BUDGET.items():
        assert abs(totals[fil_nr] - expected) <= 0.5, (
            f"Golden drift {fil_nr}: got {totals[fil_nr]:.2f}, expected {expected:.2f}")
