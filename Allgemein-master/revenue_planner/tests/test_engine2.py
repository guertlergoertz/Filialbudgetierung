"""Regression tests for the planning engine (planning/engine2.py).

Additive identity (eff_verteilung and eff_norm are always 0):

    budget_i = ist_vj + eff_oeffnung + eff_hochrechnung + eff_wochentag
             + eff_preis + eff_ferien + eff_feiertag

Golden values are computed from the deterministic fixture in conftest.py.
Change them deliberately only when the calculation intentionally
changes (drift > 0.5 EUR per branch-year = behaviour change).
"""
from collections import defaultdict

import pytest

from planning.engine import PlanParams
from planning.engine2 import PlanningEngine2

from .conftest import BRANCH_FACTORS, PLANJAHR, STICHTAG


GOLDEN_ANNUAL_BUDGET_2 = {
    "0001": 419179.41,
    "0002": 620238.15,
    "0003": 330793.76,
}


@pytest.fixture
def engine2(db):
    params = PlanParams(
        planjahr=PLANJAHR,
        stichtag=STICHTAG,
        wachstum_monat={m: 3.0 for m in range(1, 13)},
        ferien_puffer_wochen=2,
    )
    return PlanningEngine2(db, params)


def _all_plans(engine2):
    return engine2.run(list(BRANCH_FACTORS.keys()))


def test_additive_identity_per_day(engine2):
    plans = _all_plans(engine2)
    assert plans
    for p in plans:
        total = (p.ist_vj + p.eff_oeffnung + p.eff_hochrechnung + p.eff_wochentag
                 + p.eff_preis + p.eff_ferien + p.eff_feiertag)
        assert abs(p.budget_i - total) < 0.05, (
            f"Identity broken {p.fil_nr} {p.datum}: budget_i={p.budget_i} sum={total}")
        # Before validierung step, budget == budget_i
        assert abs(p.budget - p.budget_i) < 0.01, (
            f"budget != budget_i {p.fil_nr} {p.datum}: budget={p.budget} budget_i={p.budget_i}")


def test_month_normalization(engine2):
    """Sum of daily budgets per branch+month equals the final monat_plan."""
    plans = _all_plans(engine2)
    sums = defaultdict(float)
    monat_plan = {}
    for p in plans:
        key = (p.fil_nr, p.datum.month)
        sums[key] += p.budget
        monat_plan[key] = p.monat_plan
    for key, s in sums.items():
        assert abs(s - monat_plan[key]) < 1.0, (
            f"{key}: sum(budget)={s} != monat_plan={monat_plan[key]}")


def test_closed_days_zero_budget(engine2):
    plans = _all_plans(engine2)
    sundays = [p for p in plans if p.wochentag == 6]
    assert sundays
    for p in sundays:
        assert p.budget == 0.0
        assert p.budget_i == 0.0
        assert p.ist_vj == 0.0
        assert p.tagestyp == "geschlossen"


def test_365_days_per_branch(engine2):
    plans = _all_plans(engine2)
    counts = defaultdict(int)
    for p in plans:
        counts[p.fil_nr] += 1
    assert set(counts) == set(BRANCH_FACTORS)
    for fil_nr, n in counts.items():
        assert n == 365, f"{fil_nr}: {n} days"


def test_golden_annual_budget(engine2):
    plans = _all_plans(engine2)
    totals = defaultdict(float)
    for p in plans:
        totals[p.fil_nr] += p.budget
    assert set(totals) == set(GOLDEN_ANNUAL_BUDGET_2)
    for fil_nr, expected in GOLDEN_ANNUAL_BUDGET_2.items():
        assert abs(totals[fil_nr] - expected) <= 0.5, (
            f"Golden drift {fil_nr}: got {totals[fil_nr]:.2f}, expected {expected:.2f}")


def test_save_writes_planung2(db, engine2):
    plans = _all_plans(engine2)
    engine2.save(plans)
    n = db.execute(
        "SELECT COUNT(*) FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
        (PLANJAHR,),
    ).fetchone()[0]
    assert n == len(plans)
    # planung (logic 1) must remain untouched/empty
    n1 = db.execute("SELECT COUNT(*) FROM planung").fetchone()[0]
    assert n1 == 0
