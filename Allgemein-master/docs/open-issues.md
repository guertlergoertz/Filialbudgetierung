# Offene Punkte & Änderungshistorie

> Lesen vor: neuen Features, Refactorings, am Sitzungsende zum Aktualisieren

---

## Behoben ✅

- **Feiertagstag-Datumsmapping, Hochrechnung ref-base, Tagesinfo, Planungsgenauigkeit** (06/2026):
  `datumsmapping`: Step 6 (VJ-Tagesvermeidung) läuft jetzt nur noch wenn `_used_iso_kw=True`
  (kein explizites datum_vj vorhanden). Feiertagstage mit gesetztem datum_vj werden nicht mehr
  in der VJ verschoben — behebt 02.04.2026 RP (Feiertagstag in Osterferien) → 10.04.2025 falsch
  → 17.04.2025 korrekt. `engine2.run`: `ref_day_budgets` akkumuliert wieder `dp.budget` statt
  `dp.gewuenschter_monatsumsatz`. `13_Herleitung2`: Tagesinfo-Spalte zeigt Umbau/Filialeröffnung/
  Filialschließung/geschlossen aus Filialstammdaten (umbau_von/bis, eroeffnung, eroeffnung_ende).
  Planungsgenauigkeit aus Navigation + Menü entfernt (3 Dateien gelöscht).
  CLAUDE.md Regel 14: Modul-Isolation (nur explizit beauftragtes Modul ändern).

- **Umbau-Hochrechnung, Feiertagstag-Schließung, wt_shares-Ausschluss, Öffnungstage-Fenster** (06/2026):
  `2_Filialen`: Infotext von Schließdaten auf Umbau-Beschreibung geändert.
  `importer.detect_oeffnungstage`: Wochentag-Erkennung nutzt nur letzten 3 Wochen IST (nicht gesamten Basiszeitraum).
  `engine._relevant_feiertagstag()` hinzugefügt; `engine2._closed_and_type` prüft Feiertagstage
  gegen `filial_feiertag` → Fil. 60 / Tag nach CHH (29.05.2025) war im Basiszeitraum geschlossen,
  wird jetzt auch im Budgetjahr als geschlossen geplant.
  `engine2.plan_branch`: `umbau_hochrechnung_month` → `umbau_hochrechnung_months` (set[int]);
  Imputation nur für Start-/Endmonat des Umbaus im Budgetjahr, nicht für alle Monate mit 0-IST-Basis.
  `engine2.run`: erfasst beide Umbau-Monate (Start + Ende) wenn diese im Budgetjahr liegen.
  `ref_day_budgets` akkumulierte `gewuenschter_monatsumsatz` statt `budget` (später rückgängig gemacht).
  `_wt_shares_for_branch`/`_ref_wt_sums`: Feiertage/Feiertagstage/Ferien/Sondertage aller
  beteiligten BL (Union-Ausschluss) aus Zähler und Nenner entfernt, damit Zeitreihen vergleichbar.

- **Filialstammdaten: leere Zellen + Scroll-Reset + Plausibilitätsbadge + Ferienschließungen + Feiertag-Budgetregel** (06/2026):
  `geplanter_umsatz_monat`: `fillna(0.0)` entfernt → leere Zellen bleiben leer; Format von ungültigem `",.0f €"` auf `"%.0f €"` (gültiges printf) geändert. `_norm_cmp()` normalisiert Datums- und Zahlspalten vor `equals()`-Vergleich, verhindert falsche `_changed=True`-Trigger und Scroll-to-top beim Verlassen einer Zelle.
  Plausibilitätsprüfung Check 7b: `"crit"` (❌) wenn Filiale ohne Umsatz im letzten Basismonat **und** ohne Umbaudatum; `"warn"` wenn Umbaudatum vorhanden. Menü-Badge ❌ nur noch bei kritischen Fehlern oder offener Checkliste (nicht bei Warnungen).
  Schulfilialen → **Ferienschließungen** umbenannt (Nav + Seitentitel). `detect_schulfilialen()` filtert jetzt auf Werktage Mo–Fr bevor die 80%-Schwelle angewendet wird.
  engine2: Feiertage werden nur budgetiert wenn die Filiale im Basiszeitraum an diesem Feiertag offen war (`raw_basis_ist > 0`). Feiertage mit 0-Basis-IST geben `budget=0 / tagestyp=geschlossen` zurück. Imputation-Pfad: `m["base_ist"] >= _MIN_IST` als zusätzliche Bedingung verhindert Imputation für Feiertage, an denen die Filiale tatsächlich geschlossen war. Umbau-Hochrechnung funktioniert bereits korrekt durch Dreisatz (monat_basis = voller Basismonat, verteilt nur auf offene Tage).

- **Engine2 Redesign: Dreisatz-Verteilung, budget_i/Budget II, neue Feiertag-Shift-Logik** (06/2026):
  Vollständiger Umbau von `planning/engine2.py`. IST-Basis = `anteil × monat_basis` (Dreisatz:
  Raw-Basis-IST als Gewichte). Feiertag-Shift: `_same_month_normal_avg` (gleicher Monat,
  Sonntagsschnitt für echte Feiertage, WT-Schnitt für Feiertagstage/Sondertage). Ferien-Shift:
  `_neighbour_weekday_avg` (3 Nachbarmonate, unverändert). Neue Spalten `budget_i`
  (Budget I = vor Validierung) und `gewuenschter_monatsumsatz` in `planung2` + `DayPlan`.
  Validierung2 liest `SUM(COALESCE(budget_i, 0))` und schreibt `budget = budget_i × faktor`.
  `eff_verteilung` und `eff_norm` immer 0. Geschlossene Tage: alle Spalten = 0 (inkl. `ist_vj`).
  Additive Identität: `budget_i = ist_vj + eff_oeffnung + eff_hochrechnung + eff_wochentag
  + eff_preis + eff_ferien + eff_feiertag`. UI 13_Herleitung2: neue Spaltenreihenfolge,
  „= Budget I" / „= Budget II", „=gew. Monatsumsatz", alle „Logik 2"-Labels entfernt.
  Golden-Werte unverändert (mathematisch identisch). 6/6 Tests grün.

- **Logik 2 Eröffnungs-Blackout für Basistage + Ladebalken-Overcounting** (06/2026):
  `plan_branch()`: Nach `_ist_on()` wird `base_ist` auf 0 gesetzt, wenn `base_d` innerhalb
  der ersten 4 Wochen nach `eroeffnung` der Filiale liegt (gleicher Cutoff wie `_weekday_share`).
  Opening-Tage haben atypisch hohe/niedrige Umsätze (Neueröffnungseffekt) und dürfen nicht
  als Referenz dienen; betroffene Plantage werden stattdessen per Imputation hochgerechnet.
  Behoben: große negative `eff_verteilung` an 26.–28.02.2026 (Fil. 313, Mapping auf
  Eröffnungswoche), falsche Abzüge an Faschingstagen 2026. `run()`: `done += 1` in Pass 1
  für `new_fil_nrs` entfernt — sie wurden ohne Callback vorgezählt, sodass `done > n_total`
  in Pass 2 entstand und der Ladebalken >100 % anzeigte.

- **Datumsmapping: Normaltage dürfen nicht auf VJ-Feiertagstage/Sondertage landen** (06/2026):
  `_vj_special_bl` (Feiertagstage + Sondertage im Basiszeitraum, per BL) in `datumsmapping.py`
  aufgebaut und im `_avoid`-Prädikat (Schritt 6, ISO-KW-Fallback) ergänzt. Ohne Fix landete z. B.
  der normale Sonntag 1. März 2026 (ISO-KW 9) auf dem Fasching-Sonntag 2. März 2025, einem
  Feiertagstag. Regressionstest `test_normal_day_does_not_map_to_vj_feiertagstag` sichert das ab.
- **Logik 2 eff_verteilung bei monatsübergreifenden Sondertagen/Feiertagstagen/Ferien** (06/2026):
  Wenn Phase 2 einen Auf-/Abschlag für einen Tag berechnet, dessen `base_d.month ≠ plan_month`
  ist, wird `neigh_ref` (Nachbar-Wochentags-Ø) in den Day-Metas gespeichert. `_build_day` nutzt
  `neigh_ref` statt des rohen `base_ist` für `eff_verteilung`, sodass `eff_verteilung` nahe 0
  bleibt (wie bei Normaltagen). Die Differenz `neigh_ref − ist_vj` wird in `eff_feiertag` /
  `eff_ferien` verschoben; die additive Identität gilt exakt.
- **Logik 2 Neue-Filiale-Imputation: Schwellwert auf < 100 € gesenkt** (06/2026):
  Trigger von `base_ist == 0.0` auf `base_ist < _MIN_IST` (100 €) geändert, damit Tage mit
  geringem Vergleichsumsatz (z. B. 50 €) ebenfalls über Wochentagsanteile hochgerechnet werden.

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
| 19 | **Fil 17: fehlende Vergleichsumsätze im Februar** — im Herleitung-View fehlt für Fil 17 eine ganze Woche Basis-IST im Februar, obwohl die Filiale laut Import offen war. Ursache unklar (möglicher Datumsmapping-Fehler oder Import-Lücke). Prüfung per DB-Strukturabfrage empfohlen. | Mittel |
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
| `0ba239b` | Filialstammdaten leer/Format/Scroll, Plausibilitätsbadge, Ferienschließungen, Feiertag-Budgetregel |
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
