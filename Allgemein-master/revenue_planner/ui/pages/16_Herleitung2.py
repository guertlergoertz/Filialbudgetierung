"""Seite 16: Herleitung Engine 2 — Wochentagsvalidierung."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from revenue_planner.database.schema import get_connection
from revenue_planner.planning.validierung2 import SCHWELLWERT_PCT, WOCHENTAG_NAMEN

st.set_page_config(page_title="Herleitung L2", layout="wide")
st.title("Herleitung Engine 2 — Wochentagsvalidierung")

conn = get_connection()

MONATS_NAMEN = [
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _lade_korrekturen(plan_jahr: int) -> pd.DataFrame:
    try:
        df = conn.execute("""
            SELECT datum, wochentag, monat, original_gesamt, wd_schnitt,
                   abweichung_pct, korrigiert_gesamt
            FROM planwert_korrekturen2
            WHERE year(datum) = ?
            ORDER BY datum
        """, [plan_jahr]).df()
        return df
    except Exception:
        return pd.DataFrame()


def _verfuegbare_jahre() -> list[int]:
    try:
        df = conn.execute(
            "SELECT DISTINCT year(datum) as j FROM planwert_korrekturen2 ORDER BY j"
        ).df()
        return df["j"].tolist()
    except Exception:
        return []


jahre = _verfuegbare_jahre()

if not jahre:
    # Fallback: Jahre aus planwerte
    try:
        df_j = conn.execute(
            "SELECT DISTINCT year(datum) as j FROM planwerte WHERE engine='2' ORDER BY j"
        ).df()
        jahre = df_j["j"].tolist()
    except Exception:
        jahre = []

if not jahre:
    st.info("Noch keine L2-Planung vorhanden. Bitte zuerst Seite **15 – Planung (L2)** ausführen.")
    st.stop()

plan_jahr = st.selectbox("Planjahr", options=sorted(jahre, reverse=True))

korr_df = _lade_korrekturen(int(plan_jahr))

if korr_df.empty:
    st.success(
        f"Für {plan_jahr} wurden keine Ausreißer gefunden – alle Tagesumsätze lagen "
        f"innerhalb ±{SCHWELLWERT_PCT:.0f} % des Wochentagsschnitts."
    )
    st.stop()

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

st.subheader(f"Korrigierte Tage — {plan_jahr}")
st.caption(f"{len(korr_df)} Tage mit Abweichung > ±{SCHWELLWERT_PCT:.0f} % vom Wochentagsschnitt")

# Anzeigetabelle aufbereiten
anzeige = korr_df.copy()
anzeige["Datum"] = pd.to_datetime(anzeige["datum"]).dt.strftime("%d.%m.%Y")
anzeige["Wochentag"] = anzeige["wochentag"].apply(lambda w: WOCHENTAG_NAMEN[int(w)])
anzeige["Monat"] = anzeige["monat"].apply(lambda m: MONATS_NAMEN[int(m)])
anzeige["Tagesgesamt original (€)"] = anzeige["original_gesamt"].map("{:,.2f}".format)
anzeige["Wochentagsschnitt (€)"] = anzeige["wd_schnitt"].map("{:,.2f}".format)
anzeige["Abweichung (%)"] = anzeige["abweichung_pct"].map("{:+.1f}".format)
anzeige["Tagesgesamt korrigiert (€)"] = anzeige["korrigiert_gesamt"].map("{:,.2f}".format)
anzeige["Differenz (€)"] = (anzeige["korrigiert_gesamt"] - anzeige["original_gesamt"]).map(
    "{:+,.2f}".format
)

spalten = [
    "Datum", "Wochentag", "Monat",
    "Tagesgesamt original (€)", "Wochentagsschnitt (€)",
    "Abweichung (%)", "Tagesgesamt korrigiert (€)", "Differenz (€)",
]
st.dataframe(anzeige[spalten], use_container_width=True, hide_index=True)

# Zusammenfassung
gesamt_diff = (korr_df["korrigiert_gesamt"] - korr_df["original_gesamt"]).sum()
col1, col2, col3 = st.columns(3)
col1.metric("Korrigierte Tage", len(korr_df))
col2.metric(
    "Gesamtkorrektur (€)",
    f"{gesamt_diff:+,.2f}",
    help="Positive Werte = Planwerte wurden nach oben korrigiert",
)
col3.metric(
    "Ø Abweichung",
    f"{korr_df['abweichung_pct'].abs().mean():.1f} %",
)

# Legende
st.divider()
st.subheader("Methodik")
st.markdown(f"""
**Wochentagsvalidierung** prüft, ob einzelne Tage im Vergleich zu gleichartigen
Wochentagen in den umliegenden Monaten auffällig abweichen.

**Vorgehen:**
1. Für jeden Planungstag wird der **Tagesgesamtumsatz** über alle Filialen aufsummiert.
2. Als Vergleichsbasis dienen alle normalen {WOCHENTAG_NAMEN[0]}e bis {WOCHENTAG_NAMEN[6]}e
   im gleichen Monat sowie im Vormonat und Folgemonat.
3. **Ausgeschlossen** vom Vergleich (und von der Validierung) werden Tage mit:
   - Feiertagen (aus der Feiertagstabelle)
   - Schulferien (aus der Ferientabelle)
4. Weicht ein Tag um mehr als **±{SCHWELLWERT_PCT:.0f} %** vom Wochentagsschnitt ab,
   wird sein Tagesgesamt auf den Schnitt **korrigiert**.
5. Die Korrektur wird per **Dreisatz** proportional auf alle Filialen verteilt:
   Jede Filiale erhält `Originalwert × (Wochentagsschnitt ÷ Tagesoriginalgesamt)`.

**Beispiel:** Liegen alle Mittwoche bei Ø 500.000 €, sticht ein Mittwoch mit 560.000 €
(+12 %) heraus → er wird auf 500.000 € korrigiert. Eine Filiale, die 10.000 € geplant hatte
(= 1/50 des Tagesgesamts), erhält danach `10.000 × (500.000 ÷ 560.000) ≈ 8.929 €`.
""")
