"""Tests for Batch 2 — Intent Routing & Semantic Boundaries.

Covers:
* `core.text_normalize` — STT typo correction + graceful fuzzy fallback (Issues 2, 8).
* `core.workflow_orchestrator.BrowserMediaWorkflow._is_likely_media_command` —
  rejects conversational sentences that happen to contain a media verb (Issue 9).
* `modules.task_manager.plugin.TaskManagerPlugin._extract_event_title` —
  strips temporal expressions before title extraction so "schedule a meeting
  in 15 minutes" yields title="Meeting" (Issue 11).
* `IntentRecognizer._parse_voice_toggle` — "mode" word is now optional (Issue 2).
* TaskManager list disambiguation — `list_calendar_events` and `list_reminders`
  now own non-overlapping triggers (Issue 7).
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from core.assistant_context import AssistantContext
from core.stores import ContextStore
from core.dialog_state import DialogState
from core.intent_recognizer import IntentRecognizer
from core.router import CommandRouter
from core.text_normalize import fuzzy_command_match, normalize_for_routing
from core.workflow_orchestrator import BrowserMediaWorkflow, WorkflowOrchestrator
# Track 5.2d-retire: the boundary check moved to a module-level helper +
# capability — `BrowserMediaWorkflow._is_likely_media_command` is gone.
from modules.browser_automation.media_helpers import is_likely_media_command
import modules.task_manager.plugin as task_manager_plugin
from modules.task_manager.plugin import TaskManagerPlugin


# ---------------------------------------------------------------------------
# text_normalize
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_corrects_calender_to_calendar(self):
        assert normalize_for_routing("create a calender event") == "create a calendar event"

    def test_corrects_evnet_to_event(self):
        assert normalize_for_routing("add an evnet at 3pm") == "add an event at 3pm"

    def test_preserves_capitalization_of_replacement(self):
        # Leading capital is preserved across the substitution.
        assert normalize_for_routing("Calender today") == "Calendar today"

    def test_leaves_unrelated_text_unchanged(self):
        assert normalize_for_routing("schedule a meeting") == "schedule a meeting"

    def test_handles_empty_input(self):
        assert normalize_for_routing("") == ""
        assert normalize_for_routing(None) is None  # type: ignore[arg-type]

    def test_word_boundary_avoids_corrupting_substrings(self):
        # "calenderness" is invented but the regex must not match a substring
        # of a longer word — only the whole token "calender".
        assert normalize_for_routing("calenderness") == "calenderness"

    def test_cancle_typo_corrected(self):
        # The user log shows "cancle" — should become "cancel".
        assert "cancel" in normalize_for_routing("cancle the next event").lower()


class TestFuzzyMatch:
    def test_drops_modifier_word(self):
        # "set voice to manual" should match "set voice mode to manual"
        # with token_set_ratio. If rapidfuzz isn't installed this returns
        # None — covered by the next test.
        try:
            import rapidfuzz  # noqa: F401
        except ImportError:
            pytest.skip("rapidfuzz not installed — graceful fallback covered separately.")
        match = fuzzy_command_match(
            "set voice to manual",
            ["set voice mode to manual", "open file"],
            threshold=80,
        )
        assert match == "set voice mode to manual"

    def test_returns_none_below_threshold(self):
        try:
            import rapidfuzz  # noqa: F401
        except ImportError:
            pytest.skip("rapidfuzz not installed.")
        assert fuzzy_command_match("hello there friend", ["open browser url"], threshold=85) is None

    def test_graceful_when_rapidfuzz_missing(self, monkeypatch):
        # Simulate the ImportError path. The function must return None,
        # never raise.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "rapidfuzz":
                raise ImportError("simulated absence")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert fuzzy_command_match("anything", ["anything"]) is None


# ---------------------------------------------------------------------------
# BrowserMediaWorkflow — semantic boundary checks (Issue 9)
# ---------------------------------------------------------------------------


class TestMediaBoundary:
    # Track 5.2d-retire: tests now exercise the module-level helper that
    # the deleted `BrowserMediaWorkflow._is_likely_media_command` body
    # was hoisted into. The helper backs both the workflow class's
    # `can_continue` and the `detect_media_command` capability.

    def test_rejects_next_year_is_my_promotion(self):
        # The exact failing utterance from docs/Issues.md logs.
        text = (
            "remember that i work as a backend engineer at acme. "
            "next year is my promotion"
        )
        assert is_likely_media_command(text) is False

    def test_rejects_remember_to_skip_breakfast(self):
        assert is_likely_media_command("remember to skip breakfast tomorrow") is False

    def test_accepts_bare_pause(self):
        assert is_likely_media_command("pause") is True

    def test_accepts_skip_30_seconds(self):
        assert is_likely_media_command("skip 30 seconds") is True

    def test_accepts_short_next_imperative(self):
        assert is_likely_media_command("next") is True

    def test_accepts_music_instead(self):
        assert is_likely_media_command("open it in music instead") is True

    def test_rejects_long_sentence_without_media_noun(self):
        # 8 tokens, no media noun, but contains "play" — still rejected.
        text = "play with the idea of buying a new car"
        assert is_likely_media_command(text) is False

    def test_accepts_long_sentence_with_media_noun(self):
        # 8 tokens with "song" or "video" — accepted.
        text = "skip ahead to the next song in the playlist"
        assert is_likely_media_command(text) is True

    def test_rejects_next_time_phrase(self):
        assert is_likely_media_command("next time we meet") is False

    # Re-open continuations (2026-05-29 bug): "open it again" had no media
    # keyword so can_continue returned False and the turn fell through to
    # open_file ("Which file would you like me to open?").
    def test_accepts_open_it(self):
        assert is_likely_media_command("open it") is True

    def test_accepts_open_it_again(self):
        assert is_likely_media_command("open it again") is True

    def test_accepts_reopen(self):
        assert is_likely_media_command("reopen") is True

    def test_accepts_play_it_again(self):
        assert is_likely_media_command("play it again") is True

    def test_accepts_open_the_video_again(self):
        assert is_likely_media_command("open the video again") is True

    def test_rejects_open_my_budget_file(self):
        # "open it" reopens media, but opening a *named* file must NOT be
        # captured by the media boundary — no pronoun/media-noun reference.
        assert is_likely_media_command("open my budget spreadsheet") is False


# ---------------------------------------------------------------------------
# parse_media_intent — re-open mapping (2026-05-29 bug)
# ---------------------------------------------------------------------------


class TestReopenMediaIntent:
    def _state(self):
        return {"platform": "youtube", "query": "love selfie", "browser_name": "chrome"}

    def test_open_it_replays_remembered_query(self):
        from modules.browser_automation.media_helpers import parse_media_intent
        intent = parse_media_intent("open it", self._state())
        assert intent["action"] == "play"
        assert intent["query"] == "love selfie"
        assert intent["platform"] == "youtube"

    def test_open_it_again_replays(self):
        from modules.browser_automation.media_helpers import parse_media_intent
        intent = parse_media_intent("open it again", self._state())
        assert intent["action"] == "play"
        assert intent["query"] == "love selfie"

    def test_reopen_without_query_just_opens(self):
        from modules.browser_automation.media_helpers import parse_media_intent
        intent = parse_media_intent("reopen", {"platform": "youtube"})
        assert intent["action"] == "open"
        assert intent["platform"] == "youtube"

    def test_play_it_again_not_dropped_by_fresh_play_guard(self):
        from modules.browser_automation.media_helpers import parse_media_intent
        intent = parse_media_intent("play it again", self._state())
        assert intent is not None
        assert intent["action"] == "play"
        assert intent["query"] == "love selfie"

    def test_fresh_play_query_still_returns_none_without_youtube_suffix(self):
        from modules.browser_automation.media_helpers import parse_media_intent
        # A genuinely new search keeps its existing behaviour (handled by the
        # play_youtube capability, not a workflow resume).
        assert parse_media_intent("play despacito", self._state()) is None


# ---------------------------------------------------------------------------
# TaskManager — title extraction (Issue 11)
# ---------------------------------------------------------------------------


@pytest.fixture
def tm_plugin(tmp_path, monkeypatch):
    """Construct a TaskManagerPlugin against a throwaway sqlite."""
    monkeypatch.setattr(task_manager_plugin, "DB_PATH", str(tmp_path / "friday.db"))
    app = SimpleNamespace()
    app.config = SimpleNamespace(get=lambda k, d=None: d)
    app.event_bus = MagicMock()
    app.dialog_state = DialogState()
    app.assistant_context = AssistantContext()
    app.context_store = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    app.session_id = app.context_store.start_session({"source": "tests"})
    app.assistant_context.bind_context_store(app.context_store, app.session_id)
    app.router = CommandRouter(MagicMock())
    app.router.dialog_state = app.dialog_state
    app.router.assistant_context = app.assistant_context
    app.router.context_store = app.context_store
    app.router.session_id = app.session_id
    app.workflow_orchestrator = WorkflowOrchestrator(app)
    app.router.workflow_orchestrator = app.workflow_orchestrator
    app.emit_assistant_message = MagicMock()
    return TaskManagerPlugin(app)


class TestTitleExtraction:
    def test_meeting_in_15_minutes_extracts_meeting(self, tm_plugin):
        title = tm_plugin._extract_event_title("schedule a meeting in 15 minutes")
        assert title.lower() == "meeting"

    def test_meeting_titled_q4_review(self, tm_plugin):
        title = tm_plugin._extract_event_title("schedule a meeting titled Q4 review at 3pm")
        assert "q4 review" in title.lower()

    def test_appointment_tomorrow_extracts_appointment(self, tm_plugin):
        # Temporal "tomorrow" stripped; bare "schedule an appointment" → "Appointment".
        title = tm_plugin._extract_event_title("book an appointment tomorrow")
        assert title.lower() == "appointment"

    def test_strip_temporal_removes_in_n_minutes(self, tm_plugin):
        assert tm_plugin._strip_temporal_expressions("call john in 30 minutes").strip() == "call john"

    def test_strip_temporal_removes_at_time(self, tm_plugin):
        assert "3pm" not in tm_plugin._strip_temporal_expressions("standup at 3pm").lower()


# ---------------------------------------------------------------------------
# Voice toggle — "mode" optional (Issue 2)
# ---------------------------------------------------------------------------


class TestVoiceToggle:
    def setup_method(self):
        # IntentRecognizer needs a router-shape object to read _tools_by_name from.
        router = SimpleNamespace(_tools_by_name={"set_voice_mode": {}})
        self.ir = IntentRecognizer(router)

    def test_set_voice_to_manual_matches(self):
        result = self.ir._parse_voice_toggle(
            "set voice to manual", "set voice to manual", {}
        )
        assert result is not None
        assert result["tool"] == "set_voice_mode"
        assert result["args"]["mode"] == "manual"

    def test_set_voice_mode_to_manual_still_matches(self):
        # Regression — the original phrasing must still work.
        result = self.ir._parse_voice_toggle(
            "set voice mode to manual", "set voice mode to manual", {}
        )
        assert result is not None
        assert result["args"]["mode"] == "manual"

    def test_switch_voice_on_demand(self):
        result = self.ir._parse_voice_toggle(
            "switch voice on demand", "switch voice on demand", {}
        )
        assert result is not None
        assert result["args"]["mode"] == "on_demand"


# ---------------------------------------------------------------------------
# Reminder listing (local calendar events were removed 2026-05-31; calendar
# events live in Google Calendar now, so list_calendar_events is gone).
# ---------------------------------------------------------------------------


class TestListReminders:
    def test_handle_list_reminders_returns_reminders(self, tm_plugin):
        from datetime import datetime, timedelta
        soon = datetime.now() + timedelta(hours=1)
        tm_plugin.create_calendar_event("Drink water", soon, event_type="reminder")
        # A legacy calendar_event row must NOT surface in the reminder list.
        tm_plugin.create_calendar_event("Q4 review", soon + timedelta(hours=2), event_type="calendar_event")

        reminders = tm_plugin.handle_list_reminders("list reminders", {})

        assert "Drink water" in reminders
        assert "Q4 review" not in reminders

    def test_empty_reminders_message(self, tm_plugin):
        reminders = tm_plugin.handle_list_reminders("list reminders", {})
        assert "reminders" in reminders.lower()
