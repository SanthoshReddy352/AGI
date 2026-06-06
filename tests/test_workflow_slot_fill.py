"""Track 5.2a — multi-turn slot-fill primitive tests.

Verifies:
  1. YAML loader accepts `ask:` / `slot:` / `extract_with:` steps and
     rejects malformed ones.
  2. Compiler returns a clarify plan with the next question while
     ask-step slots remain unfilled; produces a tool plan once they
     are all filled.
  3. `extract_slot_value` honors `extract_with: <capability>` (with
     the raw-text fallback when the capability is missing/raises).
  4. End-to-end 3-turn round-trip: a 3-slot YAML asks three
     questions across three turns, fills each slot, and runs the
     final capability with the collected slot values.
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.workflows.template_compiler import (
    CompileError,
    WorkflowTemplateCompiler,
)
from core.workflows.template_loader import (
    TemplateError,
    WorkflowTemplateLoader,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

THREE_SLOT_YAML = textwrap.dedent("""
workflow_name: test_three_slot
description: 3-slot Q&A for round-trip testing
steps:
  - step_id: ask_name
    ask: What's your name?
    slot: user_name
  - step_id: ask_color
    ask: What's your favourite colour?
    slot: user_color
  - step_id: ask_pet
    ask: What's your pet's name?
    slot: user_pet
  - step_id: save
    capability: save_profile
    args:
      name: '{{user_name}}'
      color: '{{user_color}}'
      pet: '{{user_pet}}'
""")


@pytest.fixture()
def template_dir(tmp_path):
    path = tmp_path / "test_three_slot.yaml"
    path.write_text(THREE_SLOT_YAML, encoding="utf-8")
    return str(tmp_path)


@pytest.fixture()
def three_slot_template(template_dir):
    return WorkflowTemplateLoader(template_dir).load_all()["test_three_slot"]


# ----------------------------------------------------------------------
# Loader — schema validation
# ----------------------------------------------------------------------

def test_loader_accepts_ask_step(three_slot_template):
    steps = three_slot_template.steps
    assert steps[0].is_ask_step is True
    assert steps[0].ask == "What's your name?"
    assert steps[0].slot == "user_name"
    assert steps[0].capability == ""
    # The capability-step is NOT an ask-step.
    assert steps[3].is_ask_step is False
    assert steps[3].capability == "save_profile"


def test_loader_rejects_step_with_neither_capability_nor_ask(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent("""
        workflow_name: bad_no_cap_no_ask
        steps:
          - step_id: s1
            args: { x: 1 }
    """), encoding="utf-8")
    with pytest.raises(TemplateError, match="must declare either 'capability' or 'ask'"):
        WorkflowTemplateLoader(str(tmp_path)).load_all()


def test_loader_rejects_step_with_both_capability_and_ask(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent("""
        workflow_name: bad_both
        steps:
          - step_id: s1
            ask: Whatever?
            slot: x
            capability: some_capability
    """), encoding="utf-8")
    with pytest.raises(TemplateError, match="cannot declare both 'capability' and 'ask'"):
        WorkflowTemplateLoader(str(tmp_path)).load_all()


def test_loader_accepts_extract_with(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text(textwrap.dedent("""
        workflow_name: with_extractor
        steps:
          - step_id: a
            ask: Tell me your name.
            slot: user_name
            extract_with: extract_user_name
    """), encoding="utf-8")
    tpl = WorkflowTemplateLoader(str(tmp_path)).load_all()["with_extractor"]
    assert tpl.steps[0].extract_with == "extract_user_name"


# ----------------------------------------------------------------------
# Compiler — ask-step parking + slot-fill progression
# ----------------------------------------------------------------------

def test_compiler_parks_on_first_unfilled_ask_step(three_slot_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(three_slot_template, {})
    assert result.plan.mode == "clarify"
    assert result.plan.reply == "What's your name?"
    assert result.awaiting_slot == "user_name"
    assert result.awaiting_step_id == "ask_name"
    assert result.missing_slots == ["user_name"]


def test_compiler_advances_to_next_question_when_slot_filled(three_slot_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(three_slot_template, {"user_name": "Tricky"})
    assert result.awaiting_slot == "user_color"
    assert result.plan.reply == "What's your favourite colour?"


def test_compiler_produces_tool_plan_when_all_ask_slots_filled(three_slot_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    result = compiler.compile(three_slot_template, {
        "user_name": "Tricky",
        "user_color": "blue",
        "user_pet": "Rex",
    })
    assert result.plan.mode == "tool"
    assert result.awaiting_slot == ""
    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].capability_name == "save_profile"
    assert result.plan.steps[0].args == {
        "name": "Tricky", "color": "blue", "pet": "Rex",
    }


def test_compiler_unknown_capability_check_ignores_ask_steps(three_slot_template):
    """Track 5.2a regression: ask-steps don't have a capability — the
    registry-coverage check must not flag them as unknown."""
    registry = MagicMock()
    registry.has_capability.side_effect = lambda name: name == "save_profile"
    registry.get_descriptor.return_value = None
    compiler = WorkflowTemplateCompiler(registry=registry)
    # All ask-slots filled — should pass through to a tool plan without
    # raising CompileError for the ask steps (they have no capability).
    result = compiler.compile(three_slot_template, {
        "user_name": "Tricky",
        "user_color": "blue",
        "user_pet": "Rex",
    })
    assert result.plan.mode == "tool"


def test_compiler_unknown_capability_in_real_step_still_raises(tmp_path):
    bad = tmp_path / "missing.yaml"
    bad.write_text(textwrap.dedent("""
        workflow_name: missing_cap
        steps:
          - step_id: ask
            ask: Q?
            slot: x
          - step_id: do
            capability: not_a_real_capability
    """), encoding="utf-8")
    tpl = WorkflowTemplateLoader(str(tmp_path)).load_all()["missing_cap"]
    registry = MagicMock()
    registry.has_capability.return_value = False
    registry.get_descriptor.return_value = None
    compiler = WorkflowTemplateCompiler(registry=registry)
    with pytest.raises(CompileError, match="not_a_real_capability"):
        compiler.compile(tpl, {"x": "filled"})


# ----------------------------------------------------------------------
# extract_slot_value
# ----------------------------------------------------------------------

def test_extract_slot_value_raw_when_no_extractor(three_slot_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    step = three_slot_template.steps[0]  # ask_name (no extract_with)
    assert compiler.extract_slot_value(step, "  Tricky Reddy  ") == "Tricky Reddy"


def test_extract_slot_value_uses_extract_with_capability(tmp_path):
    path = tmp_path / "with_extractor.yaml"
    path.write_text(textwrap.dedent("""
        workflow_name: with_extractor
        steps:
          - step_id: a
            ask: Tell me your name.
            slot: user_name
            extract_with: extract_user_name
    """), encoding="utf-8")
    tpl = WorkflowTemplateLoader(str(tmp_path)).load_all()["with_extractor"]
    executor = MagicMock()
    executor.execute.return_value = "Tricky"
    compiler = WorkflowTemplateCompiler(registry=None)
    out = compiler.extract_slot_value(
        tpl.steps[0], "my name is Tricky Reddy", capability_executor=executor,
    )
    assert out == "Tricky"
    executor.execute.assert_called_once_with(
        "extract_user_name", "my name is Tricky Reddy",
        {"text": "my name is Tricky Reddy"},
    )


def test_extract_slot_value_falls_back_when_capability_raises(tmp_path):
    path = tmp_path / "x.yaml"
    path.write_text(textwrap.dedent("""
        workflow_name: x
        steps:
          - step_id: a
            ask: Whatever?
            slot: s
            extract_with: broken
    """), encoding="utf-8")
    tpl = WorkflowTemplateLoader(str(tmp_path)).load_all()["x"]
    executor = MagicMock()
    executor.execute.side_effect = RuntimeError("broken capability")
    compiler = WorkflowTemplateCompiler(registry=None)
    assert compiler.extract_slot_value(
        tpl.steps[0], "raw answer", capability_executor=executor,
    ) == "raw answer"


def test_extract_slot_value_refuses_non_ask_step(three_slot_template):
    compiler = WorkflowTemplateCompiler(registry=None)
    capability_step = three_slot_template.steps[3]  # save_profile
    with pytest.raises(CompileError, match="non-ask step"):
        compiler.extract_slot_value(capability_step, "anything")


# ----------------------------------------------------------------------
# End-to-end — 3 questions across 3 turns, then run the capability
# ----------------------------------------------------------------------

def test_end_to_end_three_turn_slot_fill(three_slot_template, tmp_path):
    """The Direction §5.2a exit test: a 3-slot YAML asks 3 questions
    across 3 turns, fills each slot, then runs the final capability with
    the collected slot values.
    """
    from core.workflow_orchestrator import TemplateWorkflow

    # Build a fake app with just the bits TemplateWorkflow.run_slot_fill_turn
    # needs: a memory_service / context_store that persists workflow state,
    # an ordered_tool_executor that records what plan was executed, and a
    # capability_executor (unused here because no extract_with).
    from core.stores import SessionStore, WorkflowStore, MemoryStore
    db = tmp_path / "friday.db"
    vec = tmp_path / "chroma"
    sess = SessionStore(str(db))
    wfs = WorkflowStore(str(db))
    mem = MemoryStore(str(db), str(vec))
    session_id = sess.start_session()

    # Tiny shim that exposes get_active_workflow / save_workflow_state, the
    # only memory APIs the slot-fill path touches.
    class _Memory:
        def get_active_workflow(self, sid, workflow_name=None):
            return wfs.get_active(sid, workflow_name)

        def save_workflow_state(self, sid, name, state):
            wfs.upsert(sid, name, state)

    captured = {}

    class _Executor:
        def execute(self, plan, user_text, turn=None):
            captured["plan"] = plan
            captured["user_text"] = user_text
            return "saved"

    app = SimpleNamespace(
        memory_service=_Memory(),
        context_store=_Memory(),  # fallback used by BaseWorkflow._memory()
        ordered_tool_executor=_Executor(),
        task_graph_executor=None,
        capability_executor=None,
        config=None,
    )

    compiler = WorkflowTemplateCompiler(registry=None)
    workflow = TemplateWorkflow(app, three_slot_template, compiler)

    # ---- Turn 0: starting the slot-fill (no user reply yet) ----
    r0 = workflow.start_slot_fill(session_id)
    assert r0.handled is True
    assert r0.response == "What's your name?"
    stored = wfs.get_active(session_id, "test_three_slot")
    assert stored["awaiting_slot"] == "user_name"
    assert stored["slots"] == {}

    # ---- Turn 1: user answers "Tricky Reddy" ----
    r1 = workflow.run_slot_fill_turn("Tricky Reddy", session_id)
    assert r1.response == "What's your favourite colour?"
    stored = wfs.get_active(session_id, "test_three_slot")
    assert stored["awaiting_slot"] == "user_color"
    assert stored["slots"] == {"user_name": "Tricky Reddy"}

    # ---- Turn 2: user answers "blue" ----
    r2 = workflow.run_slot_fill_turn("blue", session_id)
    assert r2.response == "What's your pet's name?"
    stored = wfs.get_active(session_id, "test_three_slot")
    assert stored["awaiting_slot"] == "user_pet"
    assert stored["slots"] == {"user_name": "Tricky Reddy", "user_color": "blue"}

    # ---- Turn 3: user answers "Rex" — all slots filled, capability runs ----
    r3 = workflow.run_slot_fill_turn("Rex", session_id)
    assert r3.response == "saved"
    assert "plan" in captured
    plan = captured["plan"]
    assert plan.mode == "tool"
    assert plan.steps[0].capability_name == "save_profile"
    assert plan.steps[0].args == {
        "name": "Tricky Reddy", "color": "blue", "pet": "Rex",
    }
    # Workflow is now completed; no longer active.
    final_state = wfs.get_active(session_id, "test_three_slot")
    assert final_state is None  # completed → not in 'active'/'pending' status


def test_can_continue_routes_slot_fill_resume(three_slot_template, tmp_path):
    """TemplateWorkflow.can_continue must return True while awaiting_slot
    is set so WorkflowOrchestrator.continue_active resumes the slot-fill.
    Once the workflow completes, can_continue returns False so the same
    template doesn't keep capturing turns.
    """
    from core.workflow_orchestrator import TemplateWorkflow

    workflow = TemplateWorkflow(
        SimpleNamespace(),
        three_slot_template,
        WorkflowTemplateCompiler(registry=None),
    )
    assert workflow.can_continue("anything", {
        "workflow_name": "test_three_slot",
        "awaiting_slot": "user_name",
    }) is True
    assert workflow.can_continue("anything", {
        "workflow_name": "test_three_slot",
        "status": "completed",
        "awaiting_slot": "",
    }) is False
    assert workflow.can_continue("anything", {
        "workflow_name": "different_workflow",
        "awaiting_slot": "user_name",
    }) is False
    assert workflow.can_continue("anything", {}) is False
