"""Schulfilialen — branches closed during school vacation periods."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd

require_db()
conn = get_conn()
st.title("Ferienschließungen")
st.caption(f"Firma: **{get_gmbh()}**")

st.info(
    "Schulfilialen sind Filialen, die in Ferienzeiträumen historisch geschlossen waren "
    "(z.B. Bäckereien in Schulgebäuden oder Kantinen). "
    "Werden sie als geschlossen markiert, wird für diese Zeiträume im Budgetjahr kein Umsatz geplant.\n\n"
    "Die automatische Erkennung vergleicht die IST-Umsätze an Werktagen (Mo–Fr) in den Ferienwochen: "
    "Hat eine Filiale an ≥ 80 % der Werktage in den Ferien keinen Umsatz gemeldet, "
    "wird sie als geschlossen markiert."
)


def detect_schulfilialen(conn_db, threshold=0.8) -> dict:
    """Detect school branches from IST data and ferien_kalender."""
    ferien = pd.read_sql(
        "SELECT bundesland, art, start, ende FROM ferien_kalender", conn_db
    )
    if ferien.empty:
        return {}

    ist = pd.read_sql("SELECT fil_nr, datum, umsatz FROM ist_umsatz", conn_db)
    if ist.empty:
        return {}
    ist["datum_dt"] = pd.to_datetime(ist["datum"])

    filialen_rows = conn_db.execute("SELECT fil_nr, bundesland FROM filialen").fetchall()
    fil_bl = {r["fil_nr"]: r["bundesland"] for r in filialen_rows}

    result = {}
    for _, fer in ferien.iterrows():
        bl = fer["bundesland"]
        art = fer["art"]
        try:
            start = pd.to_datetime(fer["start"])
            ende = pd.to_datetime(fer["ende"])
        except Exception:
            continue
        period = ist[
            (ist["datum_dt"] >= start)
            & (ist["datum_dt"] <= ende)
            & (ist["datum_dt"].dt.weekday < 5)
        ]

        for fil_nr, fil_bl_val in fil_bl.items():
            if bl != "alle" and fil_bl_val != bl:
                continue
            fil_data = period[period["fil_nr"] == fil_nr]
            if len(fil_data) < 3:
                continue
            days_with_revenue = int((fil_data["umsatz"] > 0).sum())
            days_without = len(fil_data) - days_with_revenue
            if days_without / len(fil_data) >= threshold:
                result[(fil_nr, art, bl)] = True
    return result


# ── Auto-detect button ────────────────────────────────────────────────────────────
if st.button("\U0001f504 Aus IST-Daten erkennen", type="secondary"):
    detected = detect_schulfilialen(conn)
    if not detected:
        st.warning(
            "Keine Schulfilialen erkannt. Stellen Sie sicher, dass Schulferien unter "
            "'Feiertage laden' importiert wurden und IST-Daten vorhanden sind."
        )
    else:
        for (fil_nr, ferien_art, bl), geschlossen in detected.items():
            conn.execute("""
                INSERT OR REPLACE INTO filial_schulferien
                    (fil_nr, ferien_art, bundesland, geschlossen)
                VALUES (?,?,?,?)
            """, (fil_nr, ferien_art, bl, int(geschlossen)))
        conn.commit()
        st.success(f"✅ {len(detected)} Schulfilial-Einträge erkannt und gespeichert.")
        st.rerun()

st.divider()

# ── Matrix display: branches x vacation types ─────────────────────────────────
ferien_kalender = pd.read_sql(
    "SELECT DISTINCT art, bundesland FROM ferien_kalender ORDER BY art", conn
)

if ferien_kalender.empty:
    st.info("Bitte zuerst Schulferien unter 'Feiertage laden' importieren.")
    st.stop()

filialen = conn.execute(
    "SELECT fil_nr, bezeichnung, bundesland FROM filialen ORDER BY fil_nr"
).fetchall()
if not filialen:
    st.info("Noch keine Filialen vorhanden.")
    st.stop()

existing_sf = {
    (r["fil_nr"], r["ferien_art"], r["bundesland"]): bool(r["geschlossen"])
    for r in conn.execute(
        "SELECT fil_nr, ferien_art, bundesland, geschlossen FROM filial_schulferien"
    ).fetchall()
}

# Nur Filialen mit mind. einem erkannten Schulferien-Eintrag anzeigen
recognized_fils = {fil_nr for (fil_nr, _, _) in existing_sf.keys()}
if not recognized_fils:
    st.info(
        "Noch keine Schulfilialen erkannt. Bitte erst 'Aus IST-Daten erkennen' ausführen."
    )
    st.stop()
filialen = [f for f in filialen if f["fil_nr"] in recognized_fils]

# Build columns: one per (ferien_art, bundesland) pair
vacation_cols = [(row["art"], row["bundesland"]) for _, row in ferien_kalender.iterrows()]
col_labels = [f"{art} ({bl})" for art, bl in vacation_cols]

data = []
for f in filialen:
    row = {
        "Filiale": f["fil_nr"],
        "Bezeichnung": f["bezeichnung"] or "",
        "Bundesland": f["bundesland"] or "",
    }
    for (art, bl), label in zip(vacation_cols, col_labels):
        fil_bl = f["bundesland"] or ""
        if bl == "alle" or fil_bl == bl:
            row[label] = existing_sf.get((f["fil_nr"], art, bl), False)
        else:
            row[label] = None
    data.append(row)

df_matrix = pd.DataFrame(data)

col_cfg = {
    "Filiale": st.column_config.TextColumn(width=80),
    "Bezeichnung": st.column_config.TextColumn(width=200),
    "Bundesland": st.column_config.TextColumn(width=60),
}
for lbl in col_labels:
    col_cfg[lbl] = st.column_config.CheckboxColumn(lbl, width=120)

st.markdown("**Schulfilial-Matrix** (Haken = geschlossen während dieser Ferienzeit):")
edited_matrix = st.data_editor(
    df_matrix,
    use_container_width=True,
    hide_index=True,
    disabled=["Filiale", "Bezeichnung", "Bundesland"],
    column_config=col_cfg,
    key="schulfilial_matrix",
    height=500,
)

if st.button("\U0001f4be Schulfilial-Zuordnung speichern", type="primary"):
    saved = 0
    for _, row in edited_matrix.iterrows():
        fil_nr = str(row["Filiale"]).strip()
        if not fil_nr:
            continue
        for (art, bl), label in zip(vacation_cols, col_labels):
            val = row.get(label)
            if val is None:
                continue
            conn.execute("""
                INSERT OR REPLACE INTO filial_schulferien
                    (fil_nr, ferien_art, bundesland, geschlossen)
                VALUES (?,?,?,?)
            """, (fil_nr, art, bl, int(bool(val))))
            saved += 1
    conn.commit()
    st.success(f"✅ Gespeichert: {saved} Einträge.")
    st.rerun()
