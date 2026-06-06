"""Intent-recognizer coverage for the Gmail/workspace email tools.

Pins the routing that broke in the 2026-05-25 session (every "check my mail"
fell into chat-mode and the 0.8B model fabricated "Checking your mail..."),
plus the "summarize mails" plural that wrongly hit summarize_file.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

EMAIL_TOOLS = [
    "check_unread_emails", "read_latest_email", "summarize_inbox",
    "daily_briefing", "read_email",
    # decoys that must NOT win for email phrasings:
    "summarize_file",
]


def _make_recognizer(tools=None):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in (tools if tools is not None else EMAIL_TOOLS)}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


@pytest.mark.parametrize("phrase", [
    "check my mail", "Check my mail", "check my mails", "check email",
    "check my emails", "any new mail", "any new mails", "any unread emails",
    "do i have any mail", "how many unread emails",
])
def test_check_unread_routes(phrase):
    r = _make_recognizer().plan(phrase)
    assert r and r[0]["tool"] == "check_unread_emails", f"{phrase!r} -> {r}"


@pytest.mark.parametrize("phrase", [
    "summarize my emails", "summarize mails", "summarize my mails",
    "summarize my inbox", "email summary", "inbox digest",
    "give me a summary of my emails", "what's in my inbox",
])
def test_summarize_inbox_routes(phrase):
    r = _make_recognizer().plan(phrase)
    assert r and r[0]["tool"] == "summarize_inbox", f"{phrase!r} -> {r}"


@pytest.mark.parametrize("phrase", [
    "read my latest email", "read the latest message", "read my most recent mail",
])
def test_read_latest_routes(phrase):
    r = _make_recognizer().plan(phrase)
    assert r and r[0]["tool"] == "read_latest_email", f"{phrase!r} -> {r}"


@pytest.mark.parametrize("phrase", [
    "the battery in my car died",          # 'mail' not present; must not match
    "send a letter to the post office",
])
def test_negatives_do_not_route_to_email(phrase):
    r = _make_recognizer().plan(phrase)
    assert not r or r[0]["tool"] not in {"check_unread_emails", "summarize_inbox"}, f"{phrase!r} -> {r}"


@pytest.mark.parametrize("phrase", [
    "summarize my emails", "summarize mails", "summarize my inbox",
])
def test_summarize_email_beats_research(phrase):
    """Live 2026-05-25 regression: with research_topic registered, the
    research parser's greedy 'summari[sz]e (.+)' poached 'summarize my emails'
    into a web-research run on the topic 'emails'. Email must win."""
    r = _make_recognizer(EMAIL_TOOLS + ["research_topic", "quick_answer"]).plan(phrase)
    assert r and r[0]["tool"] == "summarize_inbox", f"{phrase!r} -> {r}"


def test_explicit_research_still_routes_to_research():
    r = _make_recognizer(EMAIL_TOOLS + ["research_topic"]).plan("quick research on emails")
    assert r and r[0]["tool"] == "research_topic"


def test_email_tools_absent_falls_through():
    """When the workspace plugin isn't loaded, the parser stays harmless."""
    r = _make_recognizer(tools=["summarize_file"]).plan("check my mail")
    assert not r or r[0]["tool"] != "check_unread_emails"
