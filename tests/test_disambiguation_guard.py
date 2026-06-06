"""Phase 3 checkpoint 4 — DisambiguationGuard (reusable "which one?" pick).

Covers the guard itself, the shared selection parser, the app-name ambiguity
finder, and the three wired handlers (search_indexed_files, launch_app,
query_document) arming a pick.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflows.disambiguation import (
    DisambiguationGuard,
    PENDING_KEY,
    parse_selection,
    looks_like_selection,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self):
        self._states = {}

    def get_session_state(self, session_id):
        return dict(self._states.get(session_id, {}))

    def save_session_state(self, session_id, state):
        self._states[session_id] = dict(state)


class _Result:
    def __init__(self, output="", ok=True, error=""):
        self.output = output
        self.ok = ok
        self.error = error


class _FakeExecutor:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def execute(self, name, raw_text, args):
        self.calls.append((name, raw_text, dict(args)))
        return self._result


class _FakeConfig:
    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)


class _FakeApp:
    def __init__(self, *, result=None, config=None):
        self.context_store = _FakeStore()
        self.session_id = "sess-1"
        self.capability_executor = _FakeExecutor(result or _Result("done"))
        self.config = config if config is not None else _FakeConfig()


# ---------------------------------------------------------------------------
# parse_selection / looks_like_selection
# ---------------------------------------------------------------------------

import pytest


@pytest.mark.parametrize("text,expected", [
    ("1", 0), ("2", 1), ("3", 2),
    ("option 2", 1), ("number 3", 2), ("#1", 0),
    ("first", 0), ("the second one", 1), ("third option", 2),
    ("1st", 0), ("2nd one", 1),
    ("last", 2), ("the last one", 2),
    ("chromium", 1),            # unique label substring
    ("the firefox one", None),  # 'firefox' not among labels
    ("what's the weather", None),
    ("", None),
])
def test_parse_selection(text, expected):
    labels = ["chrome", "chromium", "edge"]
    assert parse_selection(text, labels) == expected


def test_parse_selection_out_of_range_returns_none():
    assert parse_selection("9", ["a", "b"]) is None


def test_parse_selection_ambiguous_substring_returns_none():
    # "bro" appears in both → not unique → no resolution.
    assert parse_selection("bro", ["brave browser", "firefox browser"]) is None


def test_looks_like_selection():
    assert looks_like_selection("2", ["a", "b", "c"]) is True
    assert looks_like_selection("tell me a joke", ["a", "b", "c"]) is False


# ---------------------------------------------------------------------------
# arm / peek / clear / render
# ---------------------------------------------------------------------------

def test_arm_persists_and_renders_numbered_list():
    app = _FakeApp()
    guard = DisambiguationGuard(app)
    prompt = guard.arm(
        action="open_file", arg_name="filename",
        candidates=["a.txt", "b.txt"], intro="Which file?",
    )
    assert "1. a.txt" in prompt and "2. b.txt" in prompt
    assert "Which file?" in prompt
    pending = app.context_store.get_session_state("sess-1")[PENDING_KEY]
    assert pending["action"] == "open_file"
    assert pending["arg_name"] == "filename"
    assert pending["candidates"][0] == {"label": "a.txt", "value": "a.txt"}


def test_arm_normalizes_dict_and_tuple_candidates():
    guard = DisambiguationGuard(_FakeApp())
    guard.arm(
        action="launch_app", arg_name="app_names",
        candidates=[{"label": "Chrome", "value": "chrome"}, ("Edge", "edge")],
    )
    pending = guard.peek()
    assert pending["candidates"] == [
        {"label": "Chrome", "value": "chrome"},
        {"label": "Edge", "value": "edge"},
    ]


def test_clear_pops():
    guard = DisambiguationGuard(_FakeApp())
    guard.arm(action="open_file", arg_name="filename", candidates=["a", "b"])
    assert guard.clear()["action"] == "open_file"
    assert guard.peek() is None


# ---------------------------------------------------------------------------
# pick / cancel
# ---------------------------------------------------------------------------

def test_pick_redispatches_with_chosen_value_and_picked_flag():
    app = _FakeApp(result=_Result("Opening report.pdf"))
    guard = DisambiguationGuard(app)
    guard.arm(
        action="open_file", arg_name="filename",
        candidates=[{"label": "report.pdf", "value": "/docs/report.pdf"},
                    {"label": "resume.pdf", "value": "/docs/resume.pdf"}],
    )
    out = guard.pick("the second one")
    assert out == "Opening report.pdf"
    name, _raw, args = app.capability_executor.calls[0]
    assert name == "open_file"
    assert args["filename"] == "/docs/resume.pdf"
    assert args["_picked"] is True
    assert guard.peek() is None  # cleared after a successful pick


def test_pick_carries_base_args():
    app = _FakeApp(result=_Result("summary"))
    guard = DisambiguationGuard(app)
    guard.arm(
        action="query_document", arg_name="file_path",
        base_args={"question": "what are the risks"},
        candidates=[{"label": "q3.pdf", "value": "/d/q3.pdf"},
                    {"label": "q4.pdf", "value": "/d/q4.pdf"}],
    )
    guard.pick("1")
    _name, _raw, args = app.capability_executor.calls[0]
    assert args["file_path"] == "/d/q3.pdf"
    assert args["question"] == "what are the risks"
    assert args["_picked"] is True


def test_pick_unresolved_reasks_and_keeps_pending():
    app = _FakeApp()
    guard = DisambiguationGuard(app)
    guard.arm(action="open_file", arg_name="filename",
              candidates=["a.txt", "b.txt"], intro="Which file?")
    out = guard.pick("hmm not sure")
    assert "1. a.txt" in out  # re-rendered
    assert guard.peek() is not None  # still armed
    assert app.capability_executor.calls == []  # nothing dispatched


def test_pick_with_nothing_armed_is_graceful():
    out = DisambiguationGuard(_FakeApp()).pick("2")
    assert "nothing waiting" in out.lower()


def test_cancel_clears_and_acknowledges():
    guard = DisambiguationGuard(_FakeApp())
    guard.arm(action="open_file", arg_name="filename", candidates=["a", "b"])
    out = guard.cancel()
    assert "never mind" in out.lower()
    assert guard.peek() is None


# ---------------------------------------------------------------------------
# needs_disambiguation / enabled
# ---------------------------------------------------------------------------

def test_needs_disambiguation_only_when_multiple_and_unpicked():
    guard = DisambiguationGuard(_FakeApp())
    assert guard.needs_disambiguation({}, ["a", "b"]) is True
    assert guard.needs_disambiguation({}, ["a"]) is False
    assert guard.needs_disambiguation({"_picked": True}, ["a", "b"]) is False


def test_disabled_by_config():
    app = _FakeApp(config=_FakeConfig({"routing.disambiguate": False}))
    guard = DisambiguationGuard(app)
    assert guard.enabled is False
    assert guard.needs_disambiguation({}, ["a", "b"]) is False


# ---------------------------------------------------------------------------
# find_app_candidates
# ---------------------------------------------------------------------------

def test_find_app_candidates_uses_registry(monkeypatch):
    from modules.system_control import app_launcher as al

    class _T:
        def __init__(self, c):
            self.canonical_name = c

    fake_registry = {
        "chrome": _T("chrome"),
        "chromium": _T("chromium"),
        "edge": _T("edge"),
        "firefox": _T("firefox"),
    }
    monkeypatch.setattr(al, "get_app_registry", lambda: fake_registry)

    assert al.find_app_candidates("chrom") == ["chrome", "chromium"]  # ambiguous
    assert al.find_app_candidates("firefox") == []                    # exact → unambiguous
    assert al.find_app_candidates("e") == []                          # <2 chars
    assert al.find_app_candidates("edge") == []                       # exact single


# ---------------------------------------------------------------------------
# Handler wiring — search_indexed_files
# ---------------------------------------------------------------------------

def _system_plugin(app):
    from modules.system_control.plugin import SystemControlPlugin
    plugin = object.__new__(SystemControlPlugin)
    plugin.app = app
    return plugin


def test_search_indexed_files_arms_pick_on_multiple():
    app = _FakeApp()
    app.file_index_store = _FakeFileIndex([
        {"name": "report.pdf", "parent_dir": "/docs", "path": "/docs/report.pdf", "ext": "pdf"},
        {"name": "report_v2.pdf", "parent_dir": "/dl", "path": "/dl/report_v2.pdf", "ext": "pdf"},
    ])
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _system_plugin(app)
    out = plugin.handle_search_indexed_files("find file report", {"query": "report"})
    assert "Which one" in out and "1. report.pdf" in out
    pending = app.disambiguation_guard.peek()
    assert pending["action"] == "open_file"
    assert pending["candidates"][1]["value"] == "/dl/report_v2.pdf"


def test_search_indexed_files_single_result_lists_no_pick():
    app = _FakeApp()
    app.file_index_store = _FakeFileIndex([
        {"name": "only.pdf", "parent_dir": "/docs", "path": "/docs/only.pdf", "ext": "pdf"},
    ])
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _system_plugin(app)
    out = plugin.handle_search_indexed_files("find file only", {"query": "only"})
    assert "only.pdf" in out
    assert app.disambiguation_guard.peek() is None


class _FakeFileIndex:
    def __init__(self, rows):
        self._rows = rows

    def search(self, query, limit=20, ext=""):
        return list(self._rows)


# ---------------------------------------------------------------------------
# Handler wiring — launch_app
# ---------------------------------------------------------------------------

def test_launch_app_arms_pick_when_ambiguous(monkeypatch):
    from modules.system_control import plugin as plugin_mod
    monkeypatch.setattr(plugin_mod, "find_app_candidates",
                        lambda tok: ["chrome", "chromium"] if "chrom" in tok else [])
    app = _FakeApp()
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _system_plugin(app)
    out = plugin.handle_launch_app("open chrom", {"app_names": ["chrome"]})
    assert "Which one" in out and "chrome" in out and "chromium" in out
    pending = app.disambiguation_guard.peek()
    assert pending["action"] == "launch_app"
    assert pending["arg_name"] == "app_names"


def test_launch_app_picked_flag_skips_disambiguation(monkeypatch):
    # Once the guard re-dispatches with _picked=True the handler must NOT
    # re-arm — it should fall through to the real launcher.
    from modules.system_control import plugin as plugin_mod
    monkeypatch.setattr(plugin_mod, "find_app_candidates", lambda tok: ["chrome", "chromium"])
    launched = {}

    def _fake_launch(names):
        launched["names"] = names
        return "Opening..."

    monkeypatch.setattr(plugin_mod, "launch_application", _fake_launch)
    app = _FakeApp()
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _system_plugin(app)
    out = plugin.handle_launch_app("open chrome", {"app_names": ["chrome"], "_picked": True})
    assert "Opening" in out
    assert launched["names"] == ["chrome"]
    assert app.disambiguation_guard.peek() is None


# ---------------------------------------------------------------------------
# Handler wiring — query_document
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("summarize prabhas.txt", "prabhas.txt"),
    ("what does the budget report say", "budget"),
    ("read my q3 financials document", "q3 financials"),
    ("summarize the document", ""),   # generic → no guess
    ("what is in this file", ""),
])
def test_doc_name_hint(question, expected):
    from modules.document_intel.plugin import DocumentIntelPlugin
    assert DocumentIntelPlugin._doc_name_hint(question) == expected


def _doc_plugin(app):
    from modules.document_intel.plugin import DocumentIntelPlugin
    plugin = object.__new__(DocumentIntelPlugin)
    plugin.app = app
    return plugin


def test_query_document_arms_pick_on_multiple_doc_matches():
    app = _FakeApp()
    app.file_index_store = _FakeFileIndex([
        {"name": "budget.pdf", "parent_dir": "/d", "path": "/d/budget.pdf", "ext": "pdf"},
        {"name": "budget.xlsx", "parent_dir": "/d", "path": "/d/budget.xlsx", "ext": "xlsx"},
        {"name": "budget.png", "parent_dir": "/d", "path": "/d/budget.png", "ext": "png"},  # filtered out
    ])
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _doc_plugin(app)
    picked = plugin._maybe_disambiguate_document({}, "summarize the budget report", "summarize the budget report")
    # Returns the wrapped pick prompt (CapabilityExecutionResult).
    assert picked is not None and getattr(picked, "output", None)
    assert "1. budget.pdf" in picked.output
    pending = app.disambiguation_guard.peek()
    assert pending["action"] == "query_document"
    assert len(pending["candidates"]) == 2  # png filtered


def test_query_document_single_doc_autoselects_path():
    app = _FakeApp()
    app.file_index_store = _FakeFileIndex([
        {"name": "budget.pdf", "parent_dir": "/d", "path": "/d/budget.pdf", "ext": "pdf"},
    ])
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _doc_plugin(app)
    picked = plugin._maybe_disambiguate_document({}, "summarize budget", "summarize budget")
    assert picked == "/d/budget.pdf"
    assert app.disambiguation_guard.peek() is None


def test_query_document_generic_question_no_disambiguation():
    app = _FakeApp()
    app.file_index_store = _FakeFileIndex([{"name": "x.pdf", "parent_dir": "/d", "path": "/d/x.pdf", "ext": "pdf"}])
    app.disambiguation_guard = DisambiguationGuard(app)
    plugin = _doc_plugin(app)
    # No name hint → returns None (caller falls back to the honest error).
    assert plugin._maybe_disambiguate_document({}, "summarize the document", "summarize the document") is None
