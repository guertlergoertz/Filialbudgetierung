"""Wochentagsvalidierung für Planwerte (die Planung) — arbeitet auf SQLite-Verbindung."""
from __future__ import annotations

import sqlite3

import pandas as pd

SCHWELLWERT_PCT = 10.0
WOCHENTAG_NAMEN = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def validiere_und_korrigiere_planwerte2(
    conn: sqlite3.Connection,
    plan_jahr: int,
) -> pd.DataFrame:
    """
    Vergleicht den Tages-Budget-Gesamtumsatz (Summe budget_i aller Filialen)
    je Wochentag mit den umliegenden Monaten (M-1, M, M+1).

    Ausgeschlossen werden:
    - Tage, deren tagestyp im Planjahr ein Sonder-/Feiertagstyp ist
      (feiertag, feiertagstag, sondertag, ferien)
    - Tage, deren Basis-Datum laut Datumsmapping ein Sonder-/Feiertagstag war
      (mapping_art IN feiertag, feiertagstag, sondertag) — z. B. der Dienstag
      nach Ostermontag, dessen IST-Basis aus dem entsprechenden Feiertagstag
      des Vorjahres stammt

    Weicht ein Tag um mehr als ±10 % vom Budget-Wochentagsschnitt ab, wird
    das Budget via eff_validierung auf den Schnittfaktor korrigiert und per
    Dreisatz proportional auf alle Filialen verteilt.
    """
    # Tages-Budget-Gesamtumsatz über alle Filialen (nur offene Tage)
    rows = conn.execute("""
        SELECT datum,
               SUM(COALESCE(budget_i, 0))                     AS tages_ist,
               MAX(wochentag)                                  AS wochentag,
               CAST(strftime('%m', datum) AS INTEGER)          AS monat
        FROM planung2
        WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?
          AND tagestyp != 'geschlossen'
        GROUP BY datum
        ORDER BY datum
    """, (plan_jahr,)).fetchall()

    if not rows:
        return pd.DataFrame()

    # Ausschlusstage:
    # 1) Plan-Jahr-Tagestyp ist sonder-/feiertagsartig
    # 2) Basis-Datum im Datumsmapping war ein Sonder-/Feiertagstag
    #    (mapping_art zeigt den Charakter des Vorjahres-Referenztags)
    ausschluss_rows = conn.execute("""
        SELECT DISTINCT p.datum
        FROM planung2 p
        WHERE CAST(strftime('%Y', p.datum) AS INTEGER) = ?
          AND (
            p.tagestyp IN ('feiertag', 'feiertagstag', 'sondertag', 'ferien')
            OR EXISTS (
                SELECT 1 FROM datumsmapping dm
                WHERE dm.plan_datum = p.datum
                  AND dm.mapping_art IN ('feiertag', 'feiertagstag', 'sondertag')
            )
          )
    """, (plan_jahr,)).fetchall()
    ausschluss: set[str] = {r[0] for r in ausschluss_rows}

    daily = []
    for r in rows:
        daily.append({
            "datum": r[0],
            "gesamt": float(r[1] or 0),
            "wochentag": int(r[2]),
            "monat": int(r[3]),
            "normal": r[0] not in ausschluss,
        })

    # Nur Normaltage für Vergleichs-Baseline
    normal_daily = [d for d in daily if d["normal"]]

    korrekturen = []
    for row in normal_daily:
        datum = row["datum"]
        monat = row["monat"]
        wd = row["wochentag"]
        gesamt = row["gesamt"]

        # Umliegende Monate (M-1, M, M+1)
        monate = {monat}
        if monat > 1:
            monate.add(monat - 1)
        if monat < 12:
            monate.add(monat + 1)

        vergleich = [
            d for d in normal_daily
            if d["wochentag"] == wd and d["monat"] in monate
        ]

        if len(vergleich) < 2:
            continue

        schnitt = sum(d["gesamt"] for d in vergleich) / len(vergleich)
        if schnitt == 0:
            continue

        abweichung_pct = (gesamt - schnitt) / schnitt * 100.0

        if abs(abweichung_pct) > SCHWELLWERT_PCT:
            korrekturen.append({
                "datum": datum,
                "wochentag": wd,
                "monat": monat,
                "original_gesamt": gesamt,
                "wd_schnitt": schnitt,
                "abweichung_pct": abweichung_pct,
                "korrigiert_gesamt": schnitt,
            })

    if not korrekturen:
        return pd.DataFrame(columns=[
            "datum", "wochentag", "monat",
            "original_gesamt", "wd_schnitt", "abweichung_pct", "korrigiert_gesamt",
        ])

    korr_df = pd.DataFrame(korrekturen)

    # Korrekturen per Dreisatz auf Filialen herunterrechnen.
    # Faktor aus Budget-Abweichung, angewendet auf budget_i via eff_validierung.
    # SQLite evaluiert alle SET-Ausdrücke mit den alten Spaltenwerten (atomic update).
    for _, korr in korr_df.iterrows():
        d = korr["datum"]
        original = korr["original_gesamt"]
        korrigiert = korr["korrigiert_gesamt"]

        if original == 0:
            continue

        faktor = float(korrigiert) / float(original)

        conn.execute("""
            UPDATE planung2
            SET eff_validierung = COALESCE(eff_validierung, 0) + budget_i * (? - 1.0),
                budget           = budget_i * ?
            WHERE datum = ? AND tagestyp != 'geschlossen'
        """, (faktor, faktor, d))

    # Korrekturtabelle aktualisieren
    conn.execute(
        "DELETE FROM planwert_korrekturen2 "
        "WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?",
        (plan_jahr,),
    )
    for _, korr in korr_df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO planwert_korrekturen2
                (datum, wochentag, monat, original_gesamt, wd_schnitt, abweichung_pct, korrigiert_gesamt)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            korr["datum"],
            int(korr["wochentag"]),
            int(korr["monat"]),
            float(korr["original_gesamt"]),
            float(korr["wd_schnitt"]),
            float(korr["abweichung_pct"]),
            float(korr["korrigiert_gesamt"]),
        ))

    conn.commit()
    return korr_df
