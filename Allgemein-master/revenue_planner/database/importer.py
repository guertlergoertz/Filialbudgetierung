"""Excel-Import-Logik für Umsatzdaten."""
from __future__ import annotations

import pandas as pd
import duckdb
from pathlib import Path


def import_umsatzdaten(conn: duckdb.DuckDBPyConnection, filepath: str | Path) -> int:
    """
    Importiert Umsatzdaten aus einer Excel-Datei in die Datenbank.

    Args:
        conn: DuckDB-Verbindung
        filepath: Pfad zur Excel-Datei

    Returns:
        Anzahl der importierten Zeilen
    """
    df = pd.read_excel(filepath, engine='openpyxl')

    required_cols = {'filiale', 'datum', 'umsatz'}
    missing = required_cols - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"Fehlende Spalten: {missing}")

    df.columns = df.columns.str.lower()
    df['datum'] = pd.to_datetime(df['datum'])

    conn.execute("BEGIN")
    try:
        conn.register('import_df', df)
        conn.execute("""
            INSERT INTO umsatzdaten (filiale, datum, umsatz)
            SELECT filiale, datum, umsatz FROM import_df
        """)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return len(df)
