"""Generator for the datumsmapping table.

For each day in the plan year × each bundesland from filialen, determines
the correct reference day in the rolling base year using:
  1. Feiertag (art='feiertag') → same-named holiday in base year via datum_vj
  2. Feiertagstag (art='feiertagstag') → ISO-KW mapping (treated as normal by engine)
  3. Sondertag → datum_referenz from sondertage table
  4. Ferien week N → same week N in VJ period (weekday-matched, same month only)
  5. Normal → same ISO-KW + weekday in base year

Description priority (combined): Feiertag > Feiertagstag > Sondertag > Ferien
Feiertagstage are labelled simply "Feiertagstag" (not the full holiday name).
Feiertagstag priority overrides Ferien: a day that falls in Ferien but is also
a Feiertagstag uses the Feiertagstag base date (parent holiday VJ + offset).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Iterator

import pandas as pd

from planning.engine import _normalize_bl, is_special_quasi_feiertag


def _date_range(start: date, end: date) -> Iterator[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _is_vj_holiday(d: date, bl: str, engine) -> bool:
    """True if d is an actual public holiday (art='feiertag') in the base year for bl.

    Holidays are stored keyed by their plan-year date (datum_plan); the base-year
    equivalent lives in the datum_vj column. The engine pre-builds feiertage_vj
    (keyed by datum_vj) so a base-year date like 2025-01-06 (Epiphany) is correctly
    recognised as a holiday and never used as a base-comparison day.
    """
    feiertage_vj = getattr(engine, "feiertage_vj", None)
    if feiertage_vj is not None:
        return any(
            fe["bundesland"] in ("alle", bl)
            for fe in feiertage_vj.get(d.isoformat(), [])
        )
    # Fallback for older engine instances without feiertage_vj
    return any(
        fe.get("art") == "feiertag" and fe["bundesland"] in ("alle", bl)
        for fe in engine.feiertage.get(d.isoformat(), [])
    )


def _ferien_base_day(period: dict, woche: int, wt: int, blocked, plan_month: int) -> tuple[date, bool]:
    """Pick the base-year reference day for a plan ferien day.

    Returns (base_date, is_Ferienabschlag) where is_Ferienabschlag=True means
    no same-weekday ferien day existed in the VJ period (restricted to the same
    calendar month as the plan date) and we fell back to the nearest forward
    non-blocked normal day (Ferienabschlag/-aufschlag logic).

    plan_month is used to restrict the in-period search to the same month as
    the plan date, preventing Dec days (e.g. Dec 23) from matching a Jan plan
    day when Weihnachtsferien is stored as a single Dec-Jan period.
    """
    vj_start = date.fromisoformat(period["start_vj"])
    vj_ende = date.fromisoformat(period["ende_vj"])
    wk_start = vj_start + timedelta(weeks=woche - 1)
    if wk_start > vj_ende:
        wk_start = vj_start
    ideal = wk_start + timedelta(days=(wt - wk_start.weekday()))

    # Prefer same-month days (avoids Dec↔Jan cross-contamination in Weihnachtsferien)
    in_period = [d for d in _date_range(vj_start, vj_ende)
                 if d.weekday() == wt and not blocked(d) and d.month == plan_month]
    if not in_period:
        # Fallback: any month in the period (e.g. very short ferien entirely in one month)
        in_period = [d for d in _date_range(vj_start, vj_ende)
                     if d.weekday() == wt and not blocked(d)]
    if in_period:
        return min(in_period, key=lambda d: abs((d - ideal).days)), False

    # No usable same-weekday day inside the period — Ferienabschlag case.
    # Search FORWARD first (nearest normal day after ferien end), then backward.
    alt_base = vj_ende + timedelta(days=1)
    days_ahead = (wt - alt_base.weekday()) % 7
    for shift in range(0, 60):
        alt = alt_base + timedelta(days=days_ahead) + timedelta(weeks=shift)
        if not blocked(alt):
            return alt, True
    alt_base2 = vj_start - timedelta(days=1)
    days_back = (alt_base2.weekday() - wt) % 7
    for shift in range(0, 60):
        alt = alt_base2 - timedelta(days=days_back) - timedelta(weeks=shift)
        if not blocked(alt):
            return alt, True
    return ideal, True


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _date_from_iso_week(year: int, week: int, weekday: int) -> date:
    """Return date for ISO year/week/weekday. Clamps if week doesn't exist in year."""
    jan4 = date(year, 1, 4)
    week1_monday = jan4 - timedelta(days=jan4.weekday())
    result = week1_monday + timedelta(weeks=week - 1, days=weekday)
    if result.isocalendar()[0] != year:
        result = week1_monday + timedelta(weeks=51, days=weekday)
    return result


def generate_datumsmapping(conn: sqlite3.Connection, planjahr: int, engine) -> int:
    """Generate and persist datumsmapping for planjahr. Returns row count."""
    py = planjahr

    bl_rows = conn.execute(
        "SELECT DISTINCT bundesland FROM filialen WHERE bundesland IS NOT NULL AND bundesland != ''"
    ).fetchall()
    bl_raw = [r["bundesland"] for r in bl_rows]
    bundeslaender = list(dict.fromkeys(_normalize_bl(b) for b in bl_raw)) if bl_raw else ["RP"]

    # Build VJ ferien dates per BL to avoid comparing normal plan days with VJ vacation days
    _vj_ferien_bl: dict[str, set[str]] = {}
    for f in engine.ferien_plan:
        bl_f = f["bundesland"]
        vs = date.fromisoformat(f["start_vj"])
        ve = date.fromisoformat(f["ende_vj"])
        s = _vj_ferien_bl.setdefault(bl_f, set())
        for d in _date_range(vs, ve):
            s.add(d.isoformat())

    # Build VJ Feiertagstage + Sondertage dates per BL — these must not serve as
    # base-comparison days for normal plan days (ISO-KW fallback, step 6).
    _vj_special_bl: dict[str, set[str]] = {}
    for entries in engine.feiertage.values():
        for ft in entries:
            if ft.get("art") == "feiertagstag" and ft.get("datum_vj"):
                bl_f = ft["bundesland"]
                target_bls = bundeslaender if bl_f in ("alle", "") else [_normalize_bl(bl_f)]
                for tbl in target_bls:
                    _vj_special_bl.setdefault(tbl, set()).add(ft["datum_vj"])
    for st in engine.sondertage.values():
        if st.get("datum_referenz"):
            bl_s = (st.get("bundesland") or "alle")
            target_bls = (bundeslaender if bl_s in ("alle", "")
                          else [_normalize_bl(bl_s)])
            for tbl in target_bls:
                _vj_special_bl.setdefault(tbl, set()).add(st["datum_referenz"])

    rows: list[tuple] = []

    for month in range(1, 13):
        by = engine.base_year_for_month(month)
        dim = pd.Period(f"{py}-{month:02d}").days_in_month

        for day in range(1, dim + 1):
            plan_d = date(py, month, day)
            iso = plan_d.isoformat()
            wt = plan_d.weekday()
            iso_week = plan_d.isocalendar()[1]

            for bl in bundeslaender:
                bezeichnung_parts: list[str] = []
                base_bezeichnung_parts: list[str] = []
                plan_typ = "normal"
                mapping_art = "iso_kw"
                base_d: date | None = None
                _used_iso_kw = False

                # 1. Feiertag (art='feiertag')
                ft = engine._relevant_feiertag(iso, bl)
                if ft:
                    plan_typ = "feiertag"
                    mapping_art = "feiertag"
                    bezeichnung_parts.append(ft["name"])
                    base_bezeichnung_parts.append(ft["name"])
                    base_d = engine._feiertag_base_date(ft, month)
                    if base_d is None:
                        base_d = _safe_date(by, month, day) or plan_d

                # 2. Feiertagstag (art='feiertagstag') — only when no actual Feiertag
                if plan_typ == "normal":
                    ft_tag = None
                    for entry in engine.feiertage.get(iso, []):
                        if entry["bundesland"] in ("alle", bl) and entry.get("art") == "feiertagstag":
                            ft_tag = entry
                            break
                    if ft_tag:
                        plan_typ = "feiertagstag"
                        mapping_art = "feiertagstag"
                        bezeichnung_parts.append("Feiertagstag")
                        base_bezeichnung_parts.append("Feiertagstag")
                        if ft_tag.get("datum_vj"):
                            try:
                                base_d = date.fromisoformat(ft_tag["datum_vj"])
                            except (ValueError, TypeError):
                                pass

                # 3. Sondertag
                st_entry = engine._relevant_sondertag(iso, bl)
                if st_entry:
                    bezeichnung_parts.append(st_entry["bezeichnung"])
                    base_bezeichnung_parts.append(st_entry["bezeichnung"])
                    if plan_typ == "normal":
                        plan_typ = "sondertag"
                        mapping_art = "sondertag"
                        if st_entry.get("datum_referenz"):
                            try:
                                base_d = date.fromisoformat(st_entry["datum_referenz"])
                            except ValueError:
                                pass

                # 4. Ferien — update plan_typ/base_d but NOT bezeichnung (shown in separate columns)
                fer = engine._ferien_info_for_day(iso, bl)
                if fer:
                    art, woche = fer
                    if plan_typ == "normal":
                        plan_typ = "ferien"
                        mapping_art = "ferien"
                        period = engine._ferien_period_for_day(iso, bl)
                        if period:
                            # A ferien plan day must always map to a ferien day
                            # in the matched VJ period (weekday-aligned), never to
                            # a public holiday or Dec 24/31.
                            def _blocked(d, _bl=bl):
                                return _is_vj_holiday(d, _bl, engine) or is_special_quasi_feiertag(d)
                            base_d, _is_abschlag = _ferien_base_day(period, woche, wt, _blocked, month)
                            if _is_abschlag:
                                mapping_art = "Ferienabschlag"

                    # 4.5. Feiertagstag override for ferien days:
                    # A day that is in Ferien but also a Feiertagstag uses
                    # the Feiertagstag base date instead of the ferien base date.
                    if plan_typ == "ferien":
                        ft_tag2 = None
                        for entry in engine.feiertage.get(iso, []):
                            if entry["bundesland"] in ("alle", bl) and entry.get("art") == "feiertagstag":
                                ft_tag2 = entry
                                break
                        if ft_tag2:
                            plan_typ = "feiertagstag"
                            mapping_art = "feiertagstag"
                            bezeichnung_parts.append("Feiertagstag")
                            base_bezeichnung_parts.append("Feiertagstag")
                            base_d = None
                            if ft_tag2.get("datum_vj"):
                                try:
                                    base_d = date.fromisoformat(ft_tag2["datum_vj"])
                                except (ValueError, TypeError):
                                    pass

                # 5. Fallback: ISO-KW
                if base_d is None:
                    base_d = _date_from_iso_week(by, iso_week, wt)
                    _used_iso_kw = True

                # 6. For normal/feiertagstag days (and ferien days that fell back
                # to ISO-KW): avoid landing on a VJ holiday, vacation, Feiertagstag,
                # Sondertag or Dec 24/31 in the base year.
                if plan_typ in ("normal", "feiertagstag") or (plan_typ == "ferien" and _used_iso_kw):
                    def _avoid(d, _bl=bl):
                        return (_is_vj_holiday(d, _bl, engine)
                                or d.isoformat() in _vj_ferien_bl.get(_bl, set())
                                or d.isoformat() in _vj_special_bl.get(_bl, set())
                                or is_special_quasi_feiertag(d))
                    if _avoid(base_d):
                        # Forward first (nearest normal week after the blocked day),
                        # mirroring the ferien fallback; avoids landing in the atypical
                        # Christmas week (e.g. Jan 6 Epiphany → Jan 13, not Dec 30).
                        for shift in range(1, 9):
                            for direction in (1, -1):
                                alt = base_d + timedelta(weeks=shift * direction)
                                if not _avoid(alt):
                                    base_d = alt
                                    break
                            else:
                                continue
                            break

                # 7. Dec 24 and Dec 31 always compare to same calendar date in base year
                # (placed last so holiday avoidance above cannot shift them away)
                if month == 12 and day in (24, 31):
                    base_d = _safe_date(by, 12, day) or base_d

                bezeichnung = ", ".join(bezeichnung_parts)
                base_bezeichnung = ", ".join(base_bezeichnung_parts)

                rows.append((
                    iso, base_d.isoformat(),
                    plan_typ, plan_typ, bl, mapping_art,
                    bezeichnung, base_bezeichnung,
                ))

    conn.execute(
        "DELETE FROM datumsmapping WHERE CAST(strftime('%Y', plan_datum) AS INTEGER) = ?",
        (py,)
    )
    conn.executemany(
        """INSERT OR REPLACE INTO datumsmapping
           (plan_datum, base_datum, plan_typ, base_typ, bundesland, mapping_art,
            bezeichnung, base_bezeichnung)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    return len(rows)
