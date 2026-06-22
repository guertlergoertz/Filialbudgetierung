"""Planning parameters page: growth %, holidays, vacations, Ramadan, Fasching."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db
import pandas as pd
from datetime import date, timedelta

require_db()
conn = get_conn()
st.title("Planungsparameter")

BUNDESLAENDER = ["alle", "RP", "HE", "BY", "BW", "NW", "NI",
                 "BE", "BB", "HB", "HH", "MV", "SH", "SL", "SN", "ST", "TH"]

planjahr = st.number_input("Planjahr", min_value=2024, max_value=2035,
                            value=date.today().year + 1, step=1)

existing = conn.execute("SELECT * FROM parameter WHERE planjahr=?", (planjahr,)).fetchone()
ex = dict(existing) if existing else {}

tabs = st.tabs(["Allgemein", "Feiertage & Sondertage", "Ferien", "Ramadan", "Fasching"])

# ── Tab 1: General ─────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("Allgemeine Parameter")

    with st.form("params_puffer"):
        puffer = st.number_input(
            "Ferien-Pufferzeitraum (Wochen vor Ferien als Referenz)",
            min_value=1, max_value=8,
            value=int(ex.get("ferien_puffer_wochen", 2)), step=1,
            help=(
                "Anzahl Wochen VOR Ferienbeginn, die als Referenz für den Ferienfaktor dienen. "
                "Der Ferienfaktor wird pro Ferienwoche berechnet: Ø Umsatz der jeweiligen "
                "Ferienwoche ÷ Ø Umsatz im Pufferzeitraum (wochentags-gematcht). "
                "Beispiel-Ergebnis: Ferienwoche 1 −10 %, Woche 2 −5 %, Woche 3 −2 %. "
                "Empfehlung: 2 Wochen."
            )
        )
        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter (planjahr, ferien_puffer_wochen)
                VALUES (?,?)
                ON CONFLICT(planjahr) DO UPDATE SET ferien_puffer_wochen=excluded.ferien_puffer_wochen
            """, (planjahr, puffer))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()

    st.divider()
    st.info(
        "Das monatliche Umsatzwachstum (%) wird auf der Seite "
        "**Preisanpassung je Monat** gepflegt (eine Quelle der Wahrheit für "
        "`parameter_monat.wachstum_pct`)."
    )

# ── Tab 2: Holidays ────────────────────────────────────────────────────────
with tabs[1]:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Feiertage")
        ft_df = pd.read_sql(
            "SELECT id, datum_plan, datum_vj, name, bundesland FROM feiertage ORDER BY datum_plan", conn
        )
        if ft_df.empty:
            st.info("Noch keine Feiertage eingetragen.")
        else:
            st.dataframe(ft_df.drop("id", axis=1), use_container_width=True, hide_index=True)
            del_id = st.number_input("ID zum Löschen", min_value=0, value=0, step=1, key="del_ft_id")
            if st.button("🗑️ Löschen", key="del_ft") and del_id > 0:
                conn.execute("DELETE FROM feiertage WHERE id=?", (del_id,))
                conn.commit()
                st.rerun()

        st.markdown("**Feiertag hinzufügen**")
        with st.form("add_feiertag"):
            f_datum_plan = st.date_input("Datum Planjahr", value=date(planjahr, 1, 1))
            f_datum_vj   = st.date_input("Datum Vorjahr (für 1:1 Planung)", value=date(planjahr - 1, 1, 1))
            f_name = st.text_input("Name", placeholder="z.B. Ostermontag")
            f_bl   = st.selectbox("Bundesland", BUNDESLAENDER, key="ft_bl")
            if st.form_submit_button("➕ Hinzufügen") and f_name:
                conn.execute(
                    "INSERT INTO feiertage (datum_plan, datum_vj, name, bundesland) VALUES (?,?,?,?)",
                    (f_datum_plan.isoformat(), f_datum_vj.isoformat(), f_name, f_bl)
                )
                conn.commit()
                st.success("✅ Hinzugefügt.")
                st.rerun()

    with col2:
        st.subheader("Sondertage")
        st.caption("Tage mit atypischem Umsatz (z.B. Ostersamstag, Tag vor Feiertag)")
        st_df = pd.read_sql(
            "SELECT id, datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage ORDER BY datum_plan", conn
        )
        if st_df.empty:
            st.info("Noch keine Sondertage eingetragen.")
        else:
            st.dataframe(st_df.drop("id", axis=1), use_container_width=True, hide_index=True)

        st.markdown("**Sondertag hinzufügen**")
        with st.form("add_sondertag"):
            s_datum  = st.date_input("Datum Planjahr", value=date(planjahr, 3, 1), key="s_datum")
            s_bez    = st.text_input("Bezeichnung", placeholder="z.B. Ostersamstag")
            s_methode = st.radio("Planungsmethode", ["referenz", "samstag"],
                                  help="referenz = Vorjahrestag × Wachstum%; samstag = Samstags-Ø der Filiale")
            s_ref = st.date_input("Referenz-Datum Vorjahr", value=date(planjahr - 1, 3, 1), key="s_ref") \
                    if s_methode == "referenz" else None
            s_bl  = st.selectbox("Bundesland", BUNDESLAENDER, key="s_bl")
            if st.form_submit_button("➕ Hinzufügen") and s_bez:
                conn.execute("""
                    INSERT INTO sondertage (datum_plan, datum_referenz, bezeichnung, methode, bundesland)
                    VALUES (?,?,?,?,?)
                """, (s_datum.isoformat(), s_ref.isoformat() if s_ref else None, s_bez, s_methode, s_bl))
                conn.commit()
                st.success("✅ Hinzugefügt.")
                st.rerun()

# ── Tab 3: Vacations ──────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Ferienzeiten")
    ferien_df = pd.read_sql("SELECT * FROM ferien ORDER BY bundesland, art", conn)
    if not ferien_df.empty:
        st.dataframe(ferien_df.drop("id", axis=1), use_container_width=True, hide_index=True)
        del_fer = st.number_input("ID zum Löschen", min_value=0, value=0, step=1, key="del_fer_id")
        if st.button("🗑️ Löschen", key="del_fer") and del_fer > 0:
            conn.execute("DELETE FROM ferien WHERE id=?", (del_fer,))
            conn.commit()
            st.rerun()

    st.markdown("**Ferien hinzufügen**")
    with st.form("add_ferien"):
        col1, col2, col3 = st.columns(3)
        with col1:
            f_bl  = st.selectbox("Bundesland", [b for b in BUNDESLAENDER if b != "alle"], key="fer_bl")
            f_art = st.selectbox("Ferienart", ["Osterferien", "Sommerferien", "Herbstferien",
                                               "Weihnachtsferien", "Winterferien", "Pfingstferien"])
        with col2:
            f_start_vj = st.date_input("Start Vorjahr",  value=date(planjahr - 1, 4, 1),  key="fsvj")
            f_ende_vj  = st.date_input("Ende Vorjahr",   value=date(planjahr - 1, 4, 14), key="fevj")
        with col3:
            f_start_p  = st.date_input("Start Planjahr", value=date(planjahr, 4, 1),      key="fsp")
            f_ende_p   = st.date_input("Ende Planjahr",  value=date(planjahr, 4, 14),     key="fep")

        if st.form_submit_button("➕ Hinzufügen"):
            conn.execute("""
                INSERT INTO ferien (bundesland, art, start_vj, ende_vj, start_plan, ende_plan)
                VALUES (?,?,?,?,?,?)
            """, (f_bl, f_art, f_start_vj.isoformat(), f_ende_vj.isoformat(),
                  f_start_p.isoformat(), f_ende_p.isoformat()))
            conn.commit()
            st.success("✅ Hinzugefügt.")
            st.rerun()

# ── Tab 4: Ramadan ────────────────────────────────────────────────────────
with tabs[3]:
    st.subheader("Ramadan-Parameter")
    st.info("Ramadan verschiebt Umsätze zwischen Monaten — kein Verlust. "
            "Nur relevant für Filialen in Gebieten mit hohem muslimischem Kundenanteil.")

    with st.form("params_ramadan"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Vorjahr ({planjahr - 1})**")
            r_vj_start = st.date_input("Ramadan Start",
                value=date.fromisoformat(ex["ramadan_vj_start"]) if ex.get("ramadan_vj_start") else date(planjahr - 1, 3, 1))
            r_vj_ende  = st.date_input("Ramadan Ende",
                value=date.fromisoformat(ex["ramadan_vj_ende"]) if ex.get("ramadan_vj_ende") else date(planjahr - 1, 3, 30))
        with col2:
            st.markdown(f"**Planjahr ({planjahr})**")
            r_plan_start = st.date_input("Ramadan Start",
                value=date.fromisoformat(ex["ramadan_plan_start"]) if ex.get("ramadan_plan_start") else date(planjahr, 2, 18),
                key="rps")
            r_plan_ende  = st.date_input("Ramadan Ende",
                value=date.fromisoformat(ex["ramadan_plan_ende"]) if ex.get("ramadan_plan_ende") else date(planjahr, 3, 19),
                key="rpe")

        shift = (r_plan_start - r_vj_start).days
        if shift != 0:
            st.info(f"ℹ️ Ramadan {planjahr} beginnt **{abs(shift)} Tage {'früher' if shift < 0 else 'später'}** als {planjahr - 1}.")

        r_pct = st.slider("Ramadan-sensitiver Anteil am Monatsumsatz (%)",
                           min_value=0.0, max_value=30.0,
                           value=float(ex.get("ramadan_umsatz_pct", 5.0)), step=0.5)

        st.caption("Welche Filialen Ramadan-sensitiv sind, kann unter **Filialen → Bearbeiten** eingestellt werden.")

        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter (planjahr, ramadan_vj_start, ramadan_vj_ende,
                  ramadan_plan_start, ramadan_plan_ende, ramadan_umsatz_pct)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(planjahr) DO UPDATE SET
                  ramadan_vj_start=excluded.ramadan_vj_start,
                  ramadan_vj_ende=excluded.ramadan_vj_ende,
                  ramadan_plan_start=excluded.ramadan_plan_start,
                  ramadan_plan_ende=excluded.ramadan_plan_ende,
                  ramadan_umsatz_pct=excluded.ramadan_umsatz_pct
            """, (planjahr, r_vj_start.isoformat(), r_vj_ende.isoformat(),
                  r_plan_start.isoformat(), r_plan_ende.isoformat(), r_pct))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()

# ── Tab 5: Fasching ───────────────────────────────────────────────────────
with tabs[4]:
    st.subheader("Fasching-Parameter")
    st.info("Eine kürzere Faschingszeit führt zu echten Umsatzverlusten (kein Shift wie bei Ramadan).")

    with st.form("params_fasching"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Vorjahr ({planjahr - 1})**")
            fa_vj_start = st.date_input("Fasching Start",
                value=date.fromisoformat(ex["fasching_vj_start"]) if ex.get("fasching_vj_start") else date(planjahr - 1, 2, 27))
            fa_vj_ende  = st.date_input("Fasching Ende",
                value=date.fromisoformat(ex["fasching_vj_ende"]) if ex.get("fasching_vj_ende") else date(planjahr - 1, 3, 4))
        with col2:
            st.markdown(f"**Planjahr ({planjahr})**")
            fa_plan_start = st.date_input("Fasching Start",
                value=date.fromisoformat(ex["fasching_plan_start"]) if ex.get("fasching_plan_start") else date(planjahr, 2, 12),
                key="faps")
            fa_plan_ende  = st.date_input("Fasching Ende",
                value=date.fromisoformat(ex["fasching_plan_ende"]) if ex.get("fasching_plan_ende") else date(planjahr, 2, 24),
                key="fape")

        vj_tage   = (fa_vj_ende - fa_vj_start).days + 1
        plan_tage = (fa_plan_ende - fa_plan_start).days + 1
        diff      = plan_tage - vj_tage

        if diff < 0:
            st.warning(f"🔴 Fasching {planjahr} ist **{abs(diff)} Tage kürzer** als {planjahr - 1} ({plan_tage} vs. {vj_tage} Tage).")
        elif diff > 0:
            st.success(f"🟢 Fasching {planjahr} ist **{diff} Tage länger** als {planjahr - 1} ({plan_tage} vs. {vj_tage} Tage).")
        else:
            st.success(f"✅ Fasching {planjahr} hat gleich viele Tage wie {planjahr - 1} ({plan_tage} Tage).")

        fa_wirkung = st.slider(
            "Umsatzwirkung pro Tag-Differenz (%)",
            min_value=-20.0, max_value=0.0,
            value=float(ex.get("fasching_wirkung_pct", -3.0)), step=0.5,
            help="Negativer Wert = Umsatzverlust pro fehlendem Faschingstag."
        )

        if st.form_submit_button("💾 Speichern"):
            conn.execute("""
                INSERT INTO parameter (planjahr, fasching_vj_start, fasching_vj_ende,
                  fasching_plan_start, fasching_plan_ende, fasching_wirkung_pct)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(planjahr) DO UPDATE SET
                  fasching_vj_start=excluded.fasching_vj_start,
                  fasching_vj_ende=excluded.fasching_vj_ende,
                  fasching_plan_start=excluded.fasching_plan_start,
                  fasching_plan_ende=excluded.fasching_plan_ende,
                  fasching_wirkung_pct=excluded.fasching_wirkung_pct
            """, (planjahr, fa_vj_start.isoformat(), fa_vj_ende.isoformat(),
                  fa_plan_start.isoformat(), fa_plan_ende.isoformat(), fa_wirkung))
            conn.commit()
            st.success("✅ Gespeichert.")
            st.rerun()
