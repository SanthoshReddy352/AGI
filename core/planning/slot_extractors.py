"""Shared slot extractors — Track 1.4b migration target.

When a parser/handler needs to pull a value out of free-form user text (a
quoted content string, an inline filename, a target URL, etc.), the
extraction logic should live here so the ContextResolver and the v1
intent parsers can call the same function. Previously each handler
shipped its own copy (`file_workspace._extract_manage_content`,
`research_agent._extract_topic`, …), which made it impossible to teach
the system a new shape without touching every consumer.

Each extractor returns a plain string (`""` on no match) so callers can
chain `extracted or args.get(name) or fallback`-style precedence rules
without dealing with `None`/exception fan-out.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta


# ----------------------------------------------------------------------
# Content extraction
# ----------------------------------------------------------------------

_DET = r"(?:(?:the|a|an|new)\s+)?"

_QUOTED_CONTENT_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bwith content\b[:\s]+(.+)$",
        r"\bthat says\b[:\s]+(.+)$",
        # Track 1.5 patterns: explicit quoted content + filename in one
        # utterance ("write 'X' to Y.txt"). Single quotes, double quotes,
        # and backticks all supported.
        r"\b(?:write|append|add)\s+['\"]([^'\"]+)['\"]\s+(?:to|into|in)\b",
        r"\b(?:write|append|add)\s+`([^`]+)`\s+(?:to|into|in)\b",
        # Looser patterns: `write X to file Y` — keeps backward-compat
        # with the pre-Track-1.5 shapes file_workspace already handled.
        rf"\bwrite\b[:\s]+(.+?)\s+\b(?:to|into|in)\s+{_DET}(?:file|document)\b",
        rf"\bappend\b[:\s]+(.+?)\s+\b(?:to|into|in)\s+{_DET}(?:file|document)\b",
        rf"\badd\b[:\s]+(.+?)\s+\bto\s+{_DET}(?:file|document)\b",
        r"\badd\b[:\s]+(.+)$",
        r"\bappend\b[:\s]+(.+)$",
    )
)


def extract_quoted_content(text: str) -> str:
    """Return the inline content carried by a manage-file-style utterance.

    Matches phrases like:
      * `write 'Hello Friday' to hello.txt`     → "Hello Friday"
      * `write "X" into Y.txt`                  → "X"
      * `add some notes to the file`            → "some notes"
      * `with content: ...`                     → the trailing text

    Returns `""` when nothing matches. Caller decides whether the
    absence of content means "ask the user" or "use a default".
    """
    if not isinstance(text, str) or not text:
        return ""
    for pattern in _QUOTED_CONTENT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip(" \n\t\"'")
    return ""


_QUOTE_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("'", "'"),
    ('"', '"'),
    ("`", "`"),
)


def content_is_quoted_in(text: str, content: str) -> bool:
    """True iff `content` appears in `text` wrapped in any supported quote
    style. Used by the literal-content guard so a quoted user string is
    written verbatim instead of being passed through the LLM content
    generator."""
    if not text or not content:
        return False
    for opener, closer in _QUOTE_WRAPPERS:
        if f"{opener}{content}{closer}" in text:
            return True
    return False


# ----------------------------------------------------------------------
# Natural-language datetime extraction
# ----------------------------------------------------------------------
#
# Track "launch-hardening §5.4 Step 1": the full, battle-tested datetime
# machinery that used to live inline in `modules/task_manager/plugin.py`
# (`_parse_datetime_parts` + `_parse_date` / `_parse_time` /
# `_parse_word_time` / `_combine_date_time`, backed by the regex / word
# tables below) now lives here as **pure functions**. `TaskManagerPlugin`
# delegates to them (its methods are thin forwards that pass a patchable
# `now=`), so reminder/calendar behaviour is byte-for-byte unchanged while
# the same parsing is reusable by template-driven (SlotFiller) workflows.
#
# Two public surfaces:
#   * `parse_datetime_parts` / `parse_date` / `parse_time` / ... — the rich
#     production parser (spoken numbers, MM/DD + ISO dates, "January 5th",
#     compact "1530", o'clock, bare-hour-on-followup, past-hour→afternoon).
#   * `extract_datetime` — a convenience wrapper returning a single ISO-8601
#     string for the common shapes, for SlotSpec/`extract_with:` consumers.

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
MINUTE_WORDS = {
    "oh": 0, "zero": 0, "five": 5, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}
WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

TIME_RE = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([ap])\s*\.?\s*m\.?\b", re.IGNORECASE)
TIME_24H_RE = re.compile(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", re.IGNORECASE)
TIME_SPOKEN_RE = re.compile(r"\b(?:at\s+)?([01]?\d|2[0-3])\s+([0-5]\d)\b", re.IGNORECASE)
TIME_BARE_AT_RE = re.compile(r"\bat\s+([1-9]|1[0-2])\b", re.IGNORECASE)
TIME_COMPACT_RE = re.compile(r"(?:^|\bat\s+)(\d{3,4})\b", re.IGNORECASE)
RELATIVE_RE = re.compile(r"\bin\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?|days?)\b", re.IGNORECASE)
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b")
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def parse_datetime_parts(text, *, allow_bare_time: bool = False, now: datetime | None = None) -> dict:
    """Parse *text* into a partial datetime spec.

    Returns one of:
      * ``{"remind_at": datetime}``    — a fully-resolved relative time
        ("in 15 minutes", "in 2 hours").
      * ``{"date": "YYYY-MM-DD", "time": "HH:MM"}`` (either key optional) —
        an absolute date and/or clock time the caller combines via
        :func:`combine_date_time`.

    ``allow_bare_time`` lets a bare number ("4") be read as an hour — only
    safe on a follow-up turn that explicitly asked for a time.
    """
    now = now or datetime.now()
    lowered = str(text or "").lower()
    parsed: dict = {}

    relative = RELATIVE_RE.search(lowered)
    if relative:
        amount = float(relative.group(1))
        unit = relative.group(2).lower()
        if unit.startswith(("minute", "min")):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        parsed["remind_at"] = now + delta
        return parsed

    date_value = parse_date(lowered, now=now)
    if date_value:
        parsed["date"] = date_value.isoformat()
    time_value = parse_time(lowered, allow_bare=allow_bare_time)
    if time_value:
        parsed["time"] = f"{time_value[0]:02d}:{time_value[1]:02d}"
    return parsed


def parse_date(lowered, *, now: datetime | None = None):
    """Return a ``date`` for a date phrase in *lowered* text, or ``None``.

    Recognizes today/tomorrow, ISO ``YYYY-MM-DD``, numeric ``DD/MM[/YY]``,
    "January 5th" / "5 Jan" (with optional year), and (next) weekday names.
    A bare day/month with no year that resolves to the past rolls forward a
    year; a weekday resolves to its next occurrence ("next" skips a week).
    """
    now = now or datetime.now()
    lowered = str(lowered or "").lower()
    today = now.date()
    if re.search(r"\btoday\b", lowered):
        return today
    if re.search(r"\btomorrow\b", lowered):
        return today + timedelta(days=1)

    iso = ISO_DATE_RE.search(lowered)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3))).date()
        except ValueError:
            return None

    numeric = DATE_NUMERIC_RE.search(lowered)
    if numeric:
        day = int(numeric.group(1))
        month = int(numeric.group(2))
        year = int(numeric.group(3) or today.year)
        if year < 100:
            year += 2000
        try:
            candidate = datetime(year, month, day).date()
            if candidate < today and numeric.group(3) is None:
                candidate = datetime(year + 1, month, day).date()
            return candidate
        except ValueError:
            return None

    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    month_first = re.search(rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", lowered)
    if month_first:
        return date_from_month_match(month_first.group(2), month_first.group(1), month_first.group(3), today)
    day_first = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})(?:,?\s+(\d{{4}}))?\b", lowered)
    if day_first:
        return date_from_month_match(day_first.group(1), day_first.group(2), day_first.group(3), today)

    next_prefix = "next " in lowered
    for name, index in WEEKDAYS.items():
        if re.search(rf"\b(?:next\s+)?{re.escape(name)}\b", lowered):
            days_ahead = (index - today.weekday()) % 7
            if days_ahead == 0 or next_prefix:
                days_ahead += 7
            return today + timedelta(days=days_ahead)
    return None


def date_from_month_match(day_text, month_text, year_text, today):
    try:
        day = int(day_text)
        month = MONTHS[month_text.lower()]
        year = int(year_text or today.year)
        candidate = datetime(year, month, day).date()
        if candidate < today and not year_text:
            candidate = datetime(year + 1, month, day).date()
        return candidate
    except Exception:
        return None


def parse_time(lowered, *, allow_bare: bool = False):
    """Return ``(hour, minute)`` for a clock time in *lowered*, or ``None``.

    Handles "3pm" / "3:30 pm", 24-hour "15:30", spoken "15 30", "at 4",
    compact "1530", spelled-out times ("four o'clock", "four p m"), and —
    when ``allow_bare`` — a lone hour number on a follow-up turn.
    """
    lowered = str(lowered or "").lower()
    match = TIME_RE.search(lowered)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridian = match.group(3).lower()
        if meridian == "p" and hour != 12:
            hour += 12
        if meridian == "a" and hour == 12:
            hour = 0
        return hour, minute
    match = TIME_24H_RE.search(lowered)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = TIME_SPOKEN_RE.search(lowered)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = TIME_BARE_AT_RE.search(lowered)
    if match:
        return int(match.group(1)), 0
    match = TIME_COMPACT_RE.search(lowered.strip())
    if match:
        digits = match.group(1)
        hour = int(digits[:-2])
        minute = int(digits[-2:])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    if allow_bare:
        match = re.search(r"\b([1-9]|1[0-2])\b", lowered)
        if match:
            return int(match.group(1)), 0
    word_time = parse_word_time(lowered, allow_bare=allow_bare)
    if word_time:
        return word_time
    return None


def parse_word_time(lowered, *, allow_bare: bool = False):
    lowered = str(lowered or "").lower()
    hour_words = "|".join(NUMBER_WORDS)
    minute_words = "|".join(MINUTE_WORDS)
    match = re.search(
        rf"\b(?:at\s+)?({hour_words})\s+({minute_words})(?:\s+([ap])\s*\.?\s*m\.?)?\b",
        lowered,
    )
    if match:
        hour = NUMBER_WORDS[match.group(1)]
        minute = MINUTE_WORDS[match.group(2)]
        meridian = (match.group(3) or "").lower()
        return apply_meridian(hour, minute, meridian)

    match = re.search(rf"\b(?:at\s+)?({hour_words})(?:\s+o\s+clock|\s+oclock)\b", lowered)
    if match:
        hour = NUMBER_WORDS[match.group(1)]
        return hour, 0

    match = re.search(rf"\b(?:at\s+)?({hour_words})\s+([ap])\s*\.?\s*m\.?\b", lowered)
    if match:
        hour = NUMBER_WORDS[match.group(1)]
        meridian = (match.group(2) or "").lower()
        return apply_meridian(hour, 0, meridian)
    if allow_bare:
        match = re.search(rf"^\s*({hour_words})\s*$", lowered)
        if match:
            return NUMBER_WORDS[match.group(1)], 0
    return None


def apply_meridian(hour, minute, meridian):
    if meridian == "p" and hour != 12:
        hour += 12
    if meridian == "a" and hour == 12:
        hour = 0
    return hour, minute


def combine_date_time(date_text, time_text, *, now: datetime | None = None):
    """Combine an ISO date string + ``HH:MM`` time string into a datetime.

    Returns ``None`` when either part is missing or unparseable. An
    ambiguous morning hour (1–11am) that has already passed *today* is
    bumped to the afternoon — the speaker almost always meant PM.
    """
    if not date_text or not time_text:
        return None
    now = now or datetime.now()
    try:
        candidate = datetime.fromisoformat(f"{date_text}T{time_text}:00")
        if candidate.date() == now.date() and candidate <= now and 1 <= candidate.hour <= 11:
            candidate = candidate + timedelta(hours=12)
        return candidate
    except Exception:
        return None


# ----------------------------------------------------------------------
# Convenience single-string wrapper (template / SlotFiller `extract_with:`)
# ----------------------------------------------------------------------
#
# Returns an ISO-8601 string ("" on no match) so it slots straight into a
# SlotSpec extractor or a YAML `extract_with: extract_datetime` step. It
# builds on the rich parsers above and adds two SlotFiller-friendly shapes
# the in-handler parser leaves to its callers: word-number / "week"
# relatives ("in an hour", "in one week") and noon/midnight, plus the
# "date with no time → 09:00" and "bare time already passed → next day"
# defaults the reminder follow-up loop would otherwise apply.

_REL_WORD_RE = re.compile(
    r"\bin\s+(\d+|a|an|one|two|three|four|five|ten|fifteen|twenty|thirty)\s+"
    r"(minute|min|hour|hr|day|week)s?\b",
    re.IGNORECASE,
)
_NOON_RE = re.compile(r"\bnoon\b", re.IGNORECASE)
_MIDNIGHT_RE = re.compile(r"\bmidnight\b", re.IGNORECASE)
_WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30,
}


def extract_datetime(text: str, *, now: datetime | None = None) -> str:
    """Return an ISO-8601 datetime for an NL time phrase in *text*, or "".

    Handles, cheapest-first:
      * relative durations  — "in 15 minutes", "in an hour", "in one week"
      * today / tomorrow / weekday / ISO / MM-DD / "January 5th" (+ clock)
      * clock times          — "at 3pm", "3:30pm", "15:00", "1530", "noon",
        "midnight", spoken "four o'clock" (today, or next day if passed)

    A date with no time defaults to 09:00. Returns "" when nothing parses,
    so a caller can fall through or ask the user.
    """
    if not isinstance(text, str) or not text.strip():
        return ""
    now = now or datetime.now()
    lowered = text.lower()

    # 1. Relative duration — most explicit, return immediately. This accepts
    #    word numbers and the "week" unit, which the production RELATIVE_RE
    #    (digits + min/hr/day only) deliberately does not.
    rel = _REL_WORD_RE.search(lowered)
    if rel:
        raw = rel.group(1).lower()
        amount = _WORD_NUMBERS.get(raw)
        if amount is None:
            try:
                amount = int(raw)
            except ValueError:
                amount = 0
        unit = rel.group(2).lower()
        if unit.startswith(("minute", "min")):
            delta = timedelta(minutes=amount)
        elif unit.startswith(("hour", "hr")):
            delta = timedelta(hours=amount)
        elif unit.startswith("week"):
            delta = timedelta(weeks=amount)
        else:
            delta = timedelta(days=amount)
        return (now + delta).isoformat(timespec="minutes")

    date_part = parse_date(lowered, now=now)
    time_part = _extract_clock_for_wrapper(lowered)

    if date_part is None and time_part is None:
        return ""

    base = date_part if date_part is not None else now.date()
    if time_part is not None:
        hour, minute = time_part
    else:  # date with no time → default morning
        hour, minute = 9, 0

    result = datetime(base.year, base.month, base.day, hour, minute)
    # Bare time with no date that has already passed today → next day.
    if date_part is None and time_part is not None and result <= now:
        result += timedelta(days=1)
    return result.isoformat(timespec="minutes")


def _extract_clock_for_wrapper(lowered: str):
    if _NOON_RE.search(lowered):
        return 12, 0
    if _MIDNIGHT_RE.search(lowered):
        return 0, 0
    return parse_time(lowered, allow_bare=False)
