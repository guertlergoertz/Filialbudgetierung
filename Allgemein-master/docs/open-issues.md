# Offene Punkte & Änderungshistorie

> Lesen vor: neuen Features, Refactorings, am Sitzungsende zum Aktualisieren

---

## Behoben ✅

- **Zweite Berechnungslogik (Logik 2)** parallel implementiert: `planning/engine2.py`
  (`PlanningEngine2`), Tabelle `planung2`, UI-Seiten 15/16/17 (Planung/Herleitung/
  Planungsgenauigkeit, jeweils „L2"), Navigationsgruppe „Logik 2 (alternativ)".
  Vorgehen: Monatsumsatz-Vorjahr als Ausgangspunkt → Wochentags-Konstellation
  (globale Wochentagsanteile) → Preis → Sondertag-/Feiertag-/Ferien-Monatsverschiebung
  → Verteilung über Datumsmapping-Basistagsanteile. Gleiche additive Identität wie
  Logik 1 (Tests `tests/test_engine2.py`, eigener Golden-Run). Ziel: vergleichen,
  welche Logik besser ist, dann eine entfernen (06/2026)
- Datumsmapping/Ferien: Weihnachtsferien-Jahresgrenze korrekt gematcht — Januar-Plantage vergleichen mit Januar-VJ (nicht mehr 20.–31.12.); `match_ferien_periods()` per nächstem Startdatum (06/2026)
- Datumsmapping: Ferien-Plantage werden IMMER mit Ferientagen der VJ-Periode verglichen (Pfingst-/Sommer-/Herbst-/Weihnachtsferien) — Same-Month-Constraint entfernt, robuste Wochentags-/Wochen-Zuordnung innerhalb der VJ-Periode (06/2026)
- Datumsmapping: 24./31.12. als Quasi-Feiertage — nie Basistag für Normal-/Ferientage; Plan-24./31.12. → gleicher Kalendertag im Basisjahr (06/2026)
- Feiertage/Ferien: Basiszeiträume in der Ferien-Tabelle editierbar; Änderung aktualisiert VJ-`ferien_kalender` und triggert Datumsmapping-Neuberechnung (06/2026)
- Herleitung: Basisdatum-Spalte gefüllt (ISO-Datum durch Aggregation getragen, BL normalisiert) (06/2026)
- Herleitung: Verteilung-Spalte leer bei Sondertag/Feiertagstag/Feiertag/Ferien; Ferien-Spalte leer bei Ferien↔Ferien (06/2026)
- Regressionstest `tests/test_datumsmapping.py`: Ferien↔Ferien, Weihnachtsferien-Grenze, 24./31.12.-Ausschluss (06/2026)

- Deutsche Zahlformate beim Import (3.000 ≠ 3,0)
- Sicherheitsabfrage vor Neuimport
- BL-Normalisierung in der Engine (Heilige Drei Könige etc. greifen jetzt)
- ferien_kalender→ferien Sync vor Planung (Sync entfernt, Engine liest direkt)
- Sondertage aus feiertage-Tabelle werden von der Engine gelesen
- Planungsgenauigkeit: Abweichung nur bis IST-Importstand
- feiertag_name bei geschlossenen Feiertagen in der Herleitung sichtbar
- Datumsmapping (wochentagsbasiertes Basis-Referenz-Matching) implementiert
- Regressionstest-Suite (pytest, 14 Tests inkl. Golden-Run)
- Importer-Datumsbug: DD.MM.YYYY-Zeilen wurden stillschweigend verworfen
- Wachstums-Redundanz: Wachstum-Editor aus 4_Parameter entfernt
- Budgetjahr wird bei Firmenwechsel zurückgesetzt
- ferien/ferien_kalender-Dualität: Engine liest direkt aus ferien_kalender
- Engine modularisiert: plan_branch als Pipeline
- Plausibilitätsprüfungs-Seite (14_Validierung) mit Gesamtampel
- Schulferien Auto-Load via `holidays.SCHOOL` für alle 16 BL (06/2026)
- Feiertage-UI: BL-Filter, Spaltenumbenennung, Sortierung BL→Datum (06/2026)
- Datumsmapping: base_bezeichnung für Feiertagstage befüllt (06/2026)
- Validierung: Feiertage/Sondertage/Ferientage Vergleich Basis vs. Budget (06/2026)
- Budgetjahr: Auto-Korrektur in Sidebar wenn gespeichertes Jahr nicht in DB (06/2026)
- Planung: Alle planung-Zeilen des Jahres vor neuem Berechnungslauf gelöscht (06/2026)
- Datumsmapping: BL-Normalisierung → Heilige Drei Könige und BL-spezifische Feiertage jetzt korrekt (06/2026)
- Datumsmapping: stichtag-Fix → Basistag ≠ Budgettag für Planjahr = laufendes Jahr (06/2026)
- Datumsmapping: Separate Ferien-Spalten für Budget- und Basiszeitraum (06/2026)
- Feiertage/Ferien: Nur BL laden, die in Filialen-Stammdaten vorhanden; Erklärungstext (06/2026)
- Validierung: Feiertags-/Ferienvergleich nur für relevante BL (mit Filialen) (06/2026)
- Filialen-Massenimport: Akzeptiert Bundesland als Abkürzung (BY), lang (Bayern) oder DE-BY (06/2026)
- Herleitung: IST aktuell + Abw. IST € + Abw. IST % als letzte Spalten (06/2026)
- Planungsgenauigkeit: Genauigkeit % Spalte (100%−|Abw%|); Analyse-Abschnitt mit Top-Abweichungen (06/2026)
- Feiertage/Ferien: BL-Auswahllisten begrenzt auf in Filialen hinterlegte BL (06/2026)
- Feiertage/Ferien: Wochentagsspalten neben Datumsspalten in allen 3 Tabs (06/2026)
- Ferien: Automatische Wochenend-Verlängerung beim Laden (Fr/Sa-Ende → So; Mo-Start → Sa) (06/2026)
- Ferien: Basiszeitraum-Vergleich im Budgetjahr-Tab (Start/Ende Basis, Wochentage, Abweichung) (06/2026)
- Planung ausführen: Tabelle wird auch bei bereits gespeicherten Daten ohne Neu-Berechnung angezeigt (06/2026)
- Herleitung: Basisdatum-Spalte (Referenztag im Basiszeitraum) im Tag-View (06/2026)
- Engine: eff_verteilung/eff_wochentag/eff_preis = 0 für Ferien-Tage; alle Effekte in eff_ferien (06/2026)
- IST-Import: Alle bisherigen Daten werden beim Neuimport vollständig gelöscht (06/2026)
- Feiertage-Tab: Art-Spalte und Art-Filter entfernt; Wochentag als Kurzform (Mo/Di/…); Spaltenbreiten angepasst (06/2026)
- Sondertage-Tab: Bundesland-Filter und Methode-Spalte entfernt; Kurzform Wochentag; Spaltenbreiten (06/2026)
- Ferien-Tab: Bundesland-Filter entfernt; Beschreibung-Spalte direkt nach Bundesland; Kurzform Wochentag; 0-Abweichung leer (06/2026)
- Feiertagstage: Keine Feiertagstage für fixe Datumsfeiertage (1.1, 6.1, 1.5, 3.10, 1.11, 25./26.12); Himmelfahrt+Fronleichnam: Sa+So als Feiertagstage (06/2026)
- Datumsmapping: Ferien-Namen nicht mehr in Bezeichnung-Spalte (separate Ferien-Spalten); Button "Mapping generieren" entfernt; Spaltenbreiten angepasst (06/2026)
- Datumsmapping: Feiertagstage verwenden nun datum_vj als Basistag (korrekte Ostern-Offset-Vergleiche) (06/2026)
- Datumsmapping: Normale Tage vermeiden VJ-Feiertags- und Ferientage als Basistag (06/2026)
- Preisanpassung: Planjahr-Auswahl entfernt; immer das aktuelle Budgetjahr (06/2026)
- Herleitung: Δ€/Δ% nach =Budget entfernt; keine Zeilenmarkierung; Abw. IST nur bis letzten importierten Tag (06/2026)
- Engine: eff_feiertag=0 für offene Feiertage (wie direct_ferien-Behandlung: Vergleich Feiertag↔Feiertag) (06/2026)
- Filialstammdaten: flag_gesperrt (auto bei XX/XXX in Bezeichnung, manuell togglebar); gesperrte Filialen in Planung + Validierung ignoriert; Auto-Save ohne Speichern-Button (06/2026)
- Ferien: Oster-/Frühjahrsferien → Osterferien überall umbenannt (06/2026)
- Herleitung: 0-Werte leer; +Verteilung-Spalte entfernt; IST Basis per Live-Lookup aus ist_umsatz; ferien_art auch für Feiertag/Feiertagstag-Tage; eff_ferien immer leer für Ferien↔Ferien; Tagesinfo/Ferien Spaltenbreite automatisch (06/2026)
- Validierung: gesperrte Filialen korrekt erkannt (Muster + Flag); Filialen-ohne-IST-Check exkludiert gesperrte (06/2026)
- Datumsmapping: Ferienabschlag/-aufschlag — wenn kein gleicher Wochentag im VJ-Ferienzeitraum vorhanden, VORWÄRTS nächsten normalen Wochentag wählen; mapping_art='ferienabschlag' (06/2026)
- Engine: ferienabschlag-Branch — ist_vj des normalen Basistags × Wachstum × Ferienfaktor → eff_ferien (06/2026)
- Engine: _ferien_faktor_woche Fallback auf gesamte VJ-Ferienperiode wenn spez. Woche leer (06/2026)
- Engine: _ferien_faktor_fallback für Ferientypen ohne VJ-Periode (nutzt letzten gleichen/beliebigen Ferientyp desselben BL) (06/2026)

---

## Offen — hohe Priorität

| # | Thema | Risiko/Nutzen |
|---|-------|---------------|
| 17 | **Logik-Entscheidung**: Logik 1 (`engine.py`/`planung`) vs. Logik 2 (`engine2.py`/`planung2`) anhand realer Planungsgenauigkeit vergleichen, dann die unterlegene Logik inkl. Tabelle/Seiten/Tests entfernen | Hoch |
| 2 | **Sondertage-Legacy** abbauen: `sondertage`-Tabelle abschaffen, nur noch `feiertage` mit art='Sondertag' | Mittelfristig |
| 4 | **Engine-Performance**: `_ist_on()` O(Tage×Zeilen). Lösung: Lookup-Dict `{(fil_nr, iso): umsatz}` einmalig bauen | Laufzeit |
| 16 | **Herleitung: Neue Ferien ohne Vorjahreszeitraum**: Grundlogik implementiert via `_ferien_faktor_fallback` (letzten gleichen/beliebigen Ferientyp des BL verwenden). Noch zu prüfen: Qualität der Schätzung in der Praxis. | Niedrig |

---

## Offen — mittlere Priorität

| # | Thema |
|---|-------|
| 7 | Feiertagsreferenz-Algorithmus: Vergleich mit umliegenden Sonntagen statt einfachem datum_vj |
| 8 | Ramadan-/Fasching-Effekt: Parameter vorhanden, Berechnung fehlt |
| 9 | Tooltip Herleitung: echte Zellen-Tooltips bräuchten Ag-Grid (Streamlit unterstützt keine) |
| 10 | `ensure_filialen_from_ist` nutzt Default "DE-RP" (Alt-Format) — auf "RP" umstellen |
| 12 | Warengruppen-Budget: bewusst Out of Scope |
| 13 | `liefer_plan` ist Dead Code (immer 0.0) — Spalte bleibt (No-Drop-Regel) |
| 14 | `_ferien_cache` je `plan_branch()`-Aufruf neu init — Performance-Optimierung möglich |

---

## Änderungshistorie

| Git-Hash | Beschreibung |
|----------|-------------|
| `98c4eaa` | Ferienabschlag-Logik (VORWÄRTS-Fallback, mapping_art='ferienabschlag', Engine-Branch); _ferien_faktor_fallback; Filialen Auto-Save |
| `9544e68` | CLAUDE.md aufgeteilt in docs/architecture, ui-patterns, open-issues; Datenschutzregel |
| `49000d9` | Feiertage/Ferien: BL-Filter, Schulferien auto alle 16 BL, Spaltenumbenennung; Datumsmapping: Feiertagstag in Basisbeschreibung; Validierung: 3 neue Vergleichs-Checks |
| `39fc92b` | Plausibilitätsprüfungs-Seite (14_Validierung) mit Ampel-Checks |
| `d5971f9` | Engine: plan_branch in Pipeline-Methoden modularisiert |
| `10cc2fe` | Engine liest Ferien direkt aus ferien_kalender, Sync entfernt |
| `457ddb7` | Budgetjahr-Reset bei Firmenwechsel |
| `fc5d42d` | Doppelter Wachstum-Editor aus 4_Parameter entfernt |
| `3bef718` | Regressionstest-Suite + Importer-Datumsbug-Fix |
| `0cb9ca8` | Logo margin-top, Budgetjahr-Dropdown, Datumsmapping Feiertagstage/Ferien-Beschreibungen |
| `f8b1118` | German UI-Polish: Auto-Save Öffnungstage, Budgetjahr-Dropdown, Datumsmapping-Redesign |
| `071ae5d` | Bugfix: ISO-String-Variable im plan_branch-Inner-Loop |
| `84d0ebe` | Datumsmapping implementiert, Logo-Größe verdoppelt |
| `67c3c85` | Planungsgenauigkeit Abw.-Fix; Engine liest Sondertage aus feiertage; CLAUDE.md überarbeitet |
| `1bce35d` | BL-Normalisierung in Engine, feiertag_name bei Schließung, Schulfilialen nur erkannte |
| `49edbb2` | Deutscher Zahlparser im Import, Import-Sicherheitsabfrage, Feiertage-Seite |
| `5588984` | Navigation: Öffnungstage nach Umsatz-Import |
| `71a6199` | German placeholders, Filter-Persistenz, 0-Branch-Filter Herleitung |
| `d3a47e2` | Feiertagstag-Bug (art-Filter), Herleitung Tag-Ebene, Planungsgenauigkeit Abw. fix |
| `ceef823` | Filter-First-Layout, Zeilenauswahl-Detailpanel, DELETE-before-INSERT, Brezel-Spinner |
| `5472f92` | Logos zurück in Sidebar, zentrierter Loader, leere Tabellen-Fix |
| `4c3623f` | UX-Überarbeitung: Sidebar Firma+Budgetjahr+Basiszeitraum, Auto-Save |
| `93ce825` | Rolling Basiszeitraum, Öffnungstage, Per-Woche-Ferienfaktoren, additive Herleitung |
| `d036d04` | Auto-Feiertag-Loader (16 BL + Fasching + Muttertag) |
| `594f7cb` | Filialen Inline-Edit, Schulfilialen-Seite, Preisanpassung-Seite |
| `e107e37` | CLAUDE.md erstellt |
