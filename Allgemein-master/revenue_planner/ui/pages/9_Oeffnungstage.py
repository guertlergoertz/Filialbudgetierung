"""Opening days input: weekday programme + holiday opening per branch."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
from database.importer import detect_oeffnungstage
import pandas as pd

require_db()
conn = get_conn()
st.title("Öffnungstage")
st.caption(f"Firma: **{get_gmbh()}**")

st.markdown("""
Aus den importierten Umsätzen wird automatisch erkannt, an welchen **Wochentagen**
und **Feiertagen** jede Filiale im Basiszeitraum geöffnet hatte. Diese Werte gelten
fürs Budgetjahr und können hier angepasst werden. Änderungen werden automatisch gespeichert.

Die **automatische Erkennung** läuft direkt nach dem Umsatz-Import.
Der Button unten ist nützlich, wenn Filialen nachträglich angelegt wurden oder
Stammdaten geändert wurden.
""")

st.markdown("""
<style>
[data-testid="stDataFrameResizable"] [role="gridcell"] input[type="checkbox"]:checked {
    accent-color: #1976d2;
}
</style>
""", unsafe_allow_html=True)

WT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

if st.button("\U0001f504 Erneut erkennen (überschreibt manuelle Änderungen)",
             help="Nützlich nach dem Import neuer IST-Daten oder nach Änderungen an den Filialen."):
    det = detect_oeffnungstage(conn, force=True)
    st.success(f"✅ Öffnungstage für {det['weekday_branches']} Filiale(n) und "
               f"{det['holiday_entries']} Feiertags-Einträge neu erkannt.")
    st.rerun()

filialen = conn.execute("SELECT fil_nr, bezeichnung FROM filialen ORDER BY fil_nr").fetchall()
if not filialen:
    st.info("Noch keine Filialen vorhanden.")
    st.stop()

tab1, tab2 = st.tabs(["Wochentage", "Feiertags-Öffnung"])

# ── Tab 1: Weekday opening (all branches, matrix) ────────────────────────────
with tab1:
    st.subheader("Wochentags-Programm je Filiale")
    oeff = {(r["fil_nr"], r["wochentag"]): bool(r["offen"])
            for r in conn.execute("SELECT fil_nr, wochentag, offen FROM filial_oeffnung").fetchall()}

    data = []
    for f in filialen:
        row = {"Filiale": f["fil_nr"], "Bezeichnung": f["bezeichnung"] or ""}
        for wt in range(7):
            row[WT[wt]] = bool(oeff.get((f["fil_nr"], wt), False))
        data.append(row)
    df_orig = pd.DataFrame(data)

    edited = st.data_editor(
        df_orig, use_container_width=True, hide_index=True,
        disabled=["Filiale", "Bezeichnung"],
        column_config={
            "Filiale":     st.column_config.TextColumn(width=80),
            "Bezeichnung": st.column_config.TextColumn(width=200),
            **{w: st.column_config.CheckboxColumn(w, width=55) for w in WT},
        },
        key="oeff_editor",
    )

    if not df_orig.astype(str).equals(edited.astype(str)):
        for _, row in edited.iterrows():
            for wt in range(7):
                conn.execute(
                    "INSERT OR REPLACE INTO filial_oeffnung (fil_nr, wochentag, offen) VALUES (?,?,?)",
                    (row["Filiale"], wt, int(bool(row[WT[wt]]))),
                )
        conn.commit()
        st.toast("✅ Wochentage gespeichert")
        st.rerun()

# ── Tab 2: Holiday opening (per branch) ───────────────────────────────────
with tab2:
    st.subheader("Feiertags-Öffnung")
    st.caption("Hatte die Filiale am jeweiligen Feiertag historisch Umsatz, wird sie als offen "
               "geplant. Neue Filialen ohne Historie werden am Feiertag als geschlossen geplant.")

    feiertage = conn.execute(
        "SELECT DISTINCT name FROM feiertage ORDER BY name"
    ).fetchall()
    if not feiertage:
        st.info("Noch keine Feiertage hinterlegt. Bitte zuerst unter **Feiertage laden** importieren.")
    else:
        fil_labels = {f["fil_nr"]: f"{f['fil_nr']} – {f['bezeichnung'] or ''}" for f in filialen}
        sel = st.selectbox("Filiale", list(fil_labels.keys()), format_func=lambda x: fil_labels[x])

        existing = {r["feiertag_name"]: bool(r["offen"]) for r in conn.execute(
            "SELECT feiertag_name, offen FROM filial_feiertag WHERE fil_nr=?", (sel,)).fetchall()}

        rows = [{"Feiertag": ft["name"], "Offen": existing.get(ft["name"], False)}
                for ft in feiertage]
        df_ft_orig = pd.DataFrame(rows)

        edited_ft = st.data_editor(
            df_ft_orig, use_container_width=True, hide_index=True,
            disabled=["Feiertag"],
            column_config={"Offen": st.column_config.CheckboxColumn("Offen", width=70)},
            key=f"ft_editor_{sel}",
            height=400,
        )

        if not df_ft_orig.astype(str).equals(edited_ft.astype(str)):
            for _, row in edited_ft.iterrows():
                conn.execute(
                    "INSERT OR REPLACE INTO filial_feiertag (fil_nr, feiertag_name, offen) VALUES (?,?,?)",
                    (sel, row["Feiertag"], int(bool(row["Offen"]))),
                )
            conn.commit()
            st.toast("✅ Feiertags-Öffnung gespeichert")
            st.rerun()
