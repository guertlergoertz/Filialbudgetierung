"""Tests für engine2.py."""
from __future__ import annotations

import pytest

from planning.engine2 import PlanParameter2, berechne_planwerte2


def test_engine2_grundberechnung(conn_with_data):
    params = PlanParameter2(
        plan_jahr=2024,
        basis_jahre=[2022, 2023],
        gewichte=[0.3, 0.7],
    )
    result = berechne_planwerte2(conn_with_data, 1, params)
    assert not result.empty
    assert 'planwert' in result.columns
    assert (result['planwert'] >= 0).all()


def test_engine2_preisanpassung(conn_with_data):
    params_ohne = PlanParameter2(
        plan_jahr=2024,
        basis_jahre=[2023],
        gewichte=[1.0],
    )
    params_mit = PlanParameter2(
        plan_jahr=2024,
        basis_jahre=[2023],
        gewichte=[1.0],
        preisanpassung=1.05,
    )
    result_ohne = berechne_planwerte2(conn_with_data, 1, params_ohne)
    result_mit = berechne_planwerte2(conn_with_data, 1, params_mit)

    import pandas as pd
    merged = result_ohne.merge(result_mit, on=['kw', 'wd'], suffixes=('_ohne', '_mit'))
    assert (merged['planwert_mit'] == pytest.approx(merged['planwert_ohne'] * 1.05, rel=1e-5)).all()


def test_engine2_falsche_parameter_laenge(conn_with_data):
    with pytest.raises(ValueError, match="gleich lang"):
        params = PlanParameter2(
            plan_jahr=2024,
            basis_jahre=[2022, 2023],
            gewichte=[1.0],  # Falsch: nur 1 Gewicht für 2 Jahre
        )
        berechne_planwerte2(conn_with_data, 1, params)
