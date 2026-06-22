"""New branch monthly plan input and delivery customer planning."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date

require_db()
conn = get_conn()
st.title("Neue Filialen")

MONTH_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
            "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1, key="pj_nf")

# ── New branches monthly plan ──────────────────────────────────────────────
if True:
    st.subheader("Monatliche Planwerte für neue Filialen")
    st.info(
        "Neue Filialen werden automatisch erkannt: alle Filialen mit einem "
        f"Eröffnungsdatum im Jahr **{planjahr}** erscheinen hier. "
        "Der Eröffnungsmonat wird automatisch mit **50%** des eingetragenen Wertes berechnet."
    )

    # Auto-detect new branches by eroeffnung in plan year
    neue_filialen = conn.execute("""
        SELECT fil_nr, bezeichnung, eroeffnung
        FROM filialen
        WHERE eroeffnung IS NOT NULL
          AND CAST(substr(eroeffnung, 1, 4) AS INTEGER) = ?
        ORDER BY fil_nr
    """, (planjahr,)).fetchall()

    if not neue_filialen:
        st.warning(
            f"Keine Filialen mit Eröffnungsdatum in {planjahr} gefunden. "
            "Bitte unter **Filialen** ein Eröffnungsdatum eintragen."
        )
    else:
        fil_options = {
            r["fil_nr"]: f"{r['fil_nr']} – {r['bezeichnung'] or ''} (Eröffnung: {r['eroeffnung']})"
            for r in neue_filialen
        }
        selected_fil = st.selectbox("Filiale", list(fil_options.keys()),
                                    format_func=lambda x: fil_options[x])

        fil_info = next(r for r in neue_filialen if r["fil_nr"] == selected_fil)
        eroeff_iso = fil_info["eroeffnung"]
        eroeff_month = int(eroeff_iso[5:7]) if eroeff_iso else None

        existing = conn.execute(
            "SELECT monat, planwert FROM neue_filialen_plan WHERE fil_nr=? AND planjahr=?",
            (selected_fil, planjahr)
        ).fetchall()
        existing_map = {r["monat"]: r["planwert"] for r in existing}

        with st.form(f"neue_fil_plan_{selected_fil}"):
            cols = st.columns(6)
            values = {}
            for i, month_name in enumerate(MONTH_DE):
                month = i + 1
                ex_val = existing_map.get(month, 0.0)
                is_eroeff = (month == eroeff_month)
                label = f"{month_name} {'🔑' if is_eroeff else ''}"
                help_txt = "Eröffnungsmonat → wird automatisch mit 50% berechnet" if is_eroeff else ""
                with cols[i % 6]:
                    values[month] = st.number_input(
                        label, min_value=0.0, value=float(ex_val),
                        step=1000.0, format="%.0f", help=help_txt, key=f"nf_{month}"
                    )

            if st.form_submit_button("💾 Speichern"):
                for month, val in values.items():
                    conn.execute("""
                        INSERT INTO neue_filialen_plan (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(fil_nr, planjahr, monat) DO UPDATE SET
                          planwert=excluded.planwert,
                          eroeffnung_datum=excluded.eroeffnung_datum
                    """, (selected_fil, planjahr, month, val, eroeff_iso))
                conn.commit()
                st.success("✅ Gespeichert.")
                st.rerun()

        if existing_map:
            st.markdown("**Aktuelle Monatswerte (Brutto, vor 50%-Kürzung Eröffnungsmonat):**")
            chart_data = {MONTH_DE[m - 1]: existing_map[m] for m in range(1, 13) if m in existing_map}
            st.bar_chart(chart_data)
