"""Core planning engine.

Basiszeitraum: rollierend die letzten 12 vollständig abgeschlossenen Monate ab
einem Stichtag (Default: heute). Jeder Kalendermonat 1–12 kommt im 12-Monats-
Fenster genau einmal vor und wird auf den gleichen Kalendermonat im (festen)
Planjahr abgebildet.

Additive Effekt-Zerlegung je Tag (exakt):
    budget = ist_vj
           + eff_oeffnung      (Öffnung/Schließung)
           + eff_verteilung    (Glättung Einzeltag → Wochentagsverteilung)
           + eff_wochentag     (Wochentagsmix-Verschiebung / Hochrechnung)
           + eff_preis         (Preisanpassung / Wachstum)
           + eff_ferien        (Ferienfaktor pro Woche)
           + eff_feiertag      (Feiertag / Sondertag)
           + eff_norm          (Normalisierungs-Rebalancing)

Dadurch lassen sich alle Effekte über beliebige Ebenen (Tag/Woche/Monat/Jahr,
Filiale/Bundesland/Gesamt) durch einfache Summenbildung aggregieren.

Ramadan & Fasching sind aktuell NICHT implementiert (offene Punkteliste).
Lieferkunden werden bewusst ignoriert.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterator

import pandas as pd


_BL_NAME_TO_ABBR = {
    "Brandenburg": "BB", "Berlin": "BE", "Baden-Württemberg": "BW",
    "Bayern": "BY", "Bremen": "HB", "Hessen": "HE", "Hamburg": "HH",
    "Mecklenburg-Vorpommern": "MV", "Niedersachsen": "NI", "Nordrhein-Westfalen": "NW",
    "Rheinland-Pfalz": "RP", "Schleswig-Holstein": "SH", "Saarland": "SL",
    "Sachsen": "SN", "Sachsen-Anhalt": "ST", "Thüringen": "TH",
    "DE-BB": "BB", "DE-BE": "BE", "DE-BW": "BW", "DE-BY": "BY",
    "DE-HB": "HB", "DE-HE": "HE", "DE-HH": "HH", "DE-MV": "MV",
    "DE-NI": "NI", "DE-NW": "NW", "DE-RP": "RP", "DE-SH": "SH",
    "DE-SL": "SL", "DE-SN": "SN", "DE-ST": "ST", "DE-TH": "TH",
}

def _normalize_bl(bl: str) -> str:
    """Normalize bundesland to 2-letter abbreviation."""
    if not bl:
        return "RP"
    return _BL_NAME_TO_ABBR.get(bl, bl)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PlanParams:
    planjahr: int
    stichtag: date | None = None            # Basiszeitraum endet am letzten abgeschl. Monat davor
    preiserhoehung_pct: float = 0.0
    wachstum_monat: dict[int, float] = field(default_factory=dict)
    ferien_puffer_wochen: int = 2
    # Ramadan/Fasching (offene Punkte – derzeit nicht angewendet)
    ramadan_vj_start: date | None = None
    ramadan_vj_ende: date | None = None
    ramadan_plan_start: date | None = None
    ramadan_plan_ende: date | None = None
    ramadan_umsatz_pct: float = 0.0
    fasching_vj_start: date | None = None
    fasching_vj_ende: date | None = None
    fasching_plan_start: date | None = None
    fasching_plan_ende: date | None = None
    fasching_wirkung_pct: float = 0.0


@dataclass
class DayPlan:
    fil_nr: str
    datum: date
    wochentag: int          # 0=Mo…6=So
    bundesland: str
    ist_vj: float
    # additive effects
    eff_oeffnung: float
    eff_hochrechnung: float     # imputation for days without base IST (new branches)
    eff_verteilung: float
    eff_wochentag: float
    eff_preis: float
    eff_ferien: float
    eff_feiertag: float
    eff_norm: float
    budget: float
    # monthly context
    monat_basis: float
    monat_hoch: float
    monat_plan: float
    tagestyp: str           # normal|feiertag|sondertag|ferien|geschlossen
    feiertag_name: str
    ferien_art: str
    normalisierung: float
    # engine2-only fields (default 0 so engine.py / L1 is unaffected)
    gewuenschter_monatsumsatz: float = 0.0
    budget_i: float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _shift_back_one_year(d: date) -> date:
    """Same calendar day one year earlier (Feb 29 → Feb 28)."""
    return _safe_date(d.year - 1, d.month, d.day) or date(d.year - 1, 2, 28)


def match_ferien_periods(plan_rows: list[dict], vj_rows: list[dict]) -> list[dict]:
    """Match plan-year ferien periods to the correct prior-year (VJ) period.

    ``(bundesland, art)`` is NOT unique: Weihnachtsferien appear twice per
    calendar year (the January tail of the previous winter break and the
    December start of the next one). Matching only on ``(bundesland, art)``
    therefore mismatched the January plan period with the December VJ period.

    Each plan period is matched to the VJ period of the same ``(bundesland,
    art)`` whose start date is closest to the plan start shifted back one year.
    This keeps January↔January and December↔December comparisons correct.

    Returns a list of dicts:
        {bundesland, art, start_vj, ende_vj, start_plan, ende_plan}
    Plan periods without any VJ counterpart are skipped (as before).
    """
    from collections import defaultdict

    vj_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for r in vj_rows:
        vj_by_key[(r["bundesland"], r["art"])].append(r)

    result: list[dict] = []
    for p in plan_rows:
        cands = vj_by_key.get((p["bundesland"], p["art"]))
        if not cands:
            continue
        p_start = date.fromisoformat(p["start"])
        target = _shift_back_one_year(p_start)
        best = min(cands,
                   key=lambda c: abs((date.fromisoformat(c["start"]) - target).days))
        result.append({
            "bundesland": p["bundesland"], "art": p["art"],
            "start_vj": best["start"], "ende_vj": best["ende"],
            "start_plan": p["start"], "ende_plan": p["ende"],
        })
    return result


def is_special_quasi_feiertag(d: date) -> bool:
    """Dec 24 and Dec 31 are treated like holidays (reduced/closed business).

    They must never serve as a base-comparison day for normal or ferien days,
    and a plan Dec 24/31 always compares to the same calendar date in the base
    year (handled in datumsmapping).
    """
    return d.month == 12 and d.day in (24, 31)


# ── Main engine ───────────────────────────────────────────────────────────────

class PlanningEngine:

    def __init__(self, conn: sqlite3.Connection, params: PlanParams):
        self.conn = conn
        self.p = params
        self._ist_branch_cache: dict[str, pd.DataFrame] = {}
        self._compute_base_window()
        self._load_reference_data()

    # ── Basiszeitraum (rollierend) ────────────────────────────────────────

    def _compute_base_window(self):
        """Letzter abgeschlossener Monat vor Stichtag → 12-Monats-Fenster."""
        stichtag = self.p.stichtag or date.today()
        last_complete = stichtag.replace(day=1) - timedelta(days=1)
        self.base_end_year = last_complete.year
        self.base_end_month = last_complete.month
        # Fenster: 12 Monate endend mit (base_end_year, base_end_month)
        self.base_start = (date(self.base_end_year, self.base_end_month, 1)
                           - timedelta(days=1)).replace(day=1)
        # base_start ist Monat (end-11). Bilde sauber:
        m = self.base_end_month - 11
        y = self.base_end_year
        while m <= 0:
            m += 12
            y -= 1
        self.base_start = date(y, m, 1)
        self.base_end = date(self.base_end_year, self.base_end_month, 1)

    def base_year_for_month(self, month: int) -> int:
        """Welches Kalenderjahr hat dieser Monat im rollierenden Fenster?"""
        return self.base_end_year if month <= self.base_end_month else self.base_end_year - 1

    def base_window_label(self) -> str:
        de = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
        return (f"{de[self.base_start.month-1]} {self.base_start.year} – "
                f"{de[self.base_end.month-1]} {self.base_end.year}")

    # ── Setup ─────────────────────────────────────────────────────────────

    def _load_reference_data(self):
        p = self.p
        c = self.conn.cursor()

        # Feiertage Planjahr: {datum_plan → list of {name, datum_vj, bundesland, art}}
        # Only art='feiertag' — feiertagstage (Vor-/Nachtage) are treated as normal open days
        rows = c.execute("SELECT datum_plan, datum_vj, name, bundesland, art FROM feiertage").fetchall()
        self.feiertage: dict[str, list[dict]] = {}
        # VJ-Feiertage: {datum_vj → list of {name, bundesland}} — nur art='feiertag'.
        # Wird gebraucht, um beim Datumsmapping Basistage zu erkennen, die im
        # Basisjahr ein Feiertag sind (feiertage ist nach datum_plan indiziert,
        # daher findet eine Suche nach Basisjahr-Datum dort sonst nichts).
        self.feiertage_vj: dict[str, list[dict]] = {}
        for r in rows:
            art = r["art"] if r["art"] else "feiertag"
            self.feiertage.setdefault(r["datum_plan"], []).append(
                {"name": r["name"], "datum_vj": r["datum_vj"], "bundesland": r["bundesland"],
                 "art": art}
            )
            if art == "feiertag" and r["datum_vj"]:
                self.feiertage_vj.setdefault(r["datum_vj"], []).append(
                    {"name": r["name"], "bundesland": r["bundesland"]}
                )

        # Sondertage (Legacy-Tabelle)
        rows = c.execute("SELECT datum_plan, datum_referenz, bezeichnung, methode, bundesland FROM sondertage").fetchall()
        self.sondertage: dict[str, dict] = {r["datum_plan"]: dict(r) for r in rows}
        # Sondertage aus feiertage (art='Sondertag') — dort speichert die UI sie
        for r in c.execute(
            "SELECT datum_plan, datum_vj, name, bundesland FROM feiertage "
            "WHERE LOWER(art)='sondertag'"
        ).fetchall():
            if r["datum_plan"] not in self.sondertage:
                self.sondertage[r["datum_plan"]] = {
                    "datum_plan": r["datum_plan"],
                    "datum_referenz": r["datum_vj"],
                    "bezeichnung": r["name"],
                    "methode": "referenz",
                    "bundesland": r["bundesland"],
                }

        # Ferien Planjahr — direkt aus ferien_kalender abgeleitet (eine Quelle
        # der Wahrheit; ersetzt den früheren Sync ferien_kalender→ferien).
        # Planjahr-Perioden + zugehörige Vorjahresperioden, gematcht über
        # bundesland+art. Ohne Vorjahresperiode wird die Periode übersprungen
        # (wie der frühere Sync). Die Legacy-Tabelle `ferien` ist deprecated.
        plan_rows = [dict(r) for r in c.execute(
            "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
            (p.planjahr,)).fetchall()]
        vj_rows = [dict(r) for r in c.execute(
            "SELECT bundesland, art, start, ende FROM ferien_kalender WHERE jahr=?",
            (p.planjahr - 1,)).fetchall()]
        # Nearest-start matching handles the Weihnachtsferien year-boundary split
        # (Jan↔Jan, Dec↔Dec) instead of an ambiguous (bundesland, art) lookup.
        self.ferien_plan: list[dict] = match_ferien_periods(plan_rows, vj_rows)
        self._build_ferien_windows()

        # IST-Daten (gesamt)
        df = pd.read_sql("SELECT fil_nr, datum, umsatz FROM ist_umsatz", self.conn)
        df["datum"] = pd.to_datetime(df["datum"])
        df["umsatz"] = df["umsatz"].round(2)
        self.ist_df = df

        # Filialen master
        self.filialen = {r["fil_nr"]: dict(r) for r in c.execute("SELECT * FROM filialen").fetchall()}

        # Öffnungstage je Filiale: {fil_nr → {wochentag → offen}}
        self.oeffnung: dict[str, dict[int, bool]] = {}
        for r in c.execute("SELECT fil_nr, wochentag, offen FROM filial_oeffnung").fetchall():
            self.oeffnung.setdefault(r["fil_nr"], {})[r["wochentag"]] = bool(r["offen"])

        # Feiertags-Öffnung: {fil_nr → {feiertag_name → offen}}
        self.feiertag_offen: dict[str, dict[str, bool]] = {}
        for r in c.execute("SELECT fil_nr, feiertag_name, offen FROM filial_feiertag").fetchall():
            self.feiertag_offen.setdefault(r["fil_nr"], {})[r["feiertag_name"]] = bool(r["offen"])

        # Manuelle Overrides
        rows = c.execute(
            "SELECT fil_nr, monat, planwert FROM planwert_override WHERE planjahr=?", (p.planjahr,)
        ).fetchall()
        self.overrides: dict[tuple, float] = {(r["fil_nr"], r["monat"]): r["planwert"] for r in rows}

        # Neue Filialen
        rows = c.execute(
            "SELECT fil_nr, monat, planwert, eroeffnung_datum FROM neue_filialen_plan WHERE planjahr=?",
            (p.planjahr,)
        ).fetchall()
        self.neue_plan: dict[tuple, dict] = {
            (r["fil_nr"], r["monat"]): {"planwert": r["planwert"], "eroeffnung": r["eroeffnung_datum"]}
            for r in rows
        }

        # Obergrenze (exklusiv) des Basisfensters für schnelle Maskierung
        self.base_mask_end = self._next_month(self.base_end_year, self.base_end_month)

        # Datumsmapping: {(plan_datum, bundesland) → base_datum_str} — nur für planjahr
        dm_rows = c.execute(
            "SELECT plan_datum, base_datum, bundesland, mapping_art FROM datumsmapping "
            "WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ?",
            (p.planjahr,)
        ).fetchall()
        self._datumsmapping: dict[tuple, str] = {
            (r["plan_datum"], r["bundesland"]): r["base_datum"] for r in dm_rows
        }
        self._datumsmapping_art: dict[tuple, str] = {
            (r["plan_datum"], r["bundesland"]): r["mapping_art"] for r in dm_rows
        }

    @staticmethod
    def _next_month(year: int, month: int) -> pd.Timestamp:
        if month == 12:
            return pd.Timestamp(date(year + 1, 1, 1))
        return pd.Timestamp(date(year, month + 1, 1))

    def _build_ferien_windows(self):
        """Mappe Plan-Ferientage → (art, wochenindex, period). Puffer separat (VJ-Berechnung)."""
        # iso → {bl: (art, woche, period)} — period disambiguates the two
        # Weihnachtsferien occurrences (Jan tail vs Dec start) per calendar year.
        self.ferien_plan_dates: dict[str, dict[str, tuple]] = {}
        self.ferien_vj_dates: set[str] = set()  # alle VJ-Ferientage (für direkte Vergleichsprüfung)
        for f in self.ferien_plan:
            bl = f["bundesland"]
            art = f["art"]
            start = date.fromisoformat(f["start_plan"])
            ende = date.fromisoformat(f["ende_plan"])
            for d in _date_range(start, ende):
                woche = (d - start).days // 7 + 1
                self.ferien_plan_dates.setdefault(d.isoformat(), {})[bl] = (art, woche, f)
            # VJ-Ferientage für direkten Vergleich tracken
            vj_start = date.fromisoformat(f["start_vj"])
            vj_ende = date.fromisoformat(f["ende_vj"])
            for d in _date_range(vj_start, vj_ende):
                self.ferien_vj_dates.add(d.isoformat())

    # ── Per-branch IST helpers (Basiszeitraum) ────────────────────────────

    def _branch_base_ist(self, fil_nr: str) -> pd.DataFrame:
        if fil_nr not in self._ist_branch_cache:
            df = self.ist_df[self.ist_df["fil_nr"] == fil_nr]
            df = df[(df["datum"] >= pd.Timestamp(self.base_start)) &
                    (df["datum"] < self.base_mask_end)]
            self._ist_branch_cache[fil_nr] = df.reset_index(drop=True)
        return self._ist_branch_cache[fil_nr]

    def _weekday_avg(self, fil_nr: str, fil: dict) -> dict[int, float]:
        """Ø Umsatz je Wochentag im Basiszeitraum (nur offene Tage, ohne erste 4 Wochen nach Eröffnung)."""
        df = self._branch_base_ist(fil_nr)
        if df.empty:
            return {i: 0.0 for i in range(7)}
        eroeffnung = fil.get("eroeffnung")
        if eroeffnung:
            cutoff = date.fromisoformat(eroeffnung) + timedelta(weeks=4)
            df = df[df["datum"] >= pd.Timestamp(cutoff)]
        df = df[df["umsatz"] > 0]
        if df.empty:
            return {i: 0.0 for i in range(7)}
        avgs = df.groupby(df["datum"].dt.weekday)["umsatz"].mean().to_dict()
        return {i: float(avgs.get(i, 0.0)) for i in range(7)}

    def _base_month_ist(self, fil_nr: str, fil: dict, month: int) -> float:
        """IST-Monatsumsatz im Basiszeitraum für Kalendermonat (rollierendes Jahr)."""
        by = self.base_year_for_month(month)
        df = self._branch_base_ist(fil_nr)
        df_m = df[(df["datum"].dt.year == by) & (df["datum"].dt.month == month)]
        if not df_m.empty and df_m["umsatz"].sum() > 0:
            return round(df_m["umsatz"].sum(), 2)
        # Extrapolation aus Wochentags-Ø
        wt_avg = self._weekday_avg(fil_nr, fil)
        dim = pd.Period(f"{by}-{month:02d}").days_in_month
        total = sum(wt_avg[date(by, month, d).weekday()] for d in range(1, dim + 1))
        return round(total, 2)

    def _count_weekdays(self, year: int, month: int) -> dict[int, int]:
        dim = pd.Period(f"{year}-{month:02d}").days_in_month
        counts = {i: 0 for i in range(7)}
        for d in range(1, dim + 1):
            counts[date(year, month, d).weekday()] += 1
        return counts

    def _weekday_pct(self, fil_nr: str, month: int) -> dict[int, float]:
        """Anteil je Wochentag am Monatsumsatz (Basiszeitraum)."""
        by = self.base_year_for_month(month)
        df = self._branch_base_ist(fil_nr)
        df_m = df[(df["datum"].dt.year == by) & (df["datum"].dt.month == month) & (df["umsatz"] > 0)]
        if df_m.empty:
            return {i: 1 / 7 for i in range(7)}
        total = df_m["umsatz"].sum()
        if total == 0:
            return {i: 1 / 7 for i in range(7)}
        pcts = df_m.groupby(df_m["datum"].dt.weekday)["umsatz"].sum() / total
        return {i: float(pcts.get(i, 0.0)) for i in range(7)}

    def _saturday_avg(self, fil_nr: str) -> float:
        df = self._branch_base_ist(fil_nr)
        sat = df[(df["datum"].dt.weekday == 5) & (df["umsatz"] > 0)]["umsatz"]
        return float(sat.mean()) if not sat.empty else 0.0

    def _ist_on(self, fil_nr: str, d: date | None) -> float:
        if d is None:
            return 0.0
        mask = (self.ist_df["fil_nr"] == fil_nr) & (self.ist_df["datum"] == pd.Timestamp(d))
        return float(self.ist_df.loc[mask, "umsatz"].sum())

    # ── Öffnungslogik ─────────────────────────────────────────────────────

    def _is_open_weekday(self, fil_nr: str, wt: int) -> bool:
        wd = self.oeffnung.get(fil_nr)
        if wd is None or wt not in wd:
            return True   # keine Info → offen annehmen
        return wd[wt]

    def _is_open_feiertag(self, fil_nr: str, feiertag_name: str) -> bool:
        fd = self.feiertag_offen.get(fil_nr, {})
        # Default: geschlossen, wenn nichts hinterlegt (neue Filiale ohne Historie)
        return fd.get(feiertag_name, False)

    # ── Ferienfaktor pro Woche ────────────────────────────────────────────

    def _ferien_faktor_fallback(self, fil_nr: str, bl: str, art: str) -> float:
        """Fallback ferien factor when no VJ period exists for this ferien type.

        Tries the most recent period of the same art for the same BL, then
        any other available ferien period for that BL.
        """
        candidates = [p for p in self.ferien_plan if p["bundesland"] == bl and p.get("start_vj")]
        # Prefer same art, then any; sort by start_vj descending (most recent first)
        same_art = [p for p in candidates if p["art"] == art]
        ordered = (same_art or candidates)
        ordered = sorted(ordered, key=lambda p: p["start_vj"], reverse=True)
        for p in ordered:
            ff = self._ferien_faktor_woche(fil_nr, p, 1)
            if ff != 1.0:
                return ff
        return 1.0

    def _ferien_faktor_woche(self, fil_nr: str, period: dict | None, woche: int) -> float:
        """Lese/berechne Ferienfaktor: Ø Umsatz Ferienwoche / Ø Puffer (Wochentags-gematcht)."""
        if not period:
            return 1.0
        key = (fil_nr, period["bundesland"], period["art"], period["start_plan"], woche)
        if key in self._ferien_cache:
            return self._ferien_cache[key]

        df = self._branch_base_ist(fil_nr)
        if df.empty:
            self._ferien_cache[key] = 1.0
            return 1.0

        vj_start = date.fromisoformat(period["start_vj"])
        vj_ende = date.fromisoformat(period["ende_vj"])
        # Pufferfenster: N Wochen vor VJ-Start
        puf_start = vj_start - timedelta(weeks=self.p.ferien_puffer_wochen)
        puf_ende = vj_start - timedelta(days=1)

        # Wochentags-Ø im Puffer
        puf = df[(df["datum"] >= pd.Timestamp(puf_start)) &
                 (df["datum"] <= pd.Timestamp(puf_ende)) & (df["umsatz"] > 0)]
        if puf.empty:
            self._ferien_cache[key] = 1.0
            return 1.0
        puf_wt = puf.groupby(puf["datum"].dt.weekday)["umsatz"].mean().to_dict()

        # Ferienwoche 'woche' im VJ
        wk_start = vj_start + timedelta(weeks=woche - 1)
        wk_ende = min(vj_start + timedelta(weeks=woche) - timedelta(days=1), vj_ende)
        wk = df[(df["datum"] >= pd.Timestamp(wk_start)) &
                (df["datum"] <= pd.Timestamp(wk_ende)) & (df["umsatz"] > 0)]
        if wk.empty:
            # Fallback: use all days in the full VJ ferien period for this weekday mix
            wk = df[(df["datum"] >= pd.Timestamp(vj_start)) &
                    (df["datum"] <= pd.Timestamp(vj_ende)) & (df["umsatz"] > 0)]

        # Wochentags-gematchtes Verhältnis
        ratios = []
        for _, r in wk.iterrows():
            wt = r["datum"].weekday()
            base = puf_wt.get(wt)
            if base and base > 0:
                ratios.append(r["umsatz"] / base)
        faktor = round(sum(ratios) / len(ratios), 4) if ratios else 1.0
        self._ferien_cache[key] = faktor
        return faktor

    def _ferien_info_for_day(self, iso: str, bl: str) -> tuple[str, int] | None:
        bls = self.ferien_plan_dates.get(iso, {})
        entry = bls.get(bl) or bls.get("alle")
        if entry is None:
            return None
        art, woche, _period = entry
        return art, woche

    def _ferien_period_for_day(self, iso: str, bl: str) -> dict | None:
        """Die konkrete Ferienperiode (mit start_vj/ende_vj), die diesen Plantag abdeckt."""
        bls = self.ferien_plan_dates.get(iso, {})
        entry = bls.get(bl) or bls.get("alle")
        if entry is None:
            return None
        return entry[2]

    # ── Feiertag / Sondertag ──────────────────────────────────────────────

    def _feiertag_base_date(self, ft: dict, plan_month: int) -> date | None:
        """Basis-Referenzdatum eines Feiertags im rollierenden Fenster.

        Nutzt das hinterlegte datum_vj, sofern es im Basisfenster liegt
        (wichtig für bewegliche Feiertage wie Ostern); sonst rekonstruiert es
        Tag/Monat im passenden Basisjahr.
        """
        vj_ref = ft.get("datum_vj")
        if vj_ref:
            try:
                d = date.fromisoformat(vj_ref)
            except ValueError:
                d = None
            if d and self.base_start <= d < self.base_mask_end.date():
                return d
            if d:
                return _safe_date(self.base_year_for_month(d.month), d.month, d.day)
        return None

    def _relevant_feiertag(self, iso: str, bl: str) -> dict | None:
        for ft in self.feiertage.get(iso, []):
            if ft["bundesland"] in ("alle", bl) and ft.get("art", "feiertag") == "feiertag":
                return ft
        return None

    def _relevant_sondertag(self, iso: str, bl: str) -> dict | None:
        st = self.sondertage.get(iso)
        if st and st["bundesland"] in ("alle", bl):
            return st
        return None

    def _growth(self, fil: dict, month: int) -> float:
        if fil.get("flag_kein_wachstum"):
            return 1.0
        pct = self.p.wachstum_monat.get(month, self.p.preiserhoehung_pct)
        return 1 + pct / 100

    # ── Monatsplan ────────────────────────────────────────────────────────

    def _monat_werte(self, fil_nr: str, fil: dict, month: int) -> tuple[float, float, float]:
        """Return (monat_basis, monat_hoch, monat_plan)."""
        # Override
        if (fil_nr, month) in self.overrides:
            ov = self.overrides[(fil_nr, month)]
            return ov, ov, ov

        # Neue Filiale → manueller Planwert
        eroeff_str = fil.get("eroeffnung")
        if eroeff_str and date.fromisoformat(eroeff_str).year == self.p.planjahr:
            entry = self.neue_plan.get((fil_nr, month))
            if entry:
                planwert = entry["planwert"]
                er = entry.get("eroeffnung")
                if er:
                    erd = date.fromisoformat(er)
                    if erd.month == month and erd.year == self.p.planjahr:
                        planwert *= 0.5
                return 0.0, 0.0, planwert
            return 0.0, 0.0, 0.0

        # Bestand: Basis → Hochrechnung → Wachstum
        monat_basis = self._base_month_ist(fil_nr, fil, month)
        by = self.base_year_for_month(month)
        wt_base = self._count_weekdays(by, month)
        wt_plan = self._count_weekdays(self.p.planjahr, month)
        wt_avg = self._weekday_avg(fil_nr, fil)
        tot_base = sum(wt_base[w] * wt_avg[w] for w in range(7))
        tot_plan = sum(wt_plan[w] * wt_avg[w] for w in range(7))
        factor = (tot_plan / tot_base) if tot_base > 0 else 1.0
        monat_hoch = round(monat_basis * factor, 2)
        monat_plan = round(monat_hoch * self._growth(fil, month), 2)
        return monat_basis, monat_hoch, monat_plan

    # ── Tagesplanung je Filiale ───────────────────────────────────────────

    def _day_status(self, fil_nr: str, fil: dict, d: date, bl: str,
                    wt_pct: dict[int, float]) -> dict:
        iso = d.isoformat()
        wt = d.weekday()
        closed = False
        tagestyp = "normal"
        feiertag_name = ""
        ferien_art = ""
        ferien_woche = 0

        eroeff = fil.get("eroeffnung")
        ende = fil.get("eroeffnung_ende")
        ft = self._relevant_feiertag(iso, bl)
        st = self._relevant_sondertag(iso, bl)
        fer = self._ferien_info_for_day(iso, bl)

        if eroeff and date.fromisoformat(eroeff) > d:
            closed = True
        elif ende and date.fromisoformat(ende) < d:
            closed = True
        elif not self._is_open_weekday(fil_nr, wt):
            closed = True
        elif ft and not self._is_open_feiertag(fil_nr, ft["name"]):
            closed = True
            feiertag_name = ft["name"]

        zaehlt_offen = False
        if not closed:
            if ft:
                tagestyp = "feiertag"
                feiertag_name = ft["name"]
            elif st:
                tagestyp = "sondertag"
                feiertag_name = st["bezeichnung"]
            elif fer:
                tagestyp = "ferien"
                ferien_art, ferien_woche = fer
            if wt_pct.get(wt, 0) > 0 or tagestyp in ("feiertag", "sondertag"):
                zaehlt_offen = True

        return {
            "d": d, "wt": wt, "closed": closed, "tagestyp": tagestyp,
            "feiertag_name": feiertag_name, "ferien_art": ferien_art,
            "ferien_woche": ferien_woche, "ft": ft, "st": st,
            "zaehlt_offen": zaehlt_offen,
        }

    def _day_raw(self, fil_nr: str, bl: str, month: int, m: dict, growth: float,
                 monat_basis: float, monat_hoch: float, monat_plan: float,
                 share) -> dict:
        d, wt = m["d"], m["wt"]
        _day_iso = d.isoformat()
        _mapping_base = (
            self._datumsmapping.get((_day_iso, bl))
            or self._datumsmapping.get((_day_iso, "alle"))
        )
        _mapping_art = (
            self._datumsmapping_art.get((_day_iso, bl))
            or self._datumsmapping_art.get((_day_iso, "alle"))
            or "iso_kw"
        )
        if _mapping_base:
            _base_d = date.fromisoformat(_mapping_base)
        else:
            _base_d = _safe_date(self.base_year_for_month(month), month, d.day)
        ist_vj = self._ist_on(fil_nr, _base_d)

        if m["closed"]:
            return {**m, "ist_vj": ist_vj, "tag_basis": 0.0, "tag_hoch": 0.0,
                    "tag_plan": 0.0, "raw": 0.0, "eff_ferien": 0.0,
                    "eff_feiertag": 0.0, "tagestyp": "geschlossen"}

        sh = share(wt)
        tag_basis = monat_basis * sh
        tag_hoch = monat_hoch * sh
        tag_plan = monat_plan * sh

        eff_ferien = 0.0
        eff_feiertag = 0.0
        raw = tag_plan
        direct_ferien = False

        if m["tagestyp"] == "feiertag":
            ft = m["ft"]
            ref = self._feiertag_base_date(ft, month)
            vj_val = self._ist_on(fil_nr, ref)
            raw = round(vj_val * growth, 2)
            eff_feiertag = 0.0
            direct_ferien = True  # reuse direct-comparison flag
        elif m["tagestyp"] == "sondertag":
            st = m["st"]
            if st["methode"] == "samstag":
                raw = round(self._saturday_avg(fil_nr) * growth, 2)
                eff_feiertag = raw - tag_plan
            elif st.get("datum_referenz"):
                raw = round(ist_vj * growth, 2)
                eff_feiertag = 0.0
                direct_ferien = True
            else:
                raw = 0.0
                eff_feiertag = raw - tag_plan
        elif m["tagestyp"] == "ferien":
            base_iso = _base_d.isoformat() if _base_d else None
            if base_iso and base_iso in self.ferien_vj_dates:
                raw = round(ist_vj * growth, 2)
                eff_ferien = 0.0
                direct_ferien = True
            elif _mapping_art == "Ferienabschlag":
                period = self._ferien_period_for_day(d.isoformat(), bl)
                if period:
                    ff = self._ferien_faktor_woche(fil_nr, period, m["ferien_woche"])
                else:
                    ff = self._ferien_faktor_fallback(fil_nr, bl, m.get("ferien_art", ""))
                raw = round(ist_vj * growth * ff, 2)
                eff_ferien = raw - round(ist_vj * growth, 2)
            else:
                period = self._ferien_period_for_day(d.isoformat(), bl)
                if period:
                    ff = self._ferien_faktor_woche(fil_nr, period, m["ferien_woche"])
                else:
                    ff = self._ferien_faktor_fallback(fil_nr, bl, m.get("ferien_art", ""))
                raw = round(tag_plan * ff, 2)
                eff_ferien = raw - tag_plan

        return {**m, "ist_vj": ist_vj, "tag_basis": tag_basis, "tag_hoch": tag_hoch,
                "tag_plan": tag_plan, "raw": raw, "eff_ferien": eff_ferien,
                "eff_feiertag": eff_feiertag, "_direct_ferien": direct_ferien,
                "_growth": growth}

    @staticmethod
    def _normalize_month(rows: list[dict], monat_plan: float) -> float:
        raw_sum = sum(r["raw"] for r in rows)
        return (monat_plan / raw_sum) if raw_sum > 0 else 1.0

    def _build_dayplan(self, fil_nr: str, bl: str, r: dict, norm: float,
                       monat_basis: float, monat_hoch: float,
                       monat_plan: float, wt_eff_per_day: float = 0.0) -> DayPlan:
        if r["tagestyp"] == "geschlossen":
            eff_oeffnung = -r["ist_vj"]
            return DayPlan(
                fil_nr=fil_nr, datum=r["d"], wochentag=r["wt"], bundesland=bl,
                ist_vj=round(r["ist_vj"], 2),
                eff_oeffnung=round(eff_oeffnung, 2), eff_hochrechnung=0.0, eff_verteilung=0.0,
                eff_wochentag=0.0, eff_preis=0.0, eff_ferien=0.0,
                eff_feiertag=0.0, eff_norm=0.0, budget=0.0,
                monat_basis=round(monat_basis, 2), monat_hoch=round(monat_hoch, 2),
                monat_plan=round(monat_plan, 2), tagestyp="geschlossen",
                feiertag_name=r["feiertag_name"], ferien_art=r["ferien_art"],
                normalisierung=round(norm, 4),
            )

        budget = round(r["raw"] * norm, 2)
        eff_norm = budget - r["raw"]

        if r.get("_direct_ferien"):
            g = r.get("_growth", 1.0)
            eff_verteilung = 0.0
            eff_wochentag = round(wt_eff_per_day, 2)
            eff_preis = round(r["ist_vj"] * (g - 1), 2)
            eff_ferien = 0.0
            eff_norm = round(budget - r["raw"] - eff_wochentag, 2)
        else:
            old_wt = r["tag_hoch"] - r["tag_basis"]
            eff_wochentag = round(wt_eff_per_day, 2)
            eff_verteilung = round(r["tag_basis"] - r["ist_vj"] + old_wt - wt_eff_per_day, 2)
            eff_preis = r["tag_plan"] - r["tag_hoch"]
            eff_ferien = r["eff_ferien"]

        return DayPlan(
            fil_nr=fil_nr, datum=r["d"], wochentag=r["wt"], bundesland=bl,
            ist_vj=round(r["ist_vj"], 2),
            eff_oeffnung=0.0,
            eff_hochrechnung=0.0,
            eff_verteilung=round(eff_verteilung, 2),
            eff_wochentag=round(eff_wochentag, 2),
            eff_preis=round(eff_preis, 2),
            eff_ferien=round(eff_ferien, 2),
            eff_feiertag=round(r["eff_feiertag"], 2),
            eff_norm=round(eff_norm, 2),
            budget=budget,
            monat_basis=round(monat_basis, 2), monat_hoch=round(monat_hoch, 2),
            monat_plan=round(monat_plan, 2),
            tagestyp=r["tagestyp"], feiertag_name=r["feiertag_name"],
            ferien_art=r["ferien_art"], normalisierung=round(norm, 4),
        )

    def plan_branch(self, fil_nr: str) -> list[DayPlan]:
        self._ferien_cache: dict[tuple, float] = {}
        fil = self.filialen.get(fil_nr, {"bundesland": "RP"})
        bl = _normalize_bl(fil.get("bundesland", "RP") or "RP")
        results: list[DayPlan] = []
        py = self.p.planjahr

        for month in range(1, 13):
            monat_basis, monat_hoch, monat_plan = self._monat_werte(fil_nr, fil, month)
            growth = self._growth(fil, month)
            wt_pct = self._weekday_pct(fil_nr, month)
            dim = pd.Period(f"{py}-{month:02d}").days_in_month

            # Schritt 1: Tagesstatus + offene Wochentags-Counts (share-Nenner)
            open_wt_count = {i: 0 for i in range(7)}
            day_meta = []
            for day in range(1, dim + 1):
                m = self._day_status(fil_nr, fil, date(py, month, day), bl, wt_pct)
                if m["zaehlt_offen"]:
                    open_wt_count[m["wt"]] += 1
                day_meta.append(m)

            # Wochentag-Effekt flach über alle offenen Tage verteilen
            n_open_days = sum(1 for m in day_meta if not m["closed"])
            wt_eff_per_day = ((monat_hoch - monat_basis) / n_open_days
                              if n_open_days > 0 else 0.0)

            # share-Nenner: offene Vorkommen je Wochentag (min 1)
            def share(wt: int) -> float:
                n = open_wt_count.get(wt, 0)
                return (wt_pct.get(wt, 0.0) / n) if n > 0 else 0.0

            # Schritt 2: raw-Werte je Tag
            rows = [self._day_raw(fil_nr, bl, month, m, growth,
                                  monat_basis, monat_hoch, monat_plan, share)
                    for m in day_meta]

            # Schritt 3: Normierung auf monat_plan (nur offene Tage)
            norm = self._normalize_month(rows, monat_plan)

            # Schritt 4: DayPlan-Konstruktion
            results.extend(
                self._build_dayplan(fil_nr, bl, r, norm,
                                    monat_basis, monat_hoch, monat_plan,
                                    wt_eff_per_day=wt_eff_per_day)
                for r in rows)

        return results

    # ── Fasching-Info (für Parameter-Anzeige; nicht angewendet) ───────────

    def fasching_info(self) -> dict:
        p = self.p
        if not all([p.fasching_vj_start, p.fasching_vj_ende, p.fasching_plan_start, p.fasching_plan_ende]):
            return {}
        vj_days = (p.fasching_vj_ende - p.fasching_vj_start).days + 1
        plan_days = (p.fasching_plan_ende - p.fasching_plan_start).days + 1
        diff = plan_days - vj_days
        return {"differenz_tage": diff,
                "hinweis": (f"Fasching {p.planjahr} ist {abs(diff)} Tage "
                            f"{'länger' if diff > 0 else 'kürzer'} (derzeit nicht in Planung berücksichtigt).")
                if diff != 0 else "Fasching gleich lang."}

    # ── Full run ──────────────────────────────────────────────────────────

    def run(self, fil_nrs: list[str] | None = None) -> list[DayPlan]:
        targets = fil_nrs if fil_nrs else list(self.filialen.keys())
        out: list[DayPlan] = []
        for fil_nr in targets:
            fil = self.filialen.get(fil_nr, {})
            if fil.get("flag_gesperrt") or fil.get("flag_inaktiv"):
                continue
            out.extend(self.plan_branch(fil_nr))
        return out

    def save(self, results: list[DayPlan]):
        if not results:
            return
        # Delete existing plan rows for these branches in this plan year
        fil_nrs = list({r.fil_nr for r in results})
        placeholders = ",".join("?" * len(fil_nrs))
        self.conn.execute(
            f"DELETE FROM planung WHERE fil_nr IN ({placeholders}) "
            f"AND CAST(strftime('%Y', datum) AS INTEGER)=?",
            fil_nrs + [self.p.planjahr],
        )
        rows = [{
            "fil_nr": r.fil_nr, "datum": r.datum.isoformat(), "wochentag": r.wochentag,
            "bundesland": r.bundesland, "ist_vj": r.ist_vj,
            "eff_oeffnung": r.eff_oeffnung, "eff_verteilung": r.eff_verteilung,
            "eff_wochentag": r.eff_wochentag, "eff_preis": r.eff_preis,
            "eff_ferien": r.eff_ferien, "eff_feiertag": r.eff_feiertag,
            "eff_norm": r.eff_norm, "budget": r.budget,
            "monat_basis": r.monat_basis, "monat_hoch": r.monat_hoch, "monat_plan": r.monat_plan,
            "monatsumsatz_ist_hoch": r.monat_hoch, "monatsumsatz_plan": r.monat_plan,
            "tagesumsatz_plan": r.budget, "liefer_plan": 0.0, "gesamt_plan": r.budget,
            "tagestyp": r.tagestyp, "feiertag_name": r.feiertag_name,
            "ferien_art": r.ferien_art, "normalisierung": r.normalisierung,
        } for r in results]
        self.conn.executemany(
            """INSERT OR REPLACE INTO planung
               (fil_nr, datum, wochentag, bundesland, ist_vj,
                eff_oeffnung, eff_verteilung, eff_wochentag, eff_preis,
                eff_ferien, eff_feiertag, eff_norm, budget,
                monat_basis, monat_hoch, monat_plan,
                monatsumsatz_ist_hoch, monatsumsatz_plan, tagesumsatz_plan,
                liefer_plan, gesamt_plan, tagestyp, feiertag_name, ferien_art, normalisierung)
               VALUES
               (:fil_nr, :datum, :wochentag, :bundesland, :ist_vj,
                :eff_oeffnung, :eff_verteilung, :eff_wochentag, :eff_preis,
                :eff_ferien, :eff_feiertag, :eff_norm, :budget,
                :monat_basis, :monat_hoch, :monat_plan,
                :monatsumsatz_ist_hoch, :monatsumsatz_plan, :tagesumsatz_plan,
                :liefer_plan, :gesamt_plan, :tagestyp, :feiertag_name, :ferien_art, :normalisierung)""",
            rows,
        )
        self.conn.commit()

    def fix_ist_vj(self, planjahr: int):
        """Update ist_vj in planung using datumsmapping + ist_umsatz (SQL, fast).

        Called after save() and after datumsmapping regeneration so the stored
        ist_vj is always in sync with the current mapping — eliminating the need
        for a row-by-row Python apply on the Herleitung page.
        """
        self.conn.execute("""
            UPDATE planung
            SET ist_vj = COALESCE(
                (SELECT i.umsatz
                 FROM datumsmapping dm
                 JOIN ist_umsatz i
                   ON i.fil_nr = planung.fil_nr AND i.datum = dm.base_datum
                 WHERE dm.plan_datum = planung.datum
                   AND dm.bundesland = planung.bundesland
                 LIMIT 1),
                (SELECT i.umsatz
                 FROM datumsmapping dm
                 JOIN ist_umsatz i
                   ON i.fil_nr = planung.fil_nr AND i.datum = dm.base_datum
                 WHERE dm.plan_datum = planung.datum
                   AND dm.bundesland = 'alle'
                 LIMIT 1),
                planung.ist_vj
            )
            WHERE CAST(strftime('%Y', datum) AS INTEGER) = ?
        """, (planjahr,))
        self.conn.commit()
