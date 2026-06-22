"""Excel-Export für Planwerte."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_planwerte(
    df: pd.DataFrame,
    filepath: str | Path,
    sheet_name: str = "Planwerte",
) -> None:
    """
    Exportiert Planwerte als Excel-Datei.

    Args:
        df: DataFrame mit Planwerten
        filepath: Zielpfad für die Excel-Datei
        sheet_name: Name des Arbeitsblatts
    """
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def format_currency(value: float) -> str:
    """Formatiert einen Wert als Währungsstring."""
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
