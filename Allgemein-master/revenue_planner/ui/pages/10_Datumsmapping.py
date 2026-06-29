"""Datumsmapping — zeigt und generiert das Mapping Budgettag → Basistag."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
import pandas as pd
from datetime import date as _date

require_db()
conn = get_conn()
st.title("Datumsmapping")
st.caption(f"Firma: **{get_gmbh()}**")

st.info(
    "Das Datumsmapping ordnet jedem Budgettag im Planjahr einen korrekten Basistag "
    "im Basiszeitraum zu — wochentagsbasiert, mit Feiertags- und Feriensonderbehandlung. "
    "Es wird automatisch neu generiert wenn Feiertage, Sondertage oder Ferien gespeichert werden."
)

planjahr = get_budgetjahr()

if st.button("🔄 Datumsmapping neu generieren", type="primary"):
    try:
        from planning.engine import PlanningEngine, PlanParams
        from planning.datumsmapping import generate_datumsmapping
        _today = _date.today()
        _stichtag = _date(planjahr, 1, 1) if planjahr <= _today.year else _today
        with st.spinner("Datumsmapping wird generiert…"):
            _engine = PlanningEngine(conn, PlanParams(planjahr=planjahr, stichtag=_stichtag))
            n = generate_datumsmapping(conn, planjahr, _engine)
            # Planungs-ist_vj mit neuem Mapping synchronisieren (falls vorhanden)
            _plan_exists = conn.execute(
                "SELECT COUNT(*) FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
                (planjahr,)
            ).fetchone()[0]
            if _plan_exists:
                _engine.fix_ist_vj(planjahr)
        st.toast(f"✅ Datumsmapping generiert: {n} Einträge")
        st.rerun()
    except Exception as e:
        st.error(f"Fehler: {e}")

MAPPING_ART_LABELS = {
    "feiertag":      "Feiertag",
    "feiertagstag":  "Feiertagstag",
    "ferien":        "Ferien",
    "sondertag":     "Sondertag",
    "iso_kw":        "KW-Vergleich",
}

TYP_LABELS = {
    "feiertag":    "Feiertag",
    "feiertagstag": "Feiertagstag (Vor-/Nachtag)",
    "sondertag":   "Sondertag",
    "ferien":      "Ferien",
    "normal":      "Normaltag",
}

st.subheader(f"Mapping für Budgetjahr {planjahr}")

# ── Daten laden ──────────────────────────────────────────────────────────────
df = pd.read_sql(
    "SELECT plan_datum, base_datum, plan_typ, bundesland, mapping_art, "
    "bezeichnung, base_bezeichnung "
    "FROM datumsmapping "
    "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ? "
    "ORDER BY bundesland, plan_datum",
    conn, params=(planjahr,)
)

# Ferien-Kalender für Budget- und Basiszeitraum laden (für separate Ferien-Spalten)
_fer_all = pd.read_sql(
    "SELECT bundesland, art, start, ende, jahr FROM ferien_kalender "
    "WHERE jahr IN (?, ?)",
    conn, params=(planjahr, planjahr - 1)
)


def _ferien_label_for(iso_str: str, bl: str, fer_df: pd.DataFrame) -> str:
    """Return ferien art if iso_str falls within a ferien period for this BL."""
    if fer_df.empty or not iso_str:
        return ""
    d = iso_str[:10]
    mask = (
        (fer_df["bundesland"] == bl) &
        (fer_df["start"] <= d) &
        (fer_df["ende"] >= d)
    )
    arts = fer_df.loc[mask, "art"].tolist()
    return ", ".join(arts) if arts else ""

if df.empty:
    st.warning(
        f"Kein Mapping für Budgetjahr **{planjahr}** vorhanden. "
        "Bitte oben auf **Datumsmapping neu generieren** klicken."
    )
    st.stop()

# ── Aufbereitungen ───────────────────────────────────────────────────────────
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

df["plan_datum_dt"]     = pd.to_datetime(df["plan_datum"])
df["plan_datum_de"]     = df["plan_datum_dt"].dt.strftime("%d.%m.%Y")
df["plan_wt"]           = df["plan_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["base_datum_dt"]     = pd.to_datetime(df["base_datum"])
df["base_datum_de"]     = df["base_datum_dt"].dt.strftime("%d.%m.%Y")
df["base_wt"]           = df["base_datum_dt"].dt.weekday.map(lambda x: WOCHENTAGE[x])
df["monat"]             = df["plan_datum_dt"].dt.month
df["mapping_art_label"] = df["mapping_art"].map(MAPPING_ART_LABELS).fillna(df["mapping_art"])

# Separate Ferien-Spalten (Budgetzeitraum / Basiszeitraum)
_fer_plan = _fer_all[_fer_all["jahr"] == planjahr].copy()
_fer_vj   = _fer_all[_fer_all["jahr"] == planjahr - 1].copy()
df["ferien_budget"] = df.apply(
    lambda r: _ferien_label_for(r["plan_datum"], r["bundesland"], _fer_plan), axis=1)
df["ferien_basis"]  = df.apply(
    lambda r: _ferien_label_for(r["base_datum"], r["bundesland"], _fer_vj), axis=1)

MONATE_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
             "Juli", "August", "September", "Oktober", "November", "Dezember"]

# ── Filter ───────────────────────────────────────────────────────────────────
fc1, fc2, fc3 = st.columns(3)
with fc1:
    monat_opts = sorted(df["monat"].unique().tolist())
    monat_sel = st.multiselect(
        "Monat",
        options=monat_opts,
        format_func=lambda m: MONATE_DE[m - 1],
        placeholder="Alle Monate",
        key="datumsmapping_monat",
    )
with fc2:
    bl_opts = sorted(df["bundesland"].unique().tolist())
    bl_sel = st.multiselect(
        "Bundesland",
        options=bl_opts,
        placeholder="Alle Bundesländer",
        key="datumsmapping_bl",
    )
with fc3:
    typ_raw_opts = sorted(df["plan_typ"].unique().tolist())
    typ_sel = st.multiselect(
        "Typ",
        options=typ_raw_opts,
        format_func=lambda t: TYP_LABELS.get(t, t),
        placeholder="Alle Typen",
        key="datumsmapping_typ",
    )

view = df.copy()
if monat_sel:
    view = view[view["monat"].isin(monat_sel)]
if bl_sel:
    view = view[view["bundesland"].isin(bl_sel)]
if typ_sel:
    view = view[view["plan_typ"].isin(typ_sel)]

# ── Anzeigetabelle ───────────────────────────────────────────────────────────
display = view[[
    "bundesland",
    "plan_datum_de", "plan_wt", "bezeichnung", "ferien_budget",
    "base_datum_de",  "base_wt", "base_bezeichnung", "ferien_basis",
    "mapping_art_label",
]].copy()
display.columns = [
    "Bundesland",
    "Budgettag", "Wochentag", "Beschreibung Budget", "Ferien Budget",
    "Basistag",  "Wochentag ", "Beschreibung Basistag", "Ferien Basis",
    "Mapping-Art",
]

st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    height=500,
    column_config={
        "Bundesland":          st.column_config.TextColumn("Bundesland", width="small"),
        "Budgettag":           st.column_config.TextColumn("Budgettag", width="small"),
        "Wochentag":           st.column_config.TextColumn("Wt.", width="small"),
        "Beschreibung Budget": st.column_config.TextColumn("Beschreibung Budget"),
        "Ferien Budget":       st.column_config.TextColumn("Ferien Budget", width="small"),
        "Basistag":            st.column_config.TextColumn("Basistag", width="small"),
        "Wochentag ":          st.column_config.TextColumn("Wt. ", width="small"),
        "Beschreibung Basistag": st.column_config.TextColumn("Beschreibung Basistag"),
        "Ferien Basis":        st.column_config.TextColumn("Ferien Basis", width="small"),
        "Mapping-Art":         st.column_config.TextColumn("Mapping-Art", width="small"),
    },
)
st.caption(
    f"{len(display):,} Zeilen angezeigt von {len(df):,} gesamt. &nbsp;"
    "**Mapping-Art:** "
    "*Feiertag* = gleichnamiger Feiertag im Basiszeitraum; "
    "*Ferien* = gleiche Ferienwoche im Basiszeitraum (wochentagsbasiert); "
    "*KW-Vergleich* = gleicher Wochentag in derselben Kalenderwoche des Basiszeitraums."
)

# Excel-Download
import io as _io
_xl_buf = _io.BytesIO()
with pd.ExcelWriter(_xl_buf, engine="openpyxl") as _writer:
    display.to_excel(_writer, index=False, sheet_name="Datumsmapping")
st.download_button(
    label="📥 Excel herunterladen",
    data=_xl_buf.getvalue(),
    file_name=f"Datumsmapping_{planjahr}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)
