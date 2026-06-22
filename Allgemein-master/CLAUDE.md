# CLAUDE.md — Filialumsatzplanung (Bäcker Görtz / Papperts)

> **Pflicht am Sitzungsstart:** Diese Datei lesen. Bei tiefergehender Arbeit die
> jeweiligen Detail-Docs lesen (siehe Verweise unten).
>
> **Pflicht am Sitzungsende (automatisch, ohne Aufforderung):**
> 1. Relevante Docs aktualisieren (neue Erkenntnisse, TODOs, Architekturentscheidungen)
> 2. Alle Änderungen committen und auf `master` pushen

---

## Projektidentität

| Feld | Wert |
|------|------|
| **Repo** | `guertlergoertz/Filialbudgetierung` |
| **Branch** | `master` |
| **Stack** | Python 3.11+, Streamlit, DuckDB, Pandas, openpyxl |
| **Einstiegspunkt** | `revenue_planner/app.py` |
| **Starten** | `streamlit run revenue_planner/app.py` |

---

## Schnell-Referenz

```
revenue_planner/
├── app.py                    # Streamlit-Einstiegspunkt
├── database/
│   ├── schema.py             # DB-Init, Tabellendefinitionen
│   └── importer.py           # Excel-Import-Logik
├── planning/
│   ├── engine.py             # Planungslogik (Engine 1)
│   ├── engine2.py            # Planungslogik (Engine 2)
│   ├── export.py             # Excel-Export
│   └── datumsmapping.py      # Datums-/Wochentags-Mapping
└── ui/
    ├── pages/                # Streamlit-Seiten (1_ bis 17_)
    └── session.py            # Session-State-Management
```

**Docs:** `docs/architecture.md` | `docs/open-issues.md` | `docs/ui-patterns.md`

---

## Kritische Regeln (IMMER beachten)

1. **Kein Datenverlust** — Nutzereingaben niemals überschreiben ohne explizite Bestätigung
2. **DuckDB-Transaktionen** — bei Schreiboperationen immer `conn.execute("BEGIN")` / `COMMIT` / `ROLLBACK`
3. **Session-State** — änderungen über `ui/session.py`-Funktionen, nie direkt `st.session_state[key] = ...`
4. **Tests laufen lassen** — nach jeder Änderung: `cd revenue_planner && python -m pytest tests/ -q`
5. **Encoding** — alle Dateien UTF-8, Excel-Import mit `encoding='utf-8-sig'` prüfen

---

## Bekannte Fallstricke

- DuckDB erlaubt keine parallelen Schreibverbindungen — Verbindung immer schließen nach Nutzung
- Streamlit re-rendert bei jedem Interaktion die gesamte Seite — teure Operationen mit `@st.cache_data` cachen
- Excel-Dateien können verschiedene Datumsformate haben — Importer robust gegen Varianten machen
- `engine2.py` hat andere Gewichtungslogik als `engine.py` — nicht vermischen
