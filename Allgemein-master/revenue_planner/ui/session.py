"""Session-State-Management für Streamlit."""
from __future__ import annotations

from typing import Any

import streamlit as st


def get_state(key: str, default: Any = None) -> Any:
    """Gibt den Wert aus dem Session State zurück."""
    return st.session_state.get(key, default)


def set_state(key: str, value: Any) -> None:
    """Setzt einen Wert im Session State."""
    st.session_state[key] = value


def clear_state(key: str) -> None:
    """Löscht einen Wert aus dem Session State."""
    st.session_state.pop(key, None)


def require_state(key: str, error_msg: str | None = None) -> Any:
    """
    Gibt den Wert aus dem Session State zurück.
    Wirft einen Fehler wenn der Wert nicht vorhanden ist.
    """
    value = st.session_state.get(key)
    if value is None:
        msg = error_msg or f"Erforderlicher State '{key}' nicht gesetzt."
        st.error(msg)
        st.stop()
    return value
