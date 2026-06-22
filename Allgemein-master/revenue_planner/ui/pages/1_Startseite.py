"""Startseite: Firmendatenbank öffnen/anlegen und Budgetjahr wählen."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import DATA_DIR, open_db, get_conn, get_gmbh, get_budgetjahr, set_budgetjahr
from datetime import date

st.title("Startseite")
st.subheader("Firmendatenbank auswählen oder anlegen")

DATA_DIR.mkdir(parents=True, exist_ok=True)
existing = sorted(p.stem.replace("_", " ") for p in DATA_DIR.glob("*.db"))

col1, col2 = st.columns(2)

with col1:
    st.markdown("#### Bestehende Firma öffnen")
    if existing:
        choice = st.selectbox("Firma auswählen", existing)
        if st.button("Öffnen", key="open_btn"):
            open_db(choice)
            st.success(f"✅ Datenbank für **{choice}** geladen.")
            st.rerun()
    else:
        st.info("Noch keine Datenbanken vorhanden. Bitte rechts eine neue Firma anlegen.")

with col2:
    st.markdown("#### Neue Firma anlegen")
    new_name = st.text_input("Firmenname", placeholder='z.B. "Bäckerei RLP GmbH"')
    if st.button("Anlegen", key="new_btn") and new_name.strip():
        open_db(new_name.strip())
        st.success(f"✅ Neue Datenbank für **{new_name.strip()}** angelegt.")
        st.rerun()

if get_gmbh():
    st.divider()
    st.success(f"Aktive Firma: **{get_gmbh()}**")
    conn = get_conn()

    # Budgetjahr auf linker Hälfte begrenzen
    bj_col, _ = st.columns(2)
    with bj_col:
        st.subheader("Budgetjahr")

        years_in_db: list[int] = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT planjahr FROM parameter ORDER BY planjahr DESC"
            ).fetchall()
        ]

        if years_in_db:
            current_bj = get_budgetjahr()
            opts = sorted(set(years_in_db), reverse=True)
            if current_bj not in opts:
                set_budgetjahr(opts[0])
                current_bj = opts[0]
            sel = st.selectbox(
                "Budgetjahr auswählen",
                options=opts,
                index=opts.index(current_bj),
                key="bj_select",
            )
            if int(sel) != current_bj:
                set_budgetjahr(int(sel))
                st.rerun()
            st.info(
                f"Aktives Budgetjahr: **{get_budgetjahr()}** — alle Berechnungen, "
                "Feiertage und Exporte beziehen sich auf dieses Jahr."
            )
        else:
            st.warning("Noch kein Budgetjahr angelegt. Bitte unten ein Budgetjahr erstellen.")

        with st.expander("➕ Neues Budgetjahr anlegen", expanded=not bool(years_in_db)):
            new_year = st.number_input(
                "Jahr", min_value=2024, max_value=2040,
                value=date.today().year + 1,
                step=1, key="new_bj_input",
            )
            if st.button("Budgetjahr anlegen", key="new_bj_btn"):
                conn.execute(
                    "INSERT OR IGNORE INTO parameter (planjahr) VALUES (?)", (int(new_year),)
                )
                conn.commit()
                set_budgetjahr(int(new_year))
                st.success(f"✅ Budgetjahr **{int(new_year)}** angelegt und ausgewählt.")
                st.rerun()

    st.caption("Weiter mit der Navigation links.")
