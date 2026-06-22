"""Planungslogik Engine 2: Alternative Gewichtungsmethode."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd


@dataclass
class PlanParameter2:
    """Parameter für Engine 2."""
    plan_jahr: int
    basis_jahre: list[int]  # Explizite Jahresliste
    gewichte: list[float]   # Gewicht je Basisjahr
    preisanpassung: float = 1.0
    schulfilialen_faktor: float = 1.0


def berechne_planwerte2(
    conn: duckdb.DuckDBPyConnection,
    filiale_id: int,
    params: PlanParameter2,
) -> pd.DataFrame:
    """
    Berechnet Planwerte für eine Filiale (Engine 2).

    Returns:
        DataFrame mit Spalten: kw, wd, planwert
    """
    if len(params.basis_jahre) != len(params.gewichte):
        raise ValueError("basis_jahre und gewichte müssen gleich lang sein")

    frames = []
    for jahr, gewicht in zip(params.basis_jahre, params.gewichte):
        df = conn.execute("""
            SELECT datum, umsatz
            FROM umsatzdaten
            WHERE filiale = ? AND YEAR(datum) = ?
            ORDER BY datum
        """, [filiale_id, jahr]).df()

        if df.empty:
            continue

        df['kw'] = pd.to_datetime(df['datum']).dt.isocalendar().week.astype(int)
        df['wd'] = pd.to_datetime(df['datum']).dt.dayofweek
        df['gewichteter_umsatz'] = df['umsatz'] * gewicht
        df['gewicht'] = gewicht
        frames.append(df[['kw', 'wd', 'gewichteter_umsatz', 'gewicht']])

    if not frames:
        return pd.DataFrame(columns=['kw', 'wd', 'planwert'])

    combined = pd.concat(frames, ignore_index=True)
    grouped = combined.groupby(['kw', 'wd']).agg(
        gesamt_umsatz=('gewichteter_umsatz', 'sum'),
        gesamt_gewicht=('gewicht', 'sum')
    ).reset_index()

    grouped['planwert'] = (
        grouped['gesamt_umsatz'] / grouped['gesamt_gewicht']
    ).fillna(0)

    grouped['planwert'] *= params.preisanpassung * params.schulfilialen_faktor

    return grouped[['kw', 'wd', 'planwert']]
