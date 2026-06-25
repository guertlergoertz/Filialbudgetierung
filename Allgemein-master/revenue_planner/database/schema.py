"""Database schema creation and migration for one SQLite file per GmbH."""
import sqlite3
from pathlib import Path


DDL = """
-- ── Branch master ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filialen (
    fil_nr          TEXT PRIMARY KEY,
    bezeichnung     TEXT,
    bundesland      TEXT NOT NULL,          -- DE-RP, DE-HE, DE-BY …
    ort             TEXT,
    eroeffnung      TEXT,                   -- ISO date; NULL = bestehend
    flag_kein_wachstum   INTEGER NOT NULL DEFAULT 0,   -- 1 = kein % Aufschlag
    flag_manuell    INTEGER NOT NULL DEFAULT 0,   -- 1 = Monatswert wird überschrieben
    flag_neue_filiale INTEGER NOT NULL DEFAULT 0, -- 1 = neue Filiale (manueller Planwert)
    flag_inaktiv    INTEGER NOT NULL DEFAULT 0,   -- 1 = ab eroeffnung_ende geschlossen
    flag_gesperrt   INTEGER NOT NULL DEFAULT 0,   -- 1 = gesperrt (auto bei XX/XXX in Bezeichnung)
    eroeffnung_ende TEXT,                   -- Schliessungsdatum
    ramadan_sensitiv INTEGER NOT NULL DEFAULT 0,  -- 1 = Filiale von Ramadan betroffen
    geplanter_umsatz_monat REAL,               -- manueller Planwert je Monat (neue Filialen)
    notiz           TEXT
);

-- ── Daily actuals ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ist_umsatz (
    fil_nr          TEXT NOT NULL,
    datum           TEXT NOT NULL,          -- ISO date
    umsatz          REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (fil_nr, datum)
);
CREATE INDEX IF NOT EXISTS idx_ist_datum ON ist_umsatz(datum);

-- ── Planning parameters (one row per plan year) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parameter (
    planjahr                INTEGER PRIMARY KEY,
    preiserhoehung_pct      REAL    NOT NULL DEFAULT 0.0,  -- z.B. 3.5 für 3,5 %

    -- Ferien-Pufferzeitraum (Wochen vor/nach Ferien für Ferienfaktor-Vergleich)
    ferien_puffer_wochen    INTEGER NOT NULL DEFAULT 3,

    -- Ramadan (leer = nicht aktiv)
    ramadan_vj_start        TEXT,           -- ISO date Vorjahr
    ramadan_vj_ende         TEXT,
    ramadan_plan_start      TEXT,           -- ISO date Planjahr
    ramadan_plan_ende       TEXT,
    ramadan_umsatz_pct      REAL DEFAULT 0.0,  -- % des Monatsumsatzes betroffen

    -- Fasching
    fasching_vj_start       TEXT,
    fasching_vj_ende        TEXT,
    fasching_plan_start     TEXT,
    fasching_plan_ende      TEXT,
    fasching_wirkung_pct    REAL DEFAULT 0.0   -- % Umsatzveränderung pro Tag-Differenz
);

-- ── Public holidays ────────────────────────────────────────────────────────────────
-- Bundesland codes: "alle" = bundesweit, sonst ISO z.B. "DE-RP"
-- art: 'feiertag' = gesetzlicher Feiertag, 'feiertagstag' = Vor-/Nachtag
CREATE TABLE IF NOT EXISTS feiertage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datum_plan      TEXT NOT NULL,          -- ISO date im Planjahr
    datum_vj        TEXT,                   -- ISO date im Vorjahr (fuer 1:1 Planung)
    name            TEXT NOT NULL,
    bundesland      TEXT NOT NULL DEFAULT 'alle',
    art             TEXT NOT NULL DEFAULT 'feiertag'
);
CREATE INDEX IF NOT EXISTS idx_feiertage_datum ON feiertage(datum_plan);

-- ── Special days (Sondertage) ──────────────────────────────────────────────────────────
-- methode: 'samstag' = Samstags-Umsatz der Filiale; 'referenz' = datum_referenz
CREATE TABLE IF NOT EXISTS sondertage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    datum_plan      TEXT NOT NULL,
    datum_referenz  TEXT,                   -- Vorjahres-Referenztag
    bezeichnung     TEXT NOT NULL,
    methode         TEXT NOT NULL DEFAULT 'referenz',  -- 'samstag' | 'referenz'
    bundesland      TEXT NOT NULL DEFAULT 'alle'
);

-- ── School vacation periods ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ferien (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bundesland      TEXT NOT NULL,
    art             TEXT NOT NULL,          -- Osterferien, Sommerferien …
    start_vj        TEXT NOT NULL,
    ende_vj         TEXT NOT NULL,
    start_plan      TEXT NOT NULL,
    ende_plan       TEXT NOT NULL
);

-- ── Delivery customer monthly revenue ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lieferkunden_monat (
    fil_nr          TEXT NOT NULL,
    jahr            INTEGER NOT NULL,
    monat           INTEGER NOT NULL,       -- 1–12
    ist_betrag      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (fil_nr, jahr, monat)
);

-- ── New branch monthly plan values ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS neue_filialen_plan (
    fil_nr          TEXT NOT NULL,          -- kann Platzhalter sein z.B. "NEU_001"
    planjahr        INTEGER NOT NULL,
    monat           INTEGER NOT NULL,
    planwert        REAL NOT NULL DEFAULT 0,
    eroeffnung_datum TEXT,                  -- NULL = bereits im Monat offen
    PRIMARY KEY (fil_nr, planjahr, monat)
);

-- ── Manual monthly override for existing branches ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS planwert_override (
    fil_nr          TEXT NOT NULL,
    planjahr        INTEGER NOT NULL,
    monat           INTEGER NOT NULL,
    planwert        REAL NOT NULL,
    PRIMARY KEY (fil_nr, planjahr, monat)
);

-- ── Monthly growth rates ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parameter_monat (
    planjahr     INTEGER NOT NULL,
    monat        INTEGER NOT NULL,  -- 1-12
    wachstum_pct REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (planjahr, monat)
);

-- ── Opening weekdays per branch (auto-detected from import, editable) ────────────────────────
-- offen=1 → Filiale hat an diesem Wochentag im Basiszeitraum geöffnet
CREATE TABLE IF NOT EXISTS filial_oeffnung (
    fil_nr      TEXT NOT NULL,
    wochentag   INTEGER NOT NULL,   -- 0=Mo … 6=So
    offen       INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (fil_nr, wochentag)
);

-- ── Opening on public holidays per branch (auto-detected, editable) ─────────────────────────
CREATE TABLE IF NOT EXISTS filial_feiertag (
    fil_nr        TEXT NOT NULL,
    feiertag_name TEXT NOT NULL,
    offen         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (fil_nr, feiertag_name)
);

-- ── School vacation calendar (loaded from library or manual) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ferien_kalender (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    bundesland TEXT NOT NULL,
    art        TEXT NOT NULL,
    jahr       INTEGER NOT NULL,
    start      TEXT NOT NULL,
    ende       TEXT NOT NULL,
    UNIQUE(bundesland, art, jahr, start)
);

-- ── School branch mapping ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filial_schulferien (
    fil_nr      TEXT NOT NULL,
    ferien_art  TEXT NOT NULL,
    bundesland  TEXT NOT NULL,
    geschlossen INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (fil_nr, ferien_art, bundesland)
);

-- ── Per-week vacation factors (computed, inspectable) ────────────────────────────────────────────
-- woche: 1..n innerhalb der Ferien; faktor = Oe Umsatz Ferienwoche / Oe Puffer (2 Wo davor)
CREATE TABLE IF NOT EXISTS ferien_faktor (
    fil_nr      TEXT NOT NULL,
    bundesland  TEXT NOT NULL,
    ferien_art  TEXT NOT NULL,
    woche       INTEGER NOT NULL,
    faktor      REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (fil_nr, bundesland, ferien_art, woche)
);

-- ── Date mapping (computed, cache per plan year × bundesland) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datumsmapping (
    plan_datum  TEXT NOT NULL,
    base_datum  TEXT NOT NULL,
    plan_typ    TEXT NOT NULL DEFAULT 'normal',
    base_typ    TEXT,
    bundesland  TEXT NOT NULL DEFAULT 'alle',
    mapping_art      TEXT NOT NULL DEFAULT 'iso_kw',
    bezeichnung      TEXT NOT NULL DEFAULT '',
    base_bezeichnung TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (plan_datum, bundesland)
);

-- ── Computed plan (written after each planning run) ───────────────────────────────────────────────
-- Additive Effekt-Zerlegung: ist_vj + Summe(eff_*) = budget (exakt je Tag)
CREATE TABLE IF NOT EXISTS planung (
    fil_nr          TEXT NOT NULL,
    datum           TEXT NOT NULL,          -- ISO date im Planjahr
    wochentag       INTEGER NOT NULL,       -- 0=Mo … 6=So
    bundesland      TEXT,
    ist_vj          REAL,                   -- Ist des korrespondierenden Basistags
    -- additive Effekte (Herleitung)
    eff_oeffnung    REAL,                   -- Öffnungs-/Schließungseffekt
    eff_verteilung  REAL,                   -- Glättung Einzeltag → Wochentagsverteilung
    eff_wochentag   REAL,                   -- Wochentagsmix-Verschiebung (Hochrechnung)
    eff_preis       REAL,                   -- Preisanpassung / Wachstum
    eff_ferien      REAL,                   -- Ferieneffekt
    eff_feiertag    REAL,                   -- Feiertags-/Sondertagseffekt
    eff_norm        REAL,                   -- Normalisierungs-Rebalancing
    budget          REAL,                   -- Endwert = ist_vj + Summe(eff_*)
    -- Monatskontext (gleich für alle Tage des Monats)
    monat_basis     REAL,                   -- Basismonatsumsatz (IST Basiszeitraum)
    monat_hoch      REAL,                   -- hochgerechnet auf Planjahr-Wochentage
    monat_plan      REAL,                   -- nach Wachstum
    -- Kompatibilitäts-Spalten (Spiegel von budget / monat_*)
    monatsumsatz_ist_hoch REAL,
    monatsumsatz_plan REAL,
    tagesumsatz_plan  REAL,
    liefer_plan     REAL,                   -- nicht mehr genutzt (immer 0)
    gesamt_plan     REAL,                   -- = budget
    tagestyp        TEXT,                   -- 'normal'|'feiertag'|'sondertag'|'ferien'|'geschlossen'
    feiertag_name   TEXT,
    ferien_art      TEXT,
    normalisierung  REAL,
    PRIMARY KEY (fil_nr, datum)
);
CREATE INDEX IF NOT EXISTS idx_planung_datum ON planung(datum);

-- ── Computed plan — LOGIC 2 (alternative engine, see planning/engine2.py) ──────────────────────────
CREATE TABLE IF NOT EXISTS planung2 (
    fil_nr          TEXT NOT NULL,
    datum           TEXT NOT NULL,
    wochentag       INTEGER NOT NULL,
    bundesland      TEXT,
    ist_vj          REAL,
    eff_oeffnung    REAL,
    eff_verteilung  REAL,
    eff_wochentag   REAL,
    eff_preis       REAL,
    eff_ferien      REAL,
    eff_feiertag    REAL,
    eff_norm        REAL,
    eff_validierung REAL,
    budget          REAL,
    monat_basis     REAL,
    monat_hoch      REAL,
    monat_plan      REAL,
    monatsumsatz_ist_hoch REAL,
    monatsumsatz_plan REAL,
    tagesumsatz_plan  REAL,
    liefer_plan     REAL,
    gesamt_plan     REAL,
    tagestyp        TEXT,
    feiertag_name   TEXT,
    ferien_art      TEXT,
    normalisierung  REAL,
    PRIMARY KEY (fil_nr, datum)
);
CREATE INDEX IF NOT EXISTS idx_planung2_datum ON planung2(datum);

-- ── L2 weekday-validation correction log ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS planwert_korrekturen2 (
    datum             TEXT NOT NULL PRIMARY KEY,
    wochentag         INTEGER NOT NULL,
    monat             INTEGER NOT NULL,
    original_gesamt   REAL NOT NULL,
    wd_schnitt        REAL NOT NULL,
    abweichung_pct    REAL NOT NULL,
    korrigiert_gesamt REAL NOT NULL
);
"""


def get_db_path(gmbh_name: str, data_dir: str = "data") -> Path:
    safe = gmbh_name.replace(" ", "_").replace("/", "-")
    return Path(data_dir) / f"{safe}.db"


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create (or open) the database and ensure the schema exists."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(DDL)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection):
    """Add columns that were missing due to schema bugs in earlier versions."""
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(filialen)").fetchall()
    }
    additions = [
        ("flag_kein_wachstum", "INTEGER NOT NULL DEFAULT 0"),
        ("geplanter_umsatz_monat", "REAL"),
        ("flag_gesperrt", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, definition in additions:
        if col not in existing:
            conn.execute(f"ALTER TABLE filialen ADD COLUMN {col} {definition}")

    # Add art column to feiertage if missing
    feiertage_cols = {row[1] for row in conn.execute("PRAGMA table_info(feiertage)").fetchall()}
    if "art" not in feiertage_cols:
        conn.execute("ALTER TABLE feiertage ADD COLUMN art TEXT NOT NULL DEFAULT 'feiertag'")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS parameter_monat (
            planjahr     INTEGER NOT NULL,
            monat        INTEGER NOT NULL,
            wachstum_pct REAL    NOT NULL DEFAULT 0.0,
            PRIMARY KEY (planjahr, monat)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS filial_oeffnung (
            fil_nr      TEXT NOT NULL,
            wochentag   INTEGER NOT NULL,
            offen       INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (fil_nr, wochentag)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filial_feiertag (
            fil_nr        TEXT NOT NULL,
            feiertag_name TEXT NOT NULL,
            offen         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (fil_nr, feiertag_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ferien_faktor (
            fil_nr      TEXT NOT NULL,
            bundesland  TEXT NOT NULL,
            ferien_art  TEXT NOT NULL,
            woche       INTEGER NOT NULL,
            faktor      REAL NOT NULL DEFAULT 1.0,
            PRIMARY KEY (fil_nr, bundesland, ferien_art, woche)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ferien_kalender (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            bundesland TEXT NOT NULL,
            art        TEXT NOT NULL,
            jahr       INTEGER NOT NULL,
            start      TEXT NOT NULL,
            ende       TEXT NOT NULL,
            UNIQUE(bundesland, art, jahr, start)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS filial_schulferien (
            fil_nr      TEXT NOT NULL,
            ferien_art  TEXT NOT NULL,
            bundesland  TEXT NOT NULL,
            geschlossen INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (fil_nr, ferien_art, bundesland)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS datumsmapping (
            plan_datum  TEXT NOT NULL,
            base_datum  TEXT NOT NULL,
            plan_typ    TEXT NOT NULL DEFAULT 'normal',
            base_typ    TEXT,
            bundesland  TEXT NOT NULL DEFAULT 'alle',
            mapping_art TEXT NOT NULL DEFAULT 'iso_kw',
            bezeichnung TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (plan_datum, bundesland)
        )
    """)
    dm_cols = {row[1] for row in conn.execute("PRAGMA table_info(datumsmapping)").fetchall()}
    if "bezeichnung" not in dm_cols:
        conn.execute("ALTER TABLE datumsmapping ADD COLUMN bezeichnung TEXT NOT NULL DEFAULT ''")
    if "base_bezeichnung" not in dm_cols:
        conn.execute("ALTER TABLE datumsmapping ADD COLUMN base_bezeichnung TEXT NOT NULL DEFAULT ''")

    plan_cols = {row[1] for row in conn.execute("PRAGMA table_info(planung)").fetchall()}
    for col in ["bundesland", "eff_oeffnung", "eff_verteilung", "eff_wochentag",
                "eff_preis", "eff_ferien", "eff_feiertag", "eff_norm", "budget",
                "monat_basis", "monat_hoch", "monat_plan"]:
        if col not in plan_cols:
            typ = "TEXT" if col == "bundesland" else "REAL"
            conn.execute(f"ALTER TABLE planung ADD COLUMN {col} {typ}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS planung2 (
            fil_nr          TEXT NOT NULL,
            datum           TEXT NOT NULL,
            wochentag       INTEGER NOT NULL,
            bundesland      TEXT,
            ist_vj          REAL,
            eff_oeffnung    REAL,
            eff_verteilung  REAL,
            eff_wochentag   REAL,
            eff_preis       REAL,
            eff_ferien      REAL,
            eff_feiertag    REAL,
            eff_norm        REAL,
            eff_validierung REAL,
            budget          REAL,
            monat_basis     REAL,
            monat_hoch      REAL,
            monat_plan      REAL,
            monatsumsatz_ist_hoch REAL,
            monatsumsatz_plan REAL,
            tagesumsatz_plan  REAL,
            liefer_plan     REAL,
            gesamt_plan     REAL,
            tagestyp        TEXT,
            feiertag_name   TEXT,
            ferien_art      TEXT,
            normalisierung  REAL,
            PRIMARY KEY (fil_nr, datum)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_planung2_datum ON planung2(datum)")

    # Add eff_validierung to existing planung2 tables
    plan2_cols = {row[1] for row in conn.execute("PRAGMA table_info(planung2)").fetchall()}
    if plan2_cols and "eff_validierung" not in plan2_cols:
        conn.execute("ALTER TABLE planung2 ADD COLUMN eff_validierung REAL")
    if plan2_cols and "eff_hochrechnung" not in plan2_cols:
        conn.execute("ALTER TABLE planung2 ADD COLUMN eff_hochrechnung REAL")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS planwert_korrekturen2 (
            datum             TEXT NOT NULL PRIMARY KEY,
            wochentag         INTEGER NOT NULL,
            monat             INTEGER NOT NULL,
            original_gesamt   REAL NOT NULL,
            wd_schnitt        REAL NOT NULL,
            abweichung_pct    REAL NOT NULL,
            korrigiert_gesamt REAL NOT NULL
        )
    """)
