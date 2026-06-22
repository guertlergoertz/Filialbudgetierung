"""Datums- und Wochentags-Mapping-Logik."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterator


def get_kw(d: date) -> int:
    """Gibt die ISO-Kalenderwoche für ein Datum zurück."""
    return d.isocalendar()[1]


def get_year_kw(d: date) -> tuple[int, int]:
    """Gibt (Jahr, KW) als Tupel zurück."""
    iso = d.isocalendar()
    return iso[0], iso[1]


def iter_dates(start: date, end: date) -> Iterator[date]:
    """Iteriert über alle Tage von start bis end (inklusiv)."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def wochentag_name(d: date) -> str:
    """Gibt den deutschen Wochentagnamen zurück."""
    namen = ["Montag", "Dienstag", "Mittwoch", "Donnerstag",
             "Freitag", "Samstag", "Sonntag"]
    return namen[d.weekday()]


def same_weekday_last_year(d: date) -> date:
    """Gibt das Datum des gleichen Wochentags im Vorjahr zurück (ISO-KW-basiert)."""
    year, kw, wd = d.isocalendar()
    # Gleiche KW, gleicher Wochentag, Vorjahr
    jan4 = date(year - 1, 1, 4)  # 4. Januar liegt immer in KW 1
    kw1_monday = jan4 - timedelta(days=jan4.weekday())
    target = kw1_monday + timedelta(weeks=kw - 1, days=wd - 1)
    return target
