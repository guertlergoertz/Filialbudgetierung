"""Datenbankschema und Initialisierung."""
from __future__ import annotations

import duckdb
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "filialplanung.duckdb"


def get_connection(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    """Gibt eine DuckDB-Verbindung zurück und initialisiert das Schema."""
    conn = duckdb.connect(str(db_path))
    _init_schema(conn)
    return conn


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Erstellt alle Tabellen falls nicht vorhanden."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filialen (
            id INTEGER PRIMARY KEY,
            name VARCHAR NOT NULL,
            typ VARCHAR,
            aktiv BOOLEAN DEFAULT TRUE
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS umsatzdaten (
            id INTEGER PRIMARY KEY,
            filiale INTEGER REFERENCES filialen(id),
            datum DATE NOT NULL,
            umsatz DECIMAL(12, 2) NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS planwerte (
            id INTEGER PRIMARY KEY,
            filiale INTEGER REFERENCES filialen(id),
            datum DATE NOT NULL,
            planwert DECIMAL(12, 2) NOT NULL,
            engine VARCHAR NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parameter (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feiertage (
            datum DATE PRIMARY KEY,
            name VARCHAR NOT NULL,
            bundesland VARCHAR
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS oeffnungstage (
            filiale INTEGER REFERENCES filialen(id),
            datum DATE NOT NULL,
            geoeffnet BOOLEAN DEFAULT TRUE,
            PRIMARY KEY (filiale, datum)
        )
    """)

    # Schulferien (Datumsbereich je Bundesland)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ferien (
            id INTEGER PRIMARY KEY,
            bundesland VARCHAR,
            bezeichnung VARCHAR,
            datum_von DATE NOT NULL,
            datum_bis DATE NOT NULL
        )
    """)

    # Korrekturen aus Wochentagsvalidierung L2
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planwert_korrekturen2 (
            datum DATE PRIMARY KEY,
            wochentag INTEGER NOT NULL,
            monat INTEGER NOT NULL,
            original_gesamt DECIMAL(14, 2) NOT NULL,
            wd_schnitt DECIMAL(14, 2) NOT NULL,
            abweichung_pct DECIMAL(8, 4) NOT NULL,
            korrigiert_gesamt DECIMAL(14, 2) NOT NULL
        )
    """)
