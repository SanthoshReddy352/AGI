"""Phase 3 / Track 2.4 — shared NL datetime extractor (slot_extractors)."""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.planning.slot_extractors import extract_datetime

# Fixed reference instant: 2026-05-31 is a Sunday, 10:00 local.
NOW = datetime(2026, 5, 31, 10, 0)


def _dt(text):
    return extract_datetime(text, now=NOW)


# --- relative durations ----------------------------------------------------

def test_relative_minutes():
    assert _dt("remind me in 15 minutes") == "2026-05-31T10:15"


def test_relative_an_hour():
    assert _dt("in an hour") == "2026-05-31T11:00"


def test_relative_two_days():
    assert _dt("in 2 days") == "2026-06-02T10:00"


def test_relative_week():
    assert _dt("in one week") == "2026-06-07T10:00"


# --- date anchors + clock --------------------------------------------------

def test_tomorrow_at_clock():
    assert _dt("tomorrow at 3pm") == "2026-06-01T15:00"


def test_today_at_noon():
    assert _dt("today at noon") == "2026-05-31T12:00"


def test_date_only_defaults_to_morning():
    assert _dt("tomorrow") == "2026-06-01T09:00"


def test_weekday_resolves_to_next_occurrence():
    # Sunday → "monday" is the next day.
    assert _dt("monday at 9am") == "2026-06-01T09:00"


def test_next_weekday_skips_a_week():
    assert _dt("next monday") == "2026-06-08T09:00"


# --- bare clock times ------------------------------------------------------

def test_future_time_today():
    assert _dt("at 5pm") == "2026-05-31T17:00"


def test_passed_time_rolls_to_tomorrow():
    # 9am already passed at 10:00 → next day.
    assert _dt("at 9am") == "2026-06-01T09:00"


def test_24h_clock():
    assert _dt("15:30") == "2026-05-31T15:30"


def test_midnight_rolls_forward():
    assert _dt("midnight") == "2026-06-01T00:00"


# --- negatives -------------------------------------------------------------

def test_no_time_returns_empty():
    assert _dt("just chatting about the weather") == ""


def test_empty_input():
    assert extract_datetime("") == ""
    assert extract_datetime(None) == ""  # type: ignore[arg-type]
