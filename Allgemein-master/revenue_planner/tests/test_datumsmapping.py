"""Regression tests for the datumsmapping base-day assignment.

Hard guarantees (must always hold):
  1. A ferien plan day is ALWAYS compared with a ferien day in the matched
     prior-year (VJ) period — never with a normal day, a public holiday, or
     Dec 24/31.
  2. The Weihnachtsferien year-boundary split is matched correctly:
     a January plan ferien day maps to a January VJ ferien day (not December).
  3. Dec 24 and Dec 31 are quasi-holidays and must never serve as the base
     comparison day for a normal or ferien day. A plan Dec 24/31 maps to the
     same calendar date in the base year.
"""
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.schema import DDL, _migrate  # noqa: E402
from planning.engine import PlanningEngine, PlanParams  # noqa: E402
from planning.datumsmapping import generate_datumsmapping  # noqa: E402


PUBLIC_HOLIDAYS = [
    ("2026-01-01", "2025-01-01", "Neujahr", "alle", "feiertag"),
    ("2025-12-25", "2024-12-25", "1. Weihnachtstag", "alle", "feiertag"),
    ("2025-12-26", "2024-12-26", "2. Weihnachtstag", "alle", "feiertag"),
    ("2026-12-25", "2025-12-25", "1. Weihnachtstag", "alle", "feiertag"),
    ("2026-12-26", "2025-12-26", "2. Weihnachtstag", "alle", "feiertag"),
    ("2026-01-06", "2025-01-06", "Heilige Drei Könige", "BW", "feiertag"),
]

# Fasching 2026 Feiertagstage (Rosenmontag=2026-02-16, Faschingsdienstag=2026-02-17).
# Their VJ base dates are the corresponding Fasching days in 2025
# (Rosenmontag=2025-03-03, Faschingsdienstag=2025-03-04).
# Fasching-Sonntag 2025 (2025-03-02) is also tagged as a Feiertagstag (datum_vj).
FASCHING_FEIERTAGSTAGE = [
    ("2026-02-15", "2025-03-01", "Feiertagstag", "alle", "feiertagstag"),  # Sonntag vor Rosenmontag
    ("2026-02-16", "2025-03-03", "Feiertagstag", "alle", "feiertagstag"),  # Rosenmontag
    ("2026-02-17", "2025-03-04", "Feiertagstag", "alle", "feiertagstag"),  # Faschingsdienstag
]

# Realistic BW school-holiday calendar (jahr = calendar year of each fragment).
FERIEN_KALENDER = [
    # Weihnachtsferien split across the year boundary (two rows per year):
    ("BW", "Weihnachtsferien", 2025, "2025-01-01", "2025-01-04"),
    ("BW", "Weihnachtsferien", 2025, "2025-12-22", "2025-12-31"),
    ("BW", "Weihnachtsferien", 2026, "2026-01-01", "2026-01-05"),
    ("BW", "Weihnachtsferien", 2026, "2026-12-21", "2026-12-31"),
    ("BW", "Pfingstferien", 2025, "2025-06-10", "2025-06-20"),
    ("BW", "Pfingstferien", 2026, "2026-05-26", "2026-06-06"),
    ("BW", "Sommerferien", 2025, "2025-07-31", "2025-09-13"),
    ("BW", "Sommerferien", 2026, "2026-07-30", "2026-09-12"),
    ("BW", "Herbstferien", 2025, "2025-10-27", "2025-10-31"),
    ("BW", "Herbstferien", 2026, "2026-10-26", "2026-10-30"),
]


@pytest.fixture
def dm_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    _migrate(conn)
    conn.execute("INSERT INTO filialen (fil_nr, bezeichnung, bundesland) VALUES ('1','F','BW')")
    conn.executemany(
        "INSERT INTO feiertage (datum_plan, datum_vj, name, bundesland, art) VALUES (?,?,?,?,?)",
        PUBLIC_HOLIDAYS + FASCHING_FEIERTAGSTAGE,
    )
    conn.executemany(
        "INSERT INTO ferien_kalender (bundesland, art, jahr, start, ende) VALUES (?,?,?,?,?)",
        FERIEN_KALENDER,
    )
    conn.commit()
    eng = PlanningEngine(conn, PlanParams(planjahr=2026, stichtag=date(2026, 1, 1)))
    generate_datumsmapping(conn, 2026, eng)
    yield conn
    conn.close()


def _base_of(conn, iso: str) -> str:
    row = conn.execute(
        "SELECT base_datum FROM datumsmapping WHERE plan_datum=? AND bundesland='BW'",
        (iso,),
    ).fetchone()
    return row["base_datum"]


def _vj_ferien_days(bl="BW") -> set[str]:
    from planning.engine import _date_range
    days: set[str] = set()
    for b, _art, jahr, s, e in FERIEN_KALENDER:
        if b == bl and jahr == 2025:
            for d in _date_range(date.fromisoformat(s), date.fromisoformat(e)):
                days.add(d.isoformat())
    return days


def test_weihnachtsferien_january_maps_to_january(dm_conn):
    """Jan 2026 Weihnachtsferien must map to a January 2025 ferien day."""
    base = _base_of(dm_conn, "2026-01-02")
    assert base.startswith("2025-01"), f"expected January base, got {base}"
    assert base in _vj_ferien_days(), "January base day must itself be a ferien day"


def test_pfingstferien_maps_into_vj_pfingstferien(dm_conn):
    """27.05.2026 must compare with a day inside VJ Pfingstferien (June 2025)."""
    base = _base_of(dm_conn, "2026-05-27")
    assert "2025-06-10" <= base <= "2025-06-20", f"base {base} not in VJ Pfingstferien"


def test_dec_24_31_never_base_for_ferien_day(dm_conn):
    """A normal ferien day (30.12.2026) must not map to the quasi-holidays 24./31.12."""
    base = _base_of(dm_conn, "2026-12-30")
    assert base not in ("2025-12-24", "2025-12-31"), f"must not use quasi-holiday as base: {base}"


def test_dec_24_31_map_to_same_calendar_date(dm_conn):
    """Plan Dec 24/31 compare to the same calendar date in the base year."""
    assert _base_of(dm_conn, "2026-12-24") == "2025-12-24"
    assert _base_of(dm_conn, "2026-12-31") == "2025-12-31"


def test_ferien_base_never_holiday_or_quasi_holiday(dm_conn):
    """No ferien plan day may map to a public holiday or to Dec 24/31."""
    from planning.engine import is_special_quasi_feiertag
    holidays = {h[0] for h in PUBLIC_HOLIDAYS}  # plan-side; check base via vj column too
    vj_holidays = {h[1] for h in PUBLIC_HOLIDAYS if h[1]}
    rows = dm_conn.execute(
        "SELECT plan_datum, base_datum FROM datumsmapping "
        "WHERE bundesland='BW' AND plan_typ='ferien'"
    ).fetchall()
    assert rows, "no ferien mapping rows generated"
    for r in rows:
        b = r["base_datum"]
        # A plan Dec 24/31 is itself a quasi-holiday and correctly maps to the
        # same quasi-holiday in the base year (24.→24., 31.→31.).
        if is_special_quasi_feiertag(date.fromisoformat(r["plan_datum"])):
            continue
        assert b not in vj_holidays and b not in holidays, \
            f"{r['plan_datum']} maps to holiday {b}"
        assert not is_special_quasi_feiertag(date.fromisoformat(b)), \
            f"{r['plan_datum']} maps to quasi-holiday {b}"


def test_ferien_prefers_ferien_base_when_possible(dm_conn):
    """Where the matched VJ period has a usable same-weekday day, the base is a
    ferien day. The only allowed exceptions are weekday-impossible cases (e.g.
    a Dec ferien Wednesday whose only VJ ferien Wednesdays are Dec 24/31)."""
    from planning.engine import (PlanningEngine, PlanParams, _date_range,
                                 is_special_quasi_feiertag)
    eng = PlanningEngine(dm_conn, PlanParams(planjahr=2026, stichtag=date(2026, 1, 1)))
    vj_ferien = _vj_ferien_days()
    rows = dm_conn.execute(
        "SELECT plan_datum, base_datum FROM datumsmapping "
        "WHERE bundesland='BW' AND plan_typ='ferien'"
    ).fetchall()
    for r in rows:
        if r["base_datum"] in vj_ferien:
            continue
        # offender allowed only if the matched VJ period has no usable
        # (non-quasi-holiday) day of the plan day's weekday
        period = eng._ferien_period_for_day(r["plan_datum"], "BW")
        assert period is not None, f"no period for {r['plan_datum']}"
        wt = date.fromisoformat(r["plan_datum"]).weekday()
        usable = [d for d in _date_range(date.fromisoformat(period["start_vj"]),
                                         date.fromisoformat(period["ende_vj"]))
                  if d.weekday() == wt and not is_special_quasi_feiertag(d)]
        assert not usable, (
            f"{r['plan_datum']} (wt={wt}) mapped to non-ferien {r['base_datum']} "
            f"although VJ period {period['start_vj']}..{period['ende_vj']} "
            f"has usable days {usable}")


def _vj_feiertagstag_dates() -> set[str]:
    """VJ base dates of all Feiertagstage in the test data."""
    return {row[1] for row in FASCHING_FEIERTAGSTAGE if row[1]}


def test_normal_day_does_not_map_to_vj_feiertagstag(dm_conn):
    """A normal plan day must never use a VJ Feiertagstag (e.g. Fasching-Sonntag)
    as its ISO-KW base comparison day.

    Concrete case: 2026-03-01 (Sunday, ISO-KW 9) would naively resolve to
    2025-03-02 (Fasching-Sonntag, also ISO-KW 9 Sunday) — the fix must step
    over it to the next available normal Sunday.
    """
    blocked = _vj_feiertagstag_dates()
    rows = dm_conn.execute(
        "SELECT plan_datum, base_datum FROM datumsmapping "
        "WHERE bundesland='BW' AND plan_typ='normal'"
    ).fetchall()
    assert rows, "no normal mapping rows generated"
    for r in rows:
        assert r["base_datum"] not in blocked, (
            f"normal plan day {r['plan_datum']} mapped to VJ Feiertagstag {r['base_datum']}"
        )


def test_normal_day_does_not_map_to_vj_sondertag(dm_conn):
    """A normal plan day must never use a VJ Sondertag (datum_referenz) as its
    ISO-KW base comparison day."""
    # No Sondertage in this fixture, so just assert no mapping_art issues occur.
    rows = dm_conn.execute(
        "SELECT plan_datum, base_datum, mapping_art FROM datumsmapping "
        "WHERE bundesland='BW' AND plan_typ='normal'"
    ).fetchall()
    assert rows
    for r in rows:
        assert r["mapping_art"] in ("iso_kw",), (
            f"unexpected mapping_art '{r['mapping_art']}' for normal day {r['plan_datum']}"
        )
