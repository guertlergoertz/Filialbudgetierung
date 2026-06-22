"""Tests for the German number/date parsing in database/importer.py."""
import io
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.importer import import_ist_umsatz  # noqa: E402
from database.schema import DDL, _migrate  # noqa: E402


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    _migrate(c)
    yield c
    c.close()


def _import_csv(conn, csv_text: str):
    n, warnings = import_ist_umsatz(conn, io.BytesIO(csv_text.encode("utf-8")),
                                    file_name="test.csv")
    return n, warnings


def _umsatz(conn, fil_nr, datum):
    row = conn.execute("SELECT umsatz FROM ist_umsatz WHERE fil_nr=? AND datum=?",
                       (fil_nr, datum)).fetchone()
    return row["umsatz"] if row else None


@pytest.mark.parametrize("raw,expected", [
    ("3.000", 3000.0),     # German thousands separator
    ('"3,5"', 3.5),        # German decimal comma
    ('"1.234,56"', 1234.56),
    ("1000", 1000.0),
    ("0", 0.0),
])
def test_number_parser(conn, raw, expected):
    csv = f"Datum;Filialnummer;Umsatz\n2024-01-15;0001;{raw}\n"
    n, _ = _import_csv(conn, csv)
    assert n == 1
    assert _umsatz(conn, "0001", "2024-01-15") == pytest.approx(expected)


@pytest.mark.parametrize("raw_date", ["15.01.2024", "2024-01-15"])
def test_date_parser(conn, raw_date):
    """German DD.MM.YYYY and ISO dates both normalize to ISO YYYY-MM-DD."""
    csv = f"Datum;Filialnummer;Umsatz\n{raw_date};0001;100\n"
    n, _ = _import_csv(conn, csv)
    assert n == 1
    assert _umsatz(conn, "0001", "2024-01-15") == pytest.approx(100.0)
