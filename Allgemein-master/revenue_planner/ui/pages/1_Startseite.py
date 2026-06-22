"""Seite 1: Startseite."""
import streamlit as st
from ui.session import get_state

st.title("🥐 Filialumsatzplanung — Startseite")

st.markdown("""
## Willkommen

Diese Anwendung unterstützt die Umsatzplanung für die Filialen von Bäcker Görtz und Papperts.

### Schnellstart
1. **Daten importieren** → Seite 3: Daten Import
2. **Parameter einstellen** → Seite 4: Parameter
3. **Planung berechnen** → Seite 6: Planung
4. **Ergebnisse prüfen** → Seite 7: Planungsgenauigkeit
""")
