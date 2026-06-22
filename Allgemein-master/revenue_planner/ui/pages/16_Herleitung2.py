"""Herleitung (L2) — Wochentagsvalidierung und additive Effekte."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, require_db, get_budgetjahr
from planning.validierung2 import SCHWELLWERT_PCT, WOCHENTAG_NAMEN
import pandas as pd

require_db()
conn = get_conn()
planjahr = get_budgetjahr()

st.title("Herleitung (L2)")

MONATS_NAMEN = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _de(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")


# Verfügbare Jahre
jahre_rows = conn.execute(
    "SELECT DISTINCT CAST(strftime('%Y', datum) AS INTEGER) as j "
    "FROM planwert_korrekturen2 ORDER BY j DESC"
).fetchall()
jahre = [r[0] for r in jahre_rows]

if not jahre:
    # Fallback: Prüfe ob L2-Planung existiert
    fallback = conn.execute(
        "SELECT COUNT(*) as n FROM planung2 WHERE CAST(strftime('%Y', datum) AS INTEGER)=?",
        (planjahr,)
    ).fetchone()
    if fallback and fallback["n"] > 0:
        st.success(
            f"Für {planjahr} wurden keine Ausreißer gefunden — alle Tagesumsätze lagen "
            f"innerhalb ±{SCHWELLWERT_PCT:.0f} % des Wochentagsschnitts."
        )
    else:
        st.info("Noch keine L2-Planung vorhanden. Bitte zuerst Seite **Planung ausführen (L2)** ausführen.")
    st.stop()

sel_jahr = st.selectbox("Planjahr", options=jahre, index=0)
if sel_jahr != planjahr:
    planjahr = sel_jahr

# ─────────────────────────────────────────────────────────────────────────────────
st.subheader(f"Korrigierte Tage — {planjahr}")

korr_rows = conn.execute("""
    SELECT datum, wochentag, monat, original_gesamt, wd_schnitt, abweichung_pct, korrigiert_gesamt
    FROM planwert_korrekturen2
    WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?
    ORDER BY datum
""", (planjahr,)).fetchall()

if not korr_rows:
    st.success(f"Keine Ausreißer für {planjahr}.")
    st.stop()

korr_df = pd.DataFrame([dict(r) for r in korr_rows])

# Monatlicher Filter
monate_im_df = sorted(korr_df["monat"].unique().tolist())
ausgewaehlte_monate = st.multiselect(
    "Monate anzeigen",
    options=monate_im_df,
    default=monate_im_df,
    format_func=lambda m: MONATS_NAMEN[m],
)
if ausgewaehlte_monate:
    korr_df = korr_df[korr_df["monat"].isin(ausgewaehlte_monate)]

st.caption(f"{len(korr_df)} Tage mit Abweichung > ±{SCHWELLWERT_PCT:.0f} % vom Wochentagsschnitt")

anzeige = korr_df.copy()
anzeige["Datum"] = pd.to_datetime(anzeige["datum"]).dt.strftime("%d.%m.%Y")
anzeige["Wochentag"] = anzeige["wochentag"].apply(lambda w: WOCHENTAG_NAMEN[int(w)])
anzeige["Monat"] = anzeige["monat"].apply(lambda m: MONATS_NAMEN[int(m)])
anzeige["Original Gesamt (€)"] = anzeige["original_gesamt"].map(_de)
anzeige["Ø Wochentag (€)"] = anzeige["wd_schnitt"].map(_de)
anzeige["Abweichung (%)"] = anzeige["abweichung_pct"].map("{:+.1f}".format)
anzeige["Korrigiert Gesamt (€)"] = anzeige["korrigiert_gesamt"].map(_de)
anzeige["Korrektur (€)"] = (anzeige["korrigiert_gesamt"] - anzeige["original_gesamt"]).map(
    lambda v: f"{v:+,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
)

st.dataframe(
    anzeige[["Datum", "Wochentag", "Monat", "Original Gesamt (€)",
             "Ø Wochentag (€)", "Abweichung (%)", "Korrigiert Gesamt (€)", "Korrektur (€)"]],
    use_container_width=True,
    hide_index=True,
)

gesamt_diff = (korr_df["korrigiert_gesamt"] - korr_df["original_gesamt"]).sum()
col1, col2, col3 = st.columns(3)
col1.metric("Korrigierte Tage", len(korr_df))
col2.metric("Gesamtkorrektur (€)", _de(gesamt_diff))
col3.metric("Ø Abweichung", f"{korr_df['abweichung_pct'].abs().mean():.1f} %")

# ─────────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Detailansicht: eff_validierung je Filiale an einem korrigierten Tag")

datums_optionen = sorted(korr_df["datum"].tolist())
sel_datum = st.selectbox(
    "Tag auswählen",
    options=datums_optionen,
    format_func=lambda d: f"{pd.Timestamp(d).strftime('%d.%m.%Y')} ({WOCHENTAG_NAMEN[korr_df.loc[korr_df['datum']==d, 'wochentag'].iloc[0]]})",
)

if sel_datum:
    detail_rows = conn.execute("""
        SELECT fil_nr,
               ist_vj,
               budget,
               COALESCE(eff_validierung, 0) AS eff_validierung
        FROM planung2
        WHERE datum = ? AND tagestyp != 'geschlossen'
        ORDER BY fil_nr
    """, (sel_datum,)).fetchall()

    if detail_rows:
        detail_df = pd.DataFrame([dict(r) for r in detail_rows])
        detail_df["Budget original (€)"] = (detail_df["budget"] - detail_df["eff_validierung"]).map(_de)
        detail_df["eff_validierung (€)"] = detail_df["eff_validierung"].map(
            lambda v: f"{v:+,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        detail_df["Budget neu (€)"] = detail_df["budget"].map(_de)
        detail_df = detail_df.rename(columns={"fil_nr": "Fil.-Nr."})

        # Summenzeile
        sum_orig = (detail_df["budget"] - detail_df["eff_validierung"]).sum()
        sum_val = detail_df["eff_validierung"].sum()
        sum_neu = detail_df["budget"].sum()
        sum_row = pd.DataFrame([{
            "Fil.-Nr.": "∑ Gesamt",
            "Budget original (€)": _de(sum_orig),
            "eff_validierung (€)": f"{sum_val:+,.0f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "Budget neu (€)": _de(sum_neu),
        }])
        anzeige_detail = pd.concat([
            detail_df[["Fil.-Nr.", "Budget original (€)", "eff_validierung (€)", "Budget neu (€)"]],
            sum_row,
        ], ignore_index=True)

        def _bold_sum(row):
            is_sum = str(row.get("Fil.-Nr.", "")).startswith("∑")
            return ["font-weight: bold" if is_sum else "" for _ in row.index]

        _max = max(len(anzeige_detail) * len(anzeige_detail.columns), 4096)
        pd.set_option("styler.render.max_elements", _max)
        st.dataframe(
            anzeige_detail.style.apply(_bold_sum, axis=1),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Keine Filialdaten für diesen Tag.")

# ─────────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Monatssumme eff_validierung je Filiale")

monats_rows = conn.execute("""
    SELECT fil_nr,
           CAST(strftime('%m', datum) AS INTEGER) AS monat,
           SUM(COALESCE(eff_validierung, 0))      AS summe_val
    FROM planung2
    WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?
    GROUP BY fil_nr, monat
    ORDER BY fil_nr, monat
""", (planjahr,)).fetchall()

if monats_rows:
    m_df = pd.DataFrame([dict(r) for r in monats_rows])
    m_pivot = m_df.pivot(index="fil_nr", columns="monat", values="summe_val").fillna(0)
    MONATE_S = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    rename_map = {m: MONATE_S[m - 1] for m in range(1, 13) if m in m_pivot.columns}
    m_pivot = m_pivot.rename(columns=rename_map)
    m_pivot["Gesamt"] = m_pivot.sum(axis=1)

    # Formatierung
    def _fmt_val(v):
        if v == 0:
            return "—"
        return f"{v:+,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")

    m_disp = m_pivot.copy().reset_index().rename(columns={"fil_nr": "Fil.-Nr."})
    for col in m_disp.columns[1:]:
        m_disp[col] = m_disp[col].map(_fmt_val)

    # Summenzeile
    sum_row_data = {"Fil.-Nr.": "∑ Gesamt"}
    for col in m_pivot.columns:
        sum_row_data[col] = _fmt_val(m_pivot[col].sum())
    m_disp = pd.concat([m_disp, pd.DataFrame([sum_row_data])], ignore_index=True)

    def _bold_sum2(row):
        is_sum = str(row.get("Fil.-Nr.", "")).startswith("∑")
        return ["font-weight: bold" if is_sum else "" for _ in row.index]

    _max2 = max(len(m_disp) * len(m_disp.columns), 4096)
    pd.set_option("styler.render.max_elements", _max2)
    st.dataframe(
        m_disp.style.apply(_bold_sum2, axis=1),
        use_container_width=True,
        hide_index=True,
        height=min(600, 36 * len(m_disp) + 40),
    )

# ─────────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Methodik")
st.markdown(f"""
**Wochentagsvalidierung** prüft, ob einzelne Tage im Vergleich zu gleichartigen
Wochentagen in den umliegenden Monaten auffällig abweichen.

**Vorgehen:**
1. Für jeden Planungstag wird der **Tagesgesamtumsatz** über alle aktiven Filialen aufsummiert.
2. Als Vergleichsbasis dienen alle Wochentage desselben Typs (Mo–So)
   im gleichen Monat sowie im Vormonat und Folgemonat.
3. **Ausgeschlossen** vom Vergleich (und von der Validierung) werden Tage, an denen
   mindestens eine Filiale als Feiertag, Feiertagstag, Sondertag oder Ferientag gebucht ist.
4. Weicht ein Tag um mehr als **±{SCHWELLWERT_PCT:.0f} %** vom Wochentagsschnitt ab,
   wird der Tagesgesamtumsatz auf den Schnitt **korrigiert**.
5. Die Korrektur wird per **Dreisatz** proportional auf alle Filialen verteilt:
   jede Filiale erhält `Originalwert × (Wochentagsschnitt ÷ Tagesoriginalgesamt)`.
6. Der Korrekturbetrag je Filiale und Tag wird in **eff_validierung** gespeichert
   (positiv = Erhöhung, negativ = Absenkung). Das additive Identitätsprinzip bleibt
   gewahrt: `budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
   + eff_preis + eff_ferien + eff_feiertag + eff_norm + eff_validierung`.

**Beispiel:** Liegen alle Mittwoche bei Ø 500.000 € und sticht ein Mittwoch mit
560.000 € (+12 %) heraus → er wird auf 500.000 € korrigiert. Eine Filiale, die
10.000 € geplant hatte (= 1/56 des Tagesgesamts), erhält danach
`10.000 × (500.000 ÷ 560.000) ≈ 8.929 €`.
""")
