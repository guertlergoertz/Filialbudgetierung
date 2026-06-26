# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Pflicht am Sitzungsstart:** Diese Datei lesen. Bei tiefergehender Arbeit die
> jeweiligen Detail-Docs lesen (siehe Verweise unten).
>
> **Pflicht am Sitzungsende (automatisch, ohne Aufforderung):**
> 1. Relevante Docs aktualisieren (neue Erkenntnisse, TODOs, Architekturentscheidungen)
> 2. Alle Änderungen committen und auf `master` pushen

---

## 1. Projektüberblick

**Ziel:** Web-App (Streamlit + SQLite) zur tagesgenauen Umsatzplanung für ~255 Filialen
der Bäcker Görtz / Papperts Gruppe. Ersetzt Excel-Budgetierung. **Stellenwert: sehr hoch**
— das komplette Unternehmensbudget basiert auf diesen Berechnungen.

**Stack:** Python 3.11+, Streamlit 1.35+, SQLite, Pandas, openpyxl, holidays, Pillow
**Start:** `streamlit run revenue_planner/app.py`

---

## 2. Verzeichnisstruktur

```
revenue_planner/
├── app.py                    # Streamlit-Einstiegspunkt, Navigation, Logos
├── database/
│   ├── schema.py             # DDL + Migration (_migrate)
│   └── importer.py           # IST-Import, detect_oeffnungstage
├── planning/
│   ├── engine.py             # Kern-Planungslogik Logik 1 (PlanningEngine → planung)
│   ├── engine2.py            # Alternative Logik 2 (PlanningEngine2 → planung2)
│   ├── datumsmapping.py      # Datumsmapping-Generator (von beiden Logiken genutzt)
│   └── export.py             # Excel-Export
├── tests/                    # pytest-Regressionssuite (inkl. test_engine2.py)
└── ui/
    ├── session.py            # get_conn(), get_gmbh(), require_db(), get_budgetjahr()
    ├── assets/               # Logos
    └── pages/                # 1_Startseite … 14_Planungsgenauigkeit2 (Logik 2 = 12/13/14; L1 entfernt)
docs/
├── architecture.md           # Schema, Datenfluss, Engine-Logik, Stolperfallen
├── ui-patterns.md            # UI-Seiten, Patterns, Formatierung
└── open-issues.md            # Offene Punkte, Änderungshistorie
```

---

## 3. Detail-Dokumentation — wann was lesen

| Aufgabe | Doc lesen |
|---------|-----------|
| Änderungen an `engine.py`, `engine2.py`, `schema.py`, `datumsmapping.py`, `importer.py` | `Read docs/architecture.md` |
| Änderungen an `ui/pages/*.py` oder `app.py` | `Read docs/ui-patterns.md` |
| Neue Features planen, TODOs prüfen, Sitzungsende | `Read docs/open-issues.md` |

---

## 4. Entwicklungsregeln

1. **Branch:** `master` (direkt, kein Feature-Branch).
2. **Commits:** Aussagekräftige englische Commit-Messages.
3. **Keine halben Implementierungen.** Zu große Tasks als TODO in `docs/open-issues.md`.
4. **Keine Breaking Changes** an der additiven Effekt-Identität ohne Regressionstest.
   `budget = ist_vj + eff_oeffnung + eff_verteilung + eff_wochentag + eff_preis + eff_ferien + eff_feiertag + eff_norm`
5. **SQLite-Migrationen** immer additiv in `schema.py::_migrate()` (nie droppen).
6. **Öffnungstage-Defaults:** Wochentag = offen, Feiertag = geschlossen.
7. **fil_nr immer als `str()`** normieren wenn `ist_umsatz` und `planung` verglichen werden.
8. **eff_norm:** In DB behalten, aus allen UI-Anzeigen ausblenden.
9. **Datumsformat UI:** immer `DD.MM.YYYY`. Placeholders immer Deutsch.
10. **Kein Speichern-Button bei data_editor:** Auto-Save + `st.toast()` + `st.rerun()`.
    Datums-Spalten vor Vergleich normalisieren (`_norm_for_compare`)!
11. **Bundesland-Vergleiche** immer über `_normalize_bl()`. In UI ausgeschrieben anzeigen.
12. **Bundesland als erste Spalte** in Tabellen, Sortierung BL → Datum.
13. **DATENSCHUTZ — NIEMALS echte Betriebs- oder Filialdaten laden:**
    `.db`-Dateien, CSV/Excel mit IST-Umsätzen oder Filialdaten **NIEMALS** per `Read`,
    `Bash cat/head`, `pd.read_sql` o.ä. in den Kontext laden. Nur Schema, Code und
    Docs lesen. DB-Abfragen ausschließlich zur Strukturprüfung (`SELECT name FROM
    sqlite_master`) — keine `SELECT *` auf echten Produktionsdaten.
