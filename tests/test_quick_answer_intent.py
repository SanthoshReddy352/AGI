"""Routing + slash coverage for the research ecosystem tiers (2026-05-25):
  /web   -> links            (web_search)
  /quick -> instant answer   (quick_answer, no storage)
  /fast  -> quick research   (research_topic mode=quick)
  /deep  -> deep research    (research_topic mode=deep)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import core.slash_commands as sc


def _make_recognizer(tools):
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


@pytest.mark.parametrize("phrase", [
    "quick answer about photosynthesis",
    "give me a quick answer on the speed of light",
    "quick search on rust borrow checker",
    "just tell me about black holes",
    "quickly look up the capital of peru",
])
def test_quick_answer_routes(phrase):
    r = _make_recognizer(["quick_answer", "research_topic"]).plan(phrase)
    assert r and r[0]["tool"] == "quick_answer", f"{phrase!r} -> {r}"


@pytest.mark.parametrize("phrase,mode", [
    ("quick research on quantum computing", "quick"),
    ("fast research on llm agents", "quick"),
    ("deep dive on fusion energy", "deep"),
    ("deep research on crispr", "deep"),
])
def test_research_modes_not_stolen_by_quick_answer(phrase, mode):
    """'quick research' must stay research, not be poached by quick_answer."""
    r = _make_recognizer(["quick_answer", "research_topic"]).plan(phrase)
    assert r and r[0]["tool"] == "research_topic"
    assert r[0]["args"].get("mode") == mode, f"{phrase!r} -> {r}"


def test_quick_answer_absent_falls_through():
    r = _make_recognizer(["research_topic"]).plan("quick answer about x")
    assert not r or r[0]["tool"] != "quick_answer"


# ── slash commands ───────────────────────────────────────────────────────────

def _app_with(caps):
    app = MagicMock()
    registry = MagicMock()
    registry.get_handler.side_effect = lambda n: (lambda *a, **k: "ok") if n in caps else None
    app.capability_registry = registry
    executor = MagicMock()
    executor.execute.return_value = MagicMock(ok=True, output="EXEC", error="")
    app.capability_executor = executor
    return app, executor


def test_slash_registry_has_four_tiers():
    names = [n for n, _, _ in sc.REGISTRY]
    for cmd in ("web", "quick", "fast", "deep"):
        assert cmd in names


def test_slash_quick_calls_quick_answer():
    app, executor = _app_with({"quick_answer"})
    out = sc.dispatch(app, "/quick who invented python")
    assert out == "EXEC"
    name, _, args = executor.execute.call_args[0]
    assert name == "quick_answer"
    assert args["query"] == "who invented python"


def test_slash_fast_uses_quick_mode():
    app, executor = _app_with({"research_topic"})
    sc.dispatch(app, "/fast latest on ai regulation")
    name, _, args = executor.execute.call_args[0]
    assert name == "research_topic" and args["mode"] == "quick"


def test_slash_deep_uses_deep_mode():
    app, executor = _app_with({"research_topic"})
    sc.dispatch(app, "/deep compare react and vue")
    name, _, args = executor.execute.call_args[0]
    assert name == "research_topic" and args["mode"] == "deep"


def test_slash_usage_when_empty():
    app, _ = _app_with({"quick_answer"})
    assert "Usage" in sc.dispatch(app, "/quick")
