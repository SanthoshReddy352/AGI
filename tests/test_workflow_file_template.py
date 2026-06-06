"""Track 5.2d foundation — file_create_with_content YAML template.

This test suite is the conversion target for the legacy
`FileWorkflow` Python class. The full retirement of `FileWorkflow`
(plus `BrowserMediaWorkflow` and `WorkflowOrchestrator.continue_active`
slot-fill) is scheduled for the 5.2d-retire follow-up sub-track —
that switch touches `modules/system_control/file_workspace.py` and
roughly 30 existing tests, so it gets its own pass.

What this file pins is:
  * the new YAML template loads + compiles,
  * the `detect_new_filename` capability is registered and behaves
    correctly as a `cancel_when:` predicate,
  * the slot-fill flow advances through write_confirmation →
    content_source → content_topic → manage_file, honoring the
    `when:` predicates,
  * the cancel_when fires when the user names a different filename
    mid-flow (Issue 10).
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflows import (
    WorkflowTemplateCompiler,
    load_templates,
)
from core.workflows.template_loader import default_template_dir
from modules.system_control.plugin import SystemControlPlugin


# ----------------------------------------------------------------------
# Capability: detect_new_filename
# ----------------------------------------------------------------------

@pytest.fixture()
def system_plugin(tmp_path, monkeypatch):
    """A SystemControlPlugin mounted on a minimal app shim — enough to
    register capabilities and reach the new ``detect_new_filename``
    handler."""
    from core.dialog_state import DialogState
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop").mkdir()
    app = SimpleNamespace()
    app.config = SimpleNamespace(get=lambda k, d=None: d)
    app.event_bus = MagicMock()
    app.dialog_state = DialogState()
    app.assistant_context = MagicMock()
    app.session_id = "test-session"
    app.context_store = MagicMock()
    app.memory_service = MagicMock()
    captured: dict[str, dict] = {}

    def _register(spec, callback):
        captured[spec["name"]] = {"spec": spec, "callback": callback}

    app.register_capability = _register
    plugin = SystemControlPlugin(app)
    return SimpleNamespace(plugin=plugin, app=app, capabilities=captured)


def test_detect_new_filename_registered(system_plugin):
    assert "detect_new_filename" in system_plugin.capabilities
    spec = system_plugin.capabilities["detect_new_filename"]["spec"]
    assert spec["side_effect_level"] == "read"


def test_detect_new_filename_true_when_different(system_plugin):
    cb = system_plugin.capabilities["detect_new_filename"]["callback"]
    result = cb("save that to reverse.py", {"slots": {"filename": "ideas.md"}})
    assert result is True


def test_detect_new_filename_false_when_same_name(system_plugin):
    cb = system_plugin.capabilities["detect_new_filename"]["callback"]
    assert cb("save that to ideas.md", {"slots": {"filename": "ideas.md"}}) is False


def test_detect_new_filename_false_when_no_explicit_name(system_plugin):
    cb = system_plugin.capabilities["detect_new_filename"]["callback"]
    assert cb("save that", {"slots": {"filename": "ideas.md"}}) is False


def test_detect_new_filename_case_insensitive(system_plugin):
    cb = system_plugin.capabilities["detect_new_filename"]["callback"]
    # Same name, different case → not a switch.
    assert cb("save that to IDEAS.MD", {"slots": {"filename": "ideas.md"}}) is False
    # Truly different file with different case → switch.
    assert cb("save that to REVERSE.PY", {"slots": {"filename": "ideas.md"}}) is True


def test_detect_new_filename_flags_any_explicit_when_no_slot(system_plugin):
    cb = system_plugin.capabilities["detect_new_filename"]["callback"]
    # No active filename in slots — any named file still flags.
    assert cb("write notes.md", {"slots": {}}) is True
    assert cb("write something down", {"slots": {}}) is False


# ----------------------------------------------------------------------
# Template: file_create_with_content
# ----------------------------------------------------------------------

@pytest.fixture()
def file_template():
    return load_templates(default_template_dir())["file_create_with_content"]


def test_file_template_loads(file_template):
    assert file_template.cancel_when == "detect_new_filename"
    # ask + capability step ordering matches the design.
    step_ids = [s.step_id for s in file_template.steps]
    assert step_ids == ["ask_write", "ask_source", "ask_topic", "write_file"]
    # write_file is the capability step.
    assert file_template.steps[-1].capability == "manage_file"


def test_file_template_parks_on_first_ask(file_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(file_template, {"filename": "notes.md"})
    assert result.awaiting_slot == "write_confirmation"
    assert result.plan.reply == "Would you like me to write anything in it?"


def test_file_template_skips_branch_when_user_said_nothing(file_template):
    """If write_confirmation slot is filled with an empty string (the
    skip-token convention), the ask_source / ask_topic / write_file
    steps all skip — workflow completes immediately with no capability
    run. Mirrors the legacy `no` branch."""
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(file_template, {
        "filename": "notes.md",
        "write_confirmation": "",
    })
    assert result.awaiting_slot == ""
    assert result.plan.mode == "tool"
    # ask_source.when=slot:write_confirmation is falsy → ask_source
    # never asked → content_source unset → ask_topic skipped →
    # write_file.when=slot:content_topic is falsy → no capability runs.
    assert result.plan.steps == []


def test_file_template_progresses_to_topic_when_yes_then_generate(file_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(file_template, {
        "filename": "notes.md",
        "write_confirmation": "yes",
        "content_source": "generate",
    })
    assert result.awaiting_slot == "content_topic"
    assert result.plan.reply == "What topic should I write about?"


def test_file_template_runs_manage_file_when_all_slots_filled(file_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(file_template, {
        "filename": "notes.md",
        "write_confirmation": "yes",
        "content_source": "generate",
        "content_topic": "morning routines",
    })
    assert result.plan.mode == "tool"
    assert len(result.plan.steps) == 1
    step = result.plan.steps[0]
    assert step.capability_name == "manage_file"
    assert step.args["action"] == "write"
    assert step.args["filename"] == "notes.md"
    assert step.args["content"] == "morning routines"


def test_file_template_cancel_when_fires_on_different_filename(
    file_template, system_plugin,
):
    """End-to-end: a parked workflow whose target is `ideas.md` cancels
    when the user names `reverse.py`."""
    compiler = WorkflowTemplateCompiler(registry=None)
    # Wire the detect_new_filename capability into a tiny executor that
    # invokes the registered handler.
    capabilities = system_plugin.capabilities

    class _Executor:
        def execute(self, name, text, args):
            cb = capabilities[name]["callback"]
            return cb(text, args)

    fires = compiler.evaluate_cancel(
        file_template,
        {"filename": "ideas.md"},
        "save that to reverse.py",
        capability_executor=_Executor(),
    )
    assert fires is True

    stays = compiler.evaluate_cancel(
        file_template,
        {"filename": "ideas.md"},
        "save that",
        capability_executor=_Executor(),
    )
    assert stays is False
