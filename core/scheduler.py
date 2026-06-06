"""P3.9 — routine scheduler.

Reads ``config/routines.yaml`` and fires user-defined prompts at cron
times (or on a fixed interval). Each fire calls ``app.process_input``
as if the user just spoke the command.

Supports a tiny subset of cron syntax: each field is one of:
    ``*``               every value
    ``*/N``             every N (step from minimum)
    ``A``               exact value
    ``A,B,C``           list
    ``A-B``             inclusive range

Field order: minute hour day-of-month month day-of-week.

A routine may opt out of the cron format and use ``interval_seconds``
instead (simpler for periodic checks). One of cron / interval_seconds
is required.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from core.logger import logger


# ----------------------------------------------------------------------
# Cron parsing
# ----------------------------------------------------------------------

_FIELD_BOUNDS = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week (Mon=0, Sun=6 — Python datetime weekday())
)


def _parse_field(spec: str, low: int, high: int) -> set[int]:
    spec = (spec or "").strip()
    if not spec or spec == "*":
        return set(range(low, high + 1))
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
            except ValueError:
                continue
            if step <= 0:
                continue
            values.update(range(low, high + 1, step))
        elif "-" in part:
            try:
                a, b = part.split("-", 1)
                a_i, b_i = int(a), int(b)
            except ValueError:
                continue
            if a_i > b_i:
                continue
            values.update(range(max(low, a_i), min(high, b_i) + 1))
        else:
            try:
                v = int(part)
            except ValueError:
                continue
            if low <= v <= high:
                values.add(v)
    return values


def parse_cron(expr: str) -> list[set[int]]:
    """Parse a 5-field cron expression. Raises ValueError if shape wrong."""
    parts = (expr or "").split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(parts)}: {expr!r}")
    return [_parse_field(parts[i], *_FIELD_BOUNDS[i]) for i in range(5)]


def cron_matches(parsed: list[set[int]], when: datetime) -> bool:
    minute, hour, dom, month, dow = parsed
    if when.minute not in minute or when.hour not in hour:
        return False
    if when.day not in dom or when.month not in month:
        return False
    if when.weekday() not in dow:
        return False
    return True


# ----------------------------------------------------------------------
# Routines
# ----------------------------------------------------------------------

@dataclass
class Routine:
    name: str
    command: str
    cron: str | None = None
    interval_seconds: int | None = None
    quiet_hours: tuple[int, int] | None = None  # inclusive (start, end), 24h
    _parsed_cron: list[set[int]] | None = field(default=None, repr=False)
    _last_fired_minute: tuple | None = field(default=None, repr=False)
    _last_fired_at: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if self.cron is not None:
            self._parsed_cron = parse_cron(self.cron)

    def should_fire(self, now: datetime, monotonic: float) -> bool:
        if self.quiet_hours is not None:
            start, end = self.quiet_hours
            if start <= end:
                if start <= now.hour <= end:
                    return False
            else:
                if now.hour >= start or now.hour <= end:
                    return False
        if self._parsed_cron is not None:
            minute_key = (now.year, now.month, now.day, now.hour, now.minute)
            if minute_key == self._last_fired_minute:
                return False
            if cron_matches(self._parsed_cron, now):
                self._last_fired_minute = minute_key
                return True
            return False
        if self.interval_seconds is not None:
            if monotonic - self._last_fired_at >= self.interval_seconds:
                self._last_fired_at = monotonic
                return True
            return False
        return False


# ----------------------------------------------------------------------
# Loader
# ----------------------------------------------------------------------

def load_routines(path: str) -> list[Routine]:
    if not path or not os.path.isfile(path):
        return []
    try:
        import yaml  # type: ignore
    except Exception:
        logger.warning("[scheduler] PyYAML not installed; cannot load %s", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("[scheduler] failed to read %s: %s", path, exc)
        return []
    raw_routines = (data or {}).get("routines") or []
    out: list[Routine] = []
    for entry in raw_routines:
        if not isinstance(entry, dict):
            continue
        try:
            qh = entry.get("quiet_hours")
            quiet = None
            if isinstance(qh, dict) and "start" in qh and "end" in qh:
                quiet = (int(qh["start"]), int(qh["end"]))
            out.append(Routine(
                name=str(entry.get("name") or "unnamed"),
                command=str(entry.get("command") or "").strip(),
                cron=entry.get("cron"),
                interval_seconds=(int(entry["interval_seconds"])
                                   if entry.get("interval_seconds") is not None else None),
                quiet_hours=quiet,
            ))
        except Exception as exc:
            logger.warning("[scheduler] skipping malformed routine %r: %s", entry, exc)
    return out


# ----------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------

class Scheduler:
    """Background thread that fires routines at cron / interval times.

    `dispatch` is called with the routine's command string on each fire.
    By default the FRIDAY integration passes ``app.process_input``.
    """

    def __init__(self, routines: list[Routine], dispatch: Callable[[str], None],
                 tick_seconds: float = 1.0) -> None:
        self._routines = list(routines)
        self._dispatch = dispatch
        self._tick = max(0.1, float(tick_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="FridayScheduler", daemon=True,
        )
        self._thread.start()
        logger.info("[scheduler] started with %d routine(s)", len(self._routines))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def tick(self, now: datetime | None = None, monotonic: float | None = None) -> int:
        """Fire any routines whose time has come. Returns the count fired.
        Exposed for tests so we don't need to wait on the thread.
        """
        when = now or datetime.now()
        mono = monotonic if monotonic is not None else time.monotonic()
        fired = 0
        for routine in self._routines:
            if not self._stop.is_set() and routine.should_fire(when, mono):
                if not routine.command:
                    continue
                try:
                    self._dispatch(routine.command)
                    fired += 1
                    logger.info("[scheduler] fired routine %r", routine.name)
                except Exception as exc:
                    logger.warning("[scheduler] dispatch %r failed: %s",
                                   routine.name, exc)
        return fired

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                logger.warning("[scheduler] tick error: %s", exc)
            self._stop.wait(self._tick)


def make_scheduler_from_config(path: str, dispatch: Callable[[str], None],
                               tick_seconds: float = 1.0) -> Scheduler:
    return Scheduler(load_routines(path), dispatch, tick_seconds=tick_seconds)
