"""IntentRecognizer coverage for media re-open continuations (2026-05-29).

The v2 turn path catches "open it again" / "reopen" via the browser_media
workflow's `can_continue` (handled before intent classification). These tests
pin the deterministic SAFETY NET in `IntentRecognizer._parse_browser_media`
for the v1 path (which has no workflow hook) — without it, "open it" falls
through to `open_file` ("Which file would you like me to open?").

Per CLAUDE.md: every media follow-up must have a robust deterministic pattern;
never leave it at the mercy of the small chat model.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.dialog_state import DialogState


BROWSER_TOOLS = ["play_youtube", "play_youtube_music", "open_browser_url",
                 "browser_media_control", "open_file"]


def _make_recognizer(active_workflow, tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else BROWSER_TOOLS)}
    store = MagicMock()
    store.get_active_workflow.return_value = active_workflow
    router.context_store = store
    router.session_id = "s1"
    router.dialog_state = DialogState()
    return IntentRecognizer(router)


_ACTIVE = {"query": "love selfie", "platform": "youtube", "browser_name": "chrome"}


@pytest.mark.parametrize("phrase", [
    "open it",
    "open it again",
    "reopen",
    "reopen it",
    "play it again",
    "resume that",
    "open the video again",
])
def test_reopen_with_query_routes_to_play_youtube(phrase):
    ir = _make_recognizer(dict(_ACTIVE))
    result = ir.plan(phrase)
    assert result, f"No plan for: {phrase!r}"
    assert result[0]["tool"] == "play_youtube", f"{phrase!r} → {result[0]['tool']}"
    assert result[0]["args"]["query"] == "love selfie"


def test_reopen_music_platform_routes_to_play_youtube_music():
    ir = _make_recognizer({"query": "lofi beats", "platform": "youtube_music", "browser_name": "chrome"})
    result = ir.plan("play it again")
    assert result and result[0]["tool"] == "play_youtube_music"
    assert result[0]["args"]["query"] == "lofi beats"


def test_reopen_without_remembered_query_opens_url():
    ir = _make_recognizer({"platform": "youtube", "browser_name": "chrome"})
    result = ir.plan("reopen")
    assert result and result[0]["tool"] == "open_browser_url"
    assert result[0]["args"]["url"] == "https://www.youtube.com"


def test_open_it_without_active_workflow_does_not_become_media():
    # No active browser_media workflow → must NOT route to a media tool.
    ir = _make_recognizer(None)
    result = ir.plan("open it")
    tool = result[0]["tool"] if result else None
    assert tool != "play_youtube"
    assert tool != "open_browser_url"


def test_named_file_open_not_poached_even_with_active_workflow():
    # A genuinely-named file open must NOT be captured by media re-open even
    # while a browser_media workflow is active. (It may then route to open_file
    # or fall through to the planner — either is fine; it just isn't media.)
    ir = _make_recognizer(dict(_ACTIVE))
    result = ir.plan("open my budget spreadsheet")
    tool = result[0]["tool"] if result else None
    assert tool not in ("play_youtube", "play_youtube_music", "open_browser_url")
