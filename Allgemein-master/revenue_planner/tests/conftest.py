"""Pytest-Konfiguration und Fixtures."""
from __future__ import annotations

import pytest
import duckdb
import pandas as pd

from database.schema import _init_schema


@pytest.fixture
def conn():
    """In-Memory DuckDB-Verbindung für Tests."""
    c = duckdb.connect(":memory:")
    _init_schema(c)
    yield c
    c.close()


@pytest.fixture
def conn_with_data(conn):
    """Verbindung mit Testdaten."""
    # Filiale einfügen
    conn.execute("INSERT INTO filialen VALUES (1, 'Testfiliale', 'normal', TRUE)")

    # Umsatzdaten für 2022 und 2023
    dates_2022 = pd.date_range('2022-01-03', periods=52 * 7, freq='D')
    dates_2023 = pd.date_range('2023-01-02', periods=52 * 7, freq='D')

    for i, d in enumerate(dates_2022):
        conn.execute(
            "INSERT INTO umsatzdaten VALUES (?, 1, ?, ?)",
            [i + 1, d.date(), 1000.0 + (i % 7) * 100]
        )

    for i, d in enumerate(dates_2023):
        conn.execute(
            "INSERT INTO umsatzdaten VALUES (?, 1, ?, ?)",
            [i + 1000, d.date(), 1100.0 + (i % 7) * 100]
        )

    return conn
