"""Track 5.2c — runtime predicates (`when:` / `cancel_when:`) tests.

Verifies:
  1. YAML loader accepts `cancel_when:` at the template level and
     `when:` on individual steps.
  2. Compiler skips capability-steps whose `when:` predicate evaluates
     false (capability-backed and `slot:` forms, with optional `not:`).
  3. Compiler skips ask-steps whose `when:` predicate evaluates false
     (so a YAML template can branch mid-slot-fill).
  4. `evaluate_cancel` returns True when the template's `cancel_when:`
     predicate fires.
  5. `TemplateWorkflow.run_slot_fill_turn` honors `cancel_when:` —
     when the predicate fires it clears state, returns
     ``handled=False``, and the orchestrator falls through.
"""
from __future__ import annotations

import os
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflows.template_compiler import WorkflowTemplateCompiler
from core.workflows.template_loader import WorkflowTemplateLoader


# ----------------------------------------------------------------------
# Loader — schema
# ----------------------------------------------------------------------

def _load(tmp_path, yaml_text: str, name: str = "tpl"):
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return WorkflowTemplateLoader(str(tmp_path)).load_all()


def test_loader_accepts_cancel_when(tmp_path):
    tpls = _load(tmp_path, textwrap.dedent("""
        workflow_name: cancel_demo
        cancel_when: detect_new_filename
        cancel_response: New target detected — releasing.
        steps:
          - step_id: ask
            ask: Q?
            slot: x
    """))
    tpl = tpls["cancel_demo"]
    assert tpl.cancel_when == "detect_new_filename"
    assert tpl.cancel_response == "New target detected — releasing."


def test_loader_accepts_step_when(tmp_path):
    tpls = _load(tmp_path, textwrap.dedent("""
        workflow_name: when_demo
        steps:
          - step_id: ask_topic
            ask: What topic?
            slot: topic
            when: "slot:write_confirmation"
          - step_id: do
            capability: noop
            when: "slot:topic"
    """))
    tpl = tpls["when_demo"]
    assert tpl.steps[0].when == "slot:write_confirmation"
    assert tpl.steps[1].when == "slot:topic"


# ----------------------------------------------------------------------
# Compiler — predicate evaluation
# ----------------------------------------------------------------------

@pytest.fixture()
def branching_template(tmp_path):
    text = textwrap.dedent("""
        workflow_name: branchy
        steps:
          - step_id: ask_yn
            ask: Yes or no?
            slot: yn
          - step_id: ask_topic
            ask: What topic?
            slot: topic
            when: "slot:yn"
          - step_id: persist
            capability: save_topic
            when: "slot:topic"
            args: { topic: '{{topic}}' }
    """)
    return _load(tmp_path, text, "branchy")["branchy"]


def test_when_slot_predicate_skips_ask_step(branching_template):
    """ask_topic.when=slot:yn — if yn is empty, ask_topic is skipped."""
    compiler = WorkflowTemplateCompiler(registry=None)
    # yn filled with "" → falsy → ask_topic skipped → fall through to
    # capability steps, which themselves get filtered by slot:topic.
    result = compiler.compile(branching_template, {"yn": ""})
    # All ask-steps consumed (ask_yn filled, ask_topic skipped via when=false)
    assert result.awaiting_slot == ""
    assert result.plan.mode == "tool"
    # save_topic was filtered out (topic still unset).
    assert result.plan.steps == []


def test_when_slot_predicate_runs_ask_step_when_truthy(branching_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    # yn filled with "yes" → truthy → ask_topic is the next question.
    result = compiler.compile(branching_template, {"yn": "yes"})
    assert result.awaiting_slot == "topic"
    assert result.plan.reply == "What topic?"


def test_when_slot_predicate_filters_capability_step(branching_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    # Both slots filled — both ask-steps consumed; capability runs.
    result = compiler.compile(branching_template, {"yn": "yes", "topic": "weather"})
    assert result.plan.mode == "tool"
    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].capability_name == "save_topic"
    assert result.plan.steps[0].args == {"topic": "weather"}


def test_when_capability_predicate_truthy(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: cap_when
        steps:
          - step_id: ask
            ask: Q?
            slot: x
            when: is_active_user
    """))["cap_when"]
    compiler = WorkflowTemplateCompiler(registry=None)
    executor = MagicMock()
    executor.execute.return_value = True
    result = compiler.compile(tpl, {}, capability_executor=executor)
    assert result.awaiting_slot == "x"
    executor.execute.assert_called_once()


def test_when_capability_predicate_falsy_skips(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: cap_when_skip
        steps:
          - step_id: ask
            ask: Q?
            slot: x
            when: is_active_user
    """))["cap_when_skip"]
    compiler = WorkflowTemplateCompiler(registry=None)
    executor = MagicMock()
    executor.execute.return_value = False
    result = compiler.compile(tpl, {}, capability_executor=executor)
    # No ask-step runs; falls through to (empty) capability steps.
    assert result.awaiting_slot == ""
    assert result.plan.steps == []


def test_when_not_prefix_inverts(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: invert_demo
        steps:
          - step_id: ask
            ask: Q?
            slot: x
            when: "not:slot:y"
    """))["invert_demo"]
    compiler = WorkflowTemplateCompiler(registry=None)
    # y is unset → not:slot:y is truthy → ask runs.
    result = compiler.compile(tpl, {})
    assert result.awaiting_slot == "x"
    # y is "yes" → not:slot:y is falsy → ask skipped.
    result = compiler.compile(tpl, {"y": "yes"})
    assert result.awaiting_slot == ""


# ----------------------------------------------------------------------
# Compiler — cancel_when evaluation
# ----------------------------------------------------------------------

def test_evaluate_cancel_returns_false_when_no_predicate(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: no_cancel
        steps:
          - step_id: ask
            ask: Q?
            slot: x
    """))["no_cancel"]
    compiler = WorkflowTemplateCompiler(registry=None)
    assert compiler.evaluate_cancel(tpl, {}, "any text") is False


def test_evaluate_cancel_fires_on_capability(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: cancellable
        cancel_when: detect_new_filename
        cancel_response: Switching files
        steps:
          - step_id: ask
            ask: Q?
            slot: x
    """))["cancellable"]
    compiler = WorkflowTemplateCompiler(registry=None)
    executor = MagicMock()
    executor.execute.return_value = True
    assert compiler.evaluate_cancel(
        tpl, {"filename": "old.md"}, "save that to new.py",
        capability_executor=executor,
    ) is True
    executor.execute.assert_called_once_with(
        "detect_new_filename", "save that to new.py",
        {"text": "save that to new.py", "slots": {"filename": "old.md"}},
    )


def test_evaluate_cancel_failure_keeps_workflow_alive(tmp_path):
    tpl = _load(tmp_path, textwrap.dedent("""
        workflow_name: cancellable
        cancel_when: detect_new_filename
        steps:
          - step_id: ask
            ask: Q?
            slot: x
    """))["cancellable"]
    compiler = WorkflowTemplateCompiler(registry=None)
    executor = MagicMock()
    executor.execute.side_effect = RuntimeError("broken")
    # Exception swallowed → False so we don't drop the workflow on noise.
    assert compiler.evaluate_cancel(
        tpl, {}, "text", capability_executor=executor,
    ) is False


# ----------------------------------------------------------------------
# TemplateWorkflow — run_slot_fill_turn honors cancel_when
# ----------------------------------------------------------------------

def test_run_slot_fill_turn_cancels_when_predicate_fires(tmp_path):
    from core.workflow_orchestrator import TemplateWorkflow
    from core.stores import SessionStore, WorkflowStore

    tpl_text = textwrap.dedent("""
        workflow_name: cancellable_flow
        cancel_when: detect_new_filename
        cancel_response: New target — releasing.
        steps:
          - step_id: ask_q
            ask: Anything to add?
            slot: extra
          - step_id: ask_t
            ask: What topic?
            slot: topic
    """)
    tpl_dir = tmp_path / "tpls"
    tpl_dir.mkdir()
    (tpl_dir / "x.yaml").write_text(tpl_text, encoding="utf-8")
    tpl = WorkflowTemplateLoader(str(tpl_dir)).load_all()["cancellable_flow"]

    db = tmp_path / "friday.db"
    sess = SessionStore(str(db))
    wfs = WorkflowStore(str(db))
    sid = sess.start_session()

    class _Memory:
        def get_active_workflow(self, sid, workflow_name=None):
            return wfs.get_active(sid, workflow_name)

        def save_workflow_state(self, sid, name, state):
            wfs.upsert(sid, name, state)

        def clear_workflow_state(self, sid, name):
            active = wfs.get_active(sid, name)
            if not active:
                return
            active["status"] = "completed"
            active["pending_slots"] = []
            wfs.upsert(sid, name, active)

    executor = MagicMock()
    # First compile during start_slot_fill: cancel_when must be FALSE; the
    # ask step's empty `when:` should not be misread.
    # Then run_slot_fill_turn's cancel_when call returns True.
    executor.execute.return_value = True

    app = SimpleNamespace(
        memory_service=_Memory(),
        context_store=_Memory(),
        ordered_tool_executor=MagicMock(),
        task_graph_executor=None,
        capability_executor=executor,
        config=None,
    )
    workflow = TemplateWorkflow(
        app, tpl, WorkflowTemplateCompiler(registry=None),
    )

    # Park the workflow on the first ask.
    workflow.start_slot_fill(sid)
    assert wfs.get_active(sid, "cancellable_flow")["awaiting_slot"] == "extra"

    # Now resume with a user reply that triggers cancel_when.
    result = workflow.run_slot_fill_turn("save that to other.py", sid)
    assert result.handled is False
    assert result.response == "New target — releasing."
    # Workflow state cleared.
    assert wfs.get_active(sid, "cancellable_flow") is None
