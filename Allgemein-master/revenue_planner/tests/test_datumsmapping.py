"""Tests für datumsmapping.py."""
from __future__ import annotations

from datetime import date

import pytest

from planning.datumsmapping import (
    get_kw,
    get_year_kw,
    iter_dates,
    wochentag_name,
    same_weekday_last_year,
)


def test_get_kw_basic():
    assert get_kw(date(2024, 1, 1)) == 1


def test_get_year_kw():
    year, kw = get_year_kw(date(2024, 3, 15))
    assert year == 2024
    assert kw == 11


def test_iter_dates_count():
    dates = list(iter_dates(date(2024, 1, 1), date(2024, 1, 7)))
    assert len(dates) == 7


def test_iter_dates_empty():
    dates = list(iter_dates(date(2024, 1, 7), date(2024, 1, 1)))
    assert dates == []


def test_wochentag_name():
    assert wochentag_name(date(2024, 3, 18)) == "Montag"
    assert wochentag_name(date(2024, 3, 24)) == "Sonntag"


def test_same_weekday_last_year():
    d = date(2024, 3, 18)  # KW 12, Montag
    prev = same_weekday_last_year(d)
    assert prev.weekday() == d.weekday()
    assert prev.year == 2023
