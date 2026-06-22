# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Pflicht am Sitzungsstart:** Diese Datei lesen. Bei tiefergehender Arbeit die
> jeweiligen Detail-Docs lesen (siehe Verweise unten).
>
> **Pflicht am Sitzungsende (automatisch, ohne Aufforderung):**
> 1. Relevante Docs aktualisieren (neue Erkenntnisse, TODOs, Architekturentscheidungen)
> 2. Alle Änderungen committen und auf `master` pushen

---

## Projektüberblick

**Ziel:** Automatisierte Jahresumsatzplanung für alle Filialen (Bäcker Görtz + Papperts) auf Tagesbasis.

**Tech-Stack:** Python 3.11 · Streamlit · SQLite · Pandas · OpenPyXL

**Einstiegspunkt:** `revenue_planner/app.py` (Streamlit-App)

---

## Wichtige Dateien

| Datei | Zweck |
|---|---|
| `revenue_planner/planning/engine.py` | Kern-Planungslogik (Umsatzherleitung) |
| `revenue_planner/planning/engine2.py` | Alternative Engine (vereinfacht) |
| `revenue_planner/planning/datumsmapping.py` | KW/Datum-Mapping, Wochentags-Indizes |
| `revenue_planner/database/schema.py` | DB-Schema + Init |
| `revenue_planner/database/importer.py` | Excel-Import |
| `revenue_planner/ui/pages/` | Streamlit-Seiten |

---

## Architektur (Kurzversion)

Siehe `docs/architecture.md` für Details.

```
Excel-Import → SQLite-DB → Planning Engine → Export (Excel)
                              ↑
                         Streamlit-UI
```

**DB-Tabellen (wichtigste):**
- `umsaetze` – historische Tagesumsatzdaten
- `filialen` – Stammdaten Filialen
- `planwerte` – berechnete Planwerte
- `parameter` – Konfigurationsparameter
- `feiertage` – Feiertagskalender
- `oeffnungstage` – Soll-Öffnungszeiten

---

## Bekannte offene Punkte

Siehe `docs/open-issues.md` für die vollständige Liste.

**Kritisch:**
- Keine automatischen Tests für Engine-Output (nur manuelle Prüfung)
- Exportformat noch nicht final abgestimmt

---

## Entwicklungs-Workflow

```bash
# App starten
cd revenue_planner && streamlit run app.py

# Tests ausführen
pytest revenue_planner/tests/ -v

# Abhängigkeiten installieren
pip install -r revenue_planner/requirements.txt
```

---

## Commit-Konvention

```
<typ>(<scope>): <was>

typen: feat | fix | refactor | test | docs | chore
scope: engine | ui | db | export | tests | docs
```

Beispiel: `feat(engine): Saisonindex für Q4 ergänzt`
