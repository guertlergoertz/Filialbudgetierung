"""Planungslogik Engine 1: Gewichteter Durchschnitt vergangener Jahre."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

import duckdb
import pandas as pd


@dataclass
class PlanParameter:
    """Parameter für die Planung."""
    plan_jahr: int
    gewichte: list[float]  # Gewichte für die letzten N Jahre (neuestes zuerst)
    preisanpassung: float = 1.0  # Multiplikator


def berechne_planwerte(
    conn: duckdb.DuckDBPyConnection,
    filiale_id: int,
    params: PlanParameter,
) -> pd.DataFrame:
    """
    Berechnet Planwerte für eine Filiale.

    Returns:
        DataFrame mit Spalten: datum, planwert
    """
    n_jahre = len(params.gewichte)
    start_hist = params.plan_jahr - n_jahre
    end_hist = params.plan_jahr - 1

    df = conn.execute("""
        SELECT datum, umsatz
        FROM umsatzdaten
        WHERE filiale = ?
          AND YEAR(datum) BETWEEN ? AND ?
        ORDER BY datum
    """, [filiale_id, start_hist, end_hist]).df()

    if df.empty:
        return pd.DataFrame(columns=['datum', 'planwert'])

    df['year'] = pd.to_datetime(df['datum']).dt.year
    df['kw'] = pd.to_datetime(df['datum']).dt.isocalendar().week.astype(int)
    df['wd'] = pd.to_datetime(df['datum']).dt.dayofweek

    gewicht_map = {
        end_hist - i: w
        for i, w in enumerate(params.gewichte)
    }

    df['gewicht'] = df['year'].map(gewicht_map).fillna(0)
    df['gewichteter_umsatz'] = df['umsatz'] * df['gewicht']

    grouped = df.groupby(['kw', 'wd']).agg(
        gesamt_gewicht=('gewicht', 'sum'),
        gesamt_umsatz=('gewichteter_umsatz', 'sum')
    ).reset_index()

    grouped['planwert_basis'] = (
        grouped['gesamt_umsatz'] / grouped['gesamt_gewicht']
    ).fillna(0)

    grouped['planwert'] = grouped['planwert_basis'] * params.preisanpassung

    return grouped[['kw', 'wd', 'planwert']]
