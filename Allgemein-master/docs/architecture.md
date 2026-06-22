# Architektur & Datenbankschema

> Lesen vor Änderungen an: `engine.py`, `schema.py`, `datumsmapping.py`, `importer.py`

---

## Datenfluss (Ende-zu-Ende)

```
1. Filialen anlegen (2_Filialen)          → filialen
2. IST-Umsätze importieren (3_Daten)      → ist_umsatz (UPSERT!) + Auto-Öffnungstage
3. Feiertage/Ferien laden (8_Feiertage)   → feiertage (art: feiertag|feiertagstag|Sondertag)
                                          → ferien_kalender (Schulferien je BL/Jahr)
4. Öffnungstage prüfen (9_Oeffnungstage)  → filial_oeffnung, filial_feiertag
5. Schulfilialen erkennen (12_Schulfil.)  → filial_schulferien
6. Wachstum je Monat (11_Preisanpassung)  → parameter_monat
7. Plausibilität prüfen (14_Validierung)  → Ampel-Checks (kein Schreiben)
8. Planung ausführen (6_Planung)          → Engine (liest ferien_kalender direkt) → planung
9. Validierung: 10_Herleitung (Effekt-Wasserfall), 7_Planungsgenauigkeit (Plan vs. IST)
```

**Wichtig:** Ein IST-Import löst KEINE Neuberechnung der Planung aus — die
Planungsgenauigkeit liest IST live. Nur eine geänderte Basis erfordert bewusst eine
neue Planung.

---

## Datenbankschema (SQLite)

### Stammdaten
```sql
filialen (fil_nr TEXT PK, bezeichnung, bundesland, aktiv,
          eroeffnung TEXT, eroeffnung_ende TEXT, flag_kein_wachstum INTEGER)
```

### IST-Daten
```sql
ist_umsatz (fil_nr TEXT, datum TEXT, umsatz REAL)  -- UNIQUE(fil_nr, datum)
-- fil_nr IMMER als TEXT (importer.py: astype(str).strip())
-- datum IMMER als ISO "YYYY-MM-DD"
-- Import ist ein UPSERT (INSERT OR REPLACE je fil_nr+datum)
```

### Feiertage / Sondertage
```sql
feiertage (id, datum_plan TEXT, datum_vj TEXT, name TEXT, bundesland TEXT, art TEXT)
  -- art: 'feiertag' | 'feiertagstag' | 'Sondertag'
  -- 'feiertagstag' = Vor-/Nachtage — Engine filtert nur art='feiertag'!
  -- bundesland: Abkürzung 'BW','BY',… oder 'alle'
sondertage (id, datum_plan, datum_referenz, bezeichnung, methode, bundesland)
  -- methode: 'samstag' | 'referenz' — LEGACY (s. Stolperfallen)
```

### Öffnungszeiten
```sql
filial_oeffnung  (fil_nr, wochentag INT, offen INT)  -- 0=Mo…6=So
filial_feiertag  (fil_nr, feiertag_name TEXT, offen INT)
ferien_faktor    (fil_nr, bundesland, ferien_art, woche INT, faktor REAL)
```

### Schulferien
```sql
ferien (id, bundesland, art, start_vj, ende_vj, start_plan, ende_plan)
  -- DEPRECATED (06/2026): Engine liest direkt aus ferien_kalender.
  -- Tabelle bleibt wegen No-Drop-Regel (nicht mehr befüllen!)
ferien_kalender (bundesland, art, jahr, start, ende)  -- EINZIGE Quelle der Wahrheit
filial_schulferien (fil_nr, ferien_art, bundesland, geschlossen)
```

### Planungsergebnis
```sql
planung (
    fil_nr, datum, bundesland, wochentag,
    ist_vj,         -- IST-Umsatz des Basiszeitraum-Referenztags
    eff_oeffnung,   -- Effekt neue/weggefallene Öffnungstage
    eff_verteilung, -- IST-Einzeltag → Wochentags-Ø des Monats
    eff_wochentag,  -- Wochentagsmix-Effekt Planjahr vs. Basisjahr
    eff_preis,      -- Preis-/Wachstumsfaktor
    eff_ferien,     -- Ferieneffekt (per Ferienwoche)
    eff_feiertag,   -- Feiertagseffekt
    eff_norm,       -- Normierungsrest (in UI ausgeblendet, in DB vorhanden)
    budget,         -- Tagesbudget = Summe aller Effekte + ist_vj
    monat_basis, monat_hoch, monat_plan,
    tagestyp TEXT,  -- 'normal'|'feiertag'|'sondertag'|'ferien'|'geschlossen'
    feiertag_name, ferien_art, normalisierung,
    tagesumsatz_plan, gesamt_plan  -- Backwards-compat-Spalten
)
```

### Sonstige
```sql
parameter_monat (planjahr, monat, wachstum_pct)
planwert_override (fil_nr, planjahr, monat, planwert)
neue_filialen_plan (fil_nr, planjahr, monat, planwert, eroeffnung_datum)
datumsmapping (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art)
```

---

## Planungslogik (engine.py)

### Basiszeitraum (Rolling 12 Monate)
- **Stichtag:** `date(today.year, 1, 1)` wenn `planjahr <= today.year`, sonst `date.today()`
- **Basiszeitraum** = 12 Monate endend am letzten Monat vor Stichtag
- Methoden: `_compute_base_window()`, `base_year_for_month(month)`, `base_window_label()`

### Additive Effektzerlegung (exakte Identität — NIE brechen!)
```
budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
       + eff_preis + eff_ferien + eff_feiertag + eff_norm
```
- `eff_norm` in DB, aber aus allen UI-Anzeigen ausgeblendet
- Identität gilt exakt auf Tagesebene und über alle Aggregationen
- Änderungen nur mit Regressionstest

### Datumsmapping
- `planning/datumsmapping.py`, Tabelle `datumsmapping`, UI-Seite 13_Datumsmapping
- Wochentagsbasiertes Matching: gleicher Wochentag in ISO-KW des Basisjahrs
- Feiertag-zu-Feiertag Matching (via datum_vj)
- Ferienwochen-Matching je Bundesland
- Muss NEU generiert werden wenn Feiertage/Sondertage/Ferien geändert werden —
  **auch bei Änderung der Basiszeiträume**. Alle drei Editier-Tabs in
  8_Feiertage rufen nach jedem Speichern `_auto_datumsmapping` auf.

#### Harte Garantien (Regressionstest `tests/test_datumsmapping.py` — NIE brechen!)
1. **Ferien ↔ Ferien:** Ein Ferien-Plantag wird IMMER mit einem Ferientag der
   gematchten VJ-Periode verglichen (wochentagsgematcht), nie mit einem
   Normaltag, Feiertag oder Quasi-Feiertag. Einzige Ausnahme: die VJ-Periode
   enthält keinen verwendbaren Tag dieses Wochentags (dann nächster passender
   Wochentag außerhalb der Periode).
2. **Weihnachtsferien-Jahresgrenze:** Weihnachtsferien kommen pro Kalenderjahr
   ZWEIMAL vor (Januar-Ausläufer + Dezember-Beginn). `(bundesland, art)` ist
   daher KEIN eindeutiger Schlüssel. `match_ferien_periods()` (engine.py) ordnet
   jede Planperiode der VJ-Periode mit dem nächstgelegenen Startdatum
   (Plan-Start minus 1 Jahr) zu → Januar↔Januar, Dezember↔Dezember.
3. **24./31.12. sind Quasi-Feiertage** (`is_special_quasi_feiertag`): dürfen
   NIE Basistag für Normal- oder Ferientage sein. Ein Plan-24./31.12. vergleicht
   sich mit demselben Kalendertag im Basisjahr (24.→24., 31.→31.).
- `_ferien_faktor_woche` und `_ferien_period_for_day` arbeiten periodengenau
  (period-Referenz in `ferien_plan_dates`), damit die zwei Weihnachtsferien-
  Vorkommen nicht kollidieren.

### Feiertagstage (art='feiertagstag')
`_relevant_feiertag()` filtert **nur** `art='feiertag'`. Feiertagstage werden als
normale Tage behandelt. Bug-History: Fil. 120, 2.1.2026 → budget=0 wegen falschem Filter.

### Öffnungstage-Defaults
- Wochentag: **offen** wenn kein Eintrag in `filial_oeffnung`
- Feiertag: **geschlossen** wenn kein Eintrag in `filial_feiertag`
- `filial_oeffnung` auto-erkannt aus IST (≥30% Tage mit Umsatz > 0)
- Geschlossener Feiertag: budget=0, `eff_oeffnung = -ist_vj`, `feiertag_name` bleibt gesetzt

### Ferieneffekt
- Pufferzeitraum: 2 Wochen vor Ferienbeginn (konfigurierbar `ferien_puffer_wochen`)
- Faktor = Ø IST Ferienwoche / Ø IST Pufferwoche (wochentagsgematcht)
- Cached in `self._ferien_cache`

### save() — DELETE before INSERT
Löscht alle `planung`-Zeilen für berechnete `fil_nr × planjahr`, dann INSERT OR REPLACE.

### PlanParams
```python
@dataclass
class PlanParams:
    planjahr: int
    stichtag: date | None = None
    preiserhoehung_pct: float = 0.0
    wachstum_monat: dict[int, float] = field(default_factory=dict)
    ferien_puffer_wochen: int = 2
    # Ramadan/Fasching — Parameter vorhanden, Berechnung NICHT implementiert
```

---

## Zweite Berechnungslogik (Logik 2) — engine2.py

Parallel zu `engine.py` existiert eine **alternative Engine** `planning/engine2.py`
(`PlanningEngine2`). Beide laufen bewusst nebeneinander, bis entschieden ist, welche
Logik besser plant — dann wird die unterlegene entfernt (offener Punkt #17).

- **Ergebnis-Tabelle:** `planung2` (strukturgleich zu `planung`, additive in
  `schema.py` DDL + `_migrate()`).
- **UI:** Seiten `15_Planung2`, `16_Herleitung2`, `17_Planungsgenauigkeit2`
  (Navigationsgruppe „Logik 2 (alternativ)"). Identische Übersichten wie Logik 1,
  lesen/schreiben aber `planung2`.
- **Wiederverwendung:** `PlanningEngine2` komponiert intern eine `PlanningEngine`
  (`self.e`) und nutzt deren geladene Referenzdaten (Basisfenster, IST, Öffnung,
  Feiertage/Ferien, **dasselbe** `datumsmapping`).

### Vorgehen Logik 2 (Monatsumsatz-basiert)
1. **Ausgangspunkt:** IST-Monatsumsatz des Basiszeitraums je Monat (`M0`,
   via `e._base_month_ist`).
2. **Wochentagsanteile** global über das ganze Basisjahr (`_weekday_share`),
   Sondertage/Feiertage/Feiertagstage/Ferien ausgeschlossen
   (`_excluded_base_dates`). Anteil = Σ Wochentagsumsatz / Σ Normaltagsumsatz.
3. **Wochentags-Konstellation:** Pro Monat `M1 = Σ_wt cnt_plan[wt] × (M0·share[wt]/cnt_base[wt])`.
   Mehr/weniger Mo…So im Planjahr verschiebt den Monatsumsatz (→ `eff_wochentag`).
4. **Sondertag-/Feiertag-/Ferien-Monatsverschiebung:** nur wenn ein Sondertag im
   Budgetjahr in einen **anderen Monat** fällt als im Basisjahr. Aufschlag =
   Basis-IST des Tages − Ø gleicher Wochentag der 3 Nachbarmonate
   (`_neighbour_weekday_avg`). Budgetmonat `+=`, Ursprungsmonat `−=`
   (→ `eff_feiertag` bzw. `eff_ferien`). **Jahresweise nullsummig** (Golden bleibt stabil).
5. **Preis:** `M3 = M2 × e._growth(fil, month)` (→ `eff_preis`).
6. **Tagesverteilung:** `budget(d) = M3 × base_ist(d) / Σ_offene base_ist`, wobei
   `base_ist(d)` der IST des via Datumsmapping bestimmten Basistags ist.

### Additive Identität (wie Logik 1, exakt)
```
budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag
       + eff_preis + eff_ferien + eff_feiertag + eff_norm
```
- `ist_vj` = base_ist(d); geschlossene Tage: `budget=0`, `eff_oeffnung=−ist_vj`.
- `eff_verteilung` (= `w·M0 − ist_vj`) und `eff_norm` (Rundungsrest) sind in der UI
  ausgeblendet (wie Logik 1).
- Test-Suite: `tests/test_engine2.py` (Identität, Monatsnormierung, 365 Tage,
  geschlossene Tage, eigener Golden-Run, Save→`planung2`).

---

## Stolperfallen

### Bundesland-Dreifachformat
Es kursieren DREI Formate: `"BW"`, `"Baden-Württemberg"`, `"DE-BW"`.
`engine._normalize_bl()` normalisiert auf 2-Buchstaben. Die `feiertage`-Tabelle
speichert Abkürzungen (oder `'alle'`). Beim Anfassen von BL-Vergleichen IMMER normalisieren.

### Sondertage — Doppelstruktur
Engine lädt Sondertage aus BEIDEN Quellen: `sondertage` UND `feiertage WHERE LOWER(art)='sondertag'`.
Langfristig: Legacy-Tabelle `sondertage` abschaffen (offener Punkt).

### ferien_kalender ist die einzige Ferien-Quelle (seit 06/2026)
`ferien`-Tabelle ist deprecated. **Ohne Vorjahres-Eintrag in ferien_kalender wird
die Periode übersprungen** → Ferien immer für Planjahr UND Vorjahr laden!

### Ferien-Perioden-Matching (Plan ↔ VJ)
NIE per `dict[(bundesland, art)]` matchen — Weihnachtsferien sind pro Jahr
doppelt vorhanden und der letzte Eintrag würde den ersten überschreiben
(Januar-Plantage landeten fälschlich auf Dezember-VJ). Immer
`match_ferien_periods(plan_rows, vj_rows)` aus `engine.py` verwenden
(nächstgelegenes Startdatum). Genutzt in: engine `_load_reference_data`,
`8_Feiertage._rebuild_ferien_from_kalender`, Ferien-Tab Basis-Spalten.

### Importer-Datumsparser (Bug behoben 06/2026)
Fallback parst die unveränderten Rohstrings (nicht die bereits NaT-coercte Spalte).
`test_importer` sichert das ab.

### liefer_plan
Dead Code in `planung` (engine.save schreibt immer 0.0). Spalte bleibt (No-Drop-Regel).

### Architektur-Leitplanken
1. Additive Identität ist heilig — jeder neue Effekt additiv in €, in Normierung integriert.
2. Neue Rechenschritte als NEUE `eff_*`-Spalte + eigenes Modul.
3. SQLite-Migrationen nur additiv in `schema.py::_migrate()` (nie droppen).
4. Jede Zahl muss bis zum Tagesbeleg nachvollziehbar sein (Herleitung).
5. Defaults: Wochentag offen, Feiertag geschlossen.

---

## Test-Suite

`python -m pytest revenue_planner/tests/` — 14 Tests, alle müssen grün sein.

- **Additive Identität** je Tag (< 0,05 €), Monatsnormierung, geschlossene Tage budget==0
- **Importer:** dt. Zahlformat, Datum DD.MM.YYYY/ISO
- **Golden-Test** (`test_golden.py`): eingefrorene Jahresbudgets — Abweichung > 0,5 € =
  Verhaltensänderung. Golden-Werte nur bei BEWUSSTER Logikänderung anpassen.

Fixture: `tests/conftest.py` (`make_test_db`/`make_engine`), 3-Filialen-DB,
Ferien-Dip (−40% Osterferien BW 2025), Planjahr 2026.

---

## Import (importer.py)

- Spalten-Fuzzy-Matching (`_detect_columns`): Datum, Filialnummer, Umsatz
- **Deutsches Zahlenformat:** `_parse_num` — "3.000"=3000, "3,5"=3.5, "1.234,56"=1234.56.
  NIE einfaches `replace(",", ".")` verwenden!
- fil_nr-Validierung gegen `filialen` → bei fehlendem Eintrag: Abbruch (keine Teilimporte)
- fil_nr als TEXT: `df["fil_nr"] = df["fil_nr"].astype(str).str.strip()`
- datum als ISO: `df["datum"] = df["datum"].dt.strftime("%Y-%m-%d")`
- Import = UPSERT (`INSERT OR REPLACE`) — löscht nichts, was nicht in der Datei steht
- Nach Import: `detect_oeffnungstage(force=False)`

---

## Feiertage (8_Feiertage_Import.py)

- `holidays.country_holidays("DE", subdiv=bl, years=year)` für alle 16 BL
- **Feiertagstage:** Tag vor + nach Feiertag; Sonntag→keine; Montag→auch Sa (-2,-1,+1)
- **Schulferien:** `_load_schulferien_all_bl()` via `holidays.SCHOOL` (holidays >= 0.40)
  → schreibt in `ferien_kalender` für VJ + Planjahr, alle 16 BL automatisch
- Nach Speichern: Ferien-Rebuild + Datumsmapping automatisch
- Auto-Save mit `_norm_for_compare()` — Datums-Spalten normalisieren vor Vergleich!
