"""Streamlit entry point with explicit page navigation."""
import streamlit as st
from pathlib import Path
import sys

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

st.set_page_config(
    page_title="Umsatzplanung",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={},
)

# Ladeindikator: Streamlits nativer Status-Indikator (oben rechts) wird sichtbar
# gelassen. Ein früherer Versuch mit einer per st.markdown injizierten Brezel-
# Animation funktionierte nicht, da Streamlit eingebettete <script>-Tags nicht
# ausführt — der MutationObserver wurde nie registriert. Schwere Operationen
# zeigen zusätzlich einen inline st.spinner() ("Berechne…").
st.markdown("""
<style>
/* Nativen Ladeindikator hervorheben (etwas größer, gut sichtbar) */
[data-testid="stStatusWidget"] { transform: scale(1.15); }
</style>
""", unsafe_allow_html=True)

ASSETS = BASE / "ui" / "assets"


import base64


def _logo_tag(path: Path, width: int = 65) -> str:
    if not path.exists():
        return ""
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".")
    return (
        f'<img src="data:image/{ext};base64,{b64}" '
        f'style="width:{width}px;background:#fff;padding:4px 6px;'
        f'border-radius:5px;object-fit:contain;">'
    )


def _combined_logo_bytes(paths: list, height: int = 88) -> bytes | None:
    """Build a combined PNG for st.logo() – plain white background, no transparency."""
    try:
        from PIL import Image
        import io

        imgs = [Image.open(p).convert("RGBA") for p in paths if p.exists()]
        if not imgs:
            return None

        gap = 10
        resized = []
        for img in imgs:
            ratio = height / img.height
            new_w = max(1, int(img.width * ratio))
            resized.append(img.resize((new_w, height), Image.LANCZOS))

        total_w = sum(i.width for i in resized) + gap * (len(resized) - 1)
        canvas = Image.new("RGB", (total_w, height), (255, 255, 255))
        x = 0
        for img in resized:
            canvas.paste(img, (x, 0), img)
            x += img.width + gap

        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


# ── Logos: st.logo() places above nav; CSS replicates the old HTML styling ─
_logo_bytes = _combined_logo_bytes([ASSETS / "goertz_logo.png", ASSETS / "papperts_logo.png"])
if _logo_bytes:
    st.logo(_logo_bytes, size="large")
    st.markdown("""
<style>
/* Logo-Bereich: margin-top auf dem Header selbst (padding-top wird von Streamlit überschrieben) */
[data-testid="stSidebarHeader"] {
    margin-top: 1rem !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    padding-bottom: 0.5rem !important;
    padding-top: 0 !important;
}
[data-testid="stSidebarHeader"] img {
    height: 80px !important;
    width: auto !important;
    max-width: 100% !important;
    background: #ffffff !important;
    padding: 4px 6px !important;
    border-radius: 5px !important;
    object-fit: contain !important;
    display: block !important;
    margin: 0 !important;
}
/* Sidebar-Einklapp-Button ausblenden */
[data-testid="stSidebarCollapseButton"],
button[aria-label="Close sidebar"],
button[aria-label="Collapse sidebar"] {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)
else:
    # Fallback: HTML logos in sidebar when Pillow unavailable
    with st.sidebar:
        g = _logo_tag(ASSETS / "goertz_logo.png")
        p_tag = _logo_tag(ASSETS / "papperts_logo.png")
        if g or p_tag:
            st.markdown(
                f'<div style="display:flex;gap:10px;align-items:center;padding:6px 0 4px 0;">{g}{p_tag}</div>',
                unsafe_allow_html=True,
            )
            st.divider()

# ── Sidebar: Firma / Budgetjahr / Basiszeitraum ────────────────────────────
from ui.session import get_gmbh as _get_gmbh, get_budgetjahr as _get_bj

_gmbh = _get_gmbh()
_bj   = _get_bj()

# Auto-correct budgetjahr: if the stored year doesn't exist in DB, pick the newest existing
if _gmbh:
    from ui.session import get_conn as _get_conn, set_budgetjahr as _set_bj_app
    _conn_app = _get_conn()
    if _conn_app:
        _yrs = [r[0] for r in _conn_app.execute(
            "SELECT DISTINCT planjahr FROM parameter ORDER BY planjahr DESC"
        ).fetchall()]
        if _yrs and _bj not in _yrs:
            _set_bj_app(_yrs[0])
            _bj = _yrs[0]

with st.sidebar:
    if _gmbh:
        from datetime import date as _date, timedelta as _td
        _stichtag = _date(_bj, 1, 1) if _bj <= _date.today().year else _date.today()
        _lc = _stichtag.replace(day=1) - _td(days=1)
        _m, _y = _lc.month, _lc.year
        _ms = _m - 11
        _ys = _y
        while _ms <= 0:
            _ms += 12
            _ys -= 1
        _mon = ["Jan","Feb","Mär","Apr","Mai","Jun","Jul","Aug","Sep","Okt","Nov","Dez"]
        _basis_label = f"{_mon[_ms-1]} {_ys} – {_mon[_m-1]} {_y}"
        st.markdown(
            f"**Firma:** {_gmbh}  \n"
            f"**Budgetjahr:** {_bj}  \n"
            f"**Basiszeitraum:** {_basis_label}"
        )
        st.divider()

# ── Navigation ─────────────────────────────────────────────────────────────
pages = st.navigation({
    " ": [
        st.Page(str(BASE / "ui/pages/1_Startseite.py"),
                title="Startseite", icon=":material/home:"),
    ],
    "Input & Stammdaten": [
        st.Page(str(BASE / "ui/pages/2_Filialen.py"),
                title="Filialen",               icon=":material/store:"),
        st.Page(str(BASE / "ui/pages/3_Daten_Import.py"),
                title="Umsatz-Import",           icon=":material/upload_file:"),
        st.Page(str(BASE / "ui/pages/9_Oeffnungstage.py"),
                title="Filial-Öffnungstage",    icon=":material/calendar_month:"),
        st.Page(str(BASE / "ui/pages/8_Feiertage_Import.py"),
                title="Feiertage u. Ferien",    icon=":material/event:"),
        st.Page(str(BASE / "ui/pages/13_Datumsmapping.py"),
                title="Datumsmapping",           icon=":material/calendar_view_day:"),
        st.Page(str(BASE / "ui/pages/11_Preisanpassung.py"),
                title="Preisanpassung je Monat", icon=":material/trending_up:"),
    ],
    "Berechnung & Validierung": [
        st.Page(str(BASE / "ui/pages/14_Validierung.py"),
                title="Plausibilitätsprüfung", icon=":material/checklist:"),
        st.Page(str(BASE / "ui/pages/6_Planung.py"),
                title="Planung ausführen",   icon=":material/calculate:"),
        st.Page(str(BASE / "ui/pages/10_Herleitung.py"),
                title="Herleitung",          icon=":material/account_tree:"),
        st.Page(str(BASE / "ui/pages/7_Planungsgenauigkeit.py"),
                title="Planungsgenauigkeit", icon=":material/analytics:"),
    ],
    "Logik 2 (alternativ)": [
        st.Page(str(BASE / "ui/pages/15_Planung2.py"),
                title="Planung ausführen (L2)",   icon=":material/calculate:"),
        st.Page(str(BASE / "ui/pages/16_Herleitung2.py"),
                title="Herleitung (L2)",          icon=":material/account_tree:"),
        st.Page(str(BASE / "ui/pages/17_Planungsgenauigkeit2.py"),
                title="Planungsgenauigkeit (L2)", icon=":material/analytics:"),
    ],
})
pages.run()
