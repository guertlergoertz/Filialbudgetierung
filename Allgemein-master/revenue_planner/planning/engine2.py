"""Alternative planning engine — Die Planung (Monatsumsatz-basiert).

Vorgehen (im Gegensatz zur tagesbasierten Hochrechnung):

1.  **Ausgangspunkt** ist der Kalender-Monatsumsatz des Basiszeitraums (Vorjahr)
    je Monat (= monat_basis). Daran werden die Parameter angerechnet.
2.  **+ Wochentag:** Über das gesamte Basisjahr wird je Wochentag sein Anteil
    am Normaltagsumsatz berechnet (Sondertage, Feiertage/Feiertagstage und Ferien
    ausgeschlossen). Weicht die Wochentags-Konstellation des Planjahres vom
    Basisjahr ab (z. B. ein Samstag mehr), verschiebt sich der Monatsumsatz
    entsprechend der Wochentagsstärke.
3.  **+ Feiertag / + Ferien:** Wirken als Auf-/Abschlag und verschieben den
    Monatsumsatz nur dann zwischen Monaten, wenn der Tag im Planjahr in einen
    anderen Monat fällt als im Basisjahr (z. B. Fasching von März nach Februar).
    - Feiertagstage/Sondertage: Vergleich mit Ø-Normaltag gleichen Wochentags
      desselben Basismonats.
    - Echte Feiertage (art=feiertag): Vergleich mit Ø-Sonntag desselben
      Basismonats.
    - Ferien: Vergleich mit Ø-Normaltag gleichen Wochentags in den drei
      angrenzenden Basismonaten (Vor-, Aktual-, Folgemonat).
    Jahresweise nullsummig.
4.  **=gewünschter Monatsumsatz:** monat_basis + shift_wochentag + shift_feiertag
    + shift_ferien. Verteilung auf Tage erfolgt über IST-Basis-Anteile:
    anteil(Tag) = raw_basis_IST(Tag) / Σ(raw_basis_IST aller offenen Tage im Monat).
    IST Basis (Tagesebene) = anteil × monat_basis.
5.  **+ Preis:** prozentualer Wachstumsfaktor je Monat.
6.  **= Budget I:** =gewünschter Monatsumsatz + + Öffnung + + Hochrechnung + + Preis.
    Für Tage mit vorhandenem Basis-IST: Budget I = anteil × monat_plan.
7.  **+ Validierung:** Wochentagsvalidierung (±10 %-Prüfung gegen Budget I).
8.  **= Budget II:** Budget I + + Validierung.

IST Basis leer (= 0) wenn das gemappte Basisdatum in den ersten 14 Tagen nach
Filialeröffnung liegt oder kein IST vorhanden ist. In diesem Fall feuert
+ Hochrechnung (wenn auch + Öffnung leer ist).

Additive Identität je Tag (exakt):
    Budget II = IST Basis
              + + Wochentag
              + + Ferien
              + + Feiertag
              + + Öffnung
              + + Hochrechnung
              + + Preis
              + + Validierung
              + + Fil.Eröffnung  (nur für neue Filialen ohne IST-Basisdaten)

eff_verteilung und eff_norm werden immer als 0.0 geschrieben (Spalten bleiben
im Schema für Rückwärtskompatibilität, sind aber rechnerisch leer).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from planning.engine import (
    DayPlan,
    PlanParams,
    PlanningEngine,
    _normalize_bl,
    _safe_date,
    is_special_quasi_feiertag,
)

_MIN_IST = 100.0   # Tage mit IST unterhalb dieses Werts gelten als „kein Umsatz"
_BLACKOUT_DAYS = 14  # Eröffnungs-Blackout: Basistage innerhalb dieser Frist werden geleert


class PlanningEngine2:
    """Monatsumsatz-basierte Planungs-Engine. Nutzt PlanningEngine für alle
    Referenzdaten (Basisfenster, IST, Öffnungsregeln, Feiertage, Ferien,
    Datumsmapping)."""

    def __init__(self, conn: sqlite3.Connection, params: PlanParams):
        self.conn = conn
        self.p = params
        self.e = PlanningEngine(conn, params)
        self.filialen = self.e.filialen
        self._excluded_cache: dict[str, set[str]] = {}

    # ── Delegierte Helfer ─────────────────────────────────────────────────

    def base_window_label(self) -> str:
        return self.e.base_window_label()

    def base_year_for_month(self, month: int) -> int:
        return self.e.base_year_for_month(month)

    # ── Basis-Sondertage (Basisjahr) ──────────────────────────────────────

    def _excluded_base_dates(self, bl: str) -> set[str]:
        """ISO-Daten im Basisfenster, die Sonder-/Feiertage oder Ferien sind
        (für BL) — ausgeschlossen aus Wochentags-Anteil- und
        Nachbar-Durchschnitts-Berechnungen."""
        if bl in self._excluded_cache:
            return self._excluded_cache[bl]
        e = self.e
        excl: set[str] = set()
        for entries in e.feiertage.values():
            for ft in entries:
                if ft["bundesland"] in ("alle", bl) and ft.get("datum_vj"):
                    excl.add(ft["datum_vj"])
        for st in e.sondertage.values():
            if st["bundesland"] in ("alle", bl) and st.get("datum_referenz"):
                excl.add(st["datum_referenz"])
        excl |= e.ferien_vj_dates
        d = e.base_start
        while d < e.base_mask_end.date():
            if is_special_quasi_feiertag(d):
                excl.add(d.isoformat())
            d += timedelta(days=1)
        self._excluded_cache[bl] = excl
        return excl

    # ── Neue-Basis-Filiale: Erkennung und Hochrechnung ────────────────────

    def _branch_had_feiertag_ist(self, fil_nr: str) -> bool:
        """True wenn die Filiale im Basiszeitraum an einem echten Feiertag Umsatz hatte."""
        e = self.e
        df = e._branch_base_ist(fil_nr)
        if df.empty:
            return False
        feiertag_iso: set[str] = set()
        for entries in e.feiertage.values():
            for ft in entries:
                if ft.get("datum_vj"):
                    feiertag_iso.add(ft["datum_vj"])
        iso_series = df["datum"].dt.strftime("%Y-%m-%d")
        return bool(((df["umsatz"] > 0) & (iso_series.isin(feiertag_iso))).any())

    def _ref_wt_sums(self, ref_fil_nrs: set[str],
                     date_from: pd.Timestamp | None = None,
                     date_to: pd.Timestamp | None = None,
                     excl: set[str] | None = None) -> dict[int, float]:
        """Wochentagsumsatz-Summen aller Referenzfilialen, optional auf ein Zeitfenster begrenzt.

        date_from / date_to sind inklusive Grenzen. Ohne Angabe wird der volle Basiszeitraum
        verwendet. Durch Übergabe des filial-spezifischen Zeitfensters (Zähler = Nenner)
        wird ein systematisch zu kleiner Anteil für neue Filialen vermieden.
        excl: ISO-Datum-Menge, die aus der Berechnung ausgeschlossen wird
        (Feiertage/Feiertagstage/Ferien/Sondertage aller beteiligten BL).
        """
        e = self.e
        d_from = date_from if date_from is not None else pd.Timestamp(e.base_start)
        d_to = date_to if date_to is not None else e.base_mask_end - pd.Timedelta(days=1)
        result: dict[int, float] = {w: 0.0 for w in range(7)}
        for fil_nr in ref_fil_nrs:
            df = e._branch_base_ist(fil_nr)
            mask = (df["datum"] >= d_from) & (df["datum"] <= d_to) & (df["umsatz"] > 0)
            if excl:
                iso = df["datum"].dt.strftime("%Y-%m-%d")
                mask = mask & (~iso.isin(excl))
            df = df[mask]
            if df.empty:
                continue
            for w, grp in df.groupby(df["datum"].dt.weekday):
                result[int(w)] += float(grp["umsatz"].sum())
        return result

    def _wt_shares_for_branch(self, fil_nr: str, ref_fil_nrs: set[str]) -> dict[int, float]:
        """Wochentagsanteil dieser Filiale relativ zu den Referenzfilialen.

        Zähler und Nenner werden auf denselben Zeitraum eingeschränkt (nach 14-Tage-Blackout),
        damit kein systematisch zu kleiner Anteil entsteht. Feiertage/Feiertagstage/Ferien/
        Sondertage aller beteiligten BL werden aus Zähler und Nenner ausgeschlossen, damit
        die Zeitreihen vergleichbar bleiben (Union-Ausschluss).
        Für Wochentage ohne historischen IST wird der Durchschnittsanteil als Fallback verwendet.
        """
        e = self.e
        fil_bl = _normalize_bl(e.filialen.get(fil_nr, {}).get("bundesland", "RP") or "RP")
        ref_bls = {_normalize_bl(e.filialen.get(r, {}).get("bundesland", "RP") or "RP")
                   for r in ref_fil_nrs}
        excl: set[str] = set()
        for bl in ref_bls | {fil_bl}:
            excl |= self._excluded_base_dates(bl)

        df = e._branch_base_ist(fil_nr)
        iso = df["datum"].dt.strftime("%Y-%m-%d")
        df = df[(df["umsatz"] >= _MIN_IST) & (~iso.isin(excl))]

        eroeff = e.filialen.get(fil_nr, {}).get("eroeffnung")
        if eroeff:
            cutoff = date.fromisoformat(eroeff) + timedelta(days=_BLACKOUT_DAYS)
            df = df[df["datum"] >= pd.Timestamp(cutoff)]

        if df.empty:
            return {w: 0.0 for w in range(7)}

        date_from = df["datum"].min()
        date_to = df["datum"].max()
        ref_wt_sums = self._ref_wt_sums(ref_fil_nrs, date_from=date_from, date_to=date_to, excl=excl)

        new_by_wt: dict[int, float] = {w: 0.0 for w in range(7)}
        for w, grp in df.groupby(df["datum"].dt.weekday):
            new_by_wt[int(w)] = float(grp["umsatz"].sum())
        shares = {w: (new_by_wt[w] / ref_wt_sums[w] if ref_wt_sums.get(w, 0.0) > 0 else 0.0)
                  for w in range(7)}
        filled = [v for v in shares.values() if v > 0]
        if filled:
            fallback = sum(filled) / len(filled)
            shares = {w: (v if v > 0 else fallback) for w, v in shares.items()}
        return shares

    # ── Wochentagsanteile (über das ganze Basisjahr) ──────────────────────

    def _weekday_share(self, fil_nr: str, fil: dict, bl: str) -> dict[int, float]:
        """Anteil je Wochentag am Normaltagsumsatz im gesamten Basiszeitraum.

        Sondertage, Feiertage/Feiertagstage und Ferien werden ausgeschlossen.
        Rückgabe: {0..6 → Anteil}, Summe über offene Wochentage = 1.0.
        """
        e = self.e
        df = e._branch_base_ist(fil_nr)
        if df.empty:
            return {i: 0.0 for i in range(7)}
        eroeffnung = fil.get("eroeffnung")
        if eroeffnung:
            cutoff = date.fromisoformat(eroeffnung) + timedelta(days=_BLACKOUT_DAYS)
            df = df[df["datum"] >= pd.Timestamp(cutoff)]
        excl = self._excluded_base_dates(bl)
        iso = df["datum"].dt.strftime("%Y-%m-%d")
        df = df[(df["umsatz"] > 0) & (~iso.isin(excl))]
        if df.empty:
            return {i: 0.0 for i in range(7)}
        total = df["umsatz"].sum()
        if total <= 0:
            return {i: 0.0 for i in range(7)}
        sums = df.groupby(df["datum"].dt.weekday)["umsatz"].sum()
        return {i: float(sums.get(i, 0.0)) / total for i in range(7)}

    # ── Durchschnitts-Helfer für Shift-Berechnung ─────────────────────────

    def _same_month_normal_avg(self, fil_nr: str, base_d: date, bl: str,
                                weekday: int | None = None) -> float:
        """Ø Umsatz von Normaltagen im Monat von base_d mit dem angegebenen Wochentag.

        Normaltage = keine Sonder-/Feiertage/Ferien. Wenn weekday=None wird
        der Wochentag von base_d verwendet. Für echte Feiertage weekday=6 (Sonntag)
        übergeben.
        """
        e = self.e
        df = e._branch_base_ist(fil_nr)
        if df.empty:
            return 0.0
        wt = base_d.weekday() if weekday is None else weekday
        excl = self._excluded_base_dates(bl)
        iso = df["datum"].dt.strftime("%Y-%m-%d")
        sel = df[
            (df["datum"].dt.weekday == wt)
            & (df["datum"].dt.month == base_d.month)
            & (df["umsatz"] > 0)
            & (~iso.isin(excl))
        ]
        if sel.empty:
            return 0.0
        return float(sel["umsatz"].mean())

    def _neighbour_weekday_avg(self, fil_nr: str, base_d: date, bl: str) -> float:
        """Ø Umsatz desselben Wochentags in den 3 Monaten um base_d
        (Vormonat, Monat, Folgemonat) im Basiszeitraum — nur Normaltage.
        Wird für Ferien-Shifts verwendet."""
        e = self.e
        df = e._branch_base_ist(fil_nr)
        if df.empty:
            return 0.0
        wt = base_d.weekday()
        months = {base_d.month}
        prev_m = base_d.month - 1 or 12
        next_m = base_d.month + 1 if base_d.month < 12 else 1
        months.update({prev_m, next_m})
        excl = self._excluded_base_dates(bl)
        iso = df["datum"].dt.strftime("%Y-%m-%d")
        sel = df[(df["datum"].dt.weekday == wt)
                 & (df["datum"].dt.month.isin(months))
                 & (df["umsatz"] > 0)
                 & (~iso.isin(excl))]
        if sel.empty:
            return 0.0
        return float(sel["umsatz"].mean())

    # ── Monats-Helfer ─────────────────────────────────────────────────────

    def _mapping_base_date(self, fil_nr: str, bl: str, month: int, d: date) -> date | None:
        e = self.e
        iso = d.isoformat()
        mb = (e._datumsmapping.get((iso, bl))
              or e._datumsmapping.get((iso, "alle")))
        if mb:
            return date.fromisoformat(mb)
        return _safe_date(self.base_year_for_month(month), month, d.day)

    def _mapping_art(self, bl: str, d: date) -> str:
        e = self.e
        iso = d.isoformat()
        return (e._datumsmapping_art.get((iso, bl))
                or e._datumsmapping_art.get((iso, "alle"))
                or "iso_kw")

    def _closed_and_type(self, fil_nr: str, fil: dict, d: date, bl: str) -> tuple:
        """Gibt (closed, tagestyp, feiertag_name, ferien_art) zurück."""
        e = self.e
        iso = d.isoformat()
        wt = d.weekday()
        ft = e._relevant_feiertag(iso, bl)
        ftt = e._relevant_feiertagstag(iso, bl)
        st = e._relevant_sondertag(iso, bl)
        fer = e._ferien_info_for_day(iso, bl)
        closed = False
        feiertag_name = ""
        eroeff = fil.get("eroeffnung")
        ende = fil.get("eroeffnung_ende")
        umbau_von_str = fil.get("umbau_von")
        umbau_bis_str = fil.get("umbau_bis")
        if eroeff and date.fromisoformat(eroeff) > d:
            closed = True
        elif ende and date.fromisoformat(ende) < d:
            closed = True
        elif umbau_von_str and umbau_bis_str:
            try:
                if date.fromisoformat(umbau_von_str) <= d <= date.fromisoformat(umbau_bis_str):
                    return True, "umbau", "", (fer[0] if fer else "")
            except ValueError as _exc:
                import logging as _log
                _log.warning("umbau date parse error fil_nr=%s: %s", fil_nr, _exc)
        if not closed:
            if not e._is_open_weekday(fil_nr, wt):
                closed = True
            elif ft and not e._is_open_feiertag(fil_nr, ft["name"]):
                closed = True
                feiertag_name = ft["name"]
            elif ftt and not e._is_open_feiertag(fil_nr, ftt["name"]):
                closed = True
                feiertag_name = ftt["name"]
        if closed:
            return True, "geschlossen", feiertag_name, (fer[0] if fer else "")
        if ft:
            return False, "feiertag", ft["name"], ""
        if st:
            return False, "sondertag", st["bezeichnung"], ""
        if fer:
            return False, "ferien", "", fer[0]
        return False, "normal", "", ""

    # ── Monatsumsatz-Pipeline je Filiale ──────────────────────────────────

    def plan_branch(self, fil_nr: str,
                    ref_day_budgets: dict[str, float] | None = None,
                    wt_shares: dict[int, float] | None = None,
                    had_feiertag_ist: bool = False,
                    umbau_hochrechnung_months: set[int] | None = None) -> list[DayPlan]:
        e = self.e
        fil = self.filialen.get(fil_nr, {"bundesland": "RP"})
        bl = _normalize_bl(fil.get("bundesland", "RP") or "RP")
        py = self.p.planjahr

        _eroeff_str = fil.get("eroeffnung")
        _geplanter_umsatz = float(fil.get("geplanter_umsatz_monat") or 0)
        is_neue_mit_planwert = (
            _eroeff_str is not None
            and _geplanter_umsatz > 0
            and date.fromisoformat(_eroeff_str).year == py
        )

        share_wt = self._weekday_share(fil_nr, fil, bl)

        # Phase 1: pro Monat Basis (monat_basis), Wochentags-Konstellation (monat_hoch),
        # Tages-Metadaten
        monat_basis: dict[int, float] = {}
        monat_hoch: dict[int, float] = {}
        shift_feiertag: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        shift_ferien: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        override_val: dict[int, float | None] = {}
        day_meta: dict[int, list[dict]] = {}

        cnt_base_by_month: dict[int, dict] = {}
        cnt_plan_by_month: dict[int, dict] = {}

        for month in range(1, 13):
            ov, is_special_month = self._month_override(fil_nr, fil, month)
            override_val[month] = ov
            base_m = e._base_month_ist(fil_nr, fil, month)
            monat_basis[month] = base_m
            by = self.base_year_for_month(month)
            cnt_base_by_month[month] = e._count_weekdays(by, month)
            cnt_plan_by_month[month] = e._count_weekdays(py, month)

            dim = pd.Period(f"{py}-{month:02d}").days_in_month
            metas = []
            for day in range(1, dim + 1):
                d = date(py, month, day)
                closed, tagestyp, ft_name, fer_art = self._closed_and_type(fil_nr, fil, d, bl)
                base_d = self._mapping_base_date(fil_nr, bl, month, d)
                base_ist = e._ist_on(fil_nr, base_d) if base_d else 0.0
                # Blackout: Basistage in den ersten 14 Tagen nach Eröffnung
                # spiegeln untypischen Eröffnungseffekt wider → auf 0 setzen.
                eroeff_str = fil.get("eroeffnung")
                if base_ist > 0 and eroeff_str and base_d:
                    eroeff_d = date.fromisoformat(eroeff_str)
                    if base_d < eroeff_d + timedelta(days=_BLACKOUT_DAYS):
                        base_ist = 0.0
                # Umbau-Hochrechnung: Im Start- und/oder End-Monat des Umbaus (Budgetjahr)
                # wird der Basis-IST auf 0 gesetzt, damit vollimputation greift und der Monat
                # wie bei neuen Filialen über Referenzfilialen hochgerechnet wird.
                if umbau_hochrechnung_months and month in umbau_hochrechnung_months and not closed:
                    base_ist = 0.0
                art = self._mapping_art(bl, d)
                metas.append({
                    "d": d, "wt": d.weekday(), "closed": closed,
                    "tagestyp": tagestyp, "feiertag_name": ft_name,
                    "ferien_art": fer_art, "base_d": base_d,
                    "base_ist": base_ist, "mapping_art": art,
                })
            day_meta[month] = metas

        # Jährlicher Durchschnitts-Tagesumsatz je Wochentag (nur Normaltage).
        umsatz_gesamt = sum(monat_basis.values())
        cnt_year_base = {w: sum(cnt_base_by_month[mo].get(w, 0) for mo in range(1, 13))
                         for w in range(7)}
        durchschnitt_wochentag = {
            w: (umsatz_gesamt * share_wt.get(w, 0.0) / cnt_year_base[w])
            if cnt_year_base[w] > 0 else 0.0
            for w in range(7)
        }
        for month in range(1, 13):
            cb = cnt_base_by_month[month]
            cp = cnt_plan_by_month[month]
            monat_hoch[month] = monat_basis[month] + sum(
                (cp.get(w, 0) - cb.get(w, 0)) * durchschnitt_wochentag[w]
                for w in range(7)
            )

        # Phase 2: Auf-/Abschlag-Verschiebung zwischen Monaten.
        #
        # Feiertag-Logik (nur bei Monatswechsel):
        #   - Echte Feiertage (art=feiertag): markup = base_ist − Ø Sonntage desselben Basismonats
        #   - Feiertagstage/Sondertage: markup = base_ist − Ø gleicher Wochentag desselben Basismonats
        #
        # Ferien-Logik (nur bei Monatswechsel):
        #   - markup = base_ist − Ø gleicher Wochentag in angrenzenden Basismonaten
        for month in range(1, 13):
            if override_val[month] is not None:
                continue
            for m in day_meta[month]:
                if m["closed"] or m["base_ist"] <= 0:
                    continue
                art = m["mapping_art"]
                is_actual_feiertag = art == "feiertag"
                is_feiertagstag_or_sondertag = art in ("feiertagstag", "sondertag")
                is_ft = is_actual_feiertag or is_feiertagstag_or_sondertag
                is_fer = art in ("ferien", "Ferienabschlag")
                if not (is_ft or is_fer):
                    continue
                base_d = m["base_d"]
                if base_d is None or base_d.month == month:
                    continue  # gleicher Monat → keine Verschiebung

                if is_ft:
                    if is_actual_feiertag:
                        # Echte Feiertage: Vergleich mit Ø Sonntag desselben Basismonats
                        neigh_avg = self._same_month_normal_avg(fil_nr, base_d, bl, weekday=6)
                    else:
                        # Feiertagstage/Sondertage: Vergleich mit Ø gleichem Wochentag desselben Basismonats
                        neigh_avg = self._same_month_normal_avg(fil_nr, base_d, bl)
                    markup = m["base_ist"] - neigh_avg
                    if abs(markup) < 0.005:
                        continue
                    shift_feiertag[month] += markup
                    if 1 <= base_d.month <= 12:
                        shift_feiertag[base_d.month] -= markup
                else:
                    # Ferien: Vergleich mit Ø gleichem Wochentag in angrenzenden Basismonaten
                    neigh_avg = self._neighbour_weekday_avg(fil_nr, base_d, bl)
                    markup = m["base_ist"] - neigh_avg
                    if abs(markup) < 0.005:
                        continue
                    shift_ferien[month] += markup
                    if 1 <= base_d.month <= 12:
                        shift_ferien[base_d.month] -= markup

        # Phase 3: Monatsumsatz finalisieren + auf Tage verteilen

        # Vollimputation vorberechnen: Wenn ein Monat >5 offene Tage ohne Basis-IST hat,
        # werden alle Tage des Monats hochgerechnet (monat_plan wird auf 0 gesetzt,
        # da der Dreisatz bei so vielen Lücken kein verlässliches Ergebnis liefert).
        # Bei Umbau-Filialen: nur für die explizit bezeichneten Umbau-Monate hochrechnen,
        # damit Monate im Basiszeitraum mit 0-IST (wegen Umbau) nicht fälschlicherweise
        # imputed werden.
        imputed_count_by_month: dict[int, int] = {}
        for _m in range(1, 13):
            if ref_day_budgets is None or wt_shares is None:
                imputed_count_by_month[_m] = 0
            elif umbau_hochrechnung_months is not None and _m not in umbau_hochrechnung_months:
                imputed_count_by_month[_m] = 0
            else:
                imputed_count_by_month[_m] = sum(
                    1 for dm in day_meta[_m]
                    if not dm["closed"] and dm["base_ist"] < _MIN_IST
                )

        results: list[DayPlan] = []
        for month in range(1, 13):
            ov = override_val[month]
            metas = day_meta[month]
            vollimputation = imputed_count_by_month[month] > 5

            if vollimputation:
                m0 = m1 = m2 = m3 = 0.0
                sft = sfer = 0.0
            elif ov is not None:
                m0 = m1 = m2 = m3 = ov
                sft = sfer = 0.0
            else:
                m0 = monat_basis[month]
                m1 = monat_hoch[month]
                sft = shift_feiertag[month]
                sfer = shift_ferien[month]
                m2 = m1 + sft + sfer
                growth = e._growth(fil, month)
                m3 = round(m2 * growth, 2)

            open_metas = [m for m in metas if not m["closed"]]
            # Summe der rohen Basis-IST-Werte aller offenen Tage (Verteilungsgewichte)
            summe_raw_basis_ist = sum(m["base_ist"] for m in open_metas)
            anzahl_offener_tage = len(open_metas)

            for m in metas:
                imputed_budget: float | None = None
                fil_eroeffnung: float | None = None

                if is_neue_mit_planwert and ov is not None and not m["closed"]:
                    fil_eroeffnung = (
                        round(ov / anzahl_offener_tage, 2)
                        if anzahl_offener_tage > 0 else 0.0
                    )
                elif ref_day_budgets is not None and wt_shares is not None and not m["closed"]:
                    _allow_impute = (
                        umbau_hochrechnung_months is None
                        or month in umbau_hochrechnung_months
                    )
                    if _allow_impute and (vollimputation or m["base_ist"] < _MIN_IST):
                        is_feiertag = m["tagestyp"] == "feiertag"
                        if is_feiertag:
                            if had_feiertag_ist and m["base_ist"] >= _MIN_IST:
                                ref_total = ref_day_budgets.get(m["d"].isoformat(), 0.0)
                                imputed_budget = round(ref_total * wt_shares.get(6, 0.0), 2)
                        else:
                            ref_total = ref_day_budgets.get(m["d"].isoformat(), 0.0)
                            imputed_budget = round(ref_total * wt_shares.get(m["wt"], 0.0), 2)
                results.append(self._build_day(
                    fil_nr, bl, m, m0, m1, m2, m3, sft, sfer,
                    summe_raw_basis_ist, anzahl_offener_tage,
                    imputed_budget=imputed_budget,
                    fil_eroeffnung_budget=fil_eroeffnung,
                ))

        return results

    # ── Override / neue Filiale ───────────────────────────────────────────

    def _month_override(self, fil_nr: str, fil: dict, month: int) -> tuple[float | None, bool]:
        """Gibt (monatswert | None, is_special) zurück. None = regulär berechnen."""
        e = self.e
        if (fil_nr, month) in e.overrides:
            return e.overrides[(fil_nr, month)], True
        eroeff_str = fil.get("eroeffnung")
        if eroeff_str and date.fromisoformat(eroeff_str).year == self.p.planjahr:
            entry = e.neue_plan.get((fil_nr, month))
            if entry:
                planwert = entry["planwert"]
                er = entry.get("eroeffnung")
                if er:
                    erd = date.fromisoformat(er)
                    if erd.month == month and erd.year == self.p.planjahr:
                        planwert *= 0.5
                return planwert, True
            return 0.0, True
        return None, False

    # ── Tagesaufbau inkl. additiver Zerlegung ─────────────────────────────

    def _build_day(self, fil_nr: str, bl: str, m: dict,
                   m0: float, m1: float, m2: float, m3: float,
                   sft: float, sfer: float,
                   summe_raw_basis_ist: float, anzahl_offener_tage: int,
                   imputed_budget: float | None = None,
                   fil_eroeffnung_budget: float | None = None) -> DayPlan:
        """Baut einen DayPlan für einen Tag auf.

        Neue additive Zerlegung (Budget II = Σ aller Effekte):
            IST Basis              = anteil × monat_basis
            + Wochentag            = anteil × shift_wochentag
            + Ferien               = anteil × shift_ferien
            + Feiertag             = anteil × shift_feiertag
            =gewünschter Monat     = anteil × (m0 + shift_wt + shift_ft + shift_fer) = anteil × m2
            + Preis                = anteil × (m3 − m2)
            = Budget I             = anteil × m3
            + Validierung          (wird separat von validierung2.py gesetzt)
            = Budget II            = Budget I + Validierung
        """
        d = m["d"]
        raw_basis_ist = m["base_ist"]

        # Geschlossene Tage: alle Spalten leer, Budget = 0
        if m["closed"]:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=0.0, eff_oeffnung=0.0, eff_hochrechnung=0.0,
                eff_verteilung=0.0, eff_wochentag=0.0, eff_preis=0.0,
                eff_ferien=0.0, eff_feiertag=0.0, eff_norm=0.0,
                budget=0.0, budget_i=0.0, gewuenschter_monatsumsatz=0.0,
                monat_basis=round(m0, 2), monat_hoch=round(m1, 2), monat_plan=round(m3, 2),
                tagestyp=m["tagestyp"], feiertag_name=m["feiertag_name"],
                ferien_art=m["ferien_art"], normalisierung=0.0,
            )

        # Feiertag ohne Basis-IST: Filiale war im Basiszeitraum an diesem Feiertag geschlossen
        if m["tagestyp"] == "feiertag" and raw_basis_ist == 0 and imputed_budget is None:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=0.0, eff_oeffnung=0.0, eff_hochrechnung=0.0,
                eff_verteilung=0.0, eff_wochentag=0.0, eff_preis=0.0,
                eff_ferien=0.0, eff_feiertag=0.0, eff_norm=0.0,
                budget=0.0, budget_i=0.0, gewuenschter_monatsumsatz=0.0,
                monat_basis=round(m0, 2), monat_hoch=round(m1, 2), monat_plan=round(m3, 2),
                tagestyp="geschlossen", feiertag_name=m["feiertag_name"],
                ferien_art=m["ferien_art"], normalisierung=0.0,
            )

        # Fil.Eröffnung: neue Filialen mit Planumsatz — kein IST-Basis, Wert in eff_fil_eroeffnung
        if fil_eroeffnung_budget is not None:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=0.0, eff_oeffnung=0.0, eff_hochrechnung=0.0,
                eff_verteilung=0.0, eff_wochentag=0.0, eff_preis=0.0,
                eff_ferien=0.0, eff_feiertag=0.0, eff_norm=0.0,
                eff_fil_eroeffnung=fil_eroeffnung_budget,
                budget=fil_eroeffnung_budget, budget_i=0.0,
                gewuenschter_monatsumsatz=0.0,
                monat_basis=round(m0, 2), monat_hoch=round(m1, 2), monat_plan=round(m3, 2),
                tagestyp=m["tagestyp"], feiertag_name=m["feiertag_name"],
                ferien_art=m["ferien_art"], normalisierung=0.0,
            )

        # Hochrechnung für Filialen ohne Basis-IST an diesem Tag
        if imputed_budget is not None:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=0.0, eff_oeffnung=0.0, eff_hochrechnung=imputed_budget,
                eff_verteilung=0.0, eff_wochentag=0.0, eff_preis=0.0,
                eff_ferien=0.0, eff_feiertag=0.0, eff_norm=0.0,
                budget=imputed_budget, budget_i=imputed_budget,
                gewuenschter_monatsumsatz=0.0,
                monat_basis=round(m0, 2), monat_hoch=round(m1, 2), monat_plan=round(m3, 2),
                tagestyp=m["tagestyp"], feiertag_name=m["feiertag_name"],
                ferien_art=m["ferien_art"], normalisierung=0.0,
            )

        # Tagesanteil: raw_basis_ist als Gewicht für Dreisatz-Verteilung des Monatsumsatzes
        if summe_raw_basis_ist > 0:
            anteil = raw_basis_ist / summe_raw_basis_ist
        else:
            anteil = (1.0 / anzahl_offener_tage) if anzahl_offener_tage else 0.0

        ist_basis_skaliert = round(anteil * m0, 2)
        eff_wochentag = round(anteil * (m1 - m0), 2)
        eff_ferien = round(anteil * sfer, 2)
        eff_feiertag = round(anteil * sft, 2)
        gewuenschter_monatsumsatz = round(anteil * m2, 2)
        eff_preis = round(anteil * (m3 - m2), 2)
        budget_i = round(anteil * m3, 2)

        norm = round(budget_i / raw_basis_ist, 4) if raw_basis_ist else 0.0
        return DayPlan(
            fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
            ist_vj=ist_basis_skaliert, eff_oeffnung=0.0, eff_hochrechnung=0.0,
            eff_verteilung=0.0,
            eff_wochentag=eff_wochentag, eff_preis=eff_preis,
            eff_ferien=eff_ferien, eff_feiertag=eff_feiertag,
            eff_norm=0.0, budget=budget_i,
            budget_i=budget_i, gewuenschter_monatsumsatz=gewuenschter_monatsumsatz,
            monat_basis=round(m0, 2), monat_hoch=round(m1, 2), monat_plan=round(m3, 2),
            tagestyp=m["tagestyp"], feiertag_name=m["feiertag_name"],
            ferien_art=m["ferien_art"], normalisierung=norm,
        )

    # ── Full run / persist ────────────────────────────────────────────────

    def run(self, fil_nrs: list[str] | None = None,
            progress_callback=None) -> list[DayPlan]:
        """Berechnet für alle (oder ausgewählte) Filialen die Planung.

        progress_callback(done: int, total: int, fil_nr: str) wird nach jeder
        Filiale aufgerufen — zum Aktualisieren eines UI-Fortschrittsbalkens.
        """
        targets = fil_nrs if fil_nrs else list(self.filialen.keys())
        active = [f for f in targets
                  if not (self.filialen.get(f, {}).get("flag_gesperrt")
                          or self.filialen.get(f, {}).get("flag_inaktiv"))]

        e = self.e
        by, bm = e.base_end_year, e.base_end_month
        plan_year = self.p.planjahr

        # Monatliche IST-Summen für alle aktiven Filialen in einem vektorisierten Pass.
        active_set = set(active)
        base_df = e.ist_df[
            (e.ist_df["fil_nr"].isin(active_set))
            & (e.ist_df["datum"] >= pd.Timestamp(e.base_start))
            & (e.ist_df["datum"] < e.base_mask_end)
        ].copy()
        base_df["ym"] = base_df["datum"].dt.to_period("M")

        all_monthly_ist: dict[str, dict[tuple[int, int], float]] = {}
        all_monthly_ist_daycounts: dict[str, dict[tuple[int, int], int]] = {}
        for fil_nr, grp_df in base_df.groupby("fil_nr"):
            mo_sums = grp_df.groupby("ym")["umsatz"].sum()
            all_monthly_ist[str(fil_nr)] = {(p.year, p.month): float(v) for p, v in mo_sums.items()}
            ist_days = grp_df[grp_df["umsatz"] >= _MIN_IST]
            mo_counts = ist_days.groupby("ym")["datum"].count()
            all_monthly_ist_daycounts[str(fil_nr)] = {
                (p.year, p.month): int(v) for p, v in mo_counts.items()
            }

        # Alle Kalendermonate im Basiszeitraum.
        all_base_months: list[tuple[int, int]] = []
        cur = e.base_start.replace(day=1)
        base_end_d = e.base_mask_end.date()
        while cur < base_end_d:
            all_base_months.append((cur.year, cur.month))
            nxt = cur.month + 1
            cur = cur.replace(year=cur.year + (nxt - 1) // 12, month=(nxt - 1) % 12 + 1)

        # Neue Filialen: alle Filialen mit IST-Lücken im Basiszeitraum (mindestens
        # ein Monat 0, mindestens ein Monat > 0) — unabhängig vom Grund der Lücke.
        neue_filialen: set[str] = set()
        for fil_nr in active:
            mo = all_monthly_ist.get(fil_nr, {})
            month_sums = [mo.get(ym, 0.0) for ym in all_base_months]
            if any(s > 0 for s in month_sums) and any(s == 0.0 for s in month_sums):
                neue_filialen.add(fil_nr)

        # Umbau-Filialen: Start- und/oder End-Monat des Umbaus im Budgetjahr werden
        # hochgerechnet (da Umbau mitten im Monat starten/enden kann).
        # Werden zu neue_filialen hinzugefügt, damit ref_day_budgets und wt_shares verfügbar sind.
        import logging as _log2
        umbau_monate: dict[str, set[int]] = {}
        for fil_nr in active:
            fil = self.filialen.get(fil_nr, {})
            months: set[int] = set()
            uvon = fil.get("umbau_von")
            ubis = fil.get("umbau_bis")
            if uvon:
                try:
                    uvon_d = date.fromisoformat(uvon)
                    if uvon_d.year == plan_year:
                        months.add(uvon_d.month)
                except (ValueError, TypeError) as _exc:
                    _log2.warning("umbau_von date parse error fil_nr=%s value=%r: %s", fil_nr, uvon, _exc)
            if ubis:
                try:
                    ubis_d = date.fromisoformat(ubis)
                    if ubis_d.year == plan_year:
                        months.add(ubis_d.month)
                except (ValueError, TypeError) as _exc:
                    _log2.warning("umbau_bis date parse error fil_nr=%s value=%r: %s", fil_nr, ubis, _exc)
            # Auch Plan-Monate hochrechnen, deren Basis-Monat in den Umbau-Zeitraum fiel
            # (z. B. Umbau im Basiszeitraum beendet → Start-Monat des Umbaus im Budgetjahr).
            if uvon and ubis:
                try:
                    uvon_d = date.fromisoformat(uvon)
                    ubis_d = date.fromisoformat(ubis)
                    for m in range(1, 13):
                        by = e.base_year_for_month(m)
                        last_day = int(pd.Period(f"{by}-{m:02d}").days_in_month)
                        if uvon_d <= date(by, m, last_day) and ubis_d >= date(by, m, 1):
                            months.add(m)
                except (ValueError, TypeError) as _exc:
                    _log2.warning("umbau base-overlap calc error fil_nr=%s: %s", fil_nr, _exc)
            if months:
                umbau_monate[fil_nr] = months
        neue_filialen |= set(umbau_monate.keys())

        # Bestandsfilialen = aktive Filialen ohne IST-Lücken, dienen als Referenz.
        referenz_filialen: set[str] = set()
        for fil_nr in active:
            if fil_nr in neue_filialen:
                continue
            mo = all_monthly_ist.get(fil_nr, {})
            month_sums = [mo.get(ym, 0.0) for ym in all_base_months]
            if all(s > 0 for s in month_sums):
                referenz_filialen.add(fil_nr)

        # Wochentagsanteile für neue Filialen vorberechnen.
        wt_shares_cache: dict[str, dict[int, float]] = {}
        feiertag_cache: dict[str, bool] = {}
        for fil_nr in neue_filialen:
            wt_shares_cache[fil_nr] = self._wt_shares_for_branch(fil_nr, referenz_filialen)
            feiertag_cache[fil_nr] = self._branch_had_feiertag_ist(fil_nr)

        # Pass 1: Bestandsfilialen und Planjahr-Neueröffnungen (ohne Imputation).
        out: list[DayPlan] = []
        ref_day_budgets: dict[str, float] = {}
        n_total = len(active)
        done = 0
        for fil_nr in active:
            if fil_nr in neue_filialen:
                continue
            fil = self.filialen.get(fil_nr, {})
            eroeff_str = fil.get("eroeffnung")
            is_plan_year_new = bool(eroeff_str and date.fromisoformat(eroeff_str).year == plan_year)
            if not is_plan_year_new:
                last_ist = all_monthly_ist.get(fil_nr, {}).get((by, bm), 0.0)
                if last_ist <= 0:
                    done += 1
                    if progress_callback:
                        progress_callback(done, n_total, fil_nr)
                    continue
            branch_results = self.plan_branch(fil_nr)
            out.extend(branch_results)
            if fil_nr in referenz_filialen:
                for dp in branch_results:
                    iso = dp.datum.isoformat()
                    ref_day_budgets[iso] = ref_day_budgets.get(iso, 0.0) + dp.budget
            done += 1
            if progress_callback:
                progress_callback(done, n_total, fil_nr)

        # Pass 2: Filialen mit IST-Lücken (neue Filialen + Umbau-Monate im Budgetjahr).
        for fil_nr in neue_filialen:
            branch_results = self.plan_branch(
                fil_nr,
                ref_day_budgets=ref_day_budgets,
                wt_shares=wt_shares_cache[fil_nr],
                had_feiertag_ist=feiertag_cache[fil_nr],
                umbau_hochrechnung_months=umbau_monate.get(fil_nr),
            )
            out.extend(branch_results)
            done += 1
            if progress_callback:
                progress_callback(done, n_total, fil_nr)

        return out

    def save(self, results: list[DayPlan]):
        if not results:
            return
        fil_nrs = list({r.fil_nr for r in results})
        placeholders = ",".join("?" * len(fil_nrs))
        self.conn.execute(
            f"DELETE FROM planung2 WHERE fil_nr IN ({placeholders}) "
            f"AND CAST(strftime('%Y', datum) AS INTEGER)=?",
            fil_nrs + [self.p.planjahr],
        )
        rows = [{
            "fil_nr": r.fil_nr, "datum": r.datum.isoformat(), "wochentag": r.wochentag,
            "bundesland": r.bundesland, "ist_vj": r.ist_vj,
            "eff_oeffnung": r.eff_oeffnung, "eff_hochrechnung": r.eff_hochrechnung,
            "eff_verteilung": r.eff_verteilung,
            "eff_wochentag": r.eff_wochentag, "eff_preis": r.eff_preis,
            "eff_ferien": r.eff_ferien, "eff_feiertag": r.eff_feiertag,
            "eff_norm": r.eff_norm, "budget": r.budget,
            "budget_i": r.budget_i, "gewuenschter_monatsumsatz": r.gewuenschter_monatsumsatz,
            "eff_fil_eroeffnung": r.eff_fil_eroeffnung,
            "monat_basis": r.monat_basis, "monat_hoch": r.monat_hoch, "monat_plan": r.monat_plan,
            "monatsumsatz_ist_hoch": r.monat_hoch, "monatsumsatz_plan": r.monat_plan,
            "tagesumsatz_plan": r.budget, "liefer_plan": 0.0, "gesamt_plan": r.budget,
            "tagestyp": r.tagestyp, "feiertag_name": r.feiertag_name,
            "ferien_art": r.ferien_art, "normalisierung": r.normalisierung,
        } for r in results]
        self.conn.executemany(
            """INSERT OR REPLACE INTO planung2
               (fil_nr, datum, wochentag, bundesland, ist_vj,
                eff_oeffnung, eff_hochrechnung, eff_verteilung, eff_wochentag, eff_preis,
                eff_ferien, eff_feiertag, eff_norm, budget,
                budget_i, gewuenschter_monatsumsatz, eff_fil_eroeffnung,
                monat_basis, monat_hoch, monat_plan,
                monatsumsatz_ist_hoch, monatsumsatz_plan, tagesumsatz_plan,
                liefer_plan, gesamt_plan, tagestyp, feiertag_name, ferien_art, normalisierung)
               VALUES
               (:fil_nr, :datum, :wochentag, :bundesland, :ist_vj,
                :eff_oeffnung, :eff_hochrechnung, :eff_verteilung, :eff_wochentag, :eff_preis,
                :eff_ferien, :eff_feiertag, :eff_norm, :budget,
                :budget_i, :gewuenschter_monatsumsatz, :eff_fil_eroeffnung,
                :monat_basis, :monat_hoch, :monat_plan,
                :monatsumsatz_ist_hoch, :monatsumsatz_plan, :tagesumsatz_plan,
                :liefer_plan, :gesamt_plan, :tagestyp, :feiertag_name, :ferien_art,
                :normalisierung)""",
            rows,
        )
        self.conn.commit()
