"""Plausibilitätsprüfung: automatische Checks vor der Planung (Ampel-Anzeige)."""
import streamlit as st
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.session import get_conn, get_gmbh, require_db, get_budgetjahr
from planning.engine import PlanningEngine, PlanParams, _normalize_bl, _BL_NAME_TO_ABBR
import pandas as pd
from datetime import date, timedelta

require_db()
conn = get_conn()
planjahr = get_budgetjahr()

st.title("Plausibilitätsprüfung")
st.caption(f"Firma: **{get_gmbh()}** — Budgetjahr: **{planjahr}**")

# ── Vorbereitungs-Checkliste ─────────────────────────────────────────────────
CHECKLIST_ITEMS = [
    ("stammdaten_import",   "Filialstammdaten importieren"),
    ("deaktivierung",       "Filialen für die Budgetierung deaktivieren"),
    ("filialschliessungen", "Filialschließungen hinterlegen"),
    ("filialumbauten",      "Filialumbauten hinterlegen (Umbau von/bis)"),
    ("kein_wachstum",       "Filialen mit keinem Wachstum kennzeichnen"),
    ("filialoeffnungen",    "Filialeröffnungen: Datum + Planumsatz"),
    ("umsatz_import",       "Umsatz-Import des Basiszeitraums"),
    ("oeffnungstage",       "Filial-Öffnungstage"),
    ("feiertage_ferien",    "Feiertage, Ferien und Sondertage"),
    ("preisanpassung",      "Preisanpassung"),
]
_cl_rows = conn.execute(
    "SELECT item_key, checked FROM plausibilitaet_checkliste WHERE planjahr=?",
    (planjahr,)
).fetchall()
_cl_db_state = {r["item_key"]: bool(r["checked"]) for r in _cl_rows}

_cl_header = st.empty()
_cl_new_state: dict[str, bool] = {}
with st.expander("📋 Vorbereitungs-Checkliste", expanded=True):
    for _key, _label in CHECKLIST_ITEMS:
        _val = st.checkbox(_label, value=_cl_db_state.get(_key, False), key=f"cl_{_key}")
        _cl_new_state[_key] = _val

_cl_all_checked = all(_cl_new_state.values())
if not _cl_all_checked:
    _cl_header.markdown("❌ **Vorbereitungs-Checkliste** — noch nicht alle Punkte erledigt")
else:
    _cl_header.markdown("✅ **Vorbereitungs-Checkliste** — alle Punkte erledigt")

if _cl_new_state != _cl_db_state:
    for _key, _checked in _cl_new_state.items():
        conn.execute(
            "INSERT OR REPLACE INTO plausibilitaet_checkliste (planjahr, item_key, checked) "
            "VALUES (?,?,?)",
            (planjahr, _key, int(_checked))
        )
    conn.commit()

st.divider()

VALID_BL = set(_BL_NAME_TO_ABBR.values())

# Gleiche Stichtagslogik wie 12_Planung2
today = date.today()
stichtag = date(planjahr, 1, 1) if planjahr <= today.year else today
engine = PlanningEngine(conn, PlanParams(planjahr=planjahr, stichtag=stichtag))

checks = []  # (status: 'ok'|'warn'|'crit', titel, detail_df oder None, caption)


def add(status, titel, details=None, caption=""):
    checks.append((status, titel, details, caption))


filialen_all = [dict(r) for r in conn.execute("SELECT * FROM filialen").fetchall()]

import re as _re

def _is_gesperrt(f) -> bool:
    """Filiale gilt als gesperrt wenn flag_gesperrt=1 ODER XX/XXX in der Bezeichnung."""
    if f.get("flag_gesperrt"):
        return True
    return bool(_re.search(r'X{2,}', str(f.get("bezeichnung") or ""), _re.IGNORECASE))

gesperrte = [f for f in filialen_all if _is_gesperrt(f)]
filialen = [f for f in filialen_all if not _is_gesperrt(f)]

# Bundesländer die tatsächlich in den Filialen hinterlegt sind (normalisiert)
_fil_bls = {_normalize_bl(f["bundesland"]) for f in filialen if f.get("bundesland")}
RELEVANT_BL = _fil_bls & set(VALID_BL)  # nur bekannte, gültige BL

# 0) Gesperrte Filialen (werden bei Planung ignoriert)
gesperrt_detail = pd.DataFrame([
    {"Filiale": f["fil_nr"], "Bezeichnung": f.get("bezeichnung") or "",
     "Grund": "XX/XXX in Bezeichnung (automatisch)" if _re.search(r'X{2,}', str(f.get("bezeichnung") or ""), _re.IGNORECASE) else "Manuell gesperrt"}
    for f in gesperrte
]) if gesperrte else None
add("warn" if gesperrte else "ok",
    f"Gesperrte Filialen (werden ignoriert): {len(gesperrte)}",
    gesperrt_detail,
    "Gesperrte Filialen fließen nicht in Planung, Herleitung und Auswertung ein. "
    "Automatisch gesperrt bei XX oder XXX in der Filialbezeichnung; zusätzlich manuell einstellbar.")

# 1) Filialen ohne/mit unbekanntem Bundesland
bad_bl = [
    {"Filiale": f["fil_nr"], "Bundesland": f.get("bundesland") or "(leer)"}
    for f in filialen
    if not f.get("bundesland") or _normalize_bl(f["bundesland"]) not in VALID_BL
]
add("crit" if bad_bl else "ok",
    f"Filialen ohne/mit unbekanntem Bundesland: {len(bad_bl)}",
    pd.DataFrame(bad_bl) if bad_bl else None,
    "Ohne gültiges Bundesland greifen Feiertage und Ferien nicht korrekt "
    "(Fallback RP).")

# 2) Filialen ohne IST-Daten im Basiszeitraum
base_start = engine.base_start.isoformat()
base_end_excl = engine.base_mask_end.date().isoformat()
ist_in_base = {
    str(r["fil_nr"]): r["n"]
    for r in conn.execute(
        "SELECT fil_nr, COUNT(*) AS n FROM ist_umsatz "
        "WHERE datum >= ? AND datum < ? AND umsatz > 0 GROUP BY fil_nr",
        (base_start, base_end_excl)).fetchall()
}
no_ist = [{"Filiale": f["fil_nr"], "Bezeichnung": f.get("bezeichnung", "")}
          for f in filialen if str(f["fil_nr"]) not in ist_in_base]
add("crit" if no_ist else "ok",
    f"Filialen ohne IST-Daten im Basiszeitraum ({engine.base_window_label()}): {len(no_ist)}",
    pd.DataFrame(no_ist) if no_ist else None,
    "Diese Filialen erhalten ohne Override/Neue-Filialen-Planwert Budget 0.")

# 3) Monate im Basisfenster ohne Umsatz je Filiale (Extrapolations-Fallback)
month_rows = conn.execute(
    "SELECT fil_nr, strftime('%Y-%m', datum) AS ym, SUM(umsatz) AS s "
    "FROM ist_umsatz WHERE datum >= ? AND datum < ? GROUP BY fil_nr, ym",
    (base_start, base_end_excl)).fetchall()
have = {(str(r["fil_nr"]), r["ym"]) for r in month_rows if (r["s"] or 0) > 0}
expected_yms = []
for m in range(1, 13):
    y = engine.base_year_for_month(m)
    expected_yms.append(f"{y:04d}-{m:02d}")
gaps = []
for f in filialen:
    fn = str(f["fil_nr"])
    if fn not in ist_in_base:
        continue  # bereits in Check 2 gemeldet
    missing = [ym for ym in expected_yms if (fn, ym) not in have]
    if missing:
        gaps.append({"Filiale": fn, "Fehlende Monate": ", ".join(sorted(missing))})
add("crit" if gaps else "ok",
    f"Filialen mit Monaten ohne Umsatz im Basisfenster: {len(gaps)}",
    pd.DataFrame(gaps) if gaps else None,
    "Für fehlende Monate greift der Extrapolations-Fallback aus dem "
    "Wochentags-Durchschnitt (prüfen, ob das fachlich gewollt ist).")

# 4) Ferienperioden des Budgetjahrs ohne passende Vorjahresperiode
fer_plan = conn.execute(
    "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
    (planjahr,)).fetchall()
fer_vj_keys = {(r["bundesland"], r["art"]) for r in conn.execute(
    "SELECT bundesland, art FROM ferien_kalender WHERE jahr=?", (planjahr - 1,))}
fer_orphans = [
    {"Bundesland": r["bundesland"], "Art": r["art"],
     "Zeitraum": f'{r["start"]} – {r["ende"]}'}
    for r in fer_plan if (r["bundesland"], r["art"]) not in fer_vj_keys
]
add("warn" if fer_orphans else "ok",
    f"Ferienperioden {planjahr} ohne Vorjahresperiode: {len(fer_orphans)}",
    pd.DataFrame(fer_orphans) if fer_orphans else None,
    "Diese Perioden werden von der Engine IGNORIERT — Ferien immer für "
    "Budgetjahr UND Vorjahr in den Ferienkalender laden.")

# 5) Feiertage des Budgetjahrs ohne datum_vj
ft_no_vj = [
    {"Datum": r["datum_plan"], "Beschreibung": r["name"], "Bundesland": r["bundesland"]}
    for r in conn.execute(
        "SELECT datum_plan, name, bundesland FROM feiertage "
        "WHERE LOWER(art)='feiertag' AND datum_plan LIKE ? "
        "AND (datum_vj IS NULL OR datum_vj='')", (f"{planjahr}-%",))
]
add("warn" if ft_no_vj else "ok",
    f"Feiertage {planjahr} ohne Vorjahres-Referenzdatum: {len(ft_no_vj)}",
    pd.DataFrame(ft_no_vj) if ft_no_vj else None,
    "Ohne datum_vj kann der Feiertagseffekt keinen IST-Referenztag finden "
    "(ist_vj = 0).")

# 6) Feiertage/Ferien für Budgetjahr überhaupt geladen?
n_ft = conn.execute(
    "SELECT COUNT(*) AS n FROM feiertage WHERE LOWER(art)='feiertag' AND datum_plan LIKE ?",
    (f"{planjahr}-%",)).fetchone()["n"]
n_fer = len(fer_plan)
add("crit" if n_ft == 0 else "ok",
    f"Feiertage für {planjahr} geladen: {n_ft}",
    None,
    "0 Feiertage → Seite 'Feiertage u. Ferien' ausführen." if n_ft == 0 else "")
add("warn" if n_fer == 0 else "ok",
    f"Ferienperioden für {planjahr} geladen: {n_fer}",
    None,
    "0 Ferienperioden → Ferienkalender pflegen (sofern relevant)." if n_fer == 0 else "")

# 6b) Vergleich Feiertage/Sondertage/Ferientage: Budgetjahr vs. Basiszeitraum
base_start_str = engine.base_start.isoformat()
base_end_str   = (engine.base_mask_end.date() - timedelta(days=1)).isoformat()
plan_start_str = f"{planjahr}-01-01"
plan_end_str   = f"{planjahr}-12-31"

# Feiertage (art='feiertag', ohne Feiertagstage)
ft_base = conn.execute(
    "SELECT bundesland, COUNT(*) AS n FROM feiertage "
    "WHERE LOWER(art)='feiertag' AND datum_plan >= ? AND datum_plan <= ? "
    "GROUP BY bundesland ORDER BY bundesland",
    (base_start_str, base_end_str)
).fetchall()
ft_plan = conn.execute(
    "SELECT bundesland, COUNT(*) AS n FROM feiertage "
    "WHERE LOWER(art)='feiertag' AND datum_plan >= ? AND datum_plan <= ? "
    "GROUP BY bundesland ORDER BY bundesland",
    (plan_start_str, plan_end_str)
).fetchall()

def _ft_dict(rows) -> dict[str, int]:
    return {r["bundesland"]: r["n"] for r in rows}

ft_base_d = _ft_dict(ft_base)
ft_plan_d = _ft_dict(ft_plan)
# Nur Bundesländer anzeigen, in denen es auch Filialen gibt (plus 'alle')
all_bl_ft = sorted(
    bl for bl in (set(ft_base_d) | set(ft_plan_d))
    if bl == "alle" or bl in RELEVANT_BL
)
ft_compare_rows = []
for bl in all_bl_ft:
    b, p = ft_base_d.get(bl, 0), ft_plan_d.get(bl, 0)
    diff = p - b
    status_flag = "⚠️" if diff != 0 else "✅"
    ft_compare_rows.append({
        "Bundesland": bl, f"Basiszeitraum ({engine.base_window_label()})": b,
        f"Budgetjahr {planjahr}": p, "Differenz": diff, "Status": status_flag
    })
ft_compare_df = pd.DataFrame(ft_compare_rows)
has_ft_diff = any(r["Differenz"] != 0 for r in ft_compare_rows)
add("warn" if has_ft_diff else "ok",
    "Feiertage je Bundesland: Basiszeitraum vs. Budgetjahr",
    ft_compare_df if not ft_compare_df.empty else None,
    "Unterschiedliche Anzahl Feiertage können Budget-Effekte erklären (z.B. Brückentage).")

# Sondertage
n_st_base = conn.execute(
    "SELECT COUNT(*) AS n FROM sondertage WHERE datum_plan >= ? AND datum_plan <= ?",
    (base_start_str, base_end_str)
).fetchone()["n"]
n_st_plan = conn.execute(
    "SELECT COUNT(*) AS n FROM sondertage WHERE datum_plan >= ? AND datum_plan <= ?",
    (plan_start_str, plan_end_str)
).fetchone()["n"]
st_rows_base = conn.execute(
    "SELECT datum_plan, bezeichnung, bundesland FROM sondertage "
    "WHERE datum_plan >= ? AND datum_plan <= ? ORDER BY datum_plan",
    (base_start_str, base_end_str)
).fetchall()
st_rows_plan = conn.execute(
    "SELECT datum_plan, bezeichnung, bundesland FROM sondertage "
    "WHERE datum_plan >= ? AND datum_plan <= ? ORDER BY datum_plan",
    (plan_start_str, plan_end_str)
).fetchall()
st_diff = n_st_plan - n_st_base
st_detail = pd.DataFrame(
    [{"Zeitraum": "Basiszeitraum", "Datum": r["datum_plan"],
      "Beschreibung": r["bezeichnung"], "Bundesland": r["bundesland"]}
     for r in st_rows_base] +
    [{"Zeitraum": f"Budgetjahr {planjahr}", "Datum": r["datum_plan"],
      "Beschreibung": r["bezeichnung"], "Bundesland": r["bundesland"]}
     for r in st_rows_plan]
)
add("warn" if st_diff != 0 else "ok",
    f"Sondertage: Basiszeitraum {n_st_base}, Budgetjahr {n_st_plan} (Differenz: {st_diff:+d})",
    st_detail if not st_detail.empty else None,
    "Unterschiedliche Sondertage-Anzahl beeinflussen den Sondertags-Effekt in der Planung.")

# Ferientage (Schulferien — Tage aus ferien_kalender)
fer_base = conn.execute(
    "SELECT bundesland, art, start, ende FROM ferien_kalender "
    "WHERE start <= ? AND ende >= ?",
    (base_end_str, base_start_str)
).fetchall()
fer_plan_all = conn.execute(
    "SELECT bundesland, art, start, ende FROM ferien_kalender "
    "WHERE start <= ? AND ende >= ?",
    (plan_end_str, plan_start_str)
).fetchall()

def _count_days(rows, yr_start, yr_end) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        bl, art = r["bundesland"], r["art"]
        s = max(date.fromisoformat(r["start"]), date.fromisoformat(yr_start))
        e = min(date.fromisoformat(r["ende"]), date.fromisoformat(yr_end))
        days = max(0, (e - s).days + 1)
        key = f"{bl} – {art}"
        counts[key] = counts.get(key, 0) + days
    return counts

fer_base_counts = _count_days(fer_base, base_start_str, base_end_str)
fer_plan_counts = _count_days(fer_plan_all, plan_start_str, plan_end_str)
# Nur Bundesländer anzeigen, in denen es auch Filialen gibt
all_fer_keys = sorted(
    k for k in (set(fer_base_counts) | set(fer_plan_counts))
    if k.split(" – ")[0] in RELEVANT_BL
)
fer_compare_rows = []
for key in all_fer_keys:
    b, p = fer_base_counts.get(key, 0), fer_plan_counts.get(key, 0)
    diff = p - b
    flag = "⚠️" if diff != 0 else "✅"
    fer_compare_rows.append({
        "Bundesland – Ferienart": key,
        f"Basiszeitraum ({engine.base_window_label()}) Tage": b,
        f"Budgetjahr {planjahr} Tage": p,
        "Differenz Tage": diff, "Status": flag
    })
fer_df = pd.DataFrame(fer_compare_rows)
has_fer_diff = any(r["Differenz Tage"] != 0 for r in fer_compare_rows)
add("warn" if has_fer_diff else "ok",
    "Schulferientage je Bundesland: Basiszeitraum vs. Budgetjahr",
    fer_df if not fer_df.empty else None,
    "Unterschiedliche Ferientage erklären den Ferieneffekt im Budget.")

# 7) IST-Datenlücken: letztes IST-Datum > 35 Tage vor Max-IST aller Filialen
max_all_row = conn.execute("SELECT MAX(datum) AS d FROM ist_umsatz").fetchone()
stale = []
if max_all_row and max_all_row["d"]:
    max_all = date.fromisoformat(max_all_row["d"])
    cutoff = (max_all - timedelta(days=35)).isoformat()
    last_per_fil = {str(r["fil_nr"]): r["d"] for r in conn.execute(
        "SELECT fil_nr, MAX(datum) AS d FROM ist_umsatz GROUP BY fil_nr")}
    for f in filialen:
        fn = str(f["fil_nr"])
        last = last_per_fil.get(fn)
        if last and last < cutoff:
            stale.append({"Filiale": fn, "Letztes IST-Datum": last,
                          "Max IST gesamt": max_all_row["d"]})
add("warn" if stale else "ok",
    f"Filialen mit IST-Datenlücke (> 35 Tage hinter Max-IST): {len(stale)}",
    pd.DataFrame(stale) if stale else None,
    "Möglicherweise geschlossene Filialen oder unvollständiger Import.")

# 7b) Aktive Filialen ohne Umsatz im letzten Basismonat (möglicher Umbau)
_last_base_day = engine.base_mask_end.date() - timedelta(days=1)
_last_ym = f"{_last_base_day.year:04d}-{_last_base_day.month:02d}"
_umbau_cols = {r[1] for r in conn.execute("PRAGMA table_info(filialen)").fetchall()}
if "umbau_von" in _umbau_cols:
    _umbau_info = {
        str(r["fil_nr"]): {"umbau_von": r["umbau_von"] or "", "umbau_bis": r["umbau_bis"] or ""}
        for r in conn.execute("SELECT fil_nr, umbau_von, umbau_bis FROM filialen").fetchall()
    }
else:
    _umbau_info = {}
_last_month_sums = {
    str(r["fil_nr"]): float(r["s"])
    for r in conn.execute(
        "SELECT fil_nr, COALESCE(SUM(umsatz), 0) AS s FROM ist_umsatz "
        "WHERE strftime('%Y-%m', datum)=? GROUP BY fil_nr",
        (_last_ym,)
    ).fetchall()
}
_no_umsatz_last = []
for f in filialen:
    fn = str(f["fil_nr"])
    if fn not in ist_in_base:
        continue
    if _last_month_sums.get(fn, 0.0) == 0.0:
        _ui = _umbau_info.get(fn, {})
        _no_umsatz_last.append({
            "Filiale": fn,
            "Bezeichnung": f.get("bezeichnung", ""),
            "Letzter Basismonat": _last_ym,
            "Umbau von": _ui.get("umbau_von", ""),
            "Umbau bis": _ui.get("umbau_bis", ""),
        })
add("warn" if _no_umsatz_last else "ok",
    f"Aktive Filialen ohne Umsatz im letzten Basismonat ({_last_ym}): {len(_no_umsatz_last)}",
    pd.DataFrame(_no_umsatz_last) if _no_umsatz_last else None,
    "Diese Filialen werden bei der Planung hochgerechnet. "
    "Liegt ein Umbau vor, bitte 'Umbau von/bis' in den Filialstammdaten hinterlegen — "
    "im Umbau-Zeitraum werden keine Budgetwerte berechnet.")

# 8) parameter_monat für Budgetjahr vorhanden?
n_pm = conn.execute(
    "SELECT COUNT(*) AS n FROM parameter_monat WHERE planjahr=?", (planjahr,)
).fetchone()["n"]
add("warn" if n_pm == 0 else "ok",
    f"Wachstumsparameter (parameter_monat) für {planjahr}: {n_pm} Monate",
    None,
    "Ohne Einträge wird mit 0 % Wachstum geplant — Seite "
    "'Preisanpassung je Monat' pflegen." if n_pm < 12 else "")

# ── Gesamtampel ─────────────────────────────────────────────────────────────
n_crit = sum(1 for c in checks if c[0] == "crit")
n_warn = sum(1 for c in checks if c[0] == "warn")
if n_crit:
    st.error(f"❌ {n_crit} kritische Punkte, {n_warn} Hinweise — vor der "
             "Planung beheben. (❌ = kritisch, ⚠️ = Hinweis)")
elif n_warn:
    st.warning(f"⚠️ {n_warn} Hinweise — Planung möglich, Punkte prüfen.")
else:
    st.success("✅ Bereit zur Planung — alle Checks bestanden.")

st.divider()

ICON = {"ok": "✅", "warn": "⚠️", "crit": "❌"}
for status, titel, details, caption in checks:
    st.markdown(f"{ICON[status]} **{titel}**")
    if caption:
        st.caption(caption)
    if details is not None and not details.empty:
        with st.expander(f"Details ({len(details)})"):
            st.dataframe(details, use_container_width=True, hide_index=True)

# ── Validierungs-Status in DB speichern (für Menü-Badge in app.py) ────────────
_has_issue = n_crit > 0 or n_warn > 0 or not _cl_all_checked
conn.execute(
    "INSERT OR REPLACE INTO validation_status (planjahr, has_issue, updated_at) VALUES (?,?,?)",
    (planjahr, int(_has_issue), date.today().isoformat())
)
conn.commit()
