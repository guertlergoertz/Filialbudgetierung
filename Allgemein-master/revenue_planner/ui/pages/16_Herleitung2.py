"""Herleitung der Budgetberechnung — LOGIK 2 (additive Effektzerlegung, planung2)."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
import pandas as pd
import io

require_db()
conn = get_conn()
gmbh = get_gmbh()
planjahr = get_budgetjahr()

st.title("Herleitung der Budgetberechnung — Logik 2")
st.caption(
    "Effektzerlegung der zweiten Berechnungslogik (Monatsumsatz-basiert). "
    "IST Basis = Tagesumsatz des via Datumsmapping bestimmten Basistags; die "
    "`+`-Spalten zeigen die additiven Effekte bis zum Tagesbudget."
)

def _render_legende():
    with st.expander("📖 Legende — Berechnungslogik 2", expanded=False):
        st.markdown("""
### Vorgehen Logik 2 (Monatsumsatz-basiert)

1. **Ausgangspunkt:** Monatsumsatz des Basiszeitraums (Vorjahr) je Monat.
2. **Wochentags-Konstellation:** Über das ganze Basisjahr wird je Wochentag
   sein Anteil am Normaltagsumsatz berechnet (ohne Sondertage/Feiertage/Ferien).
   Hat das Planjahr eine andere Mo…So-Konstellation, verschiebt sich der
   Monatsumsatz entsprechend der Wochentagsstärke (**+ Wochentag**).
3. **Preisanpassung:** prozentualer Aufschlag je Monat (**+ Preis**).
4. **Sondertage/Feiertage/Ferien:** wirken als Auf-/Abschlag und verschieben den
   Monatsumsatz nur dann zwischen Monaten, wenn der Tag im Budgetjahr in einen
   anderen Monat fällt als im Basisjahr (**+ Feiertag** / **+ Ferien**).
5. **Verteilung auf Tage (**+ Verteilung**):** der fertige Monatsumsatz wird über die Anteile
   der via Datumsmapping bestimmten Basistage am Basismonatsumsatz auf die einzelnen Tage
   verteilt. Enthält auch die Normalisierungskorrektur, damit Monatssummen exakt stimmen.
   **Neueröffnungen im Basiszeitraum:** Filialen, die erst während des Basiszeitraums
   eröffneten (und im letzten Monat des Basiszeitraums Umsätze hatten), werden für die
   Budgetierung der noch fehlenden Tage wie folgt hochgerechnet:

   1. **Auswertungszeitraum:** Die ersten 14 Tage nach Eröffnung werden ausgeschlossen.
      Verbleiben danach weniger als 3 Wochen Daten, wird die Filiale nicht hochgerechnet.
      Beispiel: Eröffnung 19.09. → Auswertungszeitraum 03.10.–31.12.
   2. **Referenzfilialen:** Für diesen Zeitraum werden die Umsätze aller Filialen je
      Wochentag summiert, die in **jedem einzelnen Monat** des Zeitraums vollständig
      geöffnet waren (Umsatz > 0 in jedem Monat).
   3. **Wochentagsanteil:** Je Wochentag wird der Anteil der neuen Filiale an der
      Gesamtsumme der Referenzfilialen berechnet.
   4. **Fehlende Budgettage:** Für alle Budgettage, deren Basisdatum vor dem
      Auswertungszeitraum liegt, ergibt sich das Budget aus:
      *Summe Budget Referenzfilialen an diesem Budgettag × Wochentagsanteil der neuen Filiale.*
      Beispiel: Wochentagsanteil 0,8 %, Ref.-Budget 500.000 € → Budget 4.000 €.
   5. **Feiertage:** Echte Feiertage (nicht Feiertagstage) werden mit dem
      **Sonntagsanteil** der neuen Filiale bewertet.
6. **Wochentagsvalidierung:** Nach der Berechnung wird geprüft, ob einzelne Tage
   (Summe **Budget** über alle Filialen) um mehr als ±10 % vom Wochentagsschnitt
   der umliegenden Monate abweichen. Ausgeschlossen werden dabei Feiertage,
   Feiertagstage, Sondertage und Ferien — sowohl im Planjahr als auch Tage, deren
   Vorjahres-Referenzdatum im Datumsmapping ein Sonder-/Feiertagstag war (z. B.
   ein Dienstag, dessen IST-Basis aus dem Dienstag nach Ostermontag stammt).
   Ausreißer werden auf den Wochentagsschnitt korrigiert, die Korrektur per
   Dreisatz proportional auf alle Filialen verteilt (**+ Validierung**).

```
Budget = IST Basis + Öffnung + Verteilung + Wochentag + Preis + Ferien + Feiertag + Validierung
```

Diese Zerlegung addiert sich durch einfache Summation auf jede Zeit- und
Aggregationsebene (Woche / Monat / Jahr, Filiale / Bundesland / Gesamt).
""")

# ── Daten laden (gecacht in session_state je GmbH + Planjahr) ──────────────────────────────
_cache_key = f"herleitung2_data_{gmbh}_{planjahr}"

_col_reload, _col_hint = st.columns([1, 6])
if _col_reload.button("🔄 Neu laden", key="herleitung2_reload"):
    st.session_state.pop(_cache_key, None)

if _cache_key not in st.session_state:
    _n_check = conn.execute(
        "SELECT COUNT(*) FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
        (planjahr,),
    ).fetchone()[0]
    if _n_check == 0:
        st.info(
            f"Noch keine Planungsdaten (Logik 2) für {planjahr} vorhanden. "
            "Bitte zuerst unter **Planung ausführen — Logik 2** eine Berechnung starten."
        )
        _render_legende()
        st.stop()

    with st.spinner("Planungsdaten werden geladen…"):
        _df_raw = pd.read_sql(
            "SELECT fil_nr, datum, bundesland, wochentag, ist_vj, "
            "eff_oeffnung, eff_wochentag, eff_preis, eff_ferien, eff_feiertag, "
            "eff_norm, eff_verteilung, eff_validierung, budget, "
            "tagestyp, feiertag_name, ferien_art "
            "FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
            conn, params=(planjahr,),
        )

        eff_cols = ["ist_vj", "eff_oeffnung", "eff_wochentag",
                    "eff_preis", "eff_ferien", "eff_feiertag", "eff_validierung", "budget"]
        for col in eff_cols + ["eff_norm", "eff_verteilung"]:
            if col not in _df_raw.columns:
                _df_raw[col] = 0.0
            _df_raw[col] = pd.to_numeric(_df_raw[col], errors="coerce").fillna(0.0)

        if "budget" not in _df_raw.columns or _df_raw["budget"].sum() == 0:
            for alt in ["gesamt_plan", "tagesumsatz_plan"]:
                if alt in _df_raw.columns:
                    _df_raw["budget"] = pd.to_numeric(_df_raw[alt], errors="coerce").fillna(0.0)
                    break

        _df_raw["fil_nr"] = _df_raw["fil_nr"].astype(str).str.strip()

        _df_raw["datum"] = pd.to_datetime(_df_raw["datum"])
        _df_raw["_iso"] = _df_raw["datum"].dt.strftime("%Y-%m-%d")

        for col in ["tagestyp", "feiertag_name", "ferien_art", "bundesland"]:
            if col not in _df_raw.columns:
                _df_raw[col] = ""
            _df_raw[col] = _df_raw[col].fillna("")

        if _df_raw["bundesland"].eq("").any():
            _bl_map = {str(r[0]): r[1] for r in conn.execute(
                "SELECT fil_nr, bundesland FROM filialen").fetchall()}
            _mask = _df_raw["bundesland"].eq("")
            _df_raw.loc[_mask, "bundesland"] = _df_raw.loc[_mask, "fil_nr"].map(_bl_map).fillna("?")

        _ist_rows = conn.execute(
            "SELECT fil_nr, datum, umsatz FROM ist_umsatz WHERE datum LIKE ?",
            (f"{planjahr}-%",),
        ).fetchall()
        _ist_lookup = {(str(r["fil_nr"]).strip(), r["datum"]): float(r["umsatz"])
                       for r in _ist_rows}
        _last_ist_date = max((r["datum"] for r in _ist_rows), default="")

        if _ist_lookup:
            _df_raw["_key"] = _df_raw["fil_nr"] + "||" + _df_raw["_iso"]
            _lookup_flat = {f"{k[0]}||{k[1]}": v for k, v in _ist_lookup.items()}
            _df_raw["ist_aktuell"] = _df_raw["_key"].map(_lookup_flat)
            _df_raw.drop(columns=["_key"], inplace=True)
        else:
            _df_raw["ist_aktuell"] = None

        _dm_rows = conn.execute(
            "SELECT plan_datum, base_datum, bundesland, plan_typ FROM datumsmapping "
            "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER)=?",
            (planjahr,),
        ).fetchall()
        _dm_lookup = {(r["plan_datum"], r["bundesland"]): r["base_datum"] for r in _dm_rows}
        _dm_typ_lookup = {(r["plan_datum"], r["bundesland"]): r["plan_typ"] for r in _dm_rows}

        _ferien_kal = conn.execute(
            "SELECT bundesland, art, start, ende FROM ferien_kalender "
            "WHERE jahr=? OR jahr=?", (planjahr, planjahr - 1)
        ).fetchall()

        import re as _re
        _gesperrte = set()
        for _r in conn.execute("SELECT fil_nr, bezeichnung, flag_gesperrt FROM filialen").fetchall():
            if _r["flag_gesperrt"] or _re.search(r'X{2,}', str(_r["bezeichnung"] or ""), _re.IGNORECASE):
                _gesperrte.add(str(_r["fil_nr"]).strip())
        if _gesperrte:
            _df_raw = _df_raw[~_df_raw["fil_nr"].isin(_gesperrte)]

        _has_data = _df_raw.groupby("fil_nr")[["budget", "ist_vj"]].sum().abs().sum(axis=1) > 0
        _df_raw = _df_raw[_df_raw["fil_nr"].isin(_has_data[_has_data].index)]

        _fil_eroeff = {
            str(r["fil_nr"]).strip(): r["eroeffnung"]
            for r in conn.execute("SELECT fil_nr, eroeffnung FROM filialen").fetchall()
        }

        st.session_state[_cache_key] = {
            "df": _df_raw,
            "last_ist_date": _last_ist_date,
            "dm_lookup": _dm_lookup,
            "dm_typ_lookup": _dm_typ_lookup,
            "ferien_kal": _ferien_kal,
            "fil_eroeff": _fil_eroeff,
        }
    st.rerun()

if _cache_key not in st.session_state:
    _render_legende()
    st.stop()

_cached = st.session_state[_cache_key]
df_all = _cached["df"].copy()
_last_ist_date = _cached["last_ist_date"]
_dm_lookup = _cached["dm_lookup"]
_dm_typ_lookup = _cached["dm_typ_lookup"]
_ferien_kal_rows = _cached["ferien_kal"]
_fil_eroeff = _cached.get("fil_eroeff", {})
_col_hint.caption(f"{len(df_all):,} Planzeilen geladen · {df_all['fil_nr'].nunique()} Filialen")

if df_all.empty:
    st.info("Keine berechneten Planungsdaten vorhanden.")
    _render_legende()
    st.stop()

eff_cols = ["ist_vj", "eff_oeffnung", "eff_verteilung", "eff_norm",
            "eff_wochentag", "eff_preis", "eff_ferien", "eff_feiertag", "eff_validierung", "budget"]

# ── Filter ─────────────────────────────────────────────────────────────────────────────────
from datetime import date as _date

_base_year = planjahr - 1
_base_start_cutoff = _date(_base_year, 1, 3)

def _classify_fil_typ(fil_nr: str) -> str:
    eroeff = _fil_eroeff.get(fil_nr)
    if not eroeff:
        return "Bestandsfiliale"
    try:
        return "Bestandsfiliale" if _date.fromisoformat(eroeff) <= _base_start_cutoff else "Neue Filiale"
    except Exception:
        return "Bestandsfiliale"

df_all["_fil_typ"] = df_all["fil_nr"].map(_classify_fil_typ)

cf1, cf2, cf3 = st.columns(3)
with cf1:
    fil_filter = st.multiselect(
        "Filtern auf Filiale(n) (leer = alle)",
        sorted(df_all["fil_nr"].unique()),
        placeholder="Filialen auswählen...",
        key="herleitung2_fil_filter",
    )
with cf2:
    bl_filter = st.multiselect(
        "Filtern auf Bundesland (leer = alle)",
        sorted(df_all["bundesland"].dropna().unique()),
        placeholder="Bundesland auswählen...",
        key="herleitung2_bl_filter",
    )
with cf3:
    fil_typ_filter = st.selectbox(
        "Filialen-Basiszeitraum",
        ["Alle", "Bestandsfilialen", "Neue Filialen"],
        index=0,
        key="herleitung2_fil_typ_filter",
        help=f"Bestandsfilialen: vor dem 04.01.{_base_year} eröffnet; Neue Filialen: danach",
    )

if fil_filter:
    df_all = df_all[df_all["fil_nr"].isin(fil_filter)]
if bl_filter:
    df_all = df_all[df_all["bundesland"].isin(bl_filter)]
if fil_typ_filter == "Bestandsfilialen":
    df_all = df_all[df_all["_fil_typ"] == "Bestandsfiliale"]
elif fil_typ_filter == "Neue Filialen":
    df_all = df_all[df_all["_fil_typ"] == "Neue Filiale"]

# ── Steuerung ─────────────────────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    zeit_ebene = st.selectbox(
        "Zeit-Ebene", ["Tag", "Woche", "Monat", "Jahr"], index=2,
        key="herleitung2_zeit",
    )
with c2:
    entity_ebene = st.selectbox(
        "Aggregations-Ebene", ["Filiale", "Bundesland", "Gesamt"], index=2,
        key="herleitung2_entity",
    )

MONATE_S = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

if zeit_ebene == "Monat":
    _available_months = sorted(df_all["datum"].dt.month.unique())
    _month_opts = [MONATE_S[m - 1] for m in _available_months]
    _sel_months = st.multiselect(
        "Monate", _month_opts, placeholder="Alle Monate",
        key="herleitung2_monat_filter",
    )
    if _sel_months:
        _sel_month_nums = [MONATE_S.index(m) + 1 for m in _sel_months]
        df_all = df_all[df_all["datum"].dt.month.isin(_sel_month_nums)]

elif zeit_ebene == "Woche":
    _iso_cal_f = df_all["datum"].dt.isocalendar()
    _kw_labels = sorted(
        ("KW " + _iso_cal_f["week"].astype(str).str.zfill(2) + "/" + _iso_cal_f["year"].astype(str)).unique()
    )
    _sel_kws = st.multiselect(
        "Kalenderwochen", _kw_labels, placeholder="Alle Wochen",
        key="herleitung2_kw_filter",
    )
    if _sel_kws:
        _sel_kw_set = set(_sel_kws)
        _kw_series = "KW " + _iso_cal_f["week"].astype(str).str.zfill(2) + "/" + _iso_cal_f["year"].astype(str)
        df_all = df_all[_kw_series.isin(_sel_kw_set)]

elif zeit_ebene == "Tag":
    _min_d = df_all["datum"].min().date()
    _max_d = df_all["datum"].max().date()
    _date_range = st.date_input(
        "Zeitraum",
        value=(_min_d, _max_d),
        min_value=_min_d,
        max_value=_max_d,
        format="DD.MM.YYYY",
        key="herleitung2_tag_filter",
    )
    if isinstance(_date_range, (list, tuple)) and len(_date_range) == 2:
        _d_from = pd.Timestamp(_date_range[0])
        _d_to   = pd.Timestamp(_date_range[1])
        df_all = df_all[(df_all["datum"] >= _d_from) & (df_all["datum"] <= _d_to)]

# ── Zeit-Gruppierung (vektorisiert) ────────────────────────────────────────────────────────────────────
if zeit_ebene == "Tag":
    df_all["Zeit"] = df_all["datum"].dt.strftime("%d.%m.%Y")
    df_all["_sort"] = df_all["datum"]
elif zeit_ebene == "Woche":
    _iso_cal = df_all["datum"].dt.isocalendar()
    df_all["Zeit"] = "KW " + _iso_cal["week"].astype(str).str.zfill(2) + "/" + _iso_cal["year"].astype(str)
    df_all["_sort"] = df_all["datum"] - pd.to_timedelta(df_all["datum"].dt.weekday, unit="D")
elif zeit_ebene == "Monat":
    df_all["Zeit"] = df_all["datum"].dt.month.map(lambda m: MONATE_S[m - 1]) + " " + df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.to_period("M").dt.to_timestamp()
else:
    df_all["Zeit"] = df_all["datum"].dt.year.astype(str)
    df_all["_sort"] = df_all["datum"].dt.year

group_keys = ["Zeit", "_sort"]
if entity_ebene == "Filiale":
    group_keys = ["fil_nr"] + group_keys
elif entity_ebene == "Bundesland":
    group_keys = ["bundesland"] + group_keys

# Ferien-Anreicherung vor Groupby (pro Rohzeile mit bekanntem Bundesland):
# Füllt ferien_art auch für Feiertage/Feiertagstage, die in einer Ferienperiode liegen.
# Ermöglicht anschließend korrekte Gesamt-Aggregation über alle Bundesländer.
_fk_index: dict[str, list] = {}
for _r in _ferien_kal_rows:
    _fk_index.setdefault(_r["bundesland"], []).append(_r)

def _get_ferien_for_date(iso: str, bl: str) -> str:
    try:
        d = pd.Timestamp(iso).date()
    except Exception:
        return ""
    for _r in _fk_index.get(bl, []):
        try:
            if pd.Timestamp(_r["start"]).date() <= d <= pd.Timestamp(_r["ende"]).date():
                return _r["art"]
        except Exception:
            pass
    return ""

def _enrich_ferien_row(row):
    existing = str(row.get("ferien_art") or "")
    if existing:
        return existing
    return _get_ferien_for_date(str(row.get("_iso") or ""), str(row.get("bundesland") or ""))

df_all["ferien_art"] = df_all.apply(_enrich_ferien_row, axis=1)

extra_agg: dict = {}
if zeit_ebene == "Tag":
    for c in ["wochentag", "tagestyp", "feiertag_name", "_iso"]:
        if c in df_all.columns:
            extra_agg[c] = "first"
    if "ferien_art" in df_all.columns:
        extra_agg["ferien_art"] = lambda x: ", ".join(sorted({v for v in x if v}))
    if entity_ebene == "Filiale" and "bundesland" in df_all.columns:
        extra_agg["bundesland"] = "first"

if _last_ist_date:
    df_all["_budget_for_ist"] = df_all["budget"].where(df_all["_iso"] <= _last_ist_date, other=None)
else:
    df_all["_budget_for_ist"] = None

agg = (df_all.groupby([k for k in group_keys if k != "_sort"], as_index=False)
       .agg({**{c: "sum" for c in eff_cols},
             "ist_aktuell": lambda x: x.sum() if x.notna().any() else None,
             "_budget_for_ist": lambda x: x.sum() if x.notna().any() else None,
             "_sort": "min",
             **extra_agg})
       .sort_values([k for k in (["_sort"] if entity_ebene == "Gesamt"
                                  else [group_keys[0], "_sort"])]))
agg = agg.reset_index(drop=True)

from planning.engine import _normalize_bl as _nbl_hrl

WT_MAP = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

if zeit_ebene == "Tag":
    if "wochentag" in agg.columns:
        agg["_wt_str"] = agg["wochentag"].apply(
            lambda w: WT_MAP[int(w)] if pd.notna(w) and str(w).strip() != "" else "")

    def _row_iso(row) -> str:
        iso = str(row.get("_iso", "") or "")
        if iso:
            return iso
        try:
            return pd.to_datetime(row["Zeit"], dayfirst=True).strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _row_bl(row) -> str:
        bl = str(row.get("bundesland", "") or "")
        return _nbl_hrl(bl) if bl else ""

    def _lookup_basisdatum(row) -> str:
        iso = _row_iso(row)
        bl = _row_bl(row)
        bd = _dm_lookup.get((iso, bl)) or _dm_lookup.get((iso, "alle")) or ""
        if not bd:
            return ""
        try:
            return pd.Timestamp(bd).strftime("%d.%m.%Y")
        except Exception:
            return bd

    def _eff_daytype(row) -> str:
        typ = str(row.get("tagestyp", "") or "")
        if typ in ("feiertag", "sondertag", "ferien", "geschlossen"):
            return typ
        iso, bl = _row_iso(row), _row_bl(row)
        dm_typ = _dm_typ_lookup.get((iso, bl)) or _dm_typ_lookup.get((iso, "alle")) or ""
        if dm_typ in ("feiertagstag", "feiertag", "sondertag"):
            return dm_typ
        return typ

    def _build_tagesinfo(tagestyp, feiertag_name):
        typ = tagestyp or ""
        name = feiertag_name or ""
        if typ in ("feiertag", "sondertag") and name:
            return name
        if typ == "geschlossen":
            return f"Geschlossen ({name})" if name else "Geschlossen"
        return ""

    def _ferien_art_for_date(iso_date: str, bl: str) -> str:
        try:
            d = pd.Timestamp(iso_date).date()
        except Exception:
            return ""
        for r in _ferien_kal_rows:
            if r["bundesland"] != bl:
                continue
            try:
                if pd.Timestamp(r["start"]).date() <= d <= pd.Timestamp(r["ende"]).date():
                    return r["art"]
            except Exception:
                pass
        return ""

    def _enrich_ferien_art(row):
        existing = str(row.get("ferien_art") or "")
        if existing:
            return existing
        daytype = str(row.get("_daytype") or "")
        if daytype in ("feiertag", "feiertagstag"):
            iso = str(row.get("_iso") or "")
            bl = _row_bl(row)
            return _ferien_art_for_date(iso, bl)
        return existing

    agg["_basisdatum"] = agg.apply(_lookup_basisdatum, axis=1)
    agg["_daytype"]    = agg.apply(_eff_daytype, axis=1)
    agg["_tagesinfo"]  = agg.apply(
        lambda r: _build_tagesinfo(r.get("tagestyp", ""), r.get("feiertag_name", "")), axis=1)
    agg["ferien_art"]  = agg.apply(_enrich_ferien_art, axis=1)

# ── IST-Abweichung ──────────────────────────────────────────────────────────────────────────────
agg["Abw. €"] = agg.apply(
    lambda x: round(float(x["ist_aktuell"]) - float(x["_budget_for_ist"]), 2)
    if pd.notna(x["ist_aktuell"]) and pd.notna(x.get("_budget_for_ist")) else None, axis=1
)
agg["Abw. %"] = agg.apply(
    lambda x: round(float(x["Abw. €"]) / float(x["_budget_for_ist"]) * 100, 0)
    if pd.notna(x.get("Abw. €")) and float(x.get("_budget_for_ist", 0) or 0) != 0 else None,
    axis=1,
)

# ── Spalten umbenennen & anordnen ───────────────────────────────────────────────────────────────────
rename = {
    "fil_nr": "Filiale", "bundesland": "Bundesland",
    "ist_vj": "IST Basis", "eff_oeffnung": "+ Öffnung",
    "eff_verteilung": "+ Verteilung",
    "eff_wochentag": "+ Wochentag", "eff_preis": "+ Preis", "eff_ferien": "+ Ferien",
    "eff_feiertag": "+ Feiertag", "eff_validierung": "+ Validierung",
    "budget": "= Budget",
    "ist_aktuell": "= IST",
}
if zeit_ebene == "Tag":
    rename["Zeit"] = "Datum"
    rename["_wt_str"] = "Wt."
    rename["_basisdatum"] = "Basisdatum"
    rename["_tagesinfo"] = "Tagesinfo"
    rename["ferien_art"] = "Ferien"

# eff_norm (hidden per rule) wird in eff_verteilung eingerechnet, damit die angezeigte Summe = Budget
agg["eff_verteilung"] = agg["eff_verteilung"].fillna(0) + agg["eff_norm"].fillna(0)

drop_cols = ["_sort", "eff_norm", "_budget_for_ist", "_iso", "_daytype", "_fil_typ"] + [
    c for c in ["wochentag", "tagestyp", "feiertag_name"] if c in agg.columns and zeit_ebene == "Tag"
]
if zeit_ebene != "Tag":
    drop_cols += [c for c in ["ferien_art", "_basisdatum"] if c in agg.columns]

disp = agg.drop(columns=[c for c in drop_cols if c in agg.columns]).rename(columns=rename)

if zeit_ebene == "Tag":
    lead = [c for c in ["Filiale", "Datum", "Basisdatum", "Wt.", "Tagesinfo", "Ferien"] if c in disp.columns]
else:
    lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]

ordered = lead + ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
                  "+ Ferien", "+ Feiertag", "+ Validierung", "= Budget",
                  "= IST", "Abw. €", "Abw. %"]
disp = disp[[c for c in ordered if c in disp.columns]]

# ── Kennzahlen ──────────────────────────────────────────────────────────────────────────────
tot_vj = agg["ist_vj"].sum()
tot_bud = agg["budget"].sum()
m1, m2, m3, m4 = st.columns(4)

def _de(val) -> str:
    try:
        if pd.isna(val):
            return "–"
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "–"

m1.metric("IST Basis", f"{_de(tot_vj)} €")
m2.metric("Budget", f"{_de(tot_bud)} €")
m3.metric("Δ €", f"{'+'  if tot_bud >= tot_vj else ''}{_de(tot_bud - tot_vj)} €")
m4.metric("Δ %", f"{(tot_bud - tot_vj) / tot_vj * 100:+.1f} %" if tot_vj else "–")

st.caption(
    "Lesart: **IST Basis** = tatsächlicher IST-Umsatz des Referenztags aus dem Basiszeitraum. "
    "Jede `+`-Spalte zeigt den additiven Effekt in €. Summe ergibt **= Budget**. "
    "**+ Validierung** = Korrektur durch die Wochentagsvalidierung (0 = kein Ausreißer)."
)
st.divider()

# ── Tabelle ───────────────────────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Öffnung", "+ Verteilung", "+ Wochentag", "+ Preis",
            "+ Ferien", "+ Feiertag", "+ Validierung", "= Budget", "= IST", "Abw. €"]

def _fmt_de(val):
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        f = float(val)
        if f == 0.0:
            return ""
        return f"{f:,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""

def _fmt_pct(val):
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return f"{float(val):+.0f} %"
    except (TypeError, ValueError):
        return ""

disp_fmt = disp.copy()
for c in num_cols:
    if c in disp_fmt.columns:
        disp_fmt[c] = disp_fmt[c].apply(_fmt_de)
if "Abw. %" in disp_fmt.columns:
    disp_fmt["Abw. %"] = disp_fmt["Abw. %"].apply(_fmt_pct)

col_cfg = {
    "Tagesinfo":      st.column_config.TextColumn("Tagesinfo",
        help="Feiertag, Sondertag oder Schließtag", width="medium"),
    "Ferien":         st.column_config.TextColumn("Ferien",
        help="Ferienname wenn der Tag in einer Ferienperiode liegt", width="medium"),
    "Basisdatum":     st.column_config.TextColumn("Basisdatum",
        help="Referenztag aus dem Basiszeitraum, dessen IST-Umsatz als Grundlage dient"),
    "IST Basis":      st.column_config.TextColumn("IST Basis",
        help="Tagesumsatz des Basiszeitraum-Referenztags (via Datumsmapping)"),
    "+ Öffnung":      st.column_config.TextColumn("+ Öffnung",
        help="Effekt geschlossener Tage (geschlossen → −IST Basis)"),
    "+ Verteilung":   st.column_config.TextColumn("+ Verteilung",
        help="Tagesverteilung: Anteil des Tages am Monatsumsatz (inkl. Normalisierungskorrektur)"),
    "+ Wochentag":    st.column_config.TextColumn("+ Wochentag",
        help="Wochentags-Konstellationseffekt: andere Mo…So-Verteilung im Planjahr"),
    "+ Preis":        st.column_config.TextColumn("+ Preis",
        help="Preis-/Wachstumseffekt aus den Preisanpassungsparametern (% je Monat)"),
    "+ Ferien":       st.column_config.TextColumn("+ Ferien",
        help="Ferien-Monatsverschiebung (Auf-/Abschlag wandert in einen anderen Monat)"),
    "+ Feiertag":     st.column_config.TextColumn("+ Feiertag",
        help="Feiertag-/Sondertag-Monatsverschiebung (z. B. Muttertag Mai → April)"),
    "+ Validierung":  st.column_config.TextColumn("+ Validierung",
        help="Wochentagsvalidierung: Korrektur auf IST-Basis-Wochentagsschnitt (0 = kein Ausreißer)"),
    "= Budget":       st.column_config.TextColumn("= Budget",
        help="Tagesbudget = IST Basis + alle Effekte inkl. Validierung"),
    "= IST":          st.column_config.TextColumn("= IST",
        help="Tatsächlich erreichter IST-Umsatz im Budgetjahr (soweit importiert)"),
    "Abw. €":        st.column_config.TextColumn("Abw. €",
        help="IST − Budget (positiv = über Budget, negativ = unter Budget)"),
    "Abw. %":         st.column_config.TextColumn("Abw. %",
        help="Abweichung IST vs. Budget in Prozent"),
}

st.dataframe(
    disp_fmt,
    use_container_width=True,
    hide_index=True,
    height=560,
    column_config={k: v for k, v in col_cfg.items() if k in disp_fmt.columns},
)

# ── Excel-Export — Button unterhalb der Tabelle ──────────────────────────────────────────────────
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as writer:
    disp.to_excel(writer, index=False, sheet_name="Herleitung_Logik2")
    from openpyxl.styles import Font
    ws = writer.sheets["Herleitung_Logik2"]
    for cell in ws[1]:
        cell.font = Font(bold=True)
st.download_button(
    "📥 Excel herunterladen",
    data=buf.getvalue(),
    file_name=f"Herleitung_Logik2_{planjahr}_{zeit_ebene}_{entity_ebene}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    key="herleitung2_dl_active",
)

_render_legende()
