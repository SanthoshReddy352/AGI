import re
import threading
import sqlite3
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from core.plugin_manager import FridayPlugin
from core.logger import logger
# Track launch-hardening §5.4 Step 1: the datetime machinery that used to be
# defined inline here (regex/word tables + _parse_* methods) now lives as pure
# functions in core.planning.slot_extractors. The handler methods below are
# thin delegators that pass a patchable `now=` so behaviour is unchanged.
from core.planning.slot_extractors import (
    apply_meridian,
    combine_date_time,
    date_from_month_match,
    parse_date,
    parse_datetime_parts,
    parse_time,
    parse_word_time,
)


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "friday.db")


def _ensure_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            remind_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'scheduled',
            created_at TEXT NOT NULL,
            fired_at TEXT,
            type TEXT NOT NULL DEFAULT 'reminder'
        )
    """)
    # Migrate existing rows that pre-date the type column
    try:
        conn.execute("ALTER TABLE calendar_events ADD COLUMN type TEXT NOT NULL DEFAULT 'reminder'")
    except Exception:
        pass  # column already exists
    conn.commit()
    conn.close()


class TaskManagerPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "TaskManager"
        self._reminder_timers = {}
        self._system_notification_event_ids = set()
        self.app.task_manager = self
        _ensure_db()
        self.on_load()
        self._cleanup_completed_calendar_events()
        self._load_pending_calendar_events()

    def on_load(self):
        self.app.register_capability({
            "name": "set_reminder",
            "description": (
                "Set a personal time-based reminder that FRIDAY will announce at a future time. "
                "Use for 'remind me to [action]' phrases — e.g. 'remind me to call John at 3pm', "
                "'remind me in 10 minutes to take a break'. "
                "Not for structured meetings or appointments with explicit event titles."
            ),
            "parameters": {
                "message": "string – what to remind the user about",
                "minutes": "integer – optional number of minutes from now to trigger the reminder",
                "datetime": "string – optional exact or natural date and time for the reminder"
            },
            "context_terms": ["remind me", "reminder", "remind me to", "set a reminder"],
        }, self.handle_set_reminder)

        self.app.register_capability({
            "name": "save_note",
            "description": "Save a quick note or piece of text for later retrieval.",
            "parameters": {
                "content": "string – the text content to save as a note"
            }
        }, self.handle_save_note)

        self.app.register_capability({
            "name": "read_notes",
            "description": "Read back the most recent saved notes.",
            "parameters": {}
        }, self.handle_read_notes)

        # NOTE: the local calendar-EVENT capabilities (create/move/cancel/
        # list_calendar_events, plus the never-live schedule_calendar_event +
        # create_calendar_event.yaml template) were removed 2026-05-31 — the
        # WorkspaceAgent's Google Calendar capabilities now own calendar events
        # entirely. TaskManager keeps only the reminder family (set_reminder /
        # list_reminders / create_reminder) which is a separate local feature
        # with local desktop/OS notifications. (Reminders are no longer
        # voice-cancellable/movable — see docs/launch_hardening_status.md §5.4.)
        self.app.register_capability({
            "name": "list_reminders",
            "description": "Read upcoming reminders with their scheduled date and time.",
            "parameters": {
                "limit": "integer – optional number of upcoming reminders to read"
            },
            "aliases": ["my reminders", "upcoming reminders", "list reminders", "show reminders"],
            "patterns": [
                r"\b(?:what(?:'s| is)?|read|show|list|brief)\s+(?:my\s+|the\s+)?reminders\b",
                r"\b(?:upcoming|scheduled)\s+reminders\b",
                r"\bwhat\s+(?:are\s+)?my\s+reminders\b",
            ],
            "context_terms": ["reminders", "my reminders"],
        }, self.handle_list_reminders)

        self.app.register_capability({
            "name": "get_time",
            "description": "Tell the user the current local time.",
            "parameters": {}
        }, lambda t, a: self._get_time())

        self.app.register_capability({
            "name": "get_date",
            "description": "Tell the user today's date.",
            "parameters": {}
        }, lambda t, a: self._get_date())

        # ------------------------------------------------------------------
        # Template-internal capabilities for the live `set_reminder` slot-fill
        # template (launch-hardening §5.4 Step 3). Intentionally NOT given an
        # IntentRecognizer pattern: the user-facing "remind me to…" phrasing
        # routes to set_reminder, and these run only as resolved template steps.
        # ------------------------------------------------------------------
        self.app.register_capability({
            "name": "extract_reminder_date",
            "description": (
                "Internal slot extractor: parse a calendar date from text and "
                "return an ISO date (YYYY-MM-DD). Backs the set_reminder "
                "template's date ask-step; not for direct user routing."
            ),
            "parameters": {"text": "string – text containing a date phrase"},
        }, self.handle_extract_reminder_date)

        self.app.register_capability({
            "name": "extract_reminder_time",
            "description": (
                "Internal slot extractor: parse a clock time from text and "
                "return HH:MM (bare hours allowed). Backs the set_reminder "
                "template's time ask-step; not for direct user routing."
            ),
            "parameters": {"text": "string – text containing a time phrase"},
        }, self.handle_extract_reminder_time)

        self.app.register_capability({
            "name": "create_reminder",
            "description": (
                "Internal: schedule a reminder from already-resolved slots "
                "(message + ISO/NL datetime). Backs the set_reminder workflow "
                "template; wraps the shared scheduling core."
            ),
            "parameters": {
                "message": "string – what to remind the user about",
                "datetime": "string – ISO timestamp or natural-language date/time",
                "minutes": "integer – optional minutes from now",
            },
        }, self.handle_create_reminder)

        logger.info("TaskManagerPlugin loaded.")

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    def handle_set_reminder(self, text, args):
        # launch-hardening §5.4 Step 3: the reminder slot-fill is now driven by
        # the `set_reminder` YAML template (the ReminderWorkflow shim is
        # retired). First-turn parsing stays here (rich `_parse_reminder_request`
        # preserved); a complete time schedules immediately, otherwise we hand
        # off to the template's date→time slot-fill loop, seeding any half the
        # first turn already gave.
        args = dict(args or {})
        raw_text = str(text or "")
        parsed = self._parse_reminder_request(raw_text, args)
        message = str(parsed.get("message") or "").strip()
        if not message:
            return "What would you like me to remind you about?"

        remind_at = parsed.get("remind_at") or self._combine_date_time(
            parsed.get("date"), parsed.get("time"),
        )
        if remind_at:
            return self._schedule_reminder(message, remind_at)

        initial = {"message": message}
        if parsed.get("date"):
            initial["date"] = parsed["date"]
        if parsed.get("time"):
            initial["time"] = parsed["time"]
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        session_id = getattr(self.app, "session_id", None)
        if orchestrator is None or not session_id:
            # Minimal test host with no orchestrator — degrade to a direct ask.
            return "When should I remind you? Please mention the date and time to remind you."
        result = orchestrator.start_template_slot_fill("set_reminder", session_id, initial)
        return result.response

    def _schedule_reminder(self, message, remind_at):
        """Validate + persist a reminder and return the spoken confirmation (or
        a past-time message). Shared by the first-turn fast path and the
        template-backed `create_reminder` capability so the wording stays
        identical to the pre-cutover behaviour. Uses the low-level
        `_create_calendar_event` (same as the retired ReminderWorkflow path) —
        the past-time guard lives here, so the public wrapper's validation is
        unnecessary."""
        if not remind_at:
            return "When should I remind you? Please mention a date and time."
        if remind_at <= datetime.now():
            return "That time has already passed. Please mention a future date and time."
        self._create_calendar_event(message, remind_at, event_type="reminder")
        return self._format_reminder_confirmation(message, remind_at)

    # ------------------------------------------------------------------
    # Template-internal handlers (launch-hardening §5.4 Steps 2-3). They take
    # already-resolved slots and wrap the unchanged scheduling core
    # (`create_calendar_event`) — no slot-fill state, no re-asking.
    # ------------------------------------------------------------------
    def handle_extract_reminder_date(self, text, args):
        """Return an ISO date ("YYYY-MM-DD") parsed from the slot text, or "".
        Backs the set_reminder template's date ask-step."""
        args = dict(args or {})
        source = str(args.get("text") or text or "").lower()
        value = self._parse_date(source)
        return value.isoformat() if value else ""

    def handle_extract_reminder_time(self, text, args):
        """Return "HH:MM" parsed from the slot text, or "". `allow_bare=True`
        because the template only asks this once it explicitly wants a time, so
        a lone "four" reads as 4 o'clock (preserving the pre-cutover behaviour).
        Backs the set_reminder template's time ask-step."""
        args = dict(args or {})
        source = str(args.get("text") or text or "").lower()
        value = self._parse_time(source, allow_bare=True)
        return f"{value[0]:02d}:{value[1]:02d}" if value else ""

    def handle_create_reminder(self, text, args):
        args = dict(args or {})
        message = str(args.get("message") or "").strip()
        if not message:
            return "What would you like me to remind you about?"
        remind_at = self._resolve_slot_datetime(args, text)
        if not remind_at:
            return "When should I remind you? Please mention a date and time."
        return self._schedule_reminder(message, remind_at)

    def _resolve_slot_datetime(self, args, text=""):
        """Resolve a datetime from already-resolved template slots. A
        ``date`` + ``time`` pair (the set_reminder template's two ask-steps) is
        combined first — preserving the ambiguous-morning→afternoon bump; then
        an ISO/NL ``datetime`` slot; then NL parsing of the slot + raw text;
        then a ``minutes`` offset. Returns ``None`` on no match."""
        date_part = str(args.get("date") or "").strip()
        time_part = str(args.get("time") or "").strip()
        if date_part and time_part:
            combined = self._combine_date_time(date_part, time_part)
            if combined:
                return combined
        raw = str(args.get("datetime") or "").strip()
        if raw:
            iso = self._parse_iso_datetime(raw)
            if iso:
                return iso
        combined = " ".join(part for part in [str(text or ""), raw] if part).strip()
        if combined:
            parsed = self._parse_datetime_parts(combined)
            candidate = parsed.get("remind_at") or self._combine_date_time(
                parsed.get("date"), parsed.get("time"),
            )
            if candidate:
                return candidate
        minutes = args.get("minutes")
        if minutes is not None:
            try:
                return datetime.now() + timedelta(minutes=float(minutes))
            except Exception:
                return None
        return None

    def handle_save_note(self, text, args):
        content = args.get("content", "").strip()
        if not content:
            # Try to extract from raw text after "save note:" or "note:"
            match = re.search(r'(?:save\s+note|note|remember)[:\s]+(.+)', text, re.IGNORECASE)
            content = match.group(1).strip() if match else ""
        if not content:
            return "What would you like me to note down?"

        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(
                "INSERT INTO notes (content, created_at) VALUES (?, ?)",
                (content, datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            logger.info(f"[TaskManager] Note saved: '{content[:50]}'")
        except Exception as e:
            logger.error(f"[TaskManager] Failed to save note: {e}")
            return "I couldn't save that note. Please try again."

        # Cross-write to the memory layer so the note is queryable through the
        # same recall pipeline as other facts. Without this, notes live in a
        # separate SQLite table that semantic_recall / Mem0 never see.
        try:
            session_id = getattr(self.app, "session_id", None)
            memory = getattr(self.app, "memory_service", None) or getattr(self.app, "context_store", None)
            if session_id and memory and hasattr(memory, "store_memory_item"):
                memory.store_memory_item(
                    session_id=session_id,
                    content=content,
                    memory_type="episodic",
                    sensitivity="explicit_user",
                    metadata={"role": "user", "source": "save_note"},
                )
        except Exception as exc:
            logger.debug("[TaskManager] note->memory mirror failed (non-fatal): %s", exc)

        return f"Note saved: \"{content}\""

    def handle_read_notes(self, text, args):
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT content, created_at FROM notes ORDER BY id DESC LIMIT 5"
            ).fetchall()
            conn.close()

            if not rows:
                return "You don't have any saved notes yet."

            lines = ["Here are your recent notes:"]
            for i, (content, created_at) in enumerate(rows, 1):
                # Format: "Apr 12, 01:30"
                try:
                    dt = datetime.fromisoformat(created_at)
                    time_str = dt.strftime("%b %d, %H:%M")
                except Exception:
                    time_str = created_at[:16]
                lines.append(f"{i}. [{time_str}] {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"[TaskManager] Failed to read notes: {e}")
            return "I couldn't retrieve your notes right now."

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fire_reminder(self, message):
        logger.info(f"[TaskManager] Firing reminder: '{message}'")
        response = f"Reminder: {message}"
        self.app.emit_assistant_message(f"⏰ {response}", source="reminder", spoken_text=response)

    def _fire_calendar_event(self, event_id, message, event_type="reminder"):
        logger.info("[TaskManager] Firing %s %s: '%s'", event_type, event_id, message)
        self._reminder_timers.pop(int(event_id), None)
        fired_at = datetime.now().isoformat(timespec="seconds")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("[TaskManager] Failed to remove completed event: %s", exc)
        payload = {"id": event_id, "title": message, "fired_at": fired_at, "type": event_type}
        self.app.event_bus.publish("calendar_event_fired", payload)
        if event_type == "calendar_event":
            notif_title = "FRIDAY Calendar"
            response = f"'{message}' is starting now."
            source = "calendar"
        else:
            notif_title = "FRIDAY Reminder"
            response = f"Reminder: {message}"
            source = "reminder"
        if event_id not in self._system_notification_event_ids:
            self._send_desktop_notification(notif_title, message)
        self.app.emit_assistant_message(f"⏰ {response}", source=source, spoken_text=response)

    def _parse_reminder_text(self, text):
        """Extract message and minutes from natural language fallback."""
        text_lower = text.lower()
        # Extract minutes: "in X minutes" or "in X min"
        min_match = re.search(r'in\s+(\d+(?:\.\d+)?)\s+(?:minutes?|mins?)', text_lower)
        minutes = float(min_match.group(1)) if min_match else None

        # Extract the reminder subject
        # Pattern: "remind me to <X> in N minutes" → capture <X>
        msg_match = re.search(
            r'remind\s+(?:me\s+)?(?:to\s+)?(.+?)(?:\s+in\s+\d+\s+(?:minutes?|mins?))?$',
            text_lower
        )
        message = msg_match.group(1).strip() if msg_match else ""
        # Clean up trailing "in X min" if it leaked into the message
        message = re.sub(r'\s+in\s+\d+\s+(?:minutes?|mins?)$', '', message).strip()

        return message, minutes

    def _parse_reminder_request(self, text, args=None):
        args = dict(args or {})
        raw_text = str(text or "")
        message = str(args.get("message") or "").strip() or self._extract_reminder_message(raw_text)
        parsed = self._parse_datetime_parts(" ".join(part for part in [raw_text, str(args.get("datetime") or "")] if part))
        minutes = args.get("minutes")
        if minutes is not None and not parsed.get("remind_at"):
            try:
                parsed["remind_at"] = datetime.now() + timedelta(minutes=float(minutes))
            except Exception:
                pass
        parsed["message"] = message
        return parsed

    # ------------------------------------------------------------------
    # Datetime parsing — thin delegators to core.planning.slot_extractors
    # (launch-hardening §5.4 Step 1). `now=datetime.now()` is resolved here
    # via the plugin-module `datetime`, which the tests monkeypatch, so the
    # shared pure functions stay deterministic under a fixed clock.
    # ------------------------------------------------------------------
    def _parse_datetime_parts(self, text, allow_bare_time=False):
        return parse_datetime_parts(
            text, allow_bare_time=allow_bare_time, now=datetime.now(),
        )

    def _parse_date(self, lowered):
        return parse_date(lowered, now=datetime.now())

    def _date_from_month_match(self, day_text, month_text, year_text, today):
        return date_from_month_match(day_text, month_text, year_text, today)

    def _parse_time(self, lowered, allow_bare=False):
        return parse_time(lowered, allow_bare=allow_bare)

    def _parse_word_time(self, lowered, allow_bare=False):
        return parse_word_time(lowered, allow_bare=allow_bare)

    def _apply_meridian(self, hour, minute, meridian):
        return apply_meridian(hour, minute, meridian)

    def _combine_date_time(self, date_text, time_text):
        return combine_date_time(date_text, time_text, now=datetime.now())

    def _parse_iso_datetime(self, value):
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _extract_reminder_message(self, text):
        match = re.search(r"\bremind\s+(?:me\s+)?(?:to\s+|about\s+)?(.+)", text, re.IGNORECASE)
        if not match:
            match = re.search(r"\bset\s+(?:a\s+)?reminder\s+(?:to\s+|about\s+)?(.+)", text, re.IGNORECASE)
        message = match.group(1).strip(" .!?") if match else ""
        if not message:
            return ""
        temporal_markers = (
            r"\s+\bin\s+\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?)\b",
            r"\s+\b(?:today|tomorrow)\b",
            r"\s+\b(?:on|at|by)\s+\d",
            r"\s+\b(?:on|at|by|next)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\s+\b(?:on|at|by)\s+(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
            r"\s+\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
        )
        for pattern in temporal_markers:
            found = re.search(pattern, message, re.IGNORECASE)
            if found:
                message = message[:found.start()].strip(" .!?")
                break
        message = re.sub(r"\s+\b(?:at|on|by|in|for)\b$", "", message, flags=re.IGNORECASE).strip(" .!?")
        return message

    def _create_calendar_event(self, message, remind_at, event_type="reminder"):
        event_id = self._insert_calendar_event(message, remind_at, event_type=event_type)
        if self._schedule_system_notification(event_id, message, remind_at):
            self._system_notification_event_ids.add(event_id)
        self._schedule_calendar_timer(event_id, message, remind_at, event_type=event_type)
        payload = {
            "id": event_id,
            "title": message,
            "remind_at": remind_at.isoformat(timespec="seconds"),
            "status": "scheduled",
            "type": event_type,
        }
        self.app.event_bus.publish("calendar_event_created", payload)
        return event_id

    def create_calendar_event(self, message, remind_at, event_type="reminder"):
        message = str(message or "").strip()
        if not message:
            return False, "Please enter a title."
        if not isinstance(remind_at, datetime):
            return False, "Please choose a valid date and time."
        if remind_at <= datetime.now():
            return False, "Please choose a future date and time."
        event_id = self._create_calendar_event(message, remind_at, event_type=event_type)
        return True, {
            "id": event_id,
            "title": message,
            "remind_at": remind_at.isoformat(timespec="seconds"),
            "status": "scheduled",
            "type": event_type,
        }

    def delete_calendar_event(self, event_id):
        try:
            event_id = int(event_id)
        except Exception:
            return False, "Please select a reminder to delete."

        timer = self._reminder_timers.pop(event_id, None)
        if timer:
            timer.cancel()
        self._cancel_system_notification(event_id)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.execute("DELETE FROM calendar_events WHERE id = ?", (event_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            conn.close()
        except Exception as exc:
            logger.warning("[TaskManager] Failed to delete reminder: %s", exc)
            return False, "I couldn't delete that reminder."

        if not deleted:
            return False, "That reminder was already completed or deleted."
        self.app.event_bus.publish("calendar_event_deleted", {"id": event_id})
        return True, "Reminder deleted."

    def _insert_calendar_event(self, message, remind_at, event_type="reminder"):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "INSERT INTO calendar_events (title, remind_at, status, created_at, type) VALUES (?, ?, 'scheduled', ?, ?)",
            (message, remind_at.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"), event_type),
        )
        conn.commit()
        event_id = int(cursor.lastrowid)
        conn.close()
        return event_id

    def _schedule_calendar_timer(self, event_id, message, remind_at, event_type="reminder"):
        seconds = max(0.1, (remind_at - datetime.now()).total_seconds())
        timer = threading.Timer(seconds, self._fire_calendar_event, args=[event_id, message, event_type])
        timer.daemon = True
        timer.start()
        self._reminder_timers[int(event_id)] = timer

    def _load_pending_calendar_events(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT id, title, remind_at, type FROM calendar_events WHERE status = 'scheduled'"
            ).fetchall()
            conn.close()
        except Exception as exc:
            logger.warning("[TaskManager] Failed to load reminders: %s", exc)
            return
        now = datetime.now()
        for event_id, title, remind_at_text, event_type in rows:
            remind_at = self._parse_iso_datetime(remind_at_text)
            if not remind_at:
                continue
            if remind_at <= now:
                self._fire_calendar_event(event_id, title, event_type or "reminder")
            else:
                if self._schedule_system_notification(event_id, title, remind_at):
                    self._system_notification_event_ids.add(event_id)
                self._schedule_calendar_timer(event_id, title, remind_at, event_type=event_type or "reminder")

    def _cleanup_completed_calendar_events(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM calendar_events WHERE status != 'scheduled' OR fired_at IS NOT NULL")
            conn.commit()
            conn.close()
        except Exception as exc:
            logger.warning("[TaskManager] Failed to clean completed reminders: %s", exc)

    def list_calendar_events(self, limit=20):
        try:
            conn = sqlite3.connect(DB_PATH)
            rows = conn.execute(
                "SELECT id, title, remind_at, status, type FROM calendar_events ORDER BY remind_at ASC LIMIT ?",
                (int(limit),),
            ).fetchall()
            conn.close()
            return [
                {"id": row[0], "title": row[1], "remind_at": row[2], "status": row[3], "type": row[4] or "reminder"}
                for row in rows
            ]
        except Exception:
            return []

    def handle_list_reminders(self, text, args):
        """List upcoming reminders. (Local calendar events were removed
        2026-05-31 — calendar events live in Google Calendar now.)"""
        limit = int((args or {}).get("limit") or 5)
        return self._render_upcoming(limit)

    def _render_upcoming(self, limit):
        """Format the upcoming local reminders. Only ``type='reminder'`` rows
        are produced now; any legacy ``calendar_event`` rows are ignored."""
        all_events = [e for e in self.list_calendar_events(limit=50) if e.get("status") == "scheduled"]
        now = datetime.now()
        matched = []
        for event in all_events:
            if event.get("type") != "reminder":
                continue
            remind_at = self._parse_iso_datetime(event.get("remind_at"))
            if remind_at and remind_at >= now:
                matched.append((remind_at, event))
        matched.sort(key=lambda x: x[0])

        if not matched:
            return "You have no upcoming reminders."

        lines = ["Here are your reminders:"]
        for remind_at, event in matched[:max(1, limit)]:
            lines.append(f"  {self._format_event_time(remind_at)}: {event.get('title', '')}")
        return "\n".join(lines)

    def get_unfinished_task_briefing(self, limit=5):
        all_events = [e for e in self.list_calendar_events(limit=50) if e.get("status") == "scheduled"]
        now = datetime.now()
        reminders = []
        for event in all_events:
            if event.get("type") != "reminder":
                continue
            remind_at = self._parse_iso_datetime(event.get("remind_at"))
            if remind_at and remind_at >= now:
                reminders.append((remind_at, event))
        reminders.sort(key=lambda x: x[0])

        if not reminders:
            return "You have no upcoming reminders."

        noun = "reminder" if len(reminders) == 1 else "reminders"
        lines = [f"You have {len(reminders)} unfinished {noun}."]
        for remind_at, event in reminders[:max(1, int(limit))]:
            lines.append(f"{self._format_event_time(remind_at)}: {event.get('title', '')}")
        if len(reminders) > limit:
            lines.append(f"And {len(reminders) - limit} more.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Shared title / temporal-text helpers. Retained after the local
    # calendar-event capabilities were removed (2026-05-31) because the
    # WorkspaceAgent (Google Calendar) path reuses them for event-summary
    # extraction — see workspace_agent.extension._extract_summary_from_text.
    # ------------------------------------------------------------------
    def _extract_event_title(self, text):
        # Issue 11: extract temporal expressions FIRST so the residue is
        # what title patterns operate on. Otherwise "schedule a meeting
        # in 15 minutes" parses title="in 15 minutes" — the greedy `(.+)`
        # captures the whole temporal clause.
        residue = self._strip_temporal_expressions(text)
        for pattern in (
            r"\b(?:create|add|schedule|set\s+up|book)\s+(?:a\s+|an\s+)?(?:calendar\s+)?(?:event|meeting|reminder|appointment)\s+(?:titled|called|named)\s+(.+)",
            r"\b(?:create|add|schedule|set\s+up|book)\s+(?:a\s+|an\s+)?(?:calendar\s+)?(?:event|meeting|reminder|appointment)\s+(?:for\s+|to\s+|about\s+)?(.+)",
            r"\b(?:add\s+to\s+(?:my\s+)?calendar)\s*[:\-]?\s*(.+)",
        ):
            match = re.search(pattern, residue, re.IGNORECASE)
            if not match:
                continue
            title = match.group(1).strip(" .!?")
            # Defensive — re-strip suffix in case any temporal slipped through.
            title = self._strip_temporal_suffix(title)
            if title:
                return title
        # Fallback: temporal stripped, no descriptive content captured.
        # Use the action noun itself — "schedule a meeting" → "Meeting".
        bare = re.search(
            r"\b(?:create|add|schedule|set\s+up|book)\s+(?:a\s+|an\s+)?(?:calendar\s+)?"
            r"(meeting|appointment|event|reminder|standup|call|sync|review|check-?in)\b",
            residue,
            re.IGNORECASE,
        )
        if bare:
            return bare.group(1).capitalize()
        return ""

    def _strip_temporal_expressions(self, text):
        """Remove temporal expressions from anywhere in ``text`` and collapse
        whitespace. Mirror of ``_strip_temporal_suffix`` but anchorless,
        used by ``_extract_event_title`` to isolate the non-temporal
        residue before title patterns run (Issue 11).
        """
        if not text:
            return text
        cleaned = text
        patterns = (
            r"\bin\s+\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?)\b",
            r"\b(?:today|tomorrow|tonight)\b",
            r"\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.?|p\.m\.?)?\b",
            r"\bon\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)\b",
            r"\bthis\s+(?:morning|afternoon|evening|weekend)\b",
            r"\bfrom\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+to\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b",
        )
        for pattern in patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _strip_temporal_suffix(self, text):
        if not text:
            return text
        cleaned = text
        for pattern in (
            r"\s+\bin\s+\d+(?:\.\d+)?\s*(?:minutes?|mins?|hours?|hrs?|days?)\b.*$",
            r"\s+\b(?:today|tomorrow|tonight)\b.*$",
            r"\s+\bat\s+\d.*$",
            r"\s+\bon\s+\d.*$",
            r"\s+\bon\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b.*$",
            r"\s+\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)\b.*$",
            r"\s+\bfrom\s+\d.*$",
        ):
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" .!?")

    def _format_event_time(self, remind_at):
        today = datetime.now().date()
        if remind_at.date() == today:
            day = "Today"
        elif remind_at.date() == today + timedelta(days=1):
            day = "Tomorrow"
        else:
            day = remind_at.strftime("%A, %B %d, %Y")
        return f"{day} at {remind_at.strftime('%I:%M %p').lstrip('0')}"

    def _send_desktop_notification(self, title, body):
        if os.name == "nt" or not shutil.which("notify-send"):
            return False
        try:
            subprocess.run(
                ["notify-send", "-a", "FRIDAY", "-u", "normal", title, body],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            return True
        except Exception as exc:
            logger.warning("[TaskManager] Desktop notification failed: %s", exc)
            return False

    def _schedule_system_notification(self, event_id, message, remind_at):
        if os.name == "nt" or remind_at <= datetime.now():
            return False
        if not shutil.which("systemd-run") or not shutil.which("notify-send"):
            return False

        unit = f"friday-reminder-{int(event_id)}"
        on_calendar = remind_at.strftime("%Y-%m-%d %H:%M:%S")
        code = (
            "import datetime, sqlite3, subprocess, sys;"
            "db=sys.argv[1]; event_id=int(sys.argv[2]); title=sys.argv[3];"
            "conn=sqlite3.connect(db);"
            "conn.execute('DELETE FROM calendar_events WHERE id = ?', (event_id,));"
            "conn.commit(); conn.close();"
            "subprocess.run(['notify-send', '-a', 'FRIDAY', '-u', 'normal', 'FRIDAY Reminder', title], check=False)"
        )
        command = [
            "systemd-run",
            "--user",
            "--unit",
            unit,
            "--description",
            f"FRIDAY reminder {event_id}",
            "--on-calendar",
            on_calendar,
            "--collect",
            sys.executable,
            "-c",
            code,
            DB_PATH,
            str(event_id),
            str(message),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
            if result.returncode == 0:
                logger.info("[TaskManager] Scheduled system notification unit %s for %s", unit, on_calendar)
                return True
            stderr = (result.stderr or result.stdout or "").strip()
            lowered = stderr.lower()
            if "already exists" in lowered or "already loaded" in lowered or "fragment file" in lowered:
                logger.info("[TaskManager] System notification unit %s already exists.", unit)
                return True
            logger.warning("[TaskManager] Failed to schedule system notification: %s", stderr)
            return False
        except Exception as exc:
            logger.warning("[TaskManager] Failed to schedule system notification: %s", exc)
            return False

    def _cancel_system_notification(self, event_id):
        if os.name == "nt" or not shutil.which("systemctl"):
            return
        unit_base = f"friday-reminder-{int(event_id)}"
        try:
            subprocess.run(
                ["systemctl", "--user", "stop", f"{unit_base}.timer", f"{unit_base}.service"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except Exception as exc:
            logger.debug("[TaskManager] Failed to cancel system notification unit %s: %s", unit_base, exc)

    def _format_reminder_confirmation(self, message, remind_at):
        time_str = remind_at.strftime("%I:%M %p").lstrip("0")
        when = remind_at.strftime("%A, %B %d, %Y") + " at " + time_str
        return f"Got it! I'll remind you to {message} on {when}."

    def _get_time(self):
        now = datetime.now()
        return f"The current time is {now.strftime('%I:%M %p')}."

    def _get_date(self):
        now = datetime.now()
        return f"Today is {now.strftime('%A, %B %d, %Y')}."


def setup(app):
    return TaskManagerPlugin(app)
