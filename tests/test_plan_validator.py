"""Phase 4 tests — PlanValidator, PlanRepair, bridge_v2_to_runtime, and the
TurnOrchestrator validator hook."""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.capability_broker import ToolPlan, ToolStep
from core.capability_registry import CapabilityRegistry
from core.planning.plan_repair import PlanRepair, bridge_v2_to_runtime
from core.planning.plan_validator import (
    PlanValidator,
    RunContext,
    SEVERITY_FATAL,
    SEVERITY_REPAIRABLE,
)
from core.planning.schemas import ToolPlanStep, ToolPlanV2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_security_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register_tool(
        {
            "name": "host_service_scan",
            "description": "Read-only service scan",
            "parameters": {"target": "...", "profile": "...", "ports": "..."},
        },
        handler=lambda t, a: "ok",
        metadata={
            "side_effect_level": "read",
            "connectivity": "local",
            "network_scope": "lab",
            "requires_authorization": True,
        },
    )
    reg.register_tool(
        {
            "name": "ping_sweep",
            "description": "Host discovery",
            "parameters": {"subnet": "..."},
        },
        handler=lambda t, a: "ok",
        metadata={
            "side_effect_level": "read",
            "connectivity": "local",
            "network_scope": "lab",
            "requires_authorization": True,
        },
    )
    return reg


def _plan(*steps: ToolStep, mode: str = "tool") -> ToolPlan:
    return ToolPlan(turn_id="t1", mode=mode, steps=list(steps))


# ---------------------------------------------------------------------------
# PlanValidator
# ---------------------------------------------------------------------------

def test_validator_passes_non_tool_plan_modes():
    v = PlanValidator(_build_security_registry())
    for mode in ("reply", "clarify", "refuse", "delegate", "planner"):
        result = v.validate(_plan(mode=mode))
        assert result.valid is True


def test_validator_passes_well_formed_lab_plan():
    reg = _build_security_registry()
    v = PlanValidator(reg)
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "192.168.56.10"},
                 side_effect_level="read",
                 node_id="s1"),
    )
    run = RunContext(authorized_scopes=["192.168.56.0/24"])
    result = v.validate(plan, run)
    assert result.valid is True
    assert result.issues == []


def test_validator_flags_unknown_capability():
    v = PlanValidator(_build_security_registry())
    plan = _plan(ToolStep(capability_name="bogus_thing", args={}, node_id="s1"))
    result = v.validate(plan)
    assert result.valid is False
    codes = {i.code for i in result.issues}
    assert "unknown_capability" in codes


def test_validator_flags_unknown_arg_as_repairable():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "127.0.0.1", "made_up": "yes"},
                 node_id="s1"),
    )
    result = v.validate(plan)
    repairables = [i for i in result.issues if i.severity == SEVERITY_REPAIRABLE]
    assert any(i.code == "unknown_arg" and "made_up" in i.message for i in repairables)


def test_validator_does_not_flag_upstream_injection_keys_as_unknown_args():
    """When a step has an arg keyed by an upstream node_id (which is how the
    executor injects results), the validator must not call it 'unknown_arg'."""
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="ping_sweep",
                 args={"subnet": "192.168.56.0/24"},
                 node_id="s1"),
        ToolStep(capability_name="host_service_scan",
                 args={"target": "192.168.56.10", "s1": ""},   # 's1' is upstream injection
                 depends_on=["s1"],
                 node_id="s2"),
    )
    run = RunContext(authorized_scopes=["192.168.56.0/24"])
    result = v.validate(plan, run)
    assert result.valid is True
    assert all(i.code != "unknown_arg" for i in result.issues)


def test_validator_detects_dependency_cycle():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="ping_sweep", args={"subnet": "192.168.56.0/24"},
                 node_id="a", depends_on=["b"]),
        ToolStep(capability_name="ping_sweep", args={"subnet": "192.168.56.0/24"},
                 node_id="b", depends_on=["a"]),
    )
    result = v.validate(plan, RunContext(authorized_scopes=["192.168.56.0/24"]))
    assert result.valid is False
    assert any(i.code == "dependency_cycle" for i in result.issues)


def test_validator_flags_forward_dependency_reference():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="ping_sweep",
                 args={"subnet": "192.168.56.0/24"},
                 node_id="s1",
                 depends_on=["does_not_exist"]),
    )
    result = v.validate(plan, RunContext(authorized_scopes=["192.168.56.0/24"]))
    assert result.valid is False
    assert any(i.code == "unknown_dependency" for i in result.issues)


def test_validator_blocks_public_target_under_lab_scope_capability():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "8.8.8.8"},
                 node_id="s1"),
    )
    result = v.validate(plan, RunContext(authorized_scopes=["192.168.56.0/24"]))
    assert result.valid is False
    assert any(i.code == "scope_violation" for i in result.issues)


def test_validator_blocks_target_outside_authorized_scopes_list():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "10.99.0.5"},     # RFC1918 but NOT in allowlist
                 node_id="s1"),
    )
    result = v.validate(plan, RunContext(authorized_scopes=["192.168.56.0/24"]))
    assert result.valid is False
    assert any(i.code == "unauthorized_target" for i in result.issues)


def test_validator_blocks_dangerous_flag_in_args():
    v = PlanValidator(_build_security_registry())
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "127.0.0.1", "profile": "quick --script vuln"},
                 node_id="s1"),
    )
    result = v.validate(plan)
    assert result.valid is False
    assert any(i.code == "dangerous_flag" for i in result.issues)


def test_validator_enforces_risk_ceiling():
    reg = _build_security_registry()
    v = PlanValidator(reg)
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "192.168.56.10"},
                 side_effect_level="critical",
                 node_id="s1"),
    )
    result = v.validate(plan, RunContext(
        authorized_scopes=["192.168.56.0/24"],
        user_risk_ceiling="read",
    ))
    assert result.valid is False
    assert any(i.code == "risk_exceeded" for i in result.issues)


# ---------------------------------------------------------------------------
# PlanRepair
# ---------------------------------------------------------------------------

def test_repair_drops_unknown_arg_key():
    reg = _build_security_registry()
    v = PlanValidator(reg)
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "127.0.0.1", "ghost_arg": "x"},
                 node_id="s1"),
    )
    result = v.validate(plan)
    assert any(i.code == "unknown_arg" for i in result.issues)

    repaired, remaining = PlanRepair(reg).try_repair(plan, result)
    assert "ghost_arg" not in repaired.steps[0].args
    assert "target" in repaired.steps[0].args
    assert not any(i.code == "unknown_arg" for i in remaining)


def test_repair_normalizes_side_effect_typos():
    reg = _build_security_registry()
    v = PlanValidator(reg)
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "127.0.0.1"},
                 side_effect_level="readonly",       # variant the LLM might use
                 node_id="s1"),
    )
    result = v.validate(plan)
    repaired, _ = PlanRepair(reg).try_repair(plan, result)
    assert repaired.steps[0].side_effect_level == "read"


def test_repair_leaves_fatal_issues_untouched():
    reg = _build_security_registry()
    v = PlanValidator(reg)
    plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "8.8.8.8"},          # fatal scope violation
                 node_id="s1"),
    )
    result = v.validate(plan, RunContext(authorized_scopes=["192.168.56.0/24"]))
    repaired, remaining = PlanRepair(reg).try_repair(plan, result)
    # Fatal issue remains; the repair does not silently change scope.
    assert any(i.code == "scope_violation" for i in remaining)
    assert repaired.steps[0].args["target"] == "8.8.8.8"


# ---------------------------------------------------------------------------
# bridge_v2_to_runtime
# ---------------------------------------------------------------------------

def test_bridge_v2_tool_plan_to_runtime():
    reg = _build_security_registry()
    v2 = ToolPlanV2(
        mode="tool",
        steps=[
            ToolPlanStep(
                step_id="s1",
                capability="ping_sweep",
                args={"subnet": "192.168.56.0/24"},
            ),
            ToolPlanStep(
                step_id="s2",
                capability="host_service_scan",
                args={"target": "${s1.first_live_host}", "profile": "quick"},
                depends_on=["s1"],
            ),
        ],
        confidence=0.9,
    )
    runtime = bridge_v2_to_runtime(v2, turn_id="t1", registry=reg)
    assert runtime.mode == "tool"
    assert len(runtime.steps) == 2
    assert runtime.steps[0].node_id == "s1"
    assert runtime.steps[1].depends_on == ["s1"]
    assert runtime.steps[1].connectivity == "local"          # from descriptor
    assert runtime.steps[1].side_effect_level == "read"      # from V2 default


def test_bridge_clarify_becomes_reply():
    v2 = ToolPlanV2(
        mode="clarify",
        ask_user="Which target?",
        confidence=0.3,
    )
    runtime = bridge_v2_to_runtime(v2, turn_id="t1")
    assert runtime.mode == "reply"
    assert "Which target?" in runtime.reply


def test_bridge_refuse_becomes_reply():
    v2 = ToolPlanV2(
        mode="refuse",
        safety_notes=["public target out of scope"],
        confidence=0.95,
    )
    runtime = bridge_v2_to_runtime(v2, turn_id="t1")
    assert runtime.mode == "reply"
    assert "public target" in runtime.reply


# ---------------------------------------------------------------------------
# TurnOrchestrator integration — validator hook
# ---------------------------------------------------------------------------

def test_turn_orchestrator_short_circuits_on_fatal_validation():
    """A plan with a fatal scope violation must produce a refusal TurnResponse
    and never reach the executor."""
    from core.planning.turn_orchestrator import TurnOrchestrator, TurnRequest

    reg = _build_security_registry()
    bad_plan = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "8.8.8.8"},
                 node_id="s1"),
    )

    app = MagicMock()
    app.capability_registry = reg
    app.config = MagicMock()
    app.config.get.side_effect = lambda k: {"security.authorized_scopes": ["192.168.56.0/24"]}.get(k)
    app.ordered_tool_executor = MagicMock()
    app.ordered_tool_executor.execute.return_value = "EXECUTED"
    app.task_graph_executor = MagicMock()
    app.task_graph_executor.execute.return_value = "EXECUTED"
    app.conversation_agent = None
    app.memory_broker = None
    app.memory_service = None
    app.capability_broker = MagicMock()
    app.capability_broker.check_pending_confirmation.return_value = None

    intent_engine = MagicMock()
    intent_engine.classify.return_value = MagicMock(confidence=0.5)
    planner_engine = MagicMock()
    planner_engine.plan.return_value = bad_plan
    workflow_coordinator = MagicMock()
    workflow_coordinator.try_resume.return_value = MagicMock(handled=False)

    orch = TurnOrchestrator(app, intent_engine, planner_engine, workflow_coordinator)
    resp = orch.handle(TurnRequest(text="scan 8.8.8.8"))

    assert resp.plan_mode == "refuse"
    assert "can't run" in resp.response.lower()
    app.ordered_tool_executor.execute.assert_not_called()
    app.task_graph_executor.execute.assert_not_called()


def test_turn_orchestrator_repairs_then_runs():
    """A plan with only repairable issues (unknown arg) should be repaired
    in place and still execute."""
    from core.planning.turn_orchestrator import TurnOrchestrator, TurnRequest

    reg = _build_security_registry()
    plan_with_ghost_arg = _plan(
        ToolStep(capability_name="host_service_scan",
                 args={"target": "192.168.56.10", "ghost_arg": "x"},
                 node_id="s1"),
    )

    app = MagicMock()
    app.capability_registry = reg
    app.config = MagicMock()
    app.config.get.side_effect = lambda k: {"security.authorized_scopes": ["192.168.56.0/24"]}.get(k)
    app.ordered_tool_executor = MagicMock()
    app.ordered_tool_executor.execute.return_value = "ok"
    app.conversation_agent = None
    app.memory_broker = None
    app.memory_service = None

    intent_engine = MagicMock()
    intent_engine.classify.return_value = MagicMock(confidence=0.5)
    planner_engine = MagicMock()
    planner_engine.plan.return_value = plan_with_ghost_arg
    workflow_coordinator = MagicMock()
    workflow_coordinator.try_resume.return_value = MagicMock(handled=False)

    orch = TurnOrchestrator(app, intent_engine, planner_engine, workflow_coordinator)
    resp = orch.handle(TurnRequest(text="scan 192.168.56.10"))

    # Executed and not refused — the ghost_arg got dropped.
    assert resp.plan_mode != "refuse"
    app.ordered_tool_executor.execute.assert_called_once()
    sent_plan = app.ordered_tool_executor.execute.call_args.args[0]
    assert "ghost_arg" not in sent_plan.steps[0].args
