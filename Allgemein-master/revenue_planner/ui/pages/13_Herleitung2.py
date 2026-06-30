"""Herleitung der Budgetberechnung — Die Planung (additive Effektzerlegung, planung2)."""
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

st.title("Herleitung der Budgetberechnung")
st.caption(
    "Effektzerlegung der Planungslogik (Monatsumsatz-basiert). "
    "IST Basis = skalierter Tagesanteil am Kalender-Monatsumsatz des Vorjahres; die "
    "`+`-Spalten zeigen die additiven Effekte bis zum Tagesbudget."
)

def _render_legende():
    with st.expander("📖 Legende — Berechnungslogik", expanded=False):
        st.markdown("""
### Vorgehen (Monatsumsatz-basiert, Dreisatz-Verteilung)

1. **IST Basis:** Anteil des Tages × Kalender-Monatsumsatz Vorjahr.
   Der Anteil ergibt sich aus dem Rohwert des Basistags geteilt durch die Summe aller
   Rohwerte offener Tage im Budgetmonat (Dreisatz-Gewichtung).
   Beispiel: Monatsumsatz VJ = 200.000 €, Tagesanteil = 0,5 % → IST Basis = 1.000 €.
2. **+ Wochentag:** Verschiebt den Monatsumsatz entsprechend der Wochentags-Konstellation.
   Hat das Planjahr eine andere Mo…So-Verteilung als das Basisjahr, ändert sich der
   erreichbare Monatsumsatz anteilig.
3. **+ Ferien:** Ferientage liefern einen Auf-/Abschlag gegenüber dem Normaltagsschnitt
   (gleicher Wochentag, umliegende Monate). Die Verschiebung wirkt nur, wenn der Tag im
   Budgetjahr in einen anderen Monat fällt als im Basisjahr.
4. **+ Feiertag:** Feiertagstage/Sondertage: Aufschlag vs. Normaltagsschnitt gleicher
   Wochentag im selben Basismonat. Echte Feiertage: Aufschlag vs. Sonntagsschnitt
   desselben Basismonats. Verschiebung nur bei Monatswechsel.
5. **=gew. Monatsumsatz:** Anteil × (M₀ + Δ Wochentag + Δ Ferien + Δ Feiertag).
   Dies ist der gewünschte Tagesumsatz vor Preis und Sondereffekten.
6. **+ Öffnung:** Tage, die im Planjahr neu geöffnet oder geschlossen sind, erhalten
   den Auf-/Abschlag zum gewünschten Monatsumsatz.
7. **+ Hochrechnung:** Filialen mit Umsatzlücken im Basiszeitraum (z. B. Neueröffnungen oder
   Bestandsfilialen mit temporärer Schließung / neu geöffnetem Wochentag) werden über
   Bestandsfilialen hochgerechnet. Voraussetzung: ≥ 21 Tage mit Umsatz ≥ 100 €.
   **Sonderfall ≥ 6 Hochrechnungstage pro Monat:** Wenn in einem Monat mehr als 5 offene Tage
   ohne Basis-IST vorliegen, werden alle Tage des Monats vollständig über Hochrechnung geplant.
   Alle Spalten von IST Basis bis + Preis bleiben leer — der monatsumsatz-basierte Dreisatz
   liefert bei so vielen Basiswert-Lücken kein verlässliches Ergebnis.
8. **+ Preis:** prozentualer Wachstumsaufschlag je Monat.
9. **= Budget I:** =gew. Monatsumsatz + Öffnung + Hochrechnung + Preis.
10. **+ Validierung:** Korrektur durch die Wochentagsvalidierung (±10 %-Schwelle über alle
    Filialen). Ausreißer werden auf den Wochentagsschnitt korrigiert, proportional verteilt.
11. **= Budget II:** Budget I + Validierung → endgültiges Tagesbudget.

```
= Budget I  = IST Basis + Wochentag + Ferien + Feiertag + Öffnung + Hochrechnung + Preis
= Budget II = Budget I + Validierung
```
*(eff_norm ist in der DB vorhanden, wird aber immer als 0 geschrieben und hier nicht angezeigt)*

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
            f"Noch keine Planungsdaten für {planjahr} vorhanden. "
            "Bitte zuerst unter **Planung ausführen** eine Berechnung starten."
        )
        _render_legende()
        st.stop()

    with st.spinner("Planungsdaten werden geladen…"):
        _df_raw = pd.read_sql(
            "SELECT fil_nr, datum, bundesland, wochentag, ist_vj, "
            "eff_oeffnung, eff_hochrechnung, eff_wochentag, eff_preis, eff_ferien, eff_feiertag, "
            "eff_validierung, eff_fil_eroeffnung, budget_i, gewuenschter_monatsumsatz, budget, "
            "tagestyp, feiertag_name, ferien_art "
            "FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
            conn, params=(planjahr,),
        )

        eff_cols = ["ist_vj", "eff_wochentag", "eff_ferien", "eff_feiertag",
                    "gewuenschter_monatsumsatz", "eff_oeffnung", "eff_hochrechnung",
                    "eff_preis", "budget_i", "eff_validierung", "eff_fil_eroeffnung", "budget"]
        for col in eff_cols:
            if col not in _df_raw.columns:
                _df_raw[col] = 0.0
            _df_raw[col] = pd.to_numeric(_df_raw[col], errors="coerce").fillna(0.0)

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

        _check_cols = [c for c in ["budget_i", "ist_vj", "eff_fil_eroeffnung", "budget"]
                       if c in _df_raw.columns]
        _has_data = _df_raw.groupby("fil_nr")[_check_cols].sum().abs().sum(axis=1) > 0
        _df_raw = _df_raw[_df_raw["fil_nr"].isin(_has_data[_has_data].index)]

        _fil_stamm = {
            str(r["fil_nr"]).strip(): {
                "eroeffnung": r["eroeffnung"],
                "eroeffnung_ende": r["eroeffnung_ende"],
                "umbau_von": r["umbau_von"],
                "umbau_bis": r["umbau_bis"],
            }
            for r in conn.execute(
                "SELECT fil_nr, eroeffnung, eroeffnung_ende, umbau_von, umbau_bis FROM filialen"
            ).fetchall()
        }

        st.session_state[_cache_key] = {
            "df": _df_raw,
            "last_ist_date": _last_ist_date,
            "dm_lookup": _dm_lookup,
            "dm_typ_lookup": _dm_typ_lookup,
            "ferien_kal": _ferien_kal,
            "fil_stamm": _fil_stamm,
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
_fil_stamm = _cached.get("fil_stamm", {})
_fil_eroeff = {k: v["eroeffnung"] for k, v in _fil_stamm.items()}
_col_hint.caption(f"{len(df_all):,} Planzeilen geladen · {df_all['fil_nr'].nunique()} Filialen")

if df_all.empty:
    st.info("Keine berechneten Planungsdaten vorhanden.")
    _render_legende()
    st.stop()

eff_cols = ["ist_vj", "eff_wochentag", "eff_ferien", "eff_feiertag",
            "gewuenschter_monatsumsatz", "eff_oeffnung", "eff_hochrechnung",
            "eff_preis", "budget_i", "eff_validierung", "eff_fil_eroeffnung", "budget"]

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

    def _parse_stamm_date(s):
        if not s:
            return None
        try:
            return pd.Timestamp(s)
        except Exception:
            return None

    def _build_tagesinfo(row) -> str:
        fil = str(row.get("fil_nr") or "")
        d = row.get("_iso")
        try:
            d_ts = pd.Timestamp(d)
        except Exception:
            d_ts = None

        if d_ts is not None and fil:
            stamm = _fil_stamm.get(fil, {})
            eroeffnung = _parse_stamm_date(stamm.get("eroeffnung"))
            ende       = _parse_stamm_date(stamm.get("eroeffnung_ende"))
            umbau_von  = _parse_stamm_date(stamm.get("umbau_von"))
            umbau_bis  = _parse_stamm_date(stamm.get("umbau_bis"))

            if ende is not None:
                if d_ts.date() == ende.date():
                    return "Filialschließung"
                if d_ts.date() > ende.date():
                    return "geschlossen"

            if umbau_von is not None and umbau_bis is not None:
                if umbau_von.date() <= d_ts.date() <= umbau_bis.date():
                    return "Umbau"

            if eroeffnung is not None:
                if d_ts.date() == eroeffnung.date():
                    return "Filialeröffnung"
                if d_ts.date() < eroeffnung.date():
                    return "geschlossen"

        typ = str(row.get("tagestyp") or "")
        name = str(row.get("feiertag_name") or "")
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
    agg["_tagesinfo"]  = agg.apply(_build_tagesinfo, axis=1)
    agg["ferien_art"]  = agg.apply(_enrich_ferien_art, axis=1)

# ── Summenzeilen ────────────────────────────────────────────────────────────────────────────────
def _make_sum_row(grp: pd.DataFrame, entity_col: str | None, entity_val: str,
                  zeit_val: str = "") -> dict:
    row: dict = {}
    if entity_col is not None:
        row[entity_col] = entity_val
    if "Zeit" in grp.columns:
        row["Zeit"] = zeit_val
    for _c in eff_cols:
        if _c in grp.columns:
            row[_c] = float(grp[_c].sum())
    for _c in ("ist_aktuell", "_budget_for_ist"):
        if _c in grp.columns:
            _valid = pd.to_numeric(grp[_c], errors="coerce").dropna()
            row[_c] = float(_valid.sum()) if len(_valid) > 0 else None
    if "_sort" in grp.columns:
        row["_sort"] = grp["_sort"].max()
    return row

if zeit_ebene == "Jahr":
    if entity_ebene == "Filiale" and "fil_nr" in agg.columns:
        _sum_row = _make_sum_row(agg, "fil_nr", "∑ Gesamt", "")
        agg = pd.concat([agg, pd.DataFrame([_sum_row])], ignore_index=True)
    elif entity_ebene == "Bundesland" and "bundesland" in agg.columns:
        _sum_row = _make_sum_row(agg, "bundesland", "∑ Gesamt", "")
        agg = pd.concat([agg, pd.DataFrame([_sum_row])], ignore_index=True)
    # Gesamt + Jahr = eine Zeile, keine Summe nötig

elif entity_ebene == "Filiale" and "fil_nr" in agg.columns:
    _pieces = []
    for _fv, _grp in agg.groupby("fil_nr", sort=True):
        _pieces.append(_grp)
        _pieces.append(pd.DataFrame([_make_sum_row(_grp, "fil_nr", f"∑ {_fv}")]))
    agg = pd.concat(_pieces, ignore_index=True) if _pieces else agg

elif entity_ebene == "Bundesland" and "bundesland" in agg.columns:
    _pieces = []
    for _bv, _grp in agg.groupby("bundesland", sort=True):
        _pieces.append(_grp)
        _pieces.append(pd.DataFrame([_make_sum_row(_grp, "bundesland", f"∑ {_bv}")]))
    agg = pd.concat(_pieces, ignore_index=True) if _pieces else agg

else:  # Gesamt, nicht Jahr
    _sum_row = _make_sum_row(agg, None, "", "∑ Gesamt")
    agg = pd.concat([agg, pd.DataFrame([_sum_row])], ignore_index=True)

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
    "ist_vj": "IST Basis",
    "eff_wochentag": "+ Wochentag", "eff_ferien": "+ Ferien",
    "eff_feiertag": "+ Feiertag",
    "gewuenschter_monatsumsatz": "=gew. Monatsumsatz",
    "eff_oeffnung": "+ Öffnung",
    "eff_hochrechnung": "+ Hochrechnung",
    "eff_preis": "+ Preis",
    "budget_i": "= Budget I",
    "eff_validierung": "+ Validierung",
    "eff_fil_eroeffnung": "+ Fil.Eröffnung",
    "budget": "= Budget II",
    "ist_aktuell": "= IST",
}
if zeit_ebene == "Tag":
    rename["Zeit"] = "Datum"
    rename["_wt_str"] = "Wt."
    rename["_basisdatum"] = "Basisdatum"
    rename["_tagesinfo"] = "Tagesinfo"
    rename["ferien_art"] = "Ferien"

drop_cols = ["_sort", "_budget_for_ist", "_iso", "_daytype", "_fil_typ"] + [
    c for c in ["wochentag", "tagestyp", "feiertag_name"] if c in agg.columns and zeit_ebene == "Tag"
]
if zeit_ebene != "Tag":
    drop_cols += [c for c in ["ferien_art", "_basisdatum"] if c in agg.columns]

disp = agg.drop(columns=[c for c in drop_cols if c in agg.columns]).rename(columns=rename)

if zeit_ebene == "Tag":
    lead = [c for c in ["Filiale", "Datum", "Basisdatum", "Wt.", "Tagesinfo", "Ferien"] if c in disp.columns]
else:
    lead = [c for c in ["Filiale", "Bundesland", "Zeit"] if c in disp.columns]

ordered = lead + ["IST Basis", "+ Wochentag", "+ Ferien", "+ Feiertag",
                  "=gew. Monatsumsatz", "+ Öffnung", "+ Hochrechnung", "+ Preis",
                  "= Budget I", "+ Validierung", "+ Fil.Eröffnung", "= Budget II",
                  "= IST", "Abw. €", "Abw. %"]
disp = disp[[c for c in ordered if c in disp.columns]]

# ── Tabelle ───────────────────────────────────────────────────────────────────────────────────
num_cols = ["IST Basis", "+ Wochentag", "+ Ferien", "+ Feiertag",
            "=gew. Monatsumsatz", "+ Öffnung", "+ Hochrechnung", "+ Preis",
            "= Budget I", "+ Validierung", "+ Fil.Eröffnung", "= Budget II", "= IST", "Abw. €"]

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
    "Tagesinfo":          st.column_config.TextColumn("Tagesinfo",
        help="Feiertag, Sondertag oder Schließtag", width="medium"),
    "Ferien":              st.column_config.TextColumn("Ferien",
        help="Ferienname wenn der Tag in einer Ferienperiode liegt", width="medium"),
    "Basisdatum":          st.column_config.TextColumn("Basisdatum",
        help="Referenztag aus dem Basiszeitraum (via Datumsmapping)"),
    "IST Basis":           st.column_config.TextColumn("IST Basis",
        help="Anteil des Tages × Kalender-Monatsumsatz Vorjahr (skalierter IST-Basiswert)"),
    "+ Wochentag":         st.column_config.TextColumn("+ Wochentag",
        help="Wochentags-Konstellationseffekt: andere Mo…So-Verteilung im Planjahr"),
    "+ Ferien":            st.column_config.TextColumn("+ Ferien",
        help="Ferien-Monatsverschiebung (Auf-/Abschlag vs. Normaltag wandert ggf. in anderen Monat)"),
    "+ Feiertag":          st.column_config.TextColumn("+ Feiertag",
        help="Feiertag-/Sondertag-Monatsverschiebung (Vergleich: selber Monat, gleicher WT bzw. Sonntag)"),
    "=gew. Monatsumsatz":  st.column_config.TextColumn("=gew. Monatsumsatz",
        help="Anteil × (M₀ + Δ Wochentag + Δ Ferien + Δ Feiertag) — gewünschter Tagesumsatz vor Preis"),
    "+ Öffnung":           st.column_config.TextColumn("+ Öffnung",
        help="Effekt von Tagen, die im Planjahr (neu) geöffnet oder geschlossen sind"),
    "+ Hochrechnung":      st.column_config.TextColumn("+ Hochrechnung",
        help="Imputation für Tage ohne Basis-IST (Neueröffnungen): Wochentagsanteil × Bestandsfilialen-Summe"),
    "+ Preis":             st.column_config.TextColumn("+ Preis",
        help="Preis-/Wachstumseffekt aus den Preisanpassungsparametern (% je Monat)"),
    "= Budget I":          st.column_config.TextColumn("= Budget I",
        help="Budget I = =gew. Monatsumsatz + Öffnung + Hochrechnung + Preis (vor Validierung)"),
    "+ Validierung":       st.column_config.TextColumn("+ Validierung",
        help="Wochentagsvalidierung: Korrektur auf Wochentagsschnitt (±10 %-Schwelle, 0 = kein Ausreißer)"),
    "+ Fil.Eröffnung":     st.column_config.TextColumn("+ Fil.Eröffnung",
        help="Geplanter Tagesumsatz für neue Filialen ohne IST-Basis (Planumsatz anteilig auf Öffnungstage)"),
    "= Budget II":         st.column_config.TextColumn("= Budget II",
        help="Tagesbudget = Budget I + Validierung + Fil.Eröffnung (endgültiger Planwert)"),
    "= IST":               st.column_config.TextColumn("= IST",
        help="Tatsächlich erreichter IST-Umsatz im Budgetjahr (soweit importiert)"),
    "Abw. €":        st.column_config.TextColumn("Abw. €",
        help="IST − Budget II (positiv = über Budget, negativ = unter Budget)"),
    "Abw. %":              st.column_config.TextColumn("Abw. %",
        help="Abweichung IST vs. Budget II in Prozent"),
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
    disp.to_excel(writer, index=False, sheet_name="Herleitung")
    from openpyxl.styles import Font
    ws = writer.sheets["Herleitung"]
    for cell in ws[1]:
        cell.font = Font(bold=True)
st.download_button(
    "📥 Excel herunterladen",
    data=buf.getvalue(),
    file_name=f"Herleitung_{planjahr}_{zeit_ebene}_{entity_ebene}_{gmbh.replace(' ', '_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    key="herleitung2_dl_active",
)

_render_legende()
