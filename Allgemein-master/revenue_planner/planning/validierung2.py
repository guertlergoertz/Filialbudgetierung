"""Wochentagsvalidierung für Planwerte aus Engine 2."""
from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

SCHWELLWERT_PCT = 10.0
WOCHENTAG_NAMEN = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _lade_ausschlusstage(conn: duckdb.DuckDBPyConnection, plan_jahr: int) -> set[date]:
    """Gibt alle Tage zurück, die von der Validierung ausgeschlossen werden (Feiertage + Ferien)."""
    ausschluss: set[date] = set()

    try:
        df_ft = conn.execute("""
            SELECT datum FROM feiertage
            WHERE year(datum) IN (?, ?, ?)
        """, [plan_jahr - 1, plan_jahr, plan_jahr + 1]).df()
        for d in df_ft["datum"]:
            ausschluss.add(pd.Timestamp(d).date())
    except Exception:
        pass

    try:
        df_f = conn.execute("""
            SELECT datum_von, datum_bis FROM ferien
            WHERE year(datum_von) IN (?, ?, ?) OR year(datum_bis) IN (?, ?, ?)
        """, [plan_jahr - 1, plan_jahr, plan_jahr + 1,
              plan_jahr - 1, plan_jahr, plan_jahr + 1]).df()
        for _, row in df_f.iterrows():
            von = pd.Timestamp(row["datum_von"]).date()
            bis = pd.Timestamp(row["datum_bis"]).date()
            cur = von
            while cur <= bis:
                ausschluss.add(cur)
                cur += timedelta(days=1)
    except Exception:
        pass

    return ausschluss


def validiere_und_korrigiere_planwerte2(
    conn: duckdb.DuckDBPyConnection,
    plan_jahr: int,
) -> pd.DataFrame:
    """
    Vergleicht Tagesumsätze (Summe aller Filialen) je Wochentag mit den umliegenden Monaten.
    Tage mit >10% Abweichung werden auf den Wochentagsschnitt korrigiert.
    Die Korrektur wird per Dreisatz auf die einzelnen Filialen heruntergerechnet.

    Returns:
        DataFrame mit Korrekturdetails für die Anzeige in Herleitung2.
    """
    df = conn.execute("""
        SELECT filiale, datum, planwert
        FROM planwerte
        WHERE engine = '2' AND year(datum) = ?
        ORDER BY datum, filiale
    """, [plan_jahr]).df()

    if df.empty:
        return pd.DataFrame()

    df["datum"] = pd.to_datetime(df["datum"]).dt.date

    # Tagesgesamtumsatz über alle Filialen
    daily = (
        df.groupby("datum")["planwert"]
        .sum()
        .reset_index()
        .rename(columns={"planwert": "gesamt"})
    )
    daily["monat"] = [d.month for d in daily["datum"]]
    daily["wochentag"] = [d.weekday() for d in daily["datum"]]  # 0=Mo, 6=So

    ausschlusstage = _lade_ausschlusstage(conn, plan_jahr)
    daily["ist_normal"] = ~daily["datum"].isin(ausschlusstage)

    normal_daily = daily[daily["ist_normal"]].copy()

    korrekturen = []

    for _, row in normal_daily.iterrows():
        monat = row["monat"]
        wd = row["wochentag"]
        datum = row["datum"]
        gesamt = row["gesamt"]

        # Umliegende Monate (Monatsarithmetik im gleichen Jahr; Jahresgrenzen werden ignoriert)
        umgebende_monate = {monat}
        if monat > 1:
            umgebende_monate.add(monat - 1)
        if monat < 12:
            umgebende_monate.add(monat + 1)

        vergleichsgruppe = normal_daily[
            (normal_daily["wochentag"] == wd)
            & (normal_daily["monat"].isin(umgebende_monate))
        ]

        if len(vergleichsgruppe) < 2:
            continue

        schnitt = vergleichsgruppe["gesamt"].mean()

        if schnitt == 0:
            continue

        abweichung_pct = (gesamt - schnitt) / schnitt * 100.0

        if abs(abweichung_pct) > SCHWELLWERT_PCT:
            korrekturen.append(
                {
                    "datum": datum,
                    "wochentag": wd,
                    "monat": monat,
                    "original_gesamt": gesamt,
                    "wd_schnitt": schnitt,
                    "abweichung_pct": abweichung_pct,
                    "korrigiert_gesamt": schnitt,
                }
            )

    if not korrekturen:
        return pd.DataFrame(
            columns=[
                "datum", "wochentag", "monat",
                "original_gesamt", "wd_schnitt",
                "abweichung_pct", "korrigiert_gesamt",
            ]
        )

    korr_df = pd.DataFrame(korrekturen)

    # Korrekturen per Dreisatz auf Filialen herunterrechnen und in DB schreiben
    for _, korr in korr_df.iterrows():
        d = korr["datum"]
        original = korr["original_gesamt"]
        korrigiert = korr["korrigiert_gesamt"]

        if original == 0:
            continue

        faktor = float(korrigiert) / float(original)

        conn.execute("""
            UPDATE planwerte
            SET planwert = planwert * ?
            WHERE engine = '2' AND datum = ?
        """, [faktor, d])

    # Korrekturtabelle aktualisieren
    conn.execute("DELETE FROM planwert_korrekturen2 WHERE year(datum) = ?", [plan_jahr])
    for _, korr in korr_df.iterrows():
        conn.execute("""
            INSERT INTO planwert_korrekturen2
                (datum, wochentag, monat, original_gesamt, wd_schnitt, abweichung_pct, korrigiert_gesamt)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [
            korr["datum"],
            int(korr["wochentag"]),
            int(korr["monat"]),
            float(korr["original_gesamt"]),
            float(korr["wd_schnitt"]),
            float(korr["abweichung_pct"]),
            float(korr["korrigiert_gesamt"]),
        ])

    return korr_df
