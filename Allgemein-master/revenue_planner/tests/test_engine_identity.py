"""Identitätstest: Engine 1 und Engine 2 müssen bei gleichen Parametern gleiche Ergebnisse liefern."""
from __future__ import annotations

import pytest
import pandas as pd

from planning.engine import PlanParameter, berechne_planwerte
from planning.engine2 import PlanParameter2, berechne_planwerte2


def test_engines_konsistent(conn_with_data):
    """
    Bei einem einzigen Basisjahr mit Gewicht 1.0 müssen beide Engines
    identische Ergebnisse liefern.
    """
    params1 = PlanParameter(
        plan_jahr=2024,
        gewichte=[1.0],  # Nur 2023
    )
    params2 = PlanParameter2(
        plan_jahr=2024,
        basis_jahre=[2023],
        gewichte=[1.0],
    )

    result1 = berechne_planwerte(conn_with_data, 1, params1)
    result2 = berechne_planwerte2(conn_with_data, 1, params2)

    merged = result1.merge(result2, on=['kw', 'wd'], suffixes=('_e1', '_e2'))
    assert len(merged) > 0, "Keine gemeinsamen KW/WD-Kombinationen"
    assert (merged['planwert_e1'] == pytest.approx(merged['planwert_e2'], rel=1e-5)).all()
