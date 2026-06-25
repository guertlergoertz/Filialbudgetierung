"""Planung ausführen (Logik 2): Berechnung starten, Monatsumsatzübersicht."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from planning.engine import PlanningEngine, PlanParams, DayPlan
from planning.engine2 import PlanningEngine2
from planning.validierung2 import validiere_und_korrigiere_planwerte2, SCHWELLWERT_PCT
import pandas as pd
from datetime import date
import time as _time

require_db()
conn = get_conn()
gmbh = get_gmbh()
planjahr = get_budgetjahr()

st.title("Planung ausführen (L2)")

monat_rows = conn.execute(
    "SELECT monat, wachstum_pct FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchall()
_incr = {r["monat"]: r["wachstum_pct"] for r in monat_rows}
_cumul = 0.0
wachstum_monat = {}
for _m in range(1, 13):
    _cumul += _incr.get(_m, 0.0)
    wachstum_monat[_m] = _cumul

today = date.today()
stichtag = date(today.year, 1, 1) if planjahr <= today.year else today

params = PlanParams(
    planjahr=planjahr,
    stichtag=stichtag,
    preiserhoehung_pct=0.0,
    wachstum_monat=wachstum_monat,
    ferien_puffer_wochen=2,
)

MONATE_S = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

import re as _re_fil

_fil_rows = conn.execute(
    "SELECT fil_nr, bezeichnung FROM filialen "
    "WHERE COALESCE(flag_inaktiv,0)=0 AND COALESCE(flag_gesperrt,0)=0 "
    "AND (eroeffnung_ende IS NULL OR eroeffnung_ende >= ?) "
    "ORDER BY fil_nr",
    (f"{planjahr}-01-01",)
).fetchall()
all_filialen = [
    r["fil_nr"] for r in _fil_rows
    if not _re_fil.search(r'X{2,}', str(r["bezeichnung"] or ""), _re_fil.IGNORECASE)
]
_active_fil_set = set(all_filialen)

run_mode = st.radio("Ausführen für", ["Alle Filialen", "Auswahl"])
if run_mode == "Auswahl":
    selected_fils = st.multiselect("Filialen auswählen", all_filialen,
                                   placeholder="Filialen auswählen...")
else:
    selected_fils = all_filialen
    st.caption(f"{len(all_filialen)} aktive Filialen")

st.divider()

existing_check = conn.execute(
    "SELECT COUNT(*) as n FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    (planjahr,),
).fetchone()
existing_n = existing_check["n"] if existing_check else 0

if st.button("🚀 Planung berechnen", type="primary", disabled=not selected_fils):
    if existing_n > 0:
        st.session_state["_confirm_replan2"] = True
    else:
        st.session_state["_do_plan2"] = True

if st.session_state.get("_confirm_replan2"):
    st.warning(
        f"Es existieren bereits **{existing_n:,}** geplante Tage für **{planjahr}** (L2). "
        "Wirklich neu berechnen? Die vorhandenen Daten werden überschrieben."
    )
    c1, c2, _ = st.columns([1.5, 1, 5])
    if c1.button("✅ Ja, überschreiben", type="primary", key="confirm_yes2"):
        st.session_state["_confirm_replan2"] = False
        st.session_state["_do_plan2"] = True
        st.rerun()
    if c2.button("❌ Abbrechen", key="confirm_no2"):
        st.session_state["_confirm_replan2"] = False
        st.rerun()

if st.session_state.get("_do_plan2"):
    st.session_state["_do_plan2"] = False
    try:
        engine2 = PlanningEngine2(conn, params)
        aktive_fils = [
            fn for fn in selected_fils
            if not engine2.filialen.get(fn, {}).get("flag_gesperrt")
            and not engine2.filialen.get(fn, {}).get("flag_inaktiv")
        ]
        n_total = len(aktive_fils)
        n_skip  = len(selected_fils) - n_total

        progress_bar = st.progress(0, text=f"Starte Berechnung… (0 / {n_total})")
        _t_start = _time.monotonic()

        def _on_progress(done: int, total: int, fil_nr: str):
            pct = int(done / total * 100) if total else 100
            elapsed = _time.monotonic() - _t_start
            if done > 1 and done < total:
                avg_s = elapsed / done
                remaining_s = avg_s * (total - done)
                _min, _sec = divmod(int(remaining_s), 60)
                time_hint = f" — noch ca. {_min}:{_sec:02d} min" if _min else f" — noch ca. {_sec} s"
            else:
                time_hint = ""
            progress_bar.progress(
                pct,
                text=f"Filiale {fil_nr} … {pct} % ({done} / {total}){time_hint}",
            )

        results = engine2.run(aktive_fils, progress_callback=_on_progress)
        progress_bar.empty()

        conn.execute(
            "DELETE FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
            (planjahr,)
        )
        conn.commit()
        engine2.save(results)

        # Wochentagsvalidierung direkt im Anschluss
        with st.spinner("Wochentagsvalidierung läuft…"):
            korr_df = validiere_und_korrigiere_planwerte2(conn, planjahr)

        skip_hint = f" ({n_skip} gesperrt/inaktiv übersprungen)" if n_skip else ""
        st.success(f"✅ {n_total} Filiale(n){skip_hint} — {len(results):,} Tage berechnet.")
        if korr_df.empty:
            st.info(f"Keine Ausreißer gefunden (Schwellwert: ±{SCHWELLWERT_PCT:.0f} %).")
        else:
            st.warning(
                f"{len(korr_df)} Tage wurden durch die Wochentagsvalidierung korrigiert "
                f"(Schwellwert: ±{SCHWELLWERT_PCT:.0f} %). Details in **Herleitung (L2)**."
            )
        st.session_state["last_plan2_results"] = results
        st.session_state["last_plan2_jahr"] = planjahr
        st.session_state.pop(f"herleitung2_data_{gmbh}_{planjahr}", None)
        st.rerun()
    except Exception as e:
        if "progress_bar" in dir():
            progress_bar.empty()
        st.error(f"Fehler: {e}")
        st.exception(e)


def _de(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _load_plan2_df_from_db(conn_db, plan_yr: int, active_fils: list) -> pd.DataFrame | None:
    rows = conn_db.execute(
        "SELECT fil_nr, datum, ist_vj, budget FROM planung2 "
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


_use_fresh = ("last_plan2_results" in st.session_state
              and st.session_state.get("last_plan2_jahr") == planjahr)
_db_df = None if _use_fresh else _load_plan2_df_from_db(conn, planjahr, all_filialen)

if _use_fresh or _db_df is not None:
    if _use_fresh:
        results = st.session_state["last_plan2_results"]
        df = pd.DataFrame([
            {"fil_nr": r.fil_nr, "monat": r.datum.month, "budget": r.budget, "ist_vj": r.ist_vj}
            for r in results
            if r.fil_nr in _active_fil_set
        ])
    else:
        df = _db_df
        results = None

    st.divider()
    st.subheader("Ergebnisvorschau — Monatsübersicht (L2)")
    if not _use_fresh:
        st.caption(f"Gespeicherte Planung aus der Datenbank ({existing_n:,} Tage)")

    budget_m = df.groupby(["fil_nr", "monat"])["budget"].sum().unstack(fill_value=0)
    ist_m    = df.groupby(["fil_nr", "monat"])["ist_vj"].sum().unstack(fill_value=0)

    for m in range(1, 13):
        if m not in budget_m.columns:
            budget_m[m] = 0.0
        if m not in ist_m.columns:
            ist_m[m] = 0.0

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

st.divider()
existing_plan2 = conn.execute(
    "SELECT COUNT(*) as n, MIN(datum) as von, MAX(datum) as bis FROM planung2 "
    "WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
    (planjahr,),
).fetchone()
if existing_plan2 and existing_plan2["n"] > 0:
    korr_cnt = conn.execute(
        "SELECT COUNT(*) as n FROM planwert_korrekturen2 "
        "WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
        (planjahr,),
    ).fetchone()
    korr_hint = f", davon {korr_cnt['n']} Tage validierungskorrigiert" if korr_cnt and korr_cnt["n"] else ""
    st.caption(
        f"Gespeicherte L2-Planung für {planjahr}: {existing_plan2['n']:,} Zeilen "
        f"({existing_plan2['von']} – {existing_plan2['bis']}){korr_hint}"
    )
