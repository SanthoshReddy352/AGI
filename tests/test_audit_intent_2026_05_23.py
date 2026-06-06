"""Intent-coverage audit follow-up (2026-05-23 evening session).

Repros for live-session bugs:
  • "What's on my list today?"        → was chat (LLM fabricated a pep talk)
  • "scan 192.168.1.50 for open ports" → was launch_app('ports') (404)
  • "ping sweep 10.0.0.0/24"           → was chat
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_recognizer(tools: list[str]):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in tools}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


# ── Calendar / reminder listing ────────────────────────────────────────────


@pytest.mark.parametrize("phrase", [
    "What's on my list today?",
    "what's on my schedule today",
    "what's my agenda today",
    "what do I have today",
    "what do I have going on today",
    "show me my agenda today",
    "show my schedule for today",
    "today's agenda",
    "today's events",
])
def test_calendar_today_listing(phrase):
    ir = _make_recognizer(["get_calendar_today"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "get_calendar_today"


@pytest.mark.parametrize("phrase", [
    "what's on my schedule this week",
    "this week's agenda",
    "show me my calendar this week",
    "show me my schedule for the week",
])
def test_calendar_week_listing(phrase):
    ir = _make_recognizer(["get_calendar_week"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "get_calendar_week"


@pytest.mark.parametrize("phrase", [
    "show my reminders",
    "list my reminders",
    "what are my reminders",
    "what reminders do I have",
    "do I have any reminders",
])
def test_reminders_listing(phrase):
    ir = _make_recognizer(["list_reminders"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "list_reminders"


# ── Security tools ────────────────────────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_target", [
    ("scan 192.168.1.50 for open ports", "192.168.1.50"),
    ("port scan 10.0.0.5", "10.0.0.5"),
    ("nmap 192.168.1.1", "192.168.1.1"),
    ("scan host 192.168.29.232 with nmap", "192.168.29.232"),
    ("service scan example.lab.local", "example.lab.local"),
])
def test_host_service_scan_routes(phrase, expected_target):
    ir = _make_recognizer(["host_service_scan", "ping_sweep", "launch_app"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "host_service_scan"
    assert result[0]["args"]["target"] == expected_target


@pytest.mark.parametrize("phrase,expected_target", [
    ("ping sweep 192.168.1.0/24", "192.168.1.0/24"),
    ("sweep 10.0.0.0/16", "10.0.0.0/16"),
    ("discover 192.168.1.0/24", "192.168.1.0/24"),
])
def test_ping_sweep_routes(phrase, expected_target):
    ir = _make_recognizer(["ping_sweep", "host_service_scan"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "ping_sweep"
    assert result[0]["args"]["target"] == expected_target


def test_security_parser_inert_without_tool():
    """If security plugin isn't loaded (lab_mode: false), parser is no-op."""
    ir = _make_recognizer(["launch_app"])  # no security tools
    result = ir.plan("scan 192.168.1.50 for open ports")
    if result:
        assert result[0]["tool"] not in ("host_service_scan", "ping_sweep")
