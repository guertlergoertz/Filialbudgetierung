"""Tests für den Excel-Importer."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from database.importer import import_umsatzdaten


def make_excel(data: dict) -> Path:
    """Hilfsfunktion: Erstellt eine temporäre Excel-Datei."""
    df = pd.DataFrame(data)
    path = Path("/tmp/test_import.xlsx")
    df.to_excel(path, index=False)
    return path


def test_import_grundlegend(conn):
    conn.execute("INSERT INTO filialen VALUES (1, 'Test', 'normal', TRUE)")
    path = make_excel({
        'filiale': [1, 1, 1],
        'datum': ['2023-01-02', '2023-01-03', '2023-01-04'],
        'umsatz': [1000.0, 1200.0, 900.0],
    })
    n = import_umsatzdaten(conn, path)
    assert n == 3


def test_import_fehlende_spalte(conn):
    path = make_excel({'filiale': [1], 'umsatz': [1000.0]})  # datum fehlt
    with pytest.raises(ValueError, match="Fehlende Spalten"):
        import_umsatzdaten(conn, path)
