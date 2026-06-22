"""Shared pytest fixtures: in-memory SQLite DB with deterministic sample data.

The fixture mirrors the production schema (database/schema.py DDL + _migrate)
and seeds:
  - 3 branches: 0001 (RP, factor 1.0), 0002 (BW, 1.5), 0003 (BW, 0.8)
  - 24 months of IST revenue (2024-01-01 .. 2025-12-31), deterministic per
    weekday (Mo=1000 .. Sa=1800, So=0 -> Sunday closed) times branch factor
  - filial_oeffnung: Sunday closed, all other weekdays open
  - holidays: Neujahr 2026 (alle), Heilige Drei Koenige 2026 (BW),
    Sondertag Muttertag 2026
  - ferien_kalender: Osterferien BW 2025 and 2026
  - parameter_monat: planjahr 2026, all months wachstum_pct = 3.0
  - datumsmapping generated for planjahr 2026 (planning/datumsmapping.py)
"""
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.schema import DDL, _migrate  # noqa: E402

PLANJAHR = 2026
STICHTAG = date(2026, 1, 1)

# Mo..So base revenue per weekday
WEEKDAY_REVENUE = {0: 1000.0, 1: 1100.0, 2: 1200.0, 3: 1300.0,
                   4: 1400.0, 5: 1800.0, 6: 0.0}
BRANCH_FACTORS = {"0001": 1.0, "0002": 1.5, "0003": 0.8}
BRANCH_BL = {"0001": "RP", "0002": "BW", "0003": "BW"}


def make_test_db() -> sqlite3.Connection:
    """Build the deterministic in-memory test DB (also usable outside pytest)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    _migrate(conn)

    cur = conn.cursor()
    # Branches
    for fil_nr, bl in BRANCH_BL.items():
        cur.execute("INSERT INTO filialen (fil_nr, bezeichnung, bundesland) VALUES (?,?,?)",
                    (fil_nr, f"Filiale {fil_nr}", bl))

    # IST revenue 2024-01-01 .. 2025-12-31
    rows = []
    d = date(2024, 1, 1)
    end = date(2025, 12, 31)
    ferien_vj = (date(2025, 4, 14), date(2025, 4, 25))  # Osterferien BW 2025
    while d <= end:
        base = WEEKDAY_REVENUE[d.weekday()]
        for fil_nr, f in BRANCH_FACTORS.items():
            val = base * f
            # BW branches lose 40% during the prior-year Osterferien so the
            # per-week ferien factor (and eff_ferien) is genuinely exercised.
            if BRANCH_BL[fil_nr] == "BW" and ferien_vj[0] <= d <= ferien_vj[1]:
                val *= 0.6
            rows.append((fil_nr, d.isoformat(), round(val, 2)))
        d += timedelta(days=1)
    cur.executemany("INSERT INTO ist_umsatz (fil_nr, datum, umsatz) VALUES (?,?,?)", rows)

    # Opening weekdays: Sunday closed
    for fil_nr in BRANCH_FACTORS:
        for wt in range(7):
            cur.execute("INSERT INTO filial_oeffnung (fil_nr, wochentag, offen) VALUES (?,?,?)",
                        (fil_nr, wt, 0 if wt == 6 else 1))

    # Holidays
    cur.executemany(
        "INSERT INTO feiertage (datum_plan, datum_vj, name, bundesland, art) VALUES (?,?,?,?,?)",
        [
            ("2026-01-01", "2025-01-01", "Neujahr", "alle", "feiertag"),
            ("2026-01-06", "2025-01-06", "Heilige Drei Könige", "BW", "feiertag"),
            ("2026-05-10", "2025-05-11", "Muttertag", "alle", "Sondertag"),
        ])

    # School vacations (ferien_kalender = single source of truth)
    cur.executemany(
        "INSERT INTO ferien_kalender (bundesland, art, jahr, start, ende) VALUES (?,?,?,?,?)",
        [
            ("BW", "Osterferien", 2025, "2025-04-14", "2025-04-25"),
            ("BW", "Osterferien", 2026, "2026-03-30", "2026-04-10"),
        ])

    # Monthly growth: 3.0 % each month
    cur.executemany(
        "INSERT INTO parameter_monat (planjahr, monat, wachstum_pct) VALUES (?,?,?)",
        [(PLANJAHR, m, 3.0) for m in range(1, 13)])
    conn.commit()

    # Generate datumsmapping for the plan year (like 13_Datumsmapping page does)
    from planning.engine import PlanningEngine, PlanParams
    from planning.datumsmapping import generate_datumsmapping
    eng = PlanningEngine(conn, PlanParams(planjahr=PLANJAHR, stichtag=STICHTAG))
    generate_datumsmapping(conn, PLANJAHR, eng)
    return conn


def make_engine(conn):
    """Standard engine config for the test DB (planjahr 2026, 3% growth)."""
    from planning.engine import PlanningEngine, PlanParams
    params = PlanParams(
        planjahr=PLANJAHR,
        stichtag=STICHTAG,
        wachstum_monat={m: 3.0 for m in range(1, 13)},
        ferien_puffer_wochen=2,
    )
    return PlanningEngine(conn, params)


@pytest.fixture
def db():
    conn = make_test_db()
    yield conn
    conn.close()


@pytest.fixture
def engine(db):
    return make_engine(db)
