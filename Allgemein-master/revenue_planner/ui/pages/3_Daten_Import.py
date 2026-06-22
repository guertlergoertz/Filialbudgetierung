"""Seite 3: Excel-Datenimport."""
import streamlit as st

st.title("Daten Import")

uploaded = st.file_uploader("Excel-Datei wählen", type=["xlsx", "xls"])

if uploaded:
    st.info(f"Datei geladen: {uploaded.name}")
    st.write("Import-Logik folgt.")
