"""IST revenue data import page."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from database.importer import import_ist_umsatz, _detect_columns, detect_oeffnungstage, _parse_num, fmt_num_de
import pandas as pd
import time as _time
import io as _io


def _read_csv_robust(file_obj, **kwargs) -> pd.DataFrame:
    """Read CSV trying explicit separators (;, ,) before auto-detection, across common encodings."""
    data = file_obj.read()
    file_obj.seek(0)
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1", "iso-8859-1"):
        for sep in (";", ",", None):
            try:
                kw = {"dtype": str, "encoding": enc, **kwargs}
                if sep is None:
                    kw["sep"] = None
                    kw["engine"] = "python"
                else:
                    kw["sep"] = sep
                df = pd.read_csv(_io.BytesIO(data), **kw)
                if len(df.columns) >= 3:
                    return df
            except (UnicodeDecodeError, Exception):
                continue
    raise ValueError(
        "CSV-Datei konnte mit keiner bekannten Zeichenkodierung gelesen werden "
        "(UTF-8, Windows-1252, Latin-1). Bitte als Excel (.xlsx) exportieren."
    )

require_db()
conn = get_conn()
st.title("IST-Umsätze importieren")

st.markdown("""
Erwartet eine CSV-Datei mit mindestens drei Spalten:
- **Datum** (z.B. `15.01.2024` oder `2024-01-15`)
- **Filialnummer** (z.B. `0120`)
- **Umsatz** (Dezimalzahl, deutsches Format: `1.234,89`)

Trennzeichen `;` oder `,` werden automatisch erkannt. Weitere Spalten werden ignoriert.
""")

# Show result from previous import (above uploader)
if "ist_import_result" in st.session_state:
    result = st.session_state.pop("ist_import_result")
    if result["type"] == "success":
        for w in result.get("warnings", []):
            st.warning(w)
        st.success(result["message"])
    elif result["type"] == "error":
        st.error(result["message"])

if "ist_upload_key" not in st.session_state:
    st.session_state["ist_upload_key"] = 0

uploaded = st.file_uploader(
    "Datei hochladen (CSV)",
    type=["csv"],
    key=f"ist_uploader_{st.session_state['ist_upload_key']}",
)

# ── Spalten-Erkennung & Vorschau ─────────────────────────────────────────────
if uploaded is not None:
    try:
        uploaded.seek(0)
        _df_prev = _read_csv_robust(uploaded)

        _col_map_prev = _detect_columns(_df_prev.columns.tolist())
        _ok = all(v is not None for v in _col_map_prev.values())

        with st.expander("🔍 Spalten-Erkennung & Vorschau", expanded=not _ok):
            c_d, c_f, c_u = st.columns(3)
            c_d.metric("Datum-Spalte",  _col_map_prev.get("datum")  or "❌ nicht erkannt")
            c_f.metric("Filial-Spalte", _col_map_prev.get("fil_nr") or "❌ nicht erkannt")
            c_u.metric("Umsatz-Spalte", _col_map_prev.get("umsatz") or "❌ nicht erkannt")
            if not _ok:
                st.error("Mindestens eine Pflicht-Spalte wurde nicht erkannt. "
                         "Spaltennamen prüfen (Datum, Filialnummer, Umsatz brutto).")

            # Vorschau-Tabelle mit formatiertem Datum und Umsatz
            _prev10 = _df_prev.head(10).copy()
            _dcol = _col_map_prev.get("datum")
            _ucol = _col_map_prev.get("umsatz")
            if _dcol and _dcol in _prev10.columns:
                _prev10[_dcol] = (
                    pd.to_datetime(_prev10[_dcol], dayfirst=True, errors="coerce")
                    .dt.strftime("%d.%m.%Y")
                    .fillna(_df_prev[_dcol].head(10))
                )
            if _ucol and _ucol in _prev10.columns:
                _prev10[_ucol] = _prev10[_ucol].apply(
                    lambda v: fmt_num_de(_parse_num(str(v))) if str(v).strip() else v
                )
            st.caption(f"Erste 10 Zeilen der Datei ({len(_df_prev):,} Zeilen gesamt):")
            st.dataframe(_prev10, use_container_width=True, hide_index=True)
    except Exception as _e:
        st.warning(f"Vorschau nicht möglich: {_e}")

# ── Import-Button ─────────────────────────────────────────────────────────────
existing_count = conn.execute("SELECT COUNT(*) FROM ist_umsatz").fetchone()[0]

if st.button("⬆️ Importieren", type="primary", disabled=uploaded is None):
    if existing_count > 0:
        st.session_state["_confirm_import"] = True
    else:
        st.session_state["_do_import"] = True

if st.session_state.get("_confirm_import"):
    st.warning(
        f"⚠️ Es sind bereits **{existing_count:,}** Datensätze vorhanden. "
        "Ein Neuimport **löscht alle bisherigen Daten** und importiert die neue Datei vollständig. "
        "Wirklich importieren?"
    )
    c1, c2, _ = st.columns([1.5, 1, 5])
    if c1.button("✅ Ja, importieren", type="primary", key="import_confirm_yes"):
        st.session_state["_confirm_import"] = False
        st.session_state["_do_import"] = True
        st.rerun()
    if c2.button("❌ Abbrechen", key="import_confirm_no"):
        st.session_state["_confirm_import"] = False
        st.rerun()

if st.session_state.get("_do_import"):
    st.session_state["_do_import"] = False
    try:
        # Validate: all fil_nrs in the file must exist in filialen
        uploaded.seek(0)
        _df_chk = _read_csv_robust(uploaded)

        _col_map = _detect_columns(_df_chk.columns.tolist())
        if _col_map.get("fil_nr"):
            _raw_fils = _df_chk[_col_map["fil_nr"]].astype(str).str.strip()
            _fils_in_file = {v for v in _raw_fils if v.lower() not in ("", "nan", "none", "nat")}
            _fils_in_db = {r[0] for r in conn.execute("SELECT fil_nr FROM filialen").fetchall()}
            _missing = sorted(_fils_in_file - _fils_in_db)
            if _missing:
                raise ValueError(
                    f"{len(_missing)} Filialnummer(n) nicht in den Stammdaten vorhanden: "
                    f"**{', '.join(_missing)}**. Bitte zuerst unter **Filialen** anlegen."
                )

        # Fortschrittsbalken mit Zeitschätzung
        _prog = st.progress(0, text="Starte Import…")
        _t_start = _time.monotonic()

        def _progress_cb(pct: float, text: str):
            elapsed = _time.monotonic() - _t_start
            if pct > 0.05 and pct < 1.0:
                remaining = elapsed / pct * (1.0 - pct)
                _m, _s = divmod(int(remaining), 60)
                hint = f" — noch ca. {_m}:{_s:02d} min" if _m else f" — noch ca. {_s} s"
            else:
                hint = ""
            _prog.progress(min(pct, 1.0), text=f"{text}{hint}")

        n, warnings = import_ist_umsatz(
            conn, uploaded, file_name=uploaded.name, progress_cb=_progress_cb
        )
        _prog.empty()

        det = detect_oeffnungstage(conn, force=False)
        msg = f"✅ {n:,} Datensätze importiert."
        if det["weekday_branches"]:
            msg += (f" Öffnungstage für {det['weekday_branches']} Filiale(n) automatisch erkannt "
                    f"(unter **Öffnungstage** prüfbar/änderbar).")
        st.session_state["ist_import_result"] = {
            "type": "success",
            "message": msg,
            "warnings": warnings,
        }
        st.session_state["ist_upload_key"] += 1
    except ValueError as e:
        st.session_state["ist_import_result"] = {
            "type": "error",
            "message": f"Import abgebrochen: {e}",
        }
    except Exception as e:
        st.session_state["ist_import_result"] = {
            "type": "error",
            "message": f"Import fehlgeschlagen: {e}",
        }
    st.rerun()

# ── Aktueller Datenbestand ────────────────────────────────────────────────────
st.divider()
st.subheader("Aktueller Datenbestand")

summary = pd.read_sql("""
    SELECT fil_nr,
           MIN(datum) AS von,
           MAX(datum) AS bis,
           COUNT(*)   AS tage,
           ROUND(SUM(umsatz), 2) AS gesamt_eur
    FROM ist_umsatz
    GROUP BY fil_nr
    ORDER BY fil_nr
""", conn)

if summary.empty:
    st.info("Noch keine IST-Daten vorhanden.")
else:
    def _fmt_int_de(v):
        try:
            return f"{int(v):,}".replace(",", ".")
        except Exception:
            return str(v)

    summary_fmt = summary.copy()
    summary_fmt["von"] = pd.to_datetime(summary_fmt["von"], errors="coerce").dt.strftime("%d.%m.%Y")
    summary_fmt["bis"] = pd.to_datetime(summary_fmt["bis"], errors="coerce").dt.strftime("%d.%m.%Y")
    summary_fmt["tage"]       = summary_fmt["tage"].apply(_fmt_int_de)
    summary_fmt["gesamt_eur"] = summary_fmt["gesamt_eur"].apply(fmt_num_de) + " €"

    summary_fmt = summary_fmt.rename(columns={
        "fil_nr":     "Filialnummer",
        "von":        "Von",
        "bis":        "Bis",
        "tage":       "Tage",
        "gesamt_eur": "Gesamtumsatz",
    })
    st.dataframe(summary_fmt, use_container_width=True, hide_index=True)

    gesamtumsatz_total = float(summary["gesamt_eur"].sum())
    col1, col2, col3 = st.columns(3)
    col1.metric("Filialen mit IST-Daten", len(summary))
    col2.metric("Datensätze gesamt", _fmt_int_de(summary["tage"].sum()))
    col3.metric("Gesamtumsatz importiert", fmt_num_de(gesamtumsatz_total) + " €")
