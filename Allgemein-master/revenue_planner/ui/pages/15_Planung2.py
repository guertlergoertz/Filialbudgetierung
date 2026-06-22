"""Seite 15: Planung ausführen (Engine 2)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from revenue_planner.database.schema import get_connection
from revenue_planner.planning.engine2 import PlanParameter2, berechne_planwerte2
from revenue_planner.planning.validierung2 import (
    SCHWELLWERT_PCT,
    validiere_und_korrigiere_planwerte2,
)

st.set_page_config(page_title="Planung (L2)", layout="wide")
st.title("Planung ausführen — Engine 2")

conn = get_connection()


def _verfuegbare_jahre() -> list[int]:
    try:
        df = conn.execute("SELECT DISTINCT year(datum) as j FROM umsatzdaten ORDER BY j").df()
        return sorted(df["j"].tolist())
    except Exception:
        return []


def _alle_filialen() -> pd.DataFrame:
    try:
        return conn.execute("SELECT id, name FROM filialen WHERE aktiv = TRUE ORDER BY name").df()
    except Exception:
        return pd.DataFrame(columns=["id", "name"])


def _datum_fuer_kw_wd(plan_jahr: int, kw: int, wd: int) -> date | None:
    """Wandelt (KW, Wochentag dayofweek 0=Mo) in ein konkretes Datum um."""
    jan4 = date(plan_jahr, 1, 4)
    kw1_montag = jan4 - timedelta(days=jan4.weekday())
    ziel = kw1_montag + timedelta(weeks=kw - 1, days=wd)
    if ziel.year != plan_jahr:
        return None
    return ziel


jahre = _verfuegbare_jahre()
filialen_df = _alle_filialen()

if not jahre:
    st.warning("Keine historischen Umsatzdaten vorhanden. Bitte zuerst Daten importieren.")
    st.stop()

if filialen_df.empty:
    st.warning("Keine Filialen vorhanden. Bitte zuerst Filialen anlegen.")
    st.stop()

st.subheader("Parameter")

col1, col2 = st.columns(2)
with col1:
    plan_jahr = st.number_input(
        "Planjahr", min_value=2020, max_value=2035, value=max(jahre) + 1, step=1
    )
    basis_jahre = st.multiselect(
        "Basisjahre (Historik)", options=jahre, default=jahre[-2:] if len(jahre) >= 2 else jahre
    )

with col2:
    preisanpassung = st.number_input(
        "Preisanpassungsfaktor", min_value=0.5, max_value=2.0, value=1.0, step=0.01, format="%.2f"
    )
    schulfilialen_faktor = st.number_input(
        "Schulfilialen-Faktor", min_value=0.0, max_value=2.0, value=1.0, step=0.01, format="%.2f"
    )

if basis_jahre:
    st.write("**Gewichte je Basisjahr**")
    gewichte = []
    gwt_cols = st.columns(len(basis_jahre))
    for i, (col, jahr) in enumerate(zip(gwt_cols, basis_jahre)):
        default_w = round(1.0 / len(basis_jahre), 2)
        w = col.number_input(
            f"{jahr}", min_value=0.0, max_value=10.0, value=default_w, step=0.05, key=f"gw_{jahr}"
        )
        gewichte.append(w)
else:
    gewichte = []

st.divider()

if not basis_jahre:
    st.info("Bitte mindestens ein Basisjahr auswählen.")
    st.stop()

if abs(sum(gewichte)) < 1e-9:
    st.warning("Die Summe der Gewichte darf nicht 0 sein.")
    st.stop()

if st.button("▶ Planung starten", type="primary"):
    params = PlanParameter2(
        plan_jahr=int(plan_jahr),
        basis_jahre=[int(j) for j in basis_jahre],
        gewichte=gewichte,
        preisanpassung=float(preisanpassung),
        schulfilialen_faktor=float(schulfilialen_faktor),
    )

    # Bestehende L2-Planwerte für das Jahr löschen
    conn.execute(
        "DELETE FROM planwerte WHERE engine = '2' AND year(datum) = ?", [int(plan_jahr)]
    )

    # Aktuell höchste ID bestimmen
    max_id_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM planwerte").fetchone()
    next_id = int(max_id_row[0]) + 1

    filialen_ids = filialen_df["id"].tolist()
    fortschritt = st.progress(0, text="Planung läuft …")
    gesamt_datensaetze = 0

    rows_to_insert = []

    for i, fil_id in enumerate(filialen_ids):
        try:
            kw_df = berechne_planwerte2(conn, fil_id, params)
        except Exception:
            kw_df = pd.DataFrame()

        for _, row in kw_df.iterrows():
            d = _datum_fuer_kw_wd(int(plan_jahr), int(row["kw"]), int(row["wd"]))
            if d is None:
                continue
            rows_to_insert.append((next_id, fil_id, d, float(row["planwert"]), "2"))
            next_id += 1
            gesamt_datensaetze += 1

        fortschritt.progress(
            (i + 1) / len(filialen_ids),
            text=f"Filiale {i + 1}/{len(filialen_ids)} …",
        )

    if rows_to_insert:
        insert_df = pd.DataFrame(rows_to_insert, columns=["id", "filiale", "datum", "planwert", "engine"])
        conn.execute("INSERT INTO planwerte SELECT * FROM insert_df")

    fortschritt.empty()
    st.success(f"Planung abgeschlossen: {gesamt_datensaetze:,} Tagesdatensätze für {len(filialen_ids)} Filialen gespeichert.")

    # Wochentagsvalidierung
    st.subheader("Wochentagsvalidierung")
    with st.spinner("Validierung läuft …"):
        korr_df = validiere_und_korrigiere_planwerte2(conn, int(plan_jahr))

    if korr_df.empty:
        st.success(f"Keine Ausreißer gefunden (Schwellwert: ±{SCHWELLWERT_PCT:.0f} %).")
    else:
        st.warning(
            f"{len(korr_df)} Tage wurden korrigiert (Schwellwert: ±{SCHWELLWERT_PCT:.0f} %). "
            "Details in **Herleitung Engine 2**."
        )

    st.rerun()

# Status bestehender Planwerte
try:
    count = conn.execute(
        "SELECT COUNT(*) FROM planwerte WHERE engine = '2' AND year(datum) = ?", [int(plan_jahr)]
    ).fetchone()[0]
    if count > 0:
        st.info(f"Aktuell {count:,} L2-Planwerte für {int(plan_jahr)} in der Datenbank.")
        korrekturen_count = conn.execute(
            "SELECT COUNT(*) FROM planwert_korrekturen2 WHERE year(datum) = ?", [int(plan_jahr)]
        ).fetchone()[0]
        if korrekturen_count > 0:
            st.caption(
                f"Davon wurden {korrekturen_count} Tage durch die Wochentagsvalidierung korrigiert."
            )
except Exception:
    pass
