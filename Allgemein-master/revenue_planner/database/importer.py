"""Import IST revenue data from Excel / CSV into the database."""
import io
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Callable


def _parse_num(s: str) -> float:
    """Parse a German or English numeric string to float.

    Handles:
      - German thousands separator: 1.234.567,89  →  1234567.89
      - German decimal only:        1234567,89     →  1234567.89
      - English decimal:            1234567.89     →  1234567.89
      - Pure integer:               1234567        →  1234567.0
    """
    s = str(s).strip().replace('\xa0', '').replace(' ', '')
    # Remove currency symbols
    for sym in ('€', '$', '£', '%'):
        s = s.replace(sym, '')
    s = s.strip()
    if not s:
        return float('nan')

    if ',' in s and '.' in s:
        # German format: dots = thousands, comma = decimal  (1.234.567,89)
        return pd.to_numeric(s.replace('.', '').replace(',', '.'), errors='coerce')
    elif ',' in s:
        # Comma is decimal separator (no thousands dot present)
        return pd.to_numeric(s.replace(',', '.'), errors='coerce')
    elif '.' in s:
        parts = s.split('.')
        # Thousands separator: first group ≤ 3 digits AND all subsequent groups exactly 3 digits
        # e.g. 2.748.956 → ["2","748","956"] ✓  but 2748.956 → ["2748","956"] ✗ (4-digit lead)
        if (len(parts) > 1
                and len(parts[0]) <= 3
                and all(len(p) == 3 for p in parts[1:])):
            return pd.to_numeric(s.replace('.', ''), errors='coerce')
        # Otherwise dot is decimal separator
        return pd.to_numeric(s, errors='coerce')
    return pd.to_numeric(s, errors='coerce')


def fmt_num_de(value) -> str:
    """Format a parsed number in German style (1.234.567,89)."""
    try:
        v = float(value)
        if pd.isna(v):
            return ""
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def import_ist_umsatz(
    conn: sqlite3.Connection,
    file_path,
    file_name: str = "",
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[int, list[str]]:
    """Import daily actuals from a file with columns:
        Datum | Filialnummer | Umsatz brutto
    (plus optional extra columns that are ignored).

    Accepts either a path (str/Path) or a file-like object (BytesIO/UploadedFile).
    Optional progress_cb(fraction 0..1, text) is called during processing.

    Returns (rows_inserted, warnings).
    """
    warnings: list[str] = []

    def _progress(pct: float, text: str):
        if progress_cb:
            progress_cb(pct, text)

    # Determine file extension for format detection
    if hasattr(file_path, "read"):
        data = io.BytesIO(file_path.read())
        suffix = Path(file_name).suffix.lower() if file_name else ""
    else:
        path = Path(file_path)
        data = path
        suffix = path.suffix.lower()

    _progress(0.05, "Datei wird gelesen…")

    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(data, dtype=str)
    else:
        raw = data.read() if hasattr(data, "read") else open(str(data), "rb").read()
        _loaded = False
        # Try explicit separators first (avoids sniffer misidentifying comma-decimal as delimiter),
        # then fall back to auto-detection.
        for _enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1", "iso-8859-1"):
            for _sep in (";", ",", None):
                try:
                    _kwargs = {"dtype": str, "encoding": _enc}
                    if _sep is None:
                        _kwargs["sep"] = None
                        _kwargs["engine"] = "python"
                    else:
                        _kwargs["sep"] = _sep
                    _df_try = pd.read_csv(io.BytesIO(raw), **_kwargs)
                    if len(_df_try.columns) >= 3:
                        df = _df_try
                        _loaded = True
                        break
                except (UnicodeDecodeError, Exception):
                    continue
            if _loaded:
                break
        if not _loaded:
            raise ValueError(
                "CSV-Datei konnte mit keiner bekannten Zeichenkodierung gelesen werden "
                "(UTF-8, Windows-1252, Latin-1). Bitte als Excel (.xlsx) exportieren."
            )

    n_total_rows = len(df)
    _progress(0.15, f"Datei gelesen: {n_total_rows:,} Zeilen — prüfe Spalten…")

    # Flexible column mapping
    col_map = _detect_columns(df.columns.tolist())
    missing = [k for k, v in col_map.items() if v is None]
    if missing:
        raise ValueError(
            f"Pflichtfelder nicht gefunden: {missing}. "
            f"Vorhandene Spalten: {df.columns.tolist()}"
        )

    df = df.rename(columns={
        col_map["datum"]:  "datum",
        col_map["fil_nr"]: "fil_nr",
        col_map["umsatz"]: "umsatz",
    })

    _progress(0.20, "Datumsfelder werden geparst…")

    # Normalise dates → ISO format
    raw_datum = df["datum"].copy()
    parsed = pd.to_datetime(raw_datum, format="ISO8601", errors="coerce")
    still_bad = parsed.isna()
    if still_bad.any():
        parsed.loc[still_bad] = pd.to_datetime(
            raw_datum.loc[still_bad], dayfirst=True, errors="coerce"
        )
    df["datum"] = parsed.dt.strftime("%Y-%m-%d")
    bad_dates = df["datum"].isna().sum()
    if bad_dates:
        warnings.append(f"{bad_dates} Zeilen mit ungültigem Datum wurden übersprungen.")
    df = df.dropna(subset=["datum"])

    # Normalise branch number
    df["fil_nr"] = df["fil_nr"].astype(str).str.strip()
    empty_fil = df["fil_nr"].isin(["", "nan", "none", "NaN", "None"]) | df["fil_nr"].isna()
    n_empty_fil = int(empty_fil.sum())
    if n_empty_fil:
        warnings.append(f"{n_empty_fil} Zeilen ohne Filialnummer wurden übersprungen.")
    df = df[~empty_fil]

    _progress(0.40, f"Umsatzwerte werden geparst ({len(df):,} Zeilen)…")

    # Normalise revenue
    df["umsatz"] = df["umsatz"].apply(_parse_num).round(2)
    bad_rev = df["umsatz"].isna().sum()
    if bad_rev:
        warnings.append(f"{bad_rev} Zeilen mit ungültigem Umsatz wurden übersprungen.")
    df = df.dropna(subset=["umsatz"])

    rows = [{"fil_nr": r.fil_nr, "datum": r.datum, "umsatz": r.umsatz}
            for r in df[["fil_nr", "datum", "umsatz"]].itertuples()]

    _progress(0.55, f"Alte Daten werden gelöscht, {len(rows):,} Zeilen werden importiert…")

    cur = conn.cursor()
    cur.execute("DELETE FROM ist_umsatz")

    # Chunked insert with per-chunk progress
    chunk_size = 2000
    total = len(rows)
    for i in range(0, total, chunk_size):
        chunk = rows[i:i + chunk_size]
        cur.executemany(
            "INSERT INTO ist_umsatz (fil_nr, datum, umsatz) "
            "VALUES (:fil_nr, :datum, :umsatz)",
            chunk,
        )
        done = min(i + chunk_size, total)
        pct = 0.55 + 0.40 * done / total if total else 0.95
        _progress(pct, f"Importiert: {done:,} / {total:,} Zeilen…")

    conn.commit()
    _progress(1.0, f"Fertig: {total:,} Zeilen importiert.")
    return total, warnings


def _detect_columns(columns: list[str]) -> dict[str, str | None]:
    """Fuzzy-match the three required columns regardless of exact naming.

    Priority: exact match > starts-with > contains.
    For umsatz: more specific candidates ('umsatz brutto') are tried before
    generic ones ('umsatz') to avoid matching 'Gesamtumsatz' or 'Umsatz netto'
    when a dedicated 'Umsatz brutto' column exists.
    """
    lower = {c.lower().strip(): c for c in columns}

    def find(candidates: list[str]) -> str | None:
        # Pass 1: exact match
        for c in candidates:
            if c in lower:
                return lower[c]
        # Pass 2: starts-with match (column name begins with candidate)
        for c in candidates:
            for k, original in lower.items():
                if k.startswith(c):
                    return original
        # Pass 3: contains match (current fallback)
        for c in candidates:
            for k, original in lower.items():
                if c in k:
                    return original
        return None

    return {
        "datum":  find(["datum", "date", "tag"]),
        "fil_nr": find(["filialnummer", "filnr", "fil_nr", "filiale", "fg", "fachgeschäft"]),
        # Specific before generic: avoids 'Gesamtumsatz' winning over 'Umsatz'
        "umsatz": find(["umsatz brutto", "umsatz netto", "umsatz", "revenue", "erlös", "betrag"]),
    }


def detect_oeffnungstage(conn: sqlite3.Connection, force: bool = False) -> dict:
    """
    Erkenne aus den IST-Daten je Filiale:
      - an welchen Wochentagen geöffnet (Umsatz > 0 in >=30% der Vorkommen)
      - an welchen Feiertagen historisch geöffnet (Umsatz > 0 am Feiertags-Vorjahrestag)

    force=False  → nur Filialen ohne bestehende Einträge befüllen (manuelle Edits bleiben).
    force=True   → alles neu erkennen (überschreibt).

    Returns dict mit Zählern.
    """
    df = pd.read_sql("SELECT fil_nr, datum, umsatz FROM ist_umsatz", conn)
    if df.empty:
        return {"weekday_branches": 0, "holiday_entries": 0}
    df["datum"] = pd.to_datetime(df["datum"])
    df["wt"] = df["datum"].dt.weekday

    cur = conn.cursor()
    existing_wd = {r[0] for r in cur.execute("SELECT DISTINCT fil_nr FROM filial_oeffnung").fetchall()}

    _MEANINGFUL_REV = 100.0  # Mindest-Umsatz für „geöffnet"

    # Wochentag-Erkennung: nur letzten 3 Wochen je Filiale verwenden
    if not df.empty:
        last_date = df["datum"].max()
        recent_cutoff = last_date - pd.Timedelta(weeks=3)
        df_recent = df[df["datum"] >= recent_cutoff]
    else:
        df_recent = df

    wd_branches = 0
    for fil_nr, g in df_recent.groupby("fil_nr"):
        if not force and fil_nr in existing_wd:
            continue
        for wt in range(7):
            sub = g[g["wt"] == wt]
            total = len(sub)
            with_rev = int((sub["umsatz"] >= _MEANINGFUL_REV).sum())
            offen = 1 if (total > 0 and with_rev / total >= 0.30) else 0
            cur.execute(
                "INSERT OR REPLACE INTO filial_oeffnung (fil_nr, wochentag, offen) VALUES (?,?,?)",
                (fil_nr, wt, offen),
            )
        wd_branches += 1

    # Feiertags-Öffnung
    feiertage = cur.execute(
        "SELECT DISTINCT name, datum_vj FROM feiertage WHERE datum_vj IS NOT NULL"
    ).fetchall()
    existing_ft = {(r[0], r[1]) for r in cur.execute(
        "SELECT fil_nr, feiertag_name FROM filial_feiertag").fetchall()}

    rev_lookup = {(r.fil_nr, r.datum.strftime("%Y-%m-%d")): r.umsatz
                  for r in df.itertuples()}
    df_md = df.assign(md=df["datum"].dt.strftime("%m-%d"))
    md_series = df_md.groupby(["fil_nr", "md"])["umsatz"].max()
    md_lookup: dict[tuple, float] = {idx: float(v) for idx, v in md_series.items()}

    ft_entries = 0
    all_fils = [r[0] for r in cur.execute("SELECT fil_nr FROM filialen").fetchall()]
    for fil_nr in all_fils:
        for ft in feiertage:
            name, datum_vj = ft["name"], ft["datum_vj"]
            if not force and (fil_nr, name) in existing_ft:
                continue
            umsatz = rev_lookup.get((fil_nr, datum_vj), 0.0)
            if not (umsatz and umsatz > 0) and datum_vj:
                umsatz = md_lookup.get((fil_nr, datum_vj[5:]), 0.0)
            offen = 1 if (umsatz and umsatz > 0) else 0
            cur.execute(
                "INSERT OR REPLACE INTO filial_feiertag (fil_nr, feiertag_name, offen) VALUES (?,?,?)",
                (fil_nr, name, offen),
            )
            ft_entries += 1

    conn.commit()
    return {"weekday_branches": wd_branches, "holiday_entries": ft_entries}


def ensure_filialen_from_ist(conn: sqlite3.Connection, bundesland_default: str = "DE-RP") -> int:
    """Auto-create filiale entries for any fil_nr present in ist_umsatz but missing in filialen."""
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO filialen (fil_nr, bundesland)
        SELECT DISTINCT fil_nr, ? FROM ist_umsatz
    """, (bundesland_default,))
    conn.commit()
    return cur.rowcount
