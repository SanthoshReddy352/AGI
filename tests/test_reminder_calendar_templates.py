"""launch-hardening §5.4 — the live `set_reminder` slot-fill template.

Compiler/loader-level coverage for ``set_reminder.yaml`` and the
template-internal capabilities (``extract_reminder_date`` /
``extract_reminder_time`` / ``create_reminder``) that ``TaskManagerPlugin``
registers. The template is the LIVE reminder slot-fill path (Step 3).

The local calendar-EVENT template/capabilities were removed 2026-05-31 — the
WorkspaceAgent's Google Calendar capabilities own calendar events now — so this
file no longer covers any local calendar-event path.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import modules.task_manager.plugin as task_manager_plugin
from core.workflows.template_compiler import WorkflowTemplateCompiler
from core.workflows.template_loader import load_templates
from modules.task_manager.plugin import TaskManagerPlugin


@pytest.fixture(scope="module")
def templates():
    return load_templates()


class _FakeApp:
    """Minimal host: records registered capabilities; nothing else the
    TaskManagerPlugin constructor touches on a fresh (empty) DB is needed."""

    def __init__(self):
        self.registered = {}

    def register_capability(self, spec, handler, metadata=None):
        self.registered[spec["name"]] = handler


# ----------------------------------------------------------------------
# Loader — template structure
# ----------------------------------------------------------------------

def test_set_reminder_template_structure(templates):
    # §5.4 Step 3: two-phase date→time ask-steps (preserves the pre-cutover
    # follow-up behaviour); schedule step wraps create_reminder.
    tpl = templates["set_reminder"]
    assert tpl.required_inputs == ["message"]
    ask_date = tpl.steps[0]
    assert ask_date.is_ask_step is True
    assert ask_date.slot == "date"
    assert ask_date.extract_with == "extract_reminder_date"
    ask_time = tpl.steps[1]
    assert ask_time.is_ask_step is True
    assert ask_time.slot == "time"
    assert ask_time.extract_with == "extract_reminder_time"
    sched = tpl.steps[2]
    assert sched.capability == "create_reminder"
    assert sched.args == {
        "message": "{{message}}", "date": "{{date}}", "time": "{{time}}",
    }


def test_no_local_calendar_event_template(templates):
    # The local calendar-event template was removed; Google owns calendar events.
    assert "create_calendar_event" not in templates


# ----------------------------------------------------------------------
# Compiler — ask-step parking + slot substitution
# ----------------------------------------------------------------------

def test_set_reminder_parks_on_date_then_time(templates):
    compiler = WorkflowTemplateCompiler(registry=None)
    # message only → asks for the date first.
    r0 = compiler.compile(templates["set_reminder"], {"message": "call mom"})
    assert r0.plan.mode == "clarify"
    assert r0.plan.reply == "What date should I remind you?"
    assert r0.awaiting_slot == "date"
    assert r0.awaiting_step_id == "ask_date"
    # date seeded → asks for the time next.
    r1 = compiler.compile(
        templates["set_reminder"], {"message": "call mom", "date": "2026-06-01"},
    )
    assert r1.plan.reply == "What time should I remind you?"
    assert r1.awaiting_slot == "time"


def test_set_reminder_compiles_schedule_step_when_filled(templates):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(
        templates["set_reminder"],
        {"message": "call mom", "date": "2026-06-01", "time": "15:00"},
    )
    assert result.plan.mode == "tool"
    assert result.awaiting_slot == ""
    assert len(result.plan.steps) == 1
    step = result.plan.steps[0]
    assert step.capability_name == "create_reminder"
    assert step.args == {
        "message": "call mom", "date": "2026-06-01", "time": "15:00",
    }


# ----------------------------------------------------------------------
# extract_with round-trip + registry coverage
# ----------------------------------------------------------------------

def test_set_reminder_date_step_uses_extract_with(templates):
    compiler = WorkflowTemplateCompiler(registry=None)
    executor = MagicMock()
    executor.execute.return_value = "2026-06-01"
    ask_date = templates["set_reminder"].steps[0]
    value = compiler.extract_slot_value(
        ask_date, "tomorrow", capability_executor=executor,
    )
    assert value == "2026-06-01"
    executor.execute.assert_called_once_with(
        "extract_reminder_date", "tomorrow", {"text": "tomorrow"},
    )


def test_plugin_registers_reminder_template_capabilities(monkeypatch, tmp_path):
    monkeypatch.setattr(task_manager_plugin, "DB_PATH", str(tmp_path / "friday.db"))
    app = _FakeApp()
    TaskManagerPlugin(app)
    for name in ("extract_reminder_date", "extract_reminder_time", "create_reminder"):
        assert name in app.registered
    # The local calendar-event capabilities are gone.
    for name in (
        "create_calendar_event", "move_calendar_event", "cancel_calendar_event",
        "list_calendar_events", "schedule_calendar_event", "extract_datetime",
    ):
        assert name not in app.registered


def test_set_reminder_template_compiles_against_registered_capabilities(templates, monkeypatch, tmp_path):
    """A template that references an unknown capability raises CompileError in
    production. Confirm set_reminder compiles against a registry mirroring
    exactly what TaskManagerPlugin registered."""
    monkeypatch.setattr(task_manager_plugin, "DB_PATH", str(tmp_path / "friday.db"))
    app = _FakeApp()
    TaskManagerPlugin(app)

    registry = MagicMock()
    registry.has_capability.side_effect = lambda n: n in app.registered
    registry.get_descriptor.return_value = None
    compiler = WorkflowTemplateCompiler(registry=registry)

    res = compiler.compile(
        templates["set_reminder"],
        {"message": "x", "date": "2026-06-01", "time": "15:00"},
    )
    assert res.plan.steps[0].capability_name == "create_reminder"


# ----------------------------------------------------------------------
# The reminder slot extractors return the expected shapes
# ----------------------------------------------------------------------

def test_reminder_extractors_return_expected_shapes(monkeypatch, tmp_path):
    monkeypatch.setattr(task_manager_plugin, "DB_PATH", str(tmp_path / "friday.db"))
    app = _FakeApp()
    TaskManagerPlugin(app)
    date_handler = app.registered["extract_reminder_date"]
    time_handler = app.registered["extract_reminder_time"]
    assert date_handler("tomorrow", {"text": "tomorrow"})  # ISO date, non-empty
    assert time_handler("four", {"text": "four"}) == "04:00"  # bare hour
