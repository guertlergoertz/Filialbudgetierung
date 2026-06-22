# UI-Seiten, Navigation und Implementierungsdetails

> Lesen vor Änderungen an: `ui/pages/*.py`, `app.py`, `ui/session.py`

---

## Navigation (app.py)

```
Input & Stammdaten:
  Filialen → Umsatz-Import → Filial-Öffnungstage → Feiertage u. Ferien
  → Schulfilialen → Datumsmapping → Preisanpassung

Berechnung & Validierung:
  Plausibilitätsprüfung → Planung ausführen → Herleitung → Planungsgenauigkeit
```

| Seite | Datei | Funktion |
|-------|-------|----------|
| Startseite | 1_Startseite.py | DB-Auswahl + Budgetjahr-Dropdown (nur linke Hälfte) |
| Filialen | 2_Filialen.py | Inline data_editor, Auto-Save, Delete-Bestätigung |
| Umsatz-Import | 3_Daten_Import.py | Excel/CSV, fil_nr-Validierung, dt. Zahlparser, Sicherheitsabfrage |
| Filial-Öffnungstage | 9_Oeffnungstage.py | Wochentag + Feiertag je Filiale, Auto-Save |
| Feiertage u. Ferien | 8_Feiertage_Import.py | Lädt alle 16 BL, Tabs: Feiertage/Sondertage/Ferien, BL-Filter, Auto-Save |
| Schulfilialen | 12_Schulfilialen.py | ≥80% Nullumsatz = Schulfiliale, Matrix-Editor, nur erkannte Filialen |
| Datumsmapping | 13_Datumsmapping.py | Mapping Budgettag→Basistag generieren + prüfen |
| Preisanpassung | 11_Preisanpassung.py | Wachstum % je Monat + Planjahr |
| Plausibilitätsprüfung | 14_Validierung.py | Ampel-Checks vor der Planung |
| Planung ausführen | 6_Planung.py | Berechnung, Bestätigungsdialog, Excel-Export |
| Herleitung | 10_Herleitung.py | Additive Effekte, Zeilenauswahl-Detailpanel |
| Planungsgenauigkeit | 7_Planungsgenauigkeit.py | Plan vs. IST, Abweichung nur bis IST-Importstand |

**Hinweis:** `4_Parameter.py` ist NICHT in der Navigation (orphan page). Wachstum-Editor
dort entfernt — einzige Quelle: `11_Preisanpassung.py`.

---

## Auto-Save Pattern

Alle `data_editor`-Seiten verwenden Auto-Save (kein Speichern-Button!):

```python
# Normierung vor Vergleich (Datums-Spalten!)
def _norm_for_compare(df, date_cols):
    out = df.copy()
    for c in date_cols:
        out[c] = pd.to_datetime(out[c], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.fillna("").astype(str)

# Vergleich
if not _norm_for_compare(orig, date_cols).equals(_norm_for_compare(edited, date_cols)):
    # ... DB-Update ...
    st.toast("✅ Gespeichert")
    st.rerun()
```

**Wichtig:** Datums-Spalten VOR dem Vergleich normalisieren — sonst Toast-Flackern
durch Timestamp-vs-date-Stringdifferenzen.

---

## Filter-Persistenz (Session State)

Alle `st.multiselect` / `st.selectbox` in Herleitung und Planungsgenauigkeit haben
`key=`-Parameter → Filterstand bleibt beim Seitenwechsel erhalten.

Keys:
- `herleitung_fil_filter`, `herleitung_bl_filter`, `herleitung_zeit`, `herleitung_entity`
- `plangenau_fil_filter`, `plangenau_bl_filter`, `plangenau_zeit`, `plangenau_entity`
- `datumsmapping_monat`, `datumsmapping_bl`, `datumsmapping_typ`

---

## Deutsches Zahlen- und Datumsformat

**Datum in der UI:** immer `DD.MM.YYYY`
```python
df["datum_de"] = pd.to_datetime(df["datum"]).dt.strftime("%d.%m.%Y")
# oder im data_editor:
st.column_config.DateColumn("Datum", format="DD.MM.YYYY")
```

**Zahlen deutsch formatieren:**
```python
f"{float(val):,.0f}".replace(",", "X").replace(".", ",").replace("X", ".")
# → "80.000" für 80000
```

**pd.NA / NaN sicher:**
```python
def _fmt_de(val):
    try:
        if pd.isna(val): return ""
    except (TypeError, ValueError): pass
    try:
        return f"{float(val):,.0f}".replace(",","X").replace(".",",").replace("X",".")
    except (TypeError, ValueError): return ""
```

**Multiselect-Placeholders:** immer auf Deutsch (`placeholder="Alle Bundesländer"` etc.).
Keine englischen "Choose options".

---

## Bundesland-Anzeige

- In der UI immer **ausgeschrieben**: `BL_ABBR_TO_NAME` dict in `8_Feiertage_Import.py`
- In der DB: 2-Buchstaben-Abkürzung (`"BW"`, `"BY"`, …) oder `"alle"`
- Bundesland als **erste Spalte** in Tabellen, dann nach BL → Datum sortieren
- BL-Filter in allen relevanten Seiten als `st.selectbox` mit "alle"-Option

---

## fil_nr Typ-Normierung

`fil_nr` in `ist_umsatz` immer TEXT, in `planung` kann INTEGER vorliegen.
**Überall `str(r["fil_nr"])` verwenden** beim Vergleich beider Tabellen.

---

## Herleitung-spezifische Patterns

**Nur berechnete Filialen anzeigen:**
```python
fil_has_data = df_all.groupby("fil_nr")[["budget","ist_vj"]].sum().abs().sum(axis=1) > 0
active_fils = set(fil_has_data[fil_has_data].index)
df_all = df_all[df_all["fil_nr"].isin(active_fils)]
```

**eff_norm ausgeblendet:** Nicht in `eff_cols`, nicht in `ordered`-Liste,
nicht im Tagesdetails-Expander, explizit gedroppt.

---

## Planungsgenauigkeit

- Liest `planung` + `ist_umsatz` live — kein Re-Plan nötig
- Abweichung € / % nur für Tage, an denen IST bereits importiert ist
  (`_budget_ist = Budget.where(IST aktuell notna)`)
- Caption zeigt "IST importiert bis TT.MM.JJJJ"
- Spalte "Budget" zeigt weiterhin volles Periodenbudget

---

## Spinner / Loading

CSS in `app.py` — spinning 🥨 Brezel:
```css
[data-testid="stStatusWidget"]::before { content: "🥨"; animation: brezel-spin 1.5s linear infinite; }
[data-testid="stStatusWidget"]::after { content: "Loading..."; }
```
