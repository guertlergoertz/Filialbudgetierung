"""Regression tests for the additive effect identity and core engine invariants.

The identity budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
+ eff_preis + eff_ferien + eff_feiertag + eff_norm must NEVER break.
"""
from collections import defaultdict

from planning.engine import _normalize_bl

from .conftest import BRANCH_FACTORS


def _all_plans(engine):
    return engine.run(list(BRANCH_FACTORS.keys()))


def test_additive_identity_per_day(engine):
    """Every DayPlan must satisfy the additive identity within rounding noise."""
    plans = _all_plans(engine)
    assert plans
    for p in plans:
        total = (p.ist_vj + p.eff_oeffnung + p.eff_verteilung + p.eff_wochentag
                 + p.eff_preis + p.eff_ferien + p.eff_feiertag + p.eff_norm)
        assert abs(p.budget - total) < 0.05, (
            f"Identity broken {p.fil_nr} {p.datum}: budget={p.budget} sum={total}")


def test_month_normalization(engine):
    """Sum of daily budgets per branch+month equals monat_plan (normalization)."""
    plans = _all_plans(engine)
    sums = defaultdict(float)
    monat_plan = {}
    for p in plans:
        key = (p.fil_nr, p.datum.month)
        sums[key] += p.budget
        monat_plan[key] = p.monat_plan
    for key, s in sums.items():
        assert abs(s - monat_plan[key]) < 1.0, (
            f"{key}: sum(budget)={s} != monat_plan={monat_plan[key]}")


def test_closed_days_zero_budget(engine):
    """Sundays are closed in the fixture -> budget must be 0."""
    plans = _all_plans(engine)
    sundays = [p for p in plans if p.wochentag == 6]
    assert sundays
    for p in sundays:
        assert p.budget == 0.0
        assert p.tagestyp == "geschlossen"


def test_365_days_per_branch(engine):
    """2026 is not a leap year -> exactly 365 planned days per branch."""
    plans = _all_plans(engine)
    counts = defaultdict(int)
    for p in plans:
        counts[p.fil_nr] += 1
    assert set(counts) == set(BRANCH_FACTORS)
    for fil_nr, n in counts.items():
        assert n == 365, f"{fil_nr}: {n} days"


def test_normalize_bl():
    assert _normalize_bl("Baden-Württemberg") == "BW"
    assert _normalize_bl("DE-BW") == "BW"
    assert _normalize_bl("BW") == "BW"
    assert _normalize_bl("") == "RP"


def test_ferien_effect_applied(engine):
    """BW Osterferien 2026 map directly to VJ Osterferien 2025 → eff_ferien = 0.

    With direct ferien-to-ferien comparison, ist_vj already reflects the
    depressed ferien IST (40% dip in fixture) so no additional ferien factor
    is applied. The ferien effect is implicitly captured in the low ist_vj.
    """
    plans = engine.plan_branch("0002")
    fer_days = [p for p in plans if p.tagestyp == "ferien"]
    assert fer_days, "no ferien days planned for BW branch"
    assert all(p.eff_ferien == 0.0 for p in fer_days), (
        "ferien days with direct VJ match must have eff_ferien=0"
    )
    from .conftest import WEEKDAY_REVENUE, BRANCH_FACTORS
    avg_ist = sum(p.ist_vj for p in fer_days if p.ist_vj > 0) / max(
        sum(1 for p in fer_days if p.ist_vj > 0), 1
    )
    avg_normal = sum(WEEKDAY_REVENUE[wt] * BRANCH_FACTORS["0002"] for wt in range(6)) / 6
    assert avg_ist < avg_normal * 0.75, (
        f"ferien ist_vj ({avg_ist:.0f}) should be depressed vs normal ({avg_normal:.0f})"
    )
