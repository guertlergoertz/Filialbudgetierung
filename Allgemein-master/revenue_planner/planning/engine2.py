"""Alternative planning engine — LOGIC 2.

Eine zweite, eigenständige Berechnungslogik, parallel zur `engine.PlanningEngine`.
Beide Engines werden bewusst nebeneinander betrieben, damit verglichen werden
kann, welche Ergebnisse besser passen, bevor eine der beiden entfernt wird.

Vorgehen (im Gegensatz zu Logik 1, die rein tagesbasiert hochrechnet):

1.  **Ausgangspunkt** ist der Monatsumsatz des Basiszeitraums (Vorjahr) je
    Monat. Daran werden die Parameter angerechnet.
2.  **Preisanpassung** wie in Logik 1 als prozentualer Aufschlag (je Monat).
3.  **Wochentagsanteile** werden über das gesamte Basisjahr berechnet
    (Sondertage, Feiertage/Feiertagstage und Ferien werden dabei ignoriert):
    je Wochentag sein Anteil am Normaltagsumsatz. Mit der Wochentags-Konstellation
    (Anzahl Mo…So im Plan- vs. Basismonat) wird der Monatsumsatz angepasst —
    ein Samstag mehr / Montag weniger verschiebt den Monatsumsatz entsprechend
    der Wochentagsstärke.
4.  **Sondertage/Feiertage/Ferien** wirken als Auf-/Abschlag und verschieben den
    Monatsumsatz NUR dann zwischen Monaten, wenn der Tag im Budgetjahr in einen
    anderen Monat fällt als im Basisjahr (z. B. Muttertag von Mai nach April).
5.  **Verteilung auf Tage:** der fertige Monatsumsatz wird über die Anteile der
    via Datumsmapping bestimmten Basistage am Basismonatsumsatz auf die einzelnen
    Budgettage verteilt (jeder Basistag → %-Anteil → Plantag × Monatsumsatz).

Additive Effekt-Zerlegung je Tag (exakt, damit Herleitung &
Planungsgenauigkeit identisch funktionieren):

    budget = ist_vj
           + eff_oeffnung       (geschlossene Tage: -ist_vj)
           + eff_hochrechnung   (Imputation für Tage ohne Basis-IST via Wochentagsanteile)
           + eff_wochentag      (Wochentags-Konstellationseffekt; absorbiert auch Verteilungsterm)
           + eff_preis          (Preisanpassung / Wachstum)
           + eff_ferien         (Ferien-Monatsverschiebung)
           + eff_feiertag       (Feiertag-/Sondertag-Monatsverschiebung)

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

_MIN_IST = 100.0   # days with IST below this are treated as "no revenue"


class PlanningEngine2:
    """Logic-2 engine. Reuses :class:`PlanningEngine` for all reference data
    (base window, IST, opening rules, holidays, ferien, datumsmapping)."""

    def __init__(self, conn: sqlite3.Connection, params: PlanParams):
        self.conn = conn
        self.p = params
        # Compose the standard engine to reuse its loaded reference data.
        self.e = PlanningEngine(conn, params)
        self.filialen = self.e.filialen
        self._excluded_cache: dict[str, set[str]] = {}

    # ── Delegated helpers ─────────────────────────────────────────────────

    def base_window_label(self) -> str:
        return self.e.base_window_label()

    def base_year_for_month(self, month: int) -> int:
        return self.e.base_year_for_month(month)

    # ── Basis-Sondertage (Basisjahr) ──────────────────────────────────────

    def _excluded_base_dates(self, bl: str) -> set[str]:
        """ISO dates in the base window that are special (holiday/feiertagstag/
        sondertag/ferien/24./31.12.) for this bundesland — excluded from the
        weekday-share and neighbour-average computations."""
        if bl in self._excluded_cache:
            return self._excluded_cache[bl]
        e = self.e
        excl: set[str] = set()
        # Feiertage + Feiertagstage (base year via datum_vj) + Sondertage
        for entries in e.feiertage.values():
            for ft in entries:
                if ft["bundesland"] in ("alle", bl) and ft.get("datum_vj"):
                    excl.add(ft["datum_vj"])
        for st in e.sondertage.values():
            if st["bundesland"] in ("alle", bl) and st.get("datum_referenz"):
                excl.add(st["datum_referenz"])
        # Ferientage des Basisjahrs
        excl |= e.ferien_vj_dates
        # 24./31.12. im Basisfenster (Quasi-Feiertage)
        d = e.base_start
        while d < e.base_mask_end.date():
            if is_special_quasi_feiertag(d):
                excl.add(d.isoformat())
            d += timedelta(days=1)
        self._excluded_cache[bl] = excl
        return excl

    # ── Neue-Basis-Filiale: Erkennung und Hochrechnung ────────────────────

    def _branch_had_feiertag_ist(self, fil_nr: str) -> bool:
        """True if the branch had any revenue on an actual Feiertag in the base period."""
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

    def _ref_wt_sums(self, ref_fil_nrs: set[str]) -> dict[int, float]:
        """Weekday IST sums for all reference branches over the full base period (computed once)."""
        e = self.e
        base_end = e.base_mask_end
        base_start_ts = pd.Timestamp(e.base_start)
        result: dict[int, float] = {w: 0.0 for w in range(7)}
        for fil_nr in ref_fil_nrs:
            df = e._branch_base_ist(fil_nr)
            df = df[(df["datum"] >= base_start_ts) & (df["datum"] < base_end) & (df["umsatz"] > 0)]
            if df.empty:
                continue
            for w, grp in df.groupby(df["datum"].dt.weekday):
                result[int(w)] += float(grp["umsatz"].sum())
        return result

    def _wt_shares_for_branch(self, fil_nr: str, ref_wt_sums: dict[int, float]) -> dict[int, float]:
        """Weekday share of this branch relative to pre-computed ref weekday sums.

        For weekdays where this branch has no historical IST (e.g. started opening
        on Sundays only recently), fall back to the branch's average share across
        all other weekdays so those days are not budgeted as zero.
        """
        e = self.e
        df = e._branch_base_ist(fil_nr)
        df = df[df["umsatz"] >= _MIN_IST]
        new_by_wt: dict[int, float] = {w: 0.0 for w in range(7)}
        if not df.empty:
            for w, grp in df.groupby(df["datum"].dt.weekday):
                new_by_wt[int(w)] = float(grp["umsatz"].sum())
        shares = {w: (new_by_wt[w] / ref_wt_sums[w] if ref_wt_sums.get(w, 0.0) > 0 else 0.0)
                  for w in range(7)}
        # Fallback for weekdays with no historical IST: use branch's average share
        # from weekdays that DO have IST.
        filled = [v for v in shares.values() if v > 0]
        if filled:
            fallback = sum(filled) / len(filled)
            shares = {w: (v if v > 0 else fallback) for w, v in shares.items()}
        return shares

    # ── Wochentagsanteile (über das ganze Basisjahr) ──────────────────────

    def _weekday_share(self, fil_nr: str, fil: dict, bl: str) -> dict[int, float]:
        """Anteil je Wochentag am Normaltagsumsatz im gesamten Basiszeitraum.

        Sondertage, Feiertage/Feiertagstage und Ferien werden ausgeschlossen.
        Rückgabe: {0..6 -> Anteil}, Summe über offene Wochentage = 1.0.
        """
        e = self.e
        df = e._branch_base_ist(fil_nr)
        if df.empty:
            return {i: 0.0 for i in range(7)}
        eroeffnung = fil.get("eroeffnung")
        if eroeffnung:
            cutoff = date.fromisoformat(eroeffnung) + timedelta(weeks=4)
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

    # ── Nachbar-Wochentagsdurchschnitt (für Auf-/Abschlag) ────────────────

    def _neighbour_weekday_avg(self, fil_nr: str, base_d: date, bl: str) -> float:
        """Ø Umsatz desselben Wochentags in den 3 Monaten um ``base_d``
        (Vormonat, Monat, Folgemonat) im Basiszeitraum — nur Normaltage."""
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
        """Return (closed, tagestyp, feiertag_name, ferien_art)."""
        e = self.e
        iso = d.isoformat()
        wt = d.weekday()
        ft = e._relevant_feiertag(iso, bl)
        st = e._relevant_sondertag(iso, bl)
        fer = e._ferien_info_for_day(iso, bl)
        closed = False
        feiertag_name = ""
        eroeff = fil.get("eroeffnung")
        ende = fil.get("eroeffnung_ende")
        if eroeff and date.fromisoformat(eroeff) > d:
            closed = True
        elif ende and date.fromisoformat(ende) < d:
            closed = True
        elif not e._is_open_weekday(fil_nr, wt):
            closed = True
        elif ft and not e._is_open_feiertag(fil_nr, ft["name"]):
            closed = True
            feiertag_name = ft["name"]
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
                    had_feiertag_ist: bool = False) -> list[DayPlan]:
        e = self.e
        fil = self.filialen.get(fil_nr, {"bundesland": "RP"})
        bl = _normalize_bl(fil.get("bundesland", "RP") or "RP")
        py = self.p.planjahr

        share_wt = self._weekday_share(fil_nr, fil, bl)
        # Phase 1: pro Monat Basis (M0), Wochentagskonstellation (M1), Tages-Meta
        m0: dict[int, float] = {}
        m1: dict[int, float] = {}
        shift_ft: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        shift_fer: dict[int, float] = {m: 0.0 for m in range(1, 13)}
        override_val: dict[int, float | None] = {}
        day_meta: dict[int, list[dict]] = {}

        cnt_base_by_month: dict[int, dict] = {}
        cnt_plan_by_month: dict[int, dict] = {}

        for month in range(1, 13):
            ov, is_special_month = self._month_override(fil_nr, fil, month)
            override_val[month] = ov
            base_m = e._base_month_ist(fil_nr, fil, month)
            m0[month] = base_m
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
                # Blackout: base dates within 4 weeks of opening are atypical
                # (opening-day effect) and must not be used as reference.
                eroeff_str = fil.get("eroeffnung")
                if base_ist > 0 and eroeff_str and base_d:
                    _eroeff_d = date.fromisoformat(eroeff_str)
                    if base_d < _eroeff_d + timedelta(weeks=4):
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
        R_annual = sum(m0.values())
        cnt_year_base = {w: sum(cnt_base_by_month[mo].get(w, 0) for mo in range(1, 13))
                         for w in range(7)}
        d_w = {w: (R_annual * share_wt.get(w, 0.0) / cnt_year_base[w])
               if cnt_year_base[w] > 0 else 0.0 for w in range(7)}
        for month in range(1, 13):
            cb = cnt_base_by_month[month]
            cp = cnt_plan_by_month[month]
            m1[month] = m0[month] + sum(
                (cp.get(w, 0) - cb.get(w, 0)) * d_w[w] for w in range(7))

        # Phase 2: Auf-/Abschlag-Verschiebung zwischen Monaten
        for month in range(1, 13):
            if override_val[month] is not None:
                continue
            for m in day_meta[month]:
                if m["closed"] or m["base_ist"] <= 0:
                    continue
                art = m["mapping_art"]
                is_ft = art in ("feiertag", "feiertagstag", "sondertag")
                is_fer = art in ("ferien", "Ferienabschlag")
                if not (is_ft or is_fer):
                    continue
                base_d = m["base_d"]
                if base_d is None or base_d.month == month:
                    continue  # gleicher Monat → keine Verschiebung
                neigh = self._neighbour_weekday_avg(fil_nr, base_d, bl)
                markup = m["base_ist"] - neigh
                if abs(markup) < 0.005:
                    continue
                bucket = shift_ft if is_ft else shift_fer
                bucket[month] += markup        # Budgetmonat erhält Auf-/Abschlag
                if 1 <= base_d.month <= 12:
                    bucket[base_d.month] -= markup  # Ursprungsmonat verliert ihn
                # Store neigh_ref so _build_day can add an adj to eff_feiertag/eff_ferien
                # that normalises the cross-month scale difference.  Without this,
                # ist_vj for a Fasching day shows the March-scale IST (e.g. 15 000 €)
                # while budget is a February-scale value (e.g. 7 000 €), making
                # eff_wochentag hugely negative.
                m["neigh_ref"] = neigh
                m["shift_bucket"] = "ft" if is_ft else "fer"

        # Phase 3: Monatsumsatz finalisieren + auf Tage verteilen
        results: list[DayPlan] = []
        for month in range(1, 13):
            ov = override_val[month]
            metas = day_meta[month]
            if ov is not None:
                _m0 = _m1 = _m2 = _m3 = ov
                sft = sfer = 0.0
            else:
                _m0 = m0[month]
                _m1 = m1[month]
                sft = shift_ft[month]
                sfer = shift_fer[month]
                _m2 = _m1 + sft + sfer
                growth = e._growth(fil, month)
                _m3 = round(_m2 * growth, 2)

            open_metas = [m for m in metas if not m["closed"]]
            s = sum(m["base_ist"] for m in open_metas)
            n_open = len(open_metas)

            for m in metas:
                imputed_budget: float | None = None
                if ref_day_budgets is not None and wt_shares is not None and not m["closed"]:
                    if m["base_ist"] < _MIN_IST:
                        is_feiertag = m["tagestyp"] == "feiertag"
                        if is_feiertag:
                            # Impute Feiertag only if branch had Feiertag revenue in base period.
                            if had_feiertag_ist:
                                ref_total = ref_day_budgets.get(m["d"].isoformat(), 0.0)
                                imputed_budget = round(ref_total * wt_shares.get(6, 0.0), 2)
                        else:
                            # Normal day with missing base IST → impute via weekday share.
                            ref_total = ref_day_budgets.get(m["d"].isoformat(), 0.0)
                            eff_wt = m["wt"]
                            imputed_budget = round(ref_total * wt_shares.get(eff_wt, 0.0), 2)
                results.append(self._build_day(
                    fil_nr, bl, m, _m0, _m1, _m2, _m3, sft, sfer, s, n_open,
                    imputed_budget=imputed_budget))

        return results

    # ── Override / neue Filiale (wie Logik 1) ─────────────────────────────

    def _month_override(self, fil_nr: str, fil: dict, month: int) -> tuple[float | None, bool]:
        """Return (monatswert | None, is_special). None = regulär berechnen."""
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
                   _m0: float, _m1: float, _m2: float, _m3: float,
                   sft: float, sfer: float, s: float, n_open: int,
                   imputed_budget: float | None = None) -> DayPlan:
        d = m["d"]
        ist_vj = round(m["base_ist"], 2)

        if m["closed"]:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=ist_vj, eff_oeffnung=round(-ist_vj, 2),
                eff_hochrechnung=0.0, eff_verteilung=0.0,
                eff_wochentag=0.0, eff_preis=0.0, eff_ferien=0.0,
                eff_feiertag=0.0, eff_norm=0.0, budget=0.0,
                monat_basis=round(_m0, 2), monat_hoch=round(_m1, 2),
                monat_plan=round(_m3, 2), tagestyp="geschlossen",
                feiertag_name=m["feiertag_name"], ferien_art=m["ferien_art"],
                normalisierung=0.0,
            )

        # Imputation for branches with missing base IST: budget goes into
        # eff_hochrechnung (separate column), not eff_verteilung.
        if imputed_budget is not None:
            return DayPlan(
                fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
                ist_vj=0.0, eff_oeffnung=0.0,
                eff_hochrechnung=imputed_budget,
                eff_verteilung=0.0,
                eff_wochentag=0.0, eff_preis=0.0, eff_ferien=0.0,
                eff_feiertag=0.0, eff_norm=0.0, budget=imputed_budget,
                monat_basis=round(_m0, 2), monat_hoch=round(_m1, 2),
                monat_plan=round(_m3, 2), tagestyp=m["tagestyp"],
                feiertag_name=m["feiertag_name"], ferien_art=m["ferien_art"],
                normalisierung=0.0,
            )

        # Tagesanteil am Monat (offene Tage). Kein direktes Basis-IST → gleichverteilt.
        if s > 0:
            w = m["base_ist"] / s
        else:
            w = (1.0 / n_open) if n_open else 0.0

        budget = round(w * _m3, 2)
        # For cross-month special days, Phase 2 stored neigh_ref = average IST of
        # same weekday in surrounding months (= the "normal" reference within the
        # plan month). Without this adj, ist_vj would be the actual Fasching/Sondertag
        # IST from the base month (e.g. March), which can be far above or below a
        # typical February day, leaving eff_wochentag with a huge spurious component.
        neigh_ref = m.get("neigh_ref")
        shift_bucket = m.get("shift_bucket")
        if neigh_ref is not None:
            adj = round(neigh_ref - ist_vj, 2)
            eff_feiertag_adj = adj if shift_bucket == "ft" else 0.0
            eff_ferien_adj   = adj if shift_bucket == "fer" else 0.0
        else:
            eff_feiertag_adj = 0.0
            eff_ferien_adj   = 0.0
        eff_feiertag = round(w * sft + eff_feiertag_adj, 2)
        eff_ferien   = round(w * sfer + eff_ferien_adj, 2)
        eff_preis    = round(w * (_m3 - _m2), 2)
        # eff_wochentag is the exact residual; with the adj above it equals
        # w*_m1 - neigh_ref (≈ small) instead of absorbing a cross-month scale gap.
        eff_wochentag = round(budget - ist_vj - eff_preis - eff_ferien - eff_feiertag, 2)
        eff_verteilung = 0.0
        eff_norm = 0.0

        norm = round(budget / m["base_ist"], 4) if m["base_ist"] else 0.0
        return DayPlan(
            fil_nr=fil_nr, datum=d, wochentag=m["wt"], bundesland=bl,
            ist_vj=ist_vj, eff_oeffnung=0.0, eff_hochrechnung=0.0,
            eff_verteilung=0.0,
            eff_wochentag=eff_wochentag, eff_preis=eff_preis,
            eff_ferien=eff_ferien, eff_feiertag=eff_feiertag,
            eff_norm=0.0, budget=budget,
            monat_basis=round(_m0, 2), monat_hoch=round(_m1, 2),
            monat_plan=round(_m3, 2), tagestyp=m["tagestyp"],
            feiertag_name=m["feiertag_name"], ferien_art=m["ferien_art"],
            normalisierung=norm,
        )

    # ── Full run / persist ────────────────────────────────────────────────

    def run(self, fil_nrs: list[str] | None = None,
            progress_callback=None) -> list[DayPlan]:
        """Run planning for all (or selected) branches.

        progress_callback(done: int, total: int, fil_nr: str) is called after
        each branch is processed — use it to update a UI progress indicator.
        """
        targets = fil_nrs if fil_nrs else list(self.filialen.keys())
        active = [f for f in targets
                  if not (self.filialen.get(f, {}).get("flag_gesperrt")
                          or self.filialen.get(f, {}).get("flag_inaktiv"))]

        e = self.e
        by, bm = e.base_end_year, e.base_end_month
        plan_year = self.p.planjahr

        # Precompute monthly IST sums for all active branches in one vectorized pass.
        active_set = set(active)
        base_df = e.ist_df[
            (e.ist_df["fil_nr"].isin(active_set))
            & (e.ist_df["datum"] >= pd.Timestamp(e.base_start))
            & (e.ist_df["datum"] < e.base_mask_end)
        ].copy()
        base_df["ym"] = base_df["datum"].dt.to_period("M")

        all_monthly_ist: dict[str, dict[tuple[int, int], float]] = {}
        for fil_nr, grp_df in base_df.groupby("fil_nr"):
            mo_sums = grp_df.groupby("ym")["umsatz"].sum()
            all_monthly_ist[str(fil_nr)] = {(p.year, p.month): float(v) for p, v in mo_sums.items()}

        # All calendar months in the base period.
        all_base_months: list[tuple[int, int]] = []
        cur = e.base_start.replace(day=1)
        base_end_d = e.base_mask_end.date()
        while cur < base_end_d:
            all_base_months.append((cur.year, cur.month))
            nxt = cur.month + 1
            cur = cur.replace(year=cur.year + (nxt - 1) // 12, month=(nxt - 1) % 12 + 1)

        # Detect branches with IST gaps (at least one month 0, at least one month > 0).
        new_fil_nrs: set[str] = set()
        for fil_nr in active:
            mo = all_monthly_ist.get(fil_nr, {})
            month_sums = [mo.get(ym, 0.0) for ym in all_base_months]
            if any(s > 0 for s in month_sums) and any(s == 0.0 for s in month_sums):
                new_fil_nrs.add(fil_nr)

        # Bestandsfilialen = active branches without IST gaps, used as reference.
        ref_fil_nrs: set[str] = set()
        for fil_nr in active:
            if fil_nr in new_fil_nrs:
                continue
            mo = all_monthly_ist.get(fil_nr, {})
            month_sums = [mo.get(ym, 0.0) for ym in all_base_months]
            if all(s > 0 for s in month_sums):
                ref_fil_nrs.add(fil_nr)

        # Precompute ref weekday sums ONCE for all new branches (key performance fix).
        ref_wt_sums = self._ref_wt_sums(ref_fil_nrs)

        # Per new branch: precompute weekday shares and Feiertag flag.
        wt_shares_cache: dict[str, dict[int, float]] = {}
        feiertag_cache: dict[str, bool] = {}
        for fil_nr in new_fil_nrs:
            wt_shares_cache[fil_nr] = self._wt_shares_for_branch(fil_nr, ref_wt_sums)
            feiertag_cache[fil_nr] = self._branch_had_feiertag_ist(fil_nr)

        # Pass 1: plan all Bestandsfilialen and plan-year-new branches (no imputation).
        out: list[DayPlan] = []
        ref_day_budgets: dict[str, float] = {}
        n_total = len(active)
        done = 0
        for fil_nr in active:
            if fil_nr in new_fil_nrs:
                continue  # counted and callback-called in Pass 2
            fil = self.filialen.get(fil_nr, {})
            eroeff_str = fil.get("eroeffnung")
            is_plan_year_new = bool(eroeff_str and date.fromisoformat(eroeff_str).year == plan_year)
            if not is_plan_year_new:
                # Skip branches with no IST in the last base month.
                last_ist = all_monthly_ist.get(fil_nr, {}).get((by, bm), 0.0)
                if last_ist <= 0:
                    done += 1
                    if progress_callback:
                        progress_callback(done, n_total, fil_nr)
                    continue
            branch_results = self.plan_branch(fil_nr)
            out.extend(branch_results)
            # Accumulate ref day budgets for Pass 2.
            if fil_nr in ref_fil_nrs:
                for dp in branch_results:
                    iso = dp.datum.isoformat()
                    ref_day_budgets[iso] = ref_day_budgets.get(iso, 0.0) + dp.budget
            done += 1
            if progress_callback:
                progress_callback(done, n_total, fil_nr)

        # Pass 2: branches with IST gaps — days with base_ist == 0 get imputed.
        for fil_nr in new_fil_nrs:
            branch_results = self.plan_branch(
                fil_nr,
                ref_day_budgets=ref_day_budgets,
                wt_shares=wt_shares_cache[fil_nr],
                had_feiertag_ist=feiertag_cache[fil_nr],
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
                monat_basis, monat_hoch, monat_plan,
                monatsumsatz_ist_hoch, monatsumsatz_plan, tagesumsatz_plan,
                liefer_plan, gesamt_plan, tagestyp, feiertag_name, ferien_art, normalisierung)
               VALUES
               (:fil_nr, :datum, :wochentag, :bundesland, :ist_vj,
                :eff_oeffnung, :eff_hochrechnung, :eff_verteilung, :eff_wochentag, :eff_preis,
                :eff_ferien, :eff_feiertag, :eff_norm, :budget,
                :monat_basis, :monat_hoch, :monat_plan,
                :monatsumsatz_ist_hoch, :monatsumsatz_plan, :tagesumsatz_plan,
                :liefer_plan, :gesamt_plan, :tagestyp, :feiertag_name, :ferien_art, :normalisierung)""",
            rows,
        )
        self.conn.commit()
