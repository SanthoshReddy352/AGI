"""P3.9 — Scheduler tests."""
from datetime import datetime

import pytest

from core.scheduler import (
    Routine,
    Scheduler,
    cron_matches,
    load_routines,
    parse_cron,
)


# ----------------------------------------------------------------------
# Cron parser
# ----------------------------------------------------------------------

def test_parse_cron_wildcards_all_minutes():
    parsed = parse_cron("* * * * *")
    assert len(parsed[0]) == 60
    assert 0 in parsed[0] and 59 in parsed[0]


def test_parse_cron_step():
    parsed = parse_cron("*/15 * * * *")
    assert parsed[0] == {0, 15, 30, 45}


def test_parse_cron_specific_time():
    parsed = parse_cron("0 8 * * *")
    assert parsed[0] == {0}
    assert parsed[1] == {8}


def test_parse_cron_list_and_range():
    parsed = parse_cron("0,30 9-11 * * *")
    assert parsed[0] == {0, 30}
    assert parsed[1] == {9, 10, 11}


def test_parse_cron_rejects_bad_shape():
    with pytest.raises(ValueError):
        parse_cron("0 8 * *")


def test_cron_matches_morning_briefing():
    parsed = parse_cron("0 8 * * *")
    assert cron_matches(parsed, datetime(2026, 5, 23, 8, 0))
    assert not cron_matches(parsed, datetime(2026, 5, 23, 8, 1))
    assert not cron_matches(parsed, datetime(2026, 5, 23, 9, 0))


# ----------------------------------------------------------------------
# Routine should_fire
# ----------------------------------------------------------------------

def test_routine_cron_fires_once_per_minute():
    r = Routine(name="t", command="hi", cron="* * * * *")
    when = datetime(2026, 5, 23, 8, 0)
    assert r.should_fire(when, monotonic=0.0)
    assert not r.should_fire(when, monotonic=0.5)  # same minute → no refire


def test_routine_interval_fires_each_interval():
    r = Routine(name="i", command="hi", interval_seconds=10)
    assert r.should_fire(datetime.now(), monotonic=100.0)
    assert not r.should_fire(datetime.now(), monotonic=105.0)
    assert r.should_fire(datetime.now(), monotonic=120.0)


def test_routine_quiet_hours_suppress():
    r = Routine(name="q", command="hi", cron="* * * * *",
                quiet_hours=(22, 7))
    assert not r.should_fire(datetime(2026, 5, 23, 23, 0), monotonic=0.0)
    assert not r.should_fire(datetime(2026, 5, 23, 3, 0), monotonic=0.0)
    assert r.should_fire(datetime(2026, 5, 23, 9, 0), monotonic=0.0)


# ----------------------------------------------------------------------
# Scheduler.tick
# ----------------------------------------------------------------------

def test_scheduler_tick_fires_due_routines():
    calls: list[str] = []
    s = Scheduler([
        Routine(name="a", command="ping", cron="* * * * *"),
        Routine(name="b", command="other", cron="0 6 * * *"),  # not due
    ], dispatch=calls.append)
    fired = s.tick(now=datetime(2026, 5, 23, 8, 0), monotonic=0.0)
    assert fired == 1
    assert calls == ["ping"]


def test_scheduler_tick_skips_empty_commands():
    calls: list[str] = []
    s = Scheduler([Routine(name="x", command="", cron="* * * * *")],
                  dispatch=calls.append)
    s.tick(now=datetime(2026, 5, 23, 8, 0))
    assert calls == []


def test_scheduler_dispatch_error_does_not_kill_tick():
    def bad(_cmd: str) -> None:
        raise RuntimeError("boom")
    s = Scheduler([Routine(name="b", command="oops", cron="* * * * *")],
                  dispatch=bad)
    # Should not raise.
    s.tick(now=datetime(2026, 5, 23, 8, 0))


# ----------------------------------------------------------------------
# YAML loader
# ----------------------------------------------------------------------

def test_load_routines_empty_file(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("routines: []\n")
    assert load_routines(str(p)) == []


def test_load_routines_parses_cron_and_interval(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "routines:\n"
        "  - name: morning\n"
        "    cron: '0 8 * * *'\n"
        "    command: hi\n"
        "  - name: ping\n"
        "    interval_seconds: 60\n"
        "    command: poll\n"
    )
    routines = load_routines(str(p))
    assert len(routines) == 2
    assert routines[0].cron == "0 8 * * *"
    assert routines[1].interval_seconds == 60


def test_load_routines_missing_file_returns_empty(tmp_path):
    assert load_routines(str(tmp_path / "nope.yaml")) == []


def test_load_routines_parses_quiet_hours(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "routines:\n"
        "  - name: night_off\n"
        "    cron: '0 * * * *'\n"
        "    command: hello\n"
        "    quiet_hours: { start: 22, end: 7 }\n"
    )
    routines = load_routines(str(p))
    assert routines[0].quiet_hours == (22, 7)


def test_load_routines_skips_malformed(tmp_path):
    p = tmp_path / "r.yaml"
    # Bad cron expr should be skipped, not crash the loader.
    p.write_text(
        "routines:\n"
        "  - name: bad\n"
        "    cron: 'nope'\n"
        "    command: x\n"
        "  - name: good\n"
        "    interval_seconds: 30\n"
        "    command: y\n"
    )
    routines = load_routines(str(p))
    names = [r.name for r in routines]
    assert "good" in names
