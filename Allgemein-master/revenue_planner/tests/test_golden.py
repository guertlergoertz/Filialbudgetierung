"""Golden-File-Tests: Planwerte dürfen sich nicht unbeabsichtigt ändern."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pandas as pd

from planning.engine2 import PlanParameter2, berechne_planwerte2

GOLDEN_FILE = Path(__file__).parent / "golden_planwerte.json"


@pytest.mark.skipif(
    not GOLDEN_FILE.exists(),
    reason="Golden file nicht vorhanden — zuerst generieren"
)
def test_golden_planwerte(conn_with_data):
    params = PlanParameter2(
        plan_jahr=2024,
        basis_jahre=[2022, 2023],
        gewichte=[0.3, 0.7],
    )
    result = berechne_planwerte2(conn_with_data, 1, params)

    with open(GOLDEN_FILE) as f:
        expected = pd.DataFrame(json.load(f))

    merged = result.merge(expected, on=['kw', 'wd'], suffixes=('_actual', '_expected'))
    assert (merged['planwert_actual'] == pytest.approx(merged['planwert_expected'], rel=1e-4)).all()
