"""Feiertage und Ferien laden — für Basiszeitraum + Budgetjahr."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from datetime import date, timedelta
import pandas as pd

require_db()
conn = get_conn()
planjahr = get_budgetjahr()
vj = planjahr - 1

# One-time migration: rename old ferien art labels in ferien_kalender + ferien tables
_FERIEN_RENAME_MIGRATION = {
    "Oster-/Frühjahrferien": "Osterferien",
    "Oster-/Frühjahrsferien": "Osterferien",
    "Frühjahrsferien": "Osterferien",
    "Frühjahrsferien (Osterferien)": "Osterferien",
    "Himmelfahrts-/Pfingstferien": "Pfingstferien",
}
for _old, _new in _FERIEN_RENAME_MIGRATION.items():
    conn.execute("UPDATE ferien_kalender SET art=? WHERE art=?", (_new, _old))
    conn.execute("UPDATE ferien SET art=? WHERE art=?", (_new, _old))
conn.commit()

st.title("Feiertage und Ferien laden")
st.caption(f"Firma: **{get_gmbh()}** · Budgetjahr: **{planjahr}** · Basiszeitraum (Vorjahr): **{vj}**")

BUNDESLAENDER = ["BB", "BE", "BW", "BY", "HB", "HE", "HH", "MV",
                 "NI", "NW", "RP", "SH", "SL", "SN", "ST", "TH"]

# Rename overlong ferien art labels from the holidays library to short display names
FERIEN_ART_RENAME: dict[str, str] = {
    "Oster-/Frühjahrferien": "Osterferien",
    "Oster-/Frühjahrsferien": "Osterferien",
    "Frühjahrsferien": "Osterferien",
    "Frühjahrsferien (Osterferien)": "Osterferien",
    "Himmelfahrts-/Pfingstferien": "Pfingstferien",
}

BL_ABBR_TO_NAME = {
    "BB": "Brandenburg", "BE": "Berlin", "BW": "Baden-Württemberg",
    "BY": "Bayern", "HB": "Bremen", "HE": "Hessen", "HH": "Hamburg",
    "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen", "NW": "Nordrhein-Westfalen",
    "RP": "Rheinland-Pfalz", "SH": "Schleswig-Holstein", "SL": "Saarland",
    "SN": "Sachsen", "ST": "Sachsen-Anhalt", "TH": "Thüringen",
}
BL_NAME_LIST = list(BL_ABBR_TO_NAME.values())

WOCHENTAG_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _wt_name(d) -> str:
    if d is None:
        return ""
    try:
        if pd.isna(d):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return WOCHENTAG_KURZ[pd.Timestamp(d).weekday()]
    except Exception:
        return ""


def _bl_to_name(bl: str) -> str:
    if not bl or str(bl).strip().lower() == "alle":
        return "Alle"
    return BL_ABBR_TO_NAME.get(str(bl).strip(), str(bl).strip())


def _bl_to_abbr(name: str) -> str:
    n = str(name or "").strip()
    if not n or n.lower() == "alle":
        return "alle"
    for abbr, full in BL_ABBR_TO_NAME.items():
        if full == n:
            return abbr
    return n


def _iso(v):
    """Convert editor cell value (Timestamp/date/str) to YYYY-MM-DD string or None."""
    if v is None:
        return None
    ts = pd.to_datetime(v, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _norm_for_compare(df: pd.DataFrame, date_cols: list) -> pd.DataFrame:
    """Normalize date columns to YYYY-MM-DD strings for stable DataFrame comparison."""
    out = df.copy()
    for c in date_cols:
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.fillna("").astype(str)

RAMADAN = {
    2023: ("2023-03-23", "2023-04-21"), 2024: ("2024-03-11", "2024-04-09"),
    2025: ("2025-03-01", "2025-03-30"), 2026: ("2026-02-18", "2026-03-19"),
    2027: ("2027-02-07", "2027-03-08"), 2028: ("2028-01-27", "2028-02-25"),
    2029: ("2029-01-15", "2029-02-13"), 2030: ("2030-01-04", "2030-02-02"),
    2031: ("2030-12-25", "2031-01-23"), 2032: ("2031-12-14", "2032-01-12"),
    2033: ("2032-12-02", "2033-01-01"), 2034: ("2033-11-21", "2033-12-20"),
    2035: ("2034-11-11", "2034-12-10"), 2036: ("2035-11-01", "2035-11-30"),
}


def _easter(year: int) -> date:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _muttertag(year: int) -> date:
    d = date(year, 5, 1)
    sundays = [d + timedelta(days=i) for i in range(31)
               if (d + timedelta(days=i)).month == 5
               and (d + timedelta(days=i)).weekday() == 6]
    return sundays[1]


def _load_public_holidays_year(plan_yr: int, bl_filter: list) -> list:
    import holidays as hol_lib
    base_yr = plan_yr - 1
    plan_by_state, vj_by_state = {}, {}
    for bl in bl_filter:
        plan_by_state[bl] = {d2.isoformat(): n for d2, n in
                             hol_lib.country_holidays("DE", subdiv=bl, years=plan_yr).items()}
        vj_by_state[bl]   = {d2.isoformat(): n for d2, n in
                             hol_lib.country_holidays("DE", subdiv=bl, years=base_yr).items()}

    date_info: dict = {}
    for bl, hdict in plan_by_state.items():
        for iso, name in hdict.items():
            date_info.setdefault(iso, {"name": name, "states": set()})["states"].add(bl)

    vj_lookup: dict = {}
    for bl, hdict in vj_by_state.items():
        for iso, name in hdict.items():
            vj_lookup.setdefault(name, {})[bl] = iso

    result = []
    for iso, info in sorted(date_info.items()):
        name, states = info["name"], info["states"]
        if len(states) == len(bl_filter):
            vj_date = next((vj_lookup.get(name, {}).get(bl) for bl in bl_filter
                            if vj_lookup.get(name, {}).get(bl)), None)
            result.append({"datum_plan": iso, "datum_vj": vj_date,
                           "name": name, "bundesland": "alle", "art": "feiertag"})
        else:
            for bl in sorted(states):
                vj_date = vj_lookup.get(name, {}).get(bl)
                result.append({"datum_plan": iso, "datum_vj": vj_date,
                               "name": name, "bundesland": bl, "art": "feiertag"})
    return result


_FIXED_DATE_MMDD = {
    "01-01", "01-06", "05-01", "08-15", "10-03", "10-31", "11-01", "12-25", "12-26", "08-08",
}
_HIMMELFAHRT_FRONLEICHNAM = {"Christi Himmelfahrt", "Fronleichnam"}


def _feiertagstage_rows(holiday_rows: list) -> list:
    result = []
    for row in holiday_rows:
        if row.get("art") != "feiertag":
            continue
        try:
            plan_d = date.fromisoformat(row["datum_plan"])
        except (ValueError, TypeError):
            continue
        # Skip fixed-date holidays (always same calendar day, no weekday alignment needed)
        plan_mmdd = row["datum_plan"][5:]
        if plan_mmdd in _FIXED_DATE_MMDD:
            continue
        vj_str = row.get("datum_vj")
        if vj_str and len(vj_str) >= 10 and vj_str[5:10] == plan_mmdd:
            continue  # same MM-DD in plan and VJ → fixed-date holiday
        wd = plan_d.weekday()
        if wd == 6:
            continue
        name = row.get("name", "")
        if name in _HIMMELFAHRT_FRONLEICHNAM:
            # Thursday: also include following Saturday (+2) and Sunday (+3)
            offsets = [-1, 1, 2, 3]
        elif wd == 0:
            offsets = [-2, -1, 1]
        else:
            offsets = [-1, 1]
        vj_d = None
        if vj_str:
            try:
                vj_d = date.fromisoformat(vj_str)
            except (ValueError, TypeError):
                vj_d = None
        for offset in offsets:
            new_plan = plan_d + timedelta(days=offset)
            new_vj = (vj_d + timedelta(days=offset)).isoformat() if vj_d else None
            result.append({
                "datum_plan": new_plan.isoformat(), "datum_vj": new_vj,
                "name": "Feiertagstag", "bundesland": row["bundesland"], "art": "feiertagstag",
            })
    return result


def _sondertage_rows(plan_yr: int, with_muttertag, with_fasching, with_ramadan) -> list:
    rows = []
    base_yr = plan_yr - 1
    if with_muttertag:
        rows.append({"datum_plan": _muttertag(plan_yr).isoformat(),
                     "datum_referenz": _muttertag(base_yr).isoformat(),
                     "bezeichnung": "Muttertag", "methode": "referenz", "bundesland": "alle"})
    if with_fasching:
        ostern_p = _easter(plan_yr)
        ostern_v = _easter(base_yr)
        for name, offset in [("Weiberfastnacht", 52), ("Rosen-Freitag", 51),
                              ("Faschings-Samstag", 50), ("Faschings-Sonntag", 49),
                              ("Rosenmontag", 48), ("Fastnachtsdienstag", 47)]:
            rows.append({"datum_plan": (ostern_p - timedelta(days=offset)).isoformat(),
                         "datum_referenz": (ostern_v - timedelta(days=offset)).isoformat(),
                         "bezeichnung": name, "methode": "referenz", "bundesland": "alle"})
    if with_ramadan and plan_yr in RAMADAN:
        s, e = RAMADAN[plan_yr]
        prev = RAMADAN.get(plan_yr - 1)
        rows.append({"datum_plan": s, "datum_referenz": prev[0] if prev else None,
                     "bezeichnung": "Ramadan (ca.) Start", "methode": "referenz", "bundesland": "alle"})
        rows.append({"datum_plan": e, "datum_referenz": None,
                     "bezeichnung": "Ramadan (ca.) Ende", "methode": "referenz", "bundesland": "alle"})
    return rows


def _extend_ferien_weekend(start: date, ende: date) -> tuple[date, date]:
    """Extend ferien period to include adjacent weekends.

    - If ferien END on Friday → extend to include Saturday + Sunday
    - If ferien END on Saturday → extend to include Sunday
    - If ferien START on Monday → extend back to include preceding Saturday + Sunday
    """
    # Extend end
    if ende.weekday() == 4:   # Friday → add Sat + Sun
        ende = ende + timedelta(days=2)
    elif ende.weekday() == 5:  # Saturday → add Sun
        ende = ende + timedelta(days=1)
    # Extend start
    if start.weekday() == 0:   # Monday → go back to preceding Saturday
        start = start - timedelta(days=2)
    return start, ende


def _load_schulferien_all_bl(years: list[int], bl_filter: list | None = None) -> list:
    """Load school holidays for given BL for given years from holidays library.
    Returns list of ferien_kalender rows (bundesland, art, jahr, start, ende)."""
    import holidays as hol_lib

    bls = bl_filter if bl_filter else BUNDESLAENDER
    result = []
    for yr in years:
        for bl in bls:
            try:
                school_hols = hol_lib.country_holidays(
                    "DE", subdiv=bl, years=yr, categories=(hol_lib.SCHOOL,)
                )
            except Exception:
                continue
            if not school_hols:
                continue

            # Group consecutive days with same name into date ranges
            by_name: dict[str, list[date]] = {}
            for d, name in school_hols.items():
                by_name.setdefault(name, []).append(d)

            for art_raw, dates in by_name.items():
                art = FERIEN_ART_RENAME.get(art_raw, art_raw)
                dates = sorted(dates)
                # Consecutive = gap of at most 1 day (handles adjacent periods)
                start = dates[0]
                prev = dates[0]
                for d in dates[1:]:
                    if (d - prev).days <= 1:
                        prev = d
                    else:
                        start, prev = _extend_ferien_weekend(start, prev)
                        result.append({
                            "bundesland": bl, "art": art, "jahr": yr,
                            "start": start.isoformat(), "ende": prev.isoformat(),
                        })
                        start = d
                        prev = d
                start, prev = _extend_ferien_weekend(start, prev)
                result.append({
                    "bundesland": bl, "art": art, "jahr": yr,
                    "start": start.isoformat(), "ende": prev.isoformat(),
                })
    return result


def _rebuild_ferien_from_kalender(conn_db, plan_yr: int):
    """Rebuild ferien table for plan_yr using ferien_kalender pairs (VJ + plan year).

    Uses nearest-start matching so the two Weihnachtsferien occurrences per year
    (January tail vs December start) map to the correct VJ period.
    """
    from planning.engine import match_ferien_periods
    base_yr = plan_yr - 1
    plan_rows = [dict(r) for r in conn_db.execute(
        "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        (plan_yr,)).fetchall()]
    vj_rows = [dict(r) for r in conn_db.execute(
        "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        (base_yr,)).fetchall()]
    conn_db.execute(
        "DELETE FROM ferien WHERE CAST(strftime('%Y', start_plan) AS INTEGER)=?", (plan_yr,)
    )
    for m in match_ferien_periods(plan_rows, vj_rows):
        conn_db.execute(
            "INSERT INTO ferien (bundesland, art, start_vj, ende_vj, start_plan, ende_plan) "
            "VALUES (?,?,?,?,?,?)",
            (m["bundesland"], m["art"], m["start_vj"], m["ende_vj"],
             m["start_plan"], m["ende_plan"])
        )
    conn_db.commit()


def _auto_datumsmapping(conn_db, plan_yr: int) -> str:
    try:
        from planning.engine import PlanningEngine, PlanParams
        from planning.datumsmapping import generate_datumsmapping
        par_row = conn_db.execute(
            "SELECT * FROM parameter WHERE planjahr=?", (plan_yr,)
        ).fetchone()
        today_dm = date.today()
        stichtag_dm = date(today_dm.year, 1, 1) if plan_yr <= today_dm.year else today_dm
        params = PlanParams(
            planjahr=plan_yr,
            stichtag=stichtag_dm,
            preiserhoehung_pct=float(par_row["preiserhoehung_pct"] or 0) if par_row else 0,
            ferien_puffer_wochen=int(par_row["ferien_puffer_wochen"] or 2) if par_row else 2,
        )
        engine = PlanningEngine(conn_db, params)
        n = generate_datumsmapping(conn_db, plan_yr, engine)
        return f"Datumsmapping: {n:,} Zeilen aktualisiert."
    except Exception as ex:
        return f"Datumsmapping-Fehler: {ex}"


# ── Bundesländer aus Filialen-Stammdaten ermitteln ───────────────────────────
from planning.engine import _normalize_bl as _nbl
_fil_bl_rows = conn.execute(
    "SELECT DISTINCT bundesland FROM filialen WHERE bundesland IS NOT NULL AND bundesland != ''"
).fetchall()
_fil_bls_abbr = list(dict.fromkeys(
    _nbl(r["bundesland"]) for r in _fil_bl_rows if _nbl(r["bundesland"]) in BUNDESLAENDER
))
# Falls noch keine Filialen angelegt: alle 16 laden
AKTIVE_BL = _fil_bls_abbr if _fil_bls_abbr else BUNDESLAENDER
AKTIVE_BL_NAMES = [BL_ABBR_TO_NAME.get(b, b) for b in sorted(AKTIVE_BL)]

# ── Abschnitt 1: Laden ───────────────────────────────────────────────────────
st.subheader("1. Feiertage, Sondertage und Ferien laden")
if AKTIVE_BL == BUNDESLAENDER:
    st.caption(
        f"Lädt Feiertage, Sondertage und Schulferien für alle 16 Bundesländer — "
        f"Budgetjahr **{planjahr}** und Basiszeitraum **{vj}**."
    )
else:
    bl_names = ", ".join(BL_ABBR_TO_NAME.get(b, b) for b in sorted(AKTIVE_BL))
    st.info(
        f"Es werden nur Feiertage und Ferien für die **{len(AKTIVE_BL)} Bundesländer** geladen, "
        f"die in den Filialstammdaten hinterlegt sind: **{bl_names}**. "
        "Bundesländer ohne Filiale werden ausgelassen, um die Datenmenge zu reduzieren. "
        "Wenn Sie weitere Bundesländer benötigen, legen Sie bitte entsprechende Filialen an."
    )

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    with_feiertagstage = st.checkbox("Feiertagstage (Vor-/Nachtage) laden", value=True)
    with_muttertag     = st.checkbox("Muttertag als Sondertag", value=True)
    with_fasching      = st.checkbox("Fasching (Do–Di) als Sondertage", value=True)
with col_opt2:
    with_ramadan       = st.checkbox("Ramadan (ca.) als Sondertage", value=False)
    replace_existing   = st.checkbox("Bestehende Einträge ersetzen", value=True)

if st.button("🔄 Feiertage, Sondertage und Ferien laden", type="primary"):
    # Check for existing manual data before overwriting
    _n_ft = conn.execute(
        "SELECT COUNT(*) FROM feiertage WHERE datum_plan LIKE ? OR datum_plan LIKE ?",
        (f"{vj}-%", f"{planjahr}-%"),
    ).fetchone()[0]
    _n_st = conn.execute(
        "SELECT COUNT(*) FROM sondertage WHERE datum_plan LIKE ? OR datum_plan LIKE ?",
        (f"{vj}-%", f"{planjahr}-%"),
    ).fetchone()[0]
    _n_fk = conn.execute(
        "SELECT COUNT(*) FROM ferien_kalender WHERE jahr=? OR jahr=?",
        (vj, planjahr),
    ).fetchone()[0]
    if replace_existing and (_n_ft + _n_st + _n_fk) > 0:
        st.session_state["_fk_confirm_laden"] = True
    else:
        st.session_state["_fk_do_laden"] = True

if st.session_state.get("_fk_confirm_laden"):
    st.warning(
        f"Es existieren bereits Feiertage, Sondertage und Ferien für "
        f"**{vj}** und **{planjahr}**. Wirklich neu laden und überschreiben?"
    )
    _c1, _c2, _ = st.columns([1.5, 1, 5])
    if _c1.button("✅ Ja, überschreiben", type="primary", key="_fk_confirm_yes"):
        st.session_state["_fk_confirm_laden"] = False
        st.session_state["_fk_do_laden"] = True
        st.rerun()
    if _c2.button("❌ Abbrechen", key="_fk_confirm_no"):
        st.session_state["_fk_confirm_laden"] = False
        st.rerun()

if st.session_state.get("_fk_do_laden"):
    st.session_state["_fk_do_laden"] = False
    with st.spinner("Lade …"):
        try:
            load_years = [vj, planjahr]
            all_ft, all_st = [], []
            for yr in load_years:
                ft_rows = _load_public_holidays_year(yr, AKTIVE_BL)
                all_ft.extend(ft_rows)
                if with_feiertagstage:
                    all_ft.extend(_feiertagstage_rows(ft_rows))
                all_st.extend(_sondertage_rows(yr, with_muttertag, with_fasching, with_ramadan))

            # Schulferien nur für relevante BL laden
            schulferien_rows = _load_schulferien_all_bl(load_years, AKTIVE_BL)

            if replace_existing:
                for yr in load_years:
                    conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
                    conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{yr}-%",))
                    conn.execute("DELETE FROM ferien_kalender WHERE jahr=?", (yr,))

            for row in all_ft:
                conn.execute(
                    "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                    "VALUES (:datum_plan, :datum_vj, :name, :bundesland, :art)", row)
            for row in all_st:
                conn.execute(
                    "INSERT OR IGNORE INTO sondertage "
                    "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                    "VALUES (:datum_plan, :datum_referenz, :bezeichnung, :methode, :bundesland)", row)
            for row in schulferien_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende) "
                    "VALUES (:bundesland, :art, :jahr, :start, :ende)", row)
            conn.commit()

            _rebuild_ferien_from_kalender(conn, planjahr)
            dm_msg = _auto_datumsmapping(conn, planjahr)

            n_schulferien_bl = len({r["bundesland"] for r in schulferien_rows})
            st.success(
                f"✅ Geladen: {len(all_ft)} Feiertag-Einträge, "
                f"{len(all_st)} Sondertage, "
                f"{len(schulferien_rows)} Schulferienperioden ({n_schulferien_bl} Bundesländer) "
                f"für Jahre {vj}+{planjahr}.  \n{dm_msg}"
            )
            st.rerun()
        except Exception as e:
            st.error(f"Fehler: {e}")
            import traceback
            st.code(traceback.format_exc())

st.divider()

# ── Abschnitt 2: Gespeicherte Feiertage, Sondertage und Ferien ───────────────
st.subheader("2. Gespeicherte Feiertage, Sondertage und Ferien")

filter_jahr = planjahr
st.caption(f"Angezeigt wird das Budgetjahr **{planjahr}**.")

tab_ft, tab_st, tab_fer = st.tabs(["Feiertage", "Sondertage", "Ferien"])

# ── Tab Feiertage ──
with tab_ft:
    bl_options_ft = ["alle"] + AKTIVE_BL_NAMES
    filter_bl_ft = st.selectbox("Bundesland", bl_options_ft, key="ft_bl_filter")

    ft_all = pd.read_sql(
        "SELECT id, datum_plan, datum_vj, name, bundesland, art FROM feiertage "
        "WHERE datum_plan LIKE ? ORDER BY bundesland, datum_plan",
        conn, params=(f"{filter_jahr}-%",)
    )
    if filter_bl_ft != "alle":
        bl_abbr = _bl_to_abbr(filter_bl_ft)
        ft_all = ft_all[ft_all["bundesland"].isin([bl_abbr, "alle"])]

    ft_orig = ft_all.drop(columns=["id"]).reset_index(drop=True)
    ft_orig = ft_orig[["bundesland", "datum_plan", "datum_vj", "name", "art"]]
    ft_orig["datum_plan"] = pd.to_datetime(ft_orig["datum_plan"], errors="coerce")
    ft_orig["datum_vj"]   = pd.to_datetime(ft_orig["datum_vj"], errors="coerce")
    ft_orig["bundesland"] = ft_orig["bundesland"].apply(_bl_to_name)
    ft_orig.insert(ft_orig.columns.get_loc("datum_plan") + 1, "wt_plan",
                   ft_orig["datum_plan"].apply(_wt_name))
    ft_orig.insert(ft_orig.columns.get_loc("datum_vj") + 1, "wt_vj",
                   ft_orig["datum_vj"].apply(_wt_name))
    # Drop art column from display (kept in data for save logic)
    ft_display = ft_orig.drop(columns=["art"])

    edited_ft = st.data_editor(
        ft_display.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"ft_editor_{filter_jahr}_{filter_bl_ft}",
        height=350,
        column_config={
            "bundesland": st.column_config.SelectboxColumn("Bundesland",
                                                           options=["Alle"] + AKTIVE_BL_NAMES,
                                                           width="small"),
            "datum_plan": st.column_config.DateColumn("Datum Budget", format="DD.MM.YYYY",
                                                       width="small"),
            "wt_plan":    st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "datum_vj":   st.column_config.DateColumn("Datum Basis", format="DD.MM.YYYY",
                                                       width="small"),
            "wt_vj":      st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "name":       st.column_config.TextColumn("Beschreibung"),
        },
    )
    st.caption(f"{len(ft_orig)} Einträge für {filter_jahr}")

    _date_cols_ft = ["datum_plan", "datum_vj"]
    _cmp_cols_ft_disp = ["bundesland", "datum_plan", "datum_vj", "name"]
    if not _norm_for_compare(ft_display[_cmp_cols_ft_disp], _date_cols_ft).equals(
            _norm_for_compare(edited_ft[_cmp_cols_ft_disp], _date_cols_ft)):
        conn.execute("DELETE FROM feiertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        # Restore art from original based on matching rows; default to original arts
        art_lookup = {
            (str(r["bundesland"]), _iso(r["datum_plan"])): str(r.get("art") or "feiertag").lower()
            for _, r in ft_orig.iterrows()
        }
        for _, row in edited_ft.dropna(subset=["datum_plan", "name"]).iterrows():
            d_iso = _iso(row.get("datum_plan"))
            bl_val = _bl_to_abbr(row.get("bundesland", "alle"))
            art_val = art_lookup.get((_bl_to_name(bl_val), d_iso), "feiertag")
            conn.execute(
                "INSERT OR IGNORE INTO feiertage (datum_plan, datum_vj, name, bundesland, art) "
                "VALUES (?,?,?,?,?)",
                (d_iso, _iso(row.get("datum_vj")), row.get("name"), bl_val, art_val)
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Feiertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Sondertage ──
with tab_st:
    st_all = pd.read_sql(
        "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage "
        "WHERE datum_plan LIKE ? ORDER BY bundesland, datum_plan",
        conn, params=(f"{filter_jahr}-%",)
    )

    st_orig = st_all.drop(columns=["id"]).reset_index(drop=True)
    st_orig = st_orig[["bundesland", "datum_plan", "datum_referenz", "bezeichnung", "methode"]]
    st_orig["datum_plan"]     = pd.to_datetime(st_orig["datum_plan"], errors="coerce")
    st_orig["datum_referenz"] = pd.to_datetime(st_orig["datum_referenz"], errors="coerce")
    st_orig["bundesland"]     = st_orig["bundesland"].apply(_bl_to_name)
    st_orig.insert(st_orig.columns.get_loc("datum_plan") + 1, "wt_plan",
                   st_orig["datum_plan"].apply(_wt_name))
    # Drop Methode from display (kept in data internally via methode_lookup)
    st_display = st_orig.drop(columns=["methode"])

    edited_st = st.data_editor(
        st_display.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"st_editor_{filter_jahr}",
        height=350,
        column_config={
            "bundesland":      st.column_config.SelectboxColumn("Bundesland",
                                                                options=["Alle"] + AKTIVE_BL_NAMES,
                                                                width="small"),
            "datum_plan":      st.column_config.DateColumn("Datum Budget", format="DD.MM.YYYY",
                                                           width="small"),
            "wt_plan":         st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "datum_referenz":  st.column_config.DateColumn("Datum Basis", format="DD.MM.YYYY",
                                                           width="small"),
            "bezeichnung":     st.column_config.TextColumn("Beschreibung"),
        },
    )
    st.caption(f"{len(st_orig)} Einträge für {filter_jahr}")

    _date_cols_st = ["datum_plan", "datum_referenz"]
    _cmp_cols_st_disp = ["bundesland", "datum_plan", "datum_referenz", "bezeichnung"]
    _edited_st_cmp = edited_st[[c for c in _cmp_cols_st_disp if c in edited_st.columns]]
    if not _norm_for_compare(st_orig[_cmp_cols_st_disp], _date_cols_st).equals(
            _norm_for_compare(_edited_st_cmp, _date_cols_st)):
        methode_lookup = {
            (_bl_to_name(_bl_to_abbr(str(r["bundesland"]))), _iso(r["datum_plan"])): str(r.get("methode") or "referenz")
            for _, r in st_orig.iterrows()
        }
        conn.execute("DELETE FROM sondertage WHERE datum_plan LIKE ?", (f"{filter_jahr}-%",))
        for _, row in edited_st.dropna(subset=["datum_plan", "bezeichnung"]).iterrows():
            d_iso = _iso(row.get("datum_plan"))
            bl_name = str(row.get("bundesland") or "alle")
            methode_val = methode_lookup.get((bl_name, d_iso), "referenz")
            conn.execute(
                "INSERT OR IGNORE INTO sondertage "
                "(datum_plan, datum_referenz, bezeichnung, methode, bundesland) "
                "VALUES (?,?,?,?,?)",
                (d_iso, _iso(row.get("datum_referenz")),
                 row.get("bezeichnung"), methode_val,
                 _bl_to_abbr(bl_name))
            )
        conn.commit()
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Sondertage gespeichert. {dm_msg}")
        st.rerun()

# ── Tab Ferien ──
with tab_fer:
    st.caption(
        "Schulferien je Bundesland — werden automatisch beim Laden-Button befüllt "
        "(Budgetjahr + Basiszeitraum für alle 16 Bundesländer). "
        "Manuelle Korrekturen hier möglich."
    )

    # Immer nur Budgetjahr anzeigen; Basis-Spalten als read-only danebengestellt
    fk_all = pd.read_sql(
        "SELECT id, bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        conn, params=[planjahr],
    )

    fk_all = fk_all.sort_values(["bundesland", "start"]).reset_index(drop=True)
    fk_orig = fk_all.drop(columns=["id"]).reset_index(drop=True)
    # art (Beschreibung) directly after bundesland
    fk_orig = fk_orig[["bundesland", "art", "start", "ende"]]
    fk_orig["start"] = pd.to_datetime(fk_orig["start"], errors="coerce")
    fk_orig["ende"]  = pd.to_datetime(fk_orig["ende"], errors="coerce")
    fk_orig["bundesland"] = fk_orig["bundesland"].apply(_bl_to_name)

    start_col = fk_orig.columns.get_loc("start")
    fk_orig.insert(start_col + 1, "wt_start", fk_orig["start"].apply(_wt_name))
    ende_col  = fk_orig.columns.get_loc("ende")
    fk_orig.insert(ende_col + 1, "wt_ende", fk_orig["ende"].apply(_wt_name))

    # Base-year comparison columns — nearest-start matching so the two
    # Weihnachtsferien occurrences per year (Jan tail / Dec start) map correctly.
    from planning.engine import match_ferien_periods
    _plan_rows_raw = [dict(r) for r in conn.execute(
        "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        (planjahr,)).fetchall()]
    _vj_rows_raw = [dict(r) for r in conn.execute(
        "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
        (vj,)).fetchall()]
    _match_map = {
        (m["bundesland"], m["art"], m["start_plan"]): (m["start_vj"], m["ende_vj"])
        for m in match_ferien_periods(_plan_rows_raw, _vj_rows_raw)
    }

    def _basis_pair(row):
        try:
            start_iso = pd.Timestamp(row["start"]).strftime("%Y-%m-%d")
        except Exception:
            return None
        return _match_map.get((_bl_to_abbr(row["bundesland"]), row["art"], start_iso))

    def _vj_col(row, which: str):
        pair = _basis_pair(row)
        if not pair:
            return pd.NaT
        return pd.Timestamp(pair[0] if which == "start" else pair[1])

    def _fer_abweichung(row) -> str:
        vj_pair = _basis_pair(row)
        if not vj_pair:
            return "kein VJ-Eintrag"
        plan_s, plan_e = row["start"], row["ende"]
        if pd.isna(plan_s) or pd.isna(plan_e):
            return ""
        basis_s = pd.Timestamp(vj_pair[0])
        basis_e = pd.Timestamp(vj_pair[1])
        plan_days  = int((plan_e - plan_s).days) + 1
        basis_days = int((basis_e - basis_s).days) + 1
        diff = plan_days - basis_days
        if diff == 0:
            return ""
        return f"{'+' if diff > 0 else ''}{diff} Tage"

    fk_orig["start_basis"] = fk_orig.apply(lambda r: _vj_col(r, "start"), axis=1)
    fk_orig.insert(fk_orig.columns.get_loc("start_basis") + 1, "wt_start_basis",
                   fk_orig["start_basis"].apply(_wt_name))
    fk_orig["ende_basis"] = fk_orig.apply(lambda r: _vj_col(r, "ende"), axis=1)
    fk_orig.insert(fk_orig.columns.get_loc("ende_basis") + 1, "wt_ende_basis",
                   fk_orig["ende_basis"].apply(_wt_name))
    fk_orig["abweichung"] = fk_orig.apply(_fer_abweichung, axis=1)

    # Basiszeiträume (start_basis/ende_basis) sind editierbar; Wochentage und
    # Abweichung bleiben abgeleitet (read-only, aktualisieren sich beim Speichern).
    _readonly_fk = ["wt_start", "wt_ende", "wt_start_basis", "wt_ende_basis", "abweichung"]

    edited_fk = st.data_editor(
        fk_orig.copy(),
        use_container_width=True, hide_index=True,
        num_rows="dynamic",
        key=f"fk_editor_{planjahr}",
        height=400,
        column_config={
            "bundesland":     st.column_config.SelectboxColumn("Bundesland",
                                                               options=["Alle"] + AKTIVE_BL_NAMES,
                                                               width="small"),
            "art":            st.column_config.TextColumn("Beschreibung"),
            "start":          st.column_config.DateColumn("Start", format="DD.MM.YYYY",
                                                          width="small"),
            "wt_start":       st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "ende":           st.column_config.DateColumn("Ende", format="DD.MM.YYYY",
                                                          width="small"),
            "wt_ende":        st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "start_basis":    st.column_config.DateColumn("Start Basis", format="DD.MM.YYYY",
                                                          width="small"),
            "wt_start_basis": st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "ende_basis":     st.column_config.DateColumn("Ende Basis", format="DD.MM.YYYY",
                                                          width="small"),
            "wt_ende_basis":  st.column_config.TextColumn("Wt.", disabled=True, width="small"),
            "abweichung":     st.column_config.TextColumn("Abweichung (Tage)", disabled=True),
        },
        disabled=_readonly_fk,
    )
    n_total = conn.execute(
        "SELECT COUNT(*) AS n FROM ferien_kalender WHERE jahr=? OR jahr=?", (vj, planjahr)
    ).fetchone()["n"]
    n_bl = conn.execute(
        "SELECT COUNT(DISTINCT bundesland) AS n FROM ferien_kalender WHERE jahr=? OR jahr=?",
        (vj, planjahr)
    ).fetchone()["n"]
    st.caption(f"{len(fk_orig)} Einträge angezeigt · {n_total} gesamt ({n_bl} Bundesländer) für {vj}+{planjahr}")

    _date_cols_plan  = ["start", "ende"]
    _date_cols_basis = ["start_basis", "ende_basis"]
    _cmp_cols_plan   = ["bundesland", "start", "ende", "art"]
    _cmp_cols_basis  = ["start_basis", "ende_basis"]

    _plan_changed = not _norm_for_compare(fk_orig[_cmp_cols_plan], _date_cols_plan).equals(
        _norm_for_compare(edited_fk[[c for c in _cmp_cols_plan if c in edited_fk.columns]],
                          _date_cols_plan))
    _basis_changed = not _norm_for_compare(fk_orig[_cmp_cols_basis], _date_cols_basis).equals(
        _norm_for_compare(edited_fk[[c for c in _cmp_cols_basis if c in edited_fk.columns]],
                          _date_cols_basis))

    if _plan_changed or _basis_changed:
        # 1. Basiszeitraum-Änderungen → zugehörige VJ-Zeilen aktualisieren
        #    (über die ursprünglich gematchte VJ-Identität identifiziert).
        if _basis_changed:
            for i in range(min(len(fk_orig), len(edited_fk))):
                o = fk_orig.iloc[i]
                e = edited_fk.iloc[i]
                old_s, old_e = _iso(o.get("start_basis")), _iso(o.get("ende_basis"))
                new_s, new_e = _iso(e.get("start_basis")), _iso(e.get("ende_basis"))
                if (old_s, old_e) == (new_s, new_e):
                    continue
                if not (old_s and old_e and new_s and new_e):
                    continue
                bl  = _bl_to_abbr(o.get("bundesland"))
                art = str(o.get("art") or "").strip()
                conn.execute(
                    "UPDATE ferien_kalender SET start=?, ende=?, jahr=? "
                    "WHERE bundesland=? AND art=? AND jahr=? AND start=? AND ende=?",
                    (new_s, new_e, int(new_s[:4]), bl, art, vj, old_s, old_e)
                )
            conn.commit()

        # 2. Budgetzeitraum-Änderungen → Planjahr-Zeilen neu aufbauen
        if _plan_changed:
            conn.execute("DELETE FROM ferien_kalender WHERE jahr=?", (planjahr,))
            for _, row in edited_fk.dropna(subset=["bundesland", "art"]).iterrows():
                bl  = _bl_to_abbr(row.get("bundesland"))
                art = str(row.get("art") or "").strip()
                s   = _iso(row.get("start"))
                e   = _iso(row.get("ende"))
                if not bl or not art or not s or not e:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO ferien_kalender (bundesland, art, jahr, start, ende) "
                    "VALUES (?,?,?,?,?)", (bl, art, int(s[:4]), s, e)
                )
            conn.commit()

        _rebuild_ferien_from_kalender(conn, planjahr)
        dm_msg = _auto_datumsmapping(conn, planjahr)
        st.toast(f"✅ Ferien gespeichert. {dm_msg}")
        st.rerun()
