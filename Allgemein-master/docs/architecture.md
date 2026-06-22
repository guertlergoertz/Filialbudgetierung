# Architektur — Filialumsatzplanung

## Überblick

Die Anwendung ist eine Streamlit-Web-App zur Planung von Filialumsatzzahlen für Bäcker Görtz und Papperts.

## Technologie-Stack

| Komponente | Technologie |
|-----------|-------------|
| Frontend | Streamlit |
| Datenbank | DuckDB (lokal, dateibasiert) |
| Datenverarbeitung | Pandas |
| Excel I/O | openpyxl |
| Sprache | Python 3.11+ |

## Modulstruktur

### `database/`
- **`schema.py`**: Initialisiert die DuckDB-Datenbank, erstellt alle Tabellen
- **`importer.py`**: Liest Excel-Dateien ein und schreibt in die DB

### `planning/`
- **`engine.py`**: Planungslogik Engine 1 (gewichteter Durchschnitt vergangener Jahre)
- **`engine2.py`**: Planungslogik Engine 2 (alternative Gewichtungsmethode)
- **`export.py`**: Generiert Excel-Ausgabedateien
- **`datumsmapping.py`**: Ordnet Kalenderwochen und Wochentage zu

### `ui/pages/`
Streamlit-Seiten (numerisch präfixiert für Reihenfolge):
- `1_Startseite.py` — Übersicht und Status
- `2_Filialen.py` — Filialdaten verwalten
- `3_Daten_Import.py` — Excel-Import
- `4_Parameter.py` — Planungsparameter einstellen
- `5_Neue_Filialen.py` — Neue Filialen anlegen
- `6_Planung.py` — Planung ausführen (Engine 1)
- `7_Planungsgenauigkeit.py` — Genauigkeit Engine 1
- `8_Feiertage_Import.py` — Feiertagsdaten importieren
- `9_Oeffnungstage.py` — Öffnungstage pflegen
- `10_Herleitung.py` — Herleitung der Planwerte
- `11_Preisanpassung.py` — Preisanpassungsfaktor
- `12_Schulfilialen.py` — Schulfilialen-Sonderlogik
- `13_Datumsmapping.py` — Datumsmapping-Verwaltung
- `14_Validierung.py` — Datenvalidierung
- `15_Planung2.py` — Planung ausführen (Engine 2)
- `16_Herleitung2.py` — Herleitung Engine 2
- `17_Planungsgenauigkeit2.py` — Genauigkeit Engine 2

## Datenfluss

```
Excel-Import → DuckDB → Planning Engine → Excel-Export
                  ↑
             Streamlit UI
```

## Datenbankschema (Kurzform)

Haupttabellen:
- `filialen` — Stammdaten der Filialen
- `umsatzdaten` — historische Umsatzzahlen
- `planwerte` — berechnete Planwerte
- `parameter` — Planungsparameter
- `feiertage` — Feiertagskalender
- `oeffnungstage` — Öffnungstagekonfiguration
