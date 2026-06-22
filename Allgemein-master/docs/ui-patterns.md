# UI-Patterns — Streamlit

## Session State

Immer über `ui/session.py` Hilfsfunktionen arbeiten:

```python
from ui.session import get_state, set_state

value = get_state('key', default=None)
set_state('key', new_value)
```

## Seiten-Struktur

Jede Seite folgt diesem Muster:

```python
import streamlit as st
from ui.session import get_state

st.title("Seitentitel")

# 1. Zustand laden
# 2. UI rendern
# 3. Bei Interaktion: Zustand aktualisieren und ggf. neu rendern
```

## Caching

```python
@st.cache_data(ttl=300)  # 5 Minuten Cache
def expensive_query():
    ...
```

## Fehleranzeige

```python
try:
    result = do_something()
    st.success("Erfolgreich!")
except Exception as e:
    st.error(f"Fehler: {e}")
```

## Formulare

Für zusammengehörige Eingaben immer `st.form` verwenden:

```python
with st.form("form_key"):
    value = st.text_input("Label")
    submitted = st.form_submit_button("Speichern")
    if submitted:
        process(value)
```
