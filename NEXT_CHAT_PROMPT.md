# Prompt für nächste Chat-Sitzung

Kopiere den folgenden Block als erste Nachricht in einen neuen Chat:

---

Wir arbeiten an einer Streamlit + SQLite App zur Filial-Umsatzplanung (Bäcker Görtz / Papperts).
Bitte lies zuerst `CLAUDE.md` im Repo für den vollständigen Projektkontext.

**Repo:** `dguertler/Allgemein`, Branch: `master`
**Arbeitsverzeichnis:** `revenue_planner/`

## Ausstehende Aufgaben (Priorität absteigend)

### 1. DATUMSMAPPING implementieren (Hohe Priorität)

Die Engine nutzt aktuell für jeden Plantag denselben Kalendertag im Basisjahr
(`_safe_date(base_year, month, day)`). Das führt zu Fehlern wenn dieser Tag im
Basisjahr ein Sonntag, Feiertag oder Ferientag war (ist_vj=0, eff_verteilung
übernimmt gesamten Tageswert — irreführend).

**Lösung:** Wochentagsbasiertes Datumsmapping:
- Neue DB-Tabelle `datumsmapping (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art)`
- Mapping-Regeln:
  1. Feiertag → Feiertag (Christi Himmelfahrt 2026 ↔ Christi Himmelfahrt 2025)
  2. Ferientag Woche N → Ferientag Woche N (je Bundesland)
  3. Normaltag → gleicher Wochentag in ISO-KW des Basisjahres
- Neue UI-Seite „Datumsmapping" zwischen Schulfilialen und Planung ausführen
  (Tabelle wie im Bild: Datum | Wochentag | Typ | Referenz | Wochentag | Typ | BL-Spalten)
- Engine-Anpassung: `ist_vj = _ist_on(fil_nr, mapping[(plan_datum, bl)].base_datum)`

### 2. IST Basis-Wert-Fix für Sonntag/Feiertag im Basisjahr

Bereits diskutiert: Wenn Basistag = Sonntag/geschlossen, ist_vj=0 → eff_verteilung
verzerrt. Nach Datumsmapping-Implementierung automatisch behoben.

### 3. Tooltips Herleitung

Streamlit unterstützt keine Hover-Tooltips auf einzelnen Tabellenzellen.
Aktueller Stand: Spalten-Header haben `help=`-Text, Zeilenklick zeigt Detail-Panel.
Falls echte Zellen-Tooltips gewünscht: Ag-Grid-Component einbinden oder
beim Klick auf eine Zelle mehr Info im Detail-Panel zeigen.

### 4. eff_norm vollständig aus Logik entfernen (optional)

Aktuell: in DB gespeichert, aus UI ausgeblendet.
Falls vollständige Entfernung gewünscht: DayPlan-Dataclass anpassen,
engine.py save() anpassen, schema.py Migration hinzufügen.
Budget bleibt `raw * norm` — die monatliche Genauigkeit geht verloren ohne Norm.

### 5. Ramadan-Effekt + Fasching-Wirkung

`apply_ramadan` und `apply_fasching` in PlanParams bereits angelegt, Logik fehlt.

## Technische Hinweise

- fil_nr IMMER als str() normieren wenn ist_umsatz und planung verglichen werden
- eff_norm in UI nicht anzeigen (in DB belassen)
- Auto-Save Pattern für alle Editoren (kein Speichern-Button)
- Filter-Keys für Session-State-Persistenz: herleitung_fil_filter, plangenau_fil_filter, etc.
- Am Ende der Sitzung: CLAUDE.md updaten + alles auf master pushen
