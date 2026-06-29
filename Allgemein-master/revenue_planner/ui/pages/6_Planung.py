"""Planung ausführen: Berechnung starten, Vorschau und Excel-Export."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from planning.engine import PlanningEngine, PlanParams, DayPlan
from planning.export import build_excel
import pandas as pd
from datetime import date
import time as _time

require_db()
conn = get_conn()
gmbh = get_gmbh()
planjahr = get_budgetjahr()

st.title("Planung ausführen")

monat_rows = conn.execute(
    "SELECT monat, wachstum_pct FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchall()
_incr = {r["monat"]: r["wachstum_pct"] for r in monat_rows}
# Preisanpassung is stored as incremental %; planning engine needs cumulative % per month
_cumul = 0.0
wachstum_monat = {}
for _m in range(1, 13):
    _cumul += _incr.get(_m, 0.0)
    wachstum_monat[_m] = _cumul

# Basiszeitraum: full previous year when planjahr <= current year, rolling 12 months otherwise
today = date.today()
stichtag = date(planjahr, 1, 1) if planjahr <= today.year else today

params = PlanParams(
    planjahr=planjahr,
    stichtag=stichtag,
    preiserhoehung_pct=0.0,
    wachstum_monat=wachstum_monat,
    ferien_puffer_wochen=2,
)

_eng = PlanningEngine(conn, params)
basis_label = _eng.base_window_label()

MONATE_S = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

all_filialen = [r["fil_nr"] for r in
                conn.execute(
                    "SELECT fil_nr FROM filialen "
                    "WHERE COALESCE(flag_inaktiv,0)=0 AND COALESCE(flag_gesperrt,0)=0 "
                    "AND (eroeffnung_ende IS NULL OR eroeffnung_ende >= ?) "
                    "ORDER BY fil_nr",
                    (f"{planjahr}-01-01",)
                ).fetchall()]

run_mode = st.radio("Ausführen für", ["Alle Filialen", "Auswahl"])
if run_mode == "Auswahl":
    selected_fils = st.multiselect("Filialen auswählen", all_filialen,
                                   placeholder="Filialen auswählen...")
else:
    selected_fils = all_filialen
    st.caption(f"{len(all_filialen)} aktive Filialen")

st.divider()

# Check existing plan data for confirm dialog
existing_check = conn.execute(
    "SELECT COUNT(*) as n FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    (planjahr,),
).fetchone()
existing_n = existing_check["n"] if existing_check else 0

if st.button("🚀 Planung berechnen", type="primary", disabled=not selected_fils):
    if existing_n > 0:
        st.session_state["_confirm_replan"] = True
    else:
        st.session_state["_do_plan"] = True

if st.session_state.get("_confirm_replan"):
    st.warning(
        f"Es existieren bereits **{existing_n:,}** geplante Tage für **{planjahr}**. "
        "Wirklich neu berechnen? Die vorhandenen Daten werden überschrieben."
    )
    c1, c2, _ = st.columns([1.5, 1, 5])
    if c1.button("✅ Ja, überschreiben", type="primary", key="confirm_yes"):
        st.session_state["_confirm_replan"] = False
        st.session_state["_do_plan"] = True
        st.rerun()
    if c2.button("❌ Abbrechen", key="confirm_no"):
        st.session_state["_confirm_replan"] = False
        st.rerun()

if st.session_state.get("_do_plan"):
    st.session_state["_do_plan"] = False
    try:
        engine = PlanningEngine(conn, params)
        # Gesperrte und inaktive Filialen vorab herausfiltern, damit der
        # Fortschrittsbalken nur aktive Filialen zählt.
        aktive_fils = [
            fn for fn in selected_fils
            if not engine.filialen.get(fn, {}).get("flag_gesperrt")
            and not engine.filialen.get(fn, {}).get("flag_inaktiv")
        ]
        n_total = len(aktive_fils)
        n_skip  = len(selected_fils) - n_total

        results: list[DayPlan] = []
        progress_bar = st.progress(0, text="Starte Berechnung…")
        _t_start = _time.monotonic()
        for i, fil_nr in enumerate(aktive_fils, start=1):
            pct = int(i / n_total * 100) if n_total else 100
            elapsed = _time.monotonic() - _t_start
            if i > 1 and n_total > i:
                avg_s = elapsed / (i - 1)
                remaining_s = avg_s * (n_total - i + 1)
                _min, _sec = divmod(int(remaining_s), 60)
                _time_hint = f" — noch ca. {_min}:{_sec:02d} min" if _min else f" — noch ca. {_sec} s"
            else:
                _time_hint = ""
            progress_bar.progress(pct, text=f"Filiale {fil_nr} … {pct} % ({i}/{n_total}){_time_hint}")
            results.extend(engine.plan_branch(fil_nr))
        progress_bar.empty()

        # Clear ALL planning data for this year before saving — ensures
        # the table never contains stale results from previous partial runs
        conn.execute(
            "DELETE FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
            (planjahr,)
        )
        conn.commit()
        engine.save(results)
        engine.fix_ist_vj(planjahr)
        skip_hint = f" ({n_skip} gesperrt/inaktiv übersprungen)" if n_skip else ""
        st.success(f"✅ {n_total} Filiale(n){skip_hint} — {len(results):,} Tage berechnet.")
        st.session_state["last_plan_results"] = results
        st.session_state["last_plan_jahr"] = planjahr
    except Exception as e:
        progress_bar.empty() if "progress_bar" in dir() else None
        st.error(f"Fehler: {e}")
        st.exception(e)


def _de(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _load_plan_df_from_db(conn_db, plan_yr: int, active_fils: list) -> pd.DataFrame | None:
    """Load plan summary from DB for the given year, restricted to active branches."""
    rows = conn_db.execute(
        "SELECT fil_nr, datum, ist_vj, budget FROM planung "
        "WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
        (plan_yr,),
    ).fetchall()
    if rows and active_fils:
        rows = [r for r in rows if r["fil_nr"] in set(active_fils)]
    if not rows:
        return None
    return pd.DataFrame([{
        "fil_nr": r["fil_nr"],
        "monat": int(r["datum"][5:7]),
        "budget": float(r["budget"] or 0),
        "ist_vj": float(r["ist_vj"] or 0),
    } for r in rows])


# Decide data source: fresh calculation > existing DB data
_use_fresh = ("last_plan_results" in st.session_state
              and st.session_state.get("last_plan_jahr") == planjahr)
_db_df = None if _use_fresh else _load_plan_df_from_db(conn, planjahr, all_filialen)

if _use_fresh or _db_df is not None:
    if _use_fresh:
        results = st.session_state["last_plan_results"]
        df = pd.DataFrame([
            {"fil_nr": r.fil_nr, "monat": r.datum.month, "budget": r.budget, "ist_vj": r.ist_vj}
            for r in results
        ])
    else:
        df = _db_df
        results = None

    st.divider()
    st.subheader("Ergebnisvorschau — Monatsübersicht")
    if not _use_fresh:
        st.caption(f"Gespeicherte Planung aus der Datenbank ({existing_n:,} Tage)")

    budget_m = df.groupby(["fil_nr", "monat"])["budget"].sum().unstack(fill_value=0)
    ist_m    = df.groupby(["fil_nr", "monat"])["ist_vj"].sum().unstack(fill_value=0)

    for m in range(1, 13):
        if m not in budget_m.columns:
            budget_m[m] = 0.0
        if m not in ist_m.columns:
            ist_m[m] = 0.0

    # Per-month Bestandsfil. classification: fil has basis data (ist_vj > 0) for that month
    fil_monat_ist = df.groupby(["fil_nr", "monat"])["ist_vj"].sum()
    fil_monat_is_bestands = {k: float(v) > 0 for k, v in fil_monat_ist.items()}

    def _month_vals(pivot, fil, monate):
        if fil in pivot.index:
            return [pivot.loc[fil, m] for m in monate]
        return [0.0] * len(monate)

    rows_display = []
    for fil_nr in sorted(df["fil_nr"].unique()):
        bud = _month_vals(budget_m, fil_nr, range(1, 13))
        ist = _month_vals(ist_m, fil_nr, range(1, 13))
        bud_sum = sum(bud)
        ist_sum = sum(ist)
        row_bud = {"Fil.-Nr.": fil_nr, "Typ": f"Budget {planjahr}"}
        row_ist = {"Fil.-Nr.": "", "Typ": "Basiszeitraum"}
        for i, mn in enumerate(MONATE_S):
            row_bud[mn] = _de(bud[i])
            row_ist[mn] = _de(ist[i]) if ist[i] != 0 else "—"
        row_bud["Gesamt"] = _de(bud_sum)
        row_ist["Gesamt"] = _de(ist_sum) if ist_sum != 0 else "—"
        rows_display.append(row_bud)
        rows_display.append(row_ist)

    # Sum rows with per-month Bestandsfil. classification
    all_fils = sorted(df["fil_nr"].unique())
    bestands_sets = {m: {f for f in all_fils if fil_monat_is_bestands.get((f, m), False)}
                     for m in range(1, 13)}
    neue_sets = {m: {f for f in all_fils if not fil_monat_is_bestands.get((f, m), False)}
                 for m in range(1, 13)}

    def _sum_rows_pm(label, month_sets):
        row = {"Fil.-Nr.": label, "Typ": f"Budget {planjahr}"}
        total = 0.0
        for i, m in enumerate(range(1, 13)):
            val = sum(
                (budget_m.at[fil, m] if (fil in budget_m.index and m in budget_m.columns) else 0.0)
                for fil in month_sets.get(m, set())
            )
            row[MONATE_S[i]] = _de(val)
            total += val
        row["Gesamt"] = _de(total)
        return row

    has_bestands = any(bestands_sets[m] for m in range(1, 13))
    has_neue = any(neue_sets[m] for m in range(1, 13))

    if has_bestands:
        rows_display.append({"Fil.-Nr.": "", "Typ": ""})
        rows_display.append(_sum_rows_pm("∑ Bestandsfil.", bestands_sets))
    if has_neue:
        rows_display.append(_sum_rows_pm("∑ Neue Fil.", neue_sets))
    rows_display.append(_sum_rows_pm("∑ Gesamt", {m: set(all_fils) for m in range(1, 13)}))

    disp_df = pd.DataFrame(rows_display).fillna("")
    cols_order = ["Fil.-Nr.", "Typ"] + MONATE_S + ["Gesamt"]
    disp_df = disp_df[[c for c in cols_order if c in disp_df.columns]]

    # Bold sum rows and Gesamt column
    def _apply_bold(row):
        fil = str(row.get("Fil.-Nr.", ""))
        is_sum = fil.startswith("∑")
        return ["font-weight: bold" if (is_sum or c == "Gesamt") else "" for c in row.index]

    _max_cells = max(len(disp_df) * len(disp_df.columns), 262144)
    pd.set_option("styler.render.max_elements", _max_cells)
    styled = disp_df.style.apply(_apply_bold, axis=1)

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        height=min(800, 36 * len(disp_df) + 40),
        column_config={
            "Fil.-Nr.": st.column_config.TextColumn(width=80),
            "Typ": st.column_config.TextColumn(width=130),
            **{m: st.column_config.TextColumn(m, width=75) for m in MONATE_S + ["Gesamt"]},
        },
    )

    if _use_fresh and results is not None:
        st.divider()
        with st.spinner("Excel wird erstellt…"):
            excel_bytes = build_excel(results, gmbh, planjahr)
        st.download_button(
            label="📥 Excel-Planung herunterladen",
            data=excel_bytes,
            file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

st.divider()
existing_plan = conn.execute(
    "SELECT COUNT(*) as n, MIN(datum) as von, MAX(datum) as bis FROM planung "
    "WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    (planjahr,),
).fetchone()
if existing_plan and existing_plan["n"] > 0:
    st.caption(
        f"Gespeicherte Planung für {planjahr}: {existing_plan['n']:,} Zeilen "
        f"({existing_plan['von']} – {existing_plan['bis']})"
    )
    if st.button("📥 Gespeicherte Planung erneut exportieren"):
        rows = conn.execute(
            "SELECT * FROM planung WHERE CAST(strftime('%Y', datum) AS INTEGER)=? ORDER BY fil_nr, datum",
            (planjahr,),
        ).fetchall()

        def _g(r, k, default=0.0):
            try:
                v = r[k]
                return v if v is not None else default
            except (IndexError, KeyError):
                return default

        saved = [
            DayPlan(
                fil_nr=r["fil_nr"], datum=date.fromisoformat(r["datum"]),
                wochentag=r["wochentag"], bundesland=_g(r, "bundesland", "") or "",
                ist_vj=_g(r, "ist_vj"),
                eff_oeffnung=_g(r, "eff_oeffnung"), eff_verteilung=_g(r, "eff_verteilung"),
                eff_wochentag=_g(r, "eff_wochentag"), eff_preis=_g(r, "eff_preis"),
                eff_ferien=_g(r, "eff_ferien"), eff_feiertag=_g(r, "eff_feiertag"),
                eff_norm=_g(r, "eff_norm"),
                budget=_g(r, "budget") or _g(r, "gesamt_plan"),
                monat_basis=_g(r, "monat_basis"), monat_hoch=_g(r, "monat_hoch") or _g(r, "monatsumsatz_ist_hoch"),
                monat_plan=_g(r, "monat_plan") or _g(r, "monatsumsatz_plan"),
                tagestyp=_g(r, "tagestyp", "normal") or "normal",
                feiertag_name=_g(r, "feiertag_name", "") or "",
                ferien_art=_g(r, "ferien_art", "") or "",
                normalisierung=_g(r, "normalisierung", 1.0) or 1.0,
            )
            for r in rows
        ]
        excel_bytes = build_excel(saved, gmbh, planjahr)
        st.download_button(
            "📥 Herunterladen",
            data=excel_bytes,
            file_name=f"Umsatzplanung_{planjahr}_{gmbh.replace(' ', '_')}_gespeichert.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
