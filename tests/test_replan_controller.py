"""Phase 6 tests — ReplanController decision rules + step-at-a-time
workflow runner."""
from __future__ import annotations

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.planning.replan_controller import (
    DEFAULT_MAX_STEP_RETRIES,
    DEFAULT_MAX_WORKFLOW_STEPS,
    ReplanController,
    StepRunState,
    WorkflowRunState,
)
from core.planning.schemas import ReplanDecision


def _controller(**kwargs) -> ReplanController:
    defaults = dict(
        max_workflow_steps=DEFAULT_MAX_WORKFLOW_STEPS,
        max_step_retries=DEFAULT_MAX_STEP_RETRIES,
        workflow_total_timeout_sec=60,
    )
    defaults.update(kwargs)
    return ReplanController(**defaults)


# ---------------------------------------------------------------------------
# Deterministic decisions
# ---------------------------------------------------------------------------

def test_success_status_yields_continue():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {"status": "success"}, step_id="s1")
    assert d.decision == "continue"
    assert d.confidence == 1.0


def test_partial_status_yields_continue():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {"status": "partial"}, step_id="s1")
    assert d.decision == "continue"


def test_timeout_with_budget_retries_with_bumped_timeout():
    c = _controller(max_step_retries=2)
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {"status": "timeout"}, step_id="s1",
                      original_args={"timeout_sec": 30, "target": "127.0.0.1"})
    assert d.decision == "retry"
    assert d.next_step_id == "s1"
    assert d.updated_args["timeout_sec"] == 60     # doubled
    assert d.updated_args["target"] == "127.0.0.1"
    assert state.step_state("s1").retries_used == 1


def test_timeout_after_retry_budget_stops():
    c = _controller(max_step_retries=1)
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    state.step_state("s1").retries_used = 1  # already spent the budget
    d = c.decide_next(state, {"status": "timeout"}, step_id="s1",
                      original_args={})
    assert d.decision == "stop"
    assert "timeout" in d.reason_summary.lower()


def test_scope_error_yields_refuse():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["target out of scope: 8.8.8.8 is public"],
    }, step_id="s1")
    assert d.decision == "refuse"
    assert "scope" in d.reason_summary.lower()


def test_authorization_error_yields_refuse():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["unauthorized target"],
    }, step_id="s1")
    assert d.decision == "refuse"


def test_missing_input_error_yields_ask_user():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["wordlist not found: /missing/path"],
    }, step_id="s_enum")
    assert d.decision == "ask_user"
    assert d.next_step_id == "s_enum"
    assert "wordlist" in d.question.lower() or "info" in d.question.lower()


def test_transient_error_retries_with_unchanged_args():
    c = _controller(max_step_retries=2)
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["connection reset by peer; retryable"],
    }, step_id="s1", original_args={"target": "127.0.0.1"})
    assert d.decision == "retry"
    assert d.updated_args == {"target": "127.0.0.1"}
    assert state.step_state("s1").retries_used == 1


def test_unclassified_failure_stops_when_no_planner():
    c = _controller()
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["weird internal goblin"],
    }, step_id="s1")
    assert d.decision == "stop"


def test_unclassified_failure_escalates_to_qwen_planner():
    qwen = MagicMock()
    qwen.replan.return_value = ReplanDecision(
        decision="ask_user", question="Which subnet?",
        reason_summary="model needs clarification", confidence=0.7,
    )
    c = _controller(qwen_planner=qwen)
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure",
        "errors": ["weird internal goblin"],
    }, step_id="s1")
    assert d.decision == "ask_user"
    assert "Which subnet" in d.question
    qwen.replan.assert_called_once()


def test_step_cap_forces_stop():
    c = _controller(max_workflow_steps=3)
    state = WorkflowRunState(workflow_name="x", total_steps=3)
    d = c.decide_next(state, {"status": "success"}, step_id="s1")
    assert d.decision == "stop"
    assert "cap" in d.reason_summary.lower()


def test_total_timeout_forces_stop():
    c = _controller(workflow_total_timeout_sec=0)   # immediate
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    # Sleep to ensure elapsed > 0 even at fast clocks.
    time.sleep(0.01)
    d = c.decide_next(state, {"status": "success"}, step_id="s1")
    assert d.decision == "stop"
    assert "wall-clock" in d.reason_summary.lower()


def test_qwen_planner_exception_falls_back_to_stop():
    qwen = MagicMock()
    qwen.replan.side_effect = RuntimeError("model died")
    c = _controller(qwen_planner=qwen)
    state = WorkflowRunState(workflow_name="x", total_steps=1)
    d = c.decide_next(state, {
        "status": "failure", "errors": ["weird"],
    }, step_id="s1")
    assert d.decision == "stop"


def test_bump_timeout_doubles_existing_timeout_keys():
    out = ReplanController._bump_timeout_args(
        {"timeout_sec": 30, "timeout_ms": 1000, "target": "127.0.0.1"}
    )
    assert out["timeout_sec"] == 60
    assert out["timeout_ms"] == 2000
    assert out["target"] == "127.0.0.1"


def test_bump_timeout_does_not_add_key_when_absent():
    out = ReplanController._bump_timeout_args({"target": "127.0.0.1"})
    assert "timeout_sec" not in out
    assert "timeout_ms" not in out


# ---------------------------------------------------------------------------
# TemplateWorkflow.run_with_replanning — full step-at-a-time loop
# ---------------------------------------------------------------------------

def _make_app_with_security_registry():
    """Build a fake app with a CapabilityRegistry containing ping_sweep
    and host_service_scan, plus mocked executors and config."""
    from core.capability_registry import CapabilityRegistry

    app = MagicMock()
    reg = CapabilityRegistry()
    reg.register_tool(
        {"name": "ping_sweep", "description": "x", "parameters": {"subnet": "..."}},
        handler=lambda t, a: "ok",
    )
    reg.register_tool(
        {"name": "host_service_scan",
         "description": "x",
         "parameters": {"target": "...", "profile": "...", "ports": "..."}},
        handler=lambda t, a: "ok",
    )
    app.capability_registry = reg
    app.config = MagicMock()
    app.config.get.side_effect = lambda key: {
        "routing.execution_engine": "ordered",
        "routing.use_replanning": True,
        "routing.max_workflow_steps": 12,
        "routing.max_step_retries": 2,
        "routing.workflow_total_timeout_sec": 60,
    }.get(key)
    app.ordered_tool_executor = MagicMock()
    app.task_graph_executor = MagicMock()
    app.context_store = MagicMock()
    app.context_store.get_active_workflow.return_value = None
    app.memory_service = None
    return app


def test_run_with_replanning_completes_all_steps_on_success():
    from core.turn_context import TurnContext, turn_scope
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    app.replan_controller = _controller()

    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="cli", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success", "summary": "live host"}
        ctx.observations["s2"] = {"status": "success", "summary": "open port"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.handled is True
    assert "sweep ok" in result.response
    assert "scan ok" in result.response
    assert result.state["final_decision"] == "continue"
    assert result.state["total_steps"] == 2
    assert app.ordered_tool_executor.execute.call_count == 2


def test_run_with_replanning_stops_on_refuse_observation():
    from core.turn_context import TurnContext, turn_scope
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.side_effect = ["refused"]
    app.replan_controller = _controller()

    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="cli", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {
            "status": "failure",
            "errors": ["target out of scope"],
        }
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "8.8.8.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "refuse"
    assert app.ordered_tool_executor.execute.call_count == 1   # never reached s2


def test_run_with_replanning_retries_on_timeout_then_succeeds():
    from core.turn_context import TurnContext, turn_scope
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.replan_controller = _controller(max_step_retries=2)

    responses = ["timed out", "live host", "scan ok"]
    observations = [
        {"status": "timeout", "summary": "timed out"},
        {"status": "success", "summary": "live host"},
        {"status": "success", "summary": "open port"},
    ]
    call_count = {"n": 0}

    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="cli", text="")
    with turn_scope(ctx):
        def fake_execute(plan, text, turn=None):
            step_id = plan.steps[0].node_id
            ctx.observations[step_id] = observations[call_count["n"]]
            response = responses[call_count["n"]]
            call_count["n"] += 1
            return response

        app.ordered_tool_executor.execute = MagicMock(side_effect=fake_execute)

        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )

    assert result.state["final_decision"] == "continue"
    # s1 attempted twice (timeout → retry → success), then s2 once.
    assert app.ordered_tool_executor.execute.call_count == 3
    assert result.state["retries_by_step"]["s1"] == 1


def test_run_with_replanning_falls_back_to_one_shot_when_no_controller():
    """Without a replan_controller, run_with_replanning() must defer
    to run_with_slots() so existing behavior is preserved."""
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.return_value = "one-shot"
    app.replan_controller = None   # no controller

    orch = WorkflowOrchestrator(app)
    # Use the single-step template so the executor is invoked once via the
    # ordered path.
    result = orch.run_template(
        "own_machine_open_services",
        slots={"target_host": "127.0.0.1"},
        session_id="s",
        with_replanning=True,
    )
    assert result.handled is True
    assert "one-shot" in result.response


def test_run_with_replanning_clarify_when_required_slot_missing():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_app_with_security_registry()
    app.replan_controller = _controller()
    orch = WorkflowOrchestrator(app)

    result = orch.run_template(
        "lab_network_inventory",
        slots={},   # no target_subnet
        session_id="s",
        with_replanning=True,
    )
    assert result.handled is True
    assert "target_subnet" in result.response
    app.ordered_tool_executor.execute.assert_not_called()


def test_run_with_replanning_stops_at_step_cap():
    """Synthetic: a 2-step plan with max_workflow_steps=1 must stop after
    the first step regardless of decision payload."""
    from core.turn_context import TurnContext, turn_scope
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_security_registry()
    app.ordered_tool_executor.execute.side_effect = ["ok"]
    app.replan_controller = _controller(max_workflow_steps=1)

    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="cli", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "stop"
    assert app.ordered_tool_executor.execute.call_count == 1
