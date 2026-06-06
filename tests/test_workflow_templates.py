"""Phase 2 tests — YAML workflow templates, loader, compiler, TemplateWorkflow."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.capability_broker import ToolPlan
from core.capability_registry import CapabilityRegistry
from core.workflows import (
    CompileError,
    TemplateError,
    WorkflowTemplate,
    WorkflowTemplateCompiler,
    WorkflowTemplateLoader,
    default_template_dir,
    load_templates,
)


TEMPLATE_DIR = Path(default_template_dir())


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def test_loader_discovers_bundled_templates():
    templates = load_templates()
    assert "lab_network_inventory" in templates
    assert "own_machine_open_services" in templates
    assert "web_app_recon_lab" in templates
    assert "dns_enum_owned_domain" in templates
    assert "report_from_scan_artifacts" in templates
    assert "compare_two_scan_results" in templates


def test_loader_parses_steps_and_dependencies():
    templates = load_templates()
    inv = templates["lab_network_inventory"]
    assert inv.required_inputs == ["target_subnet"]
    assert [s.step_id for s in inv.steps] == ["s1", "s2"]
    assert inv.steps[1].depends_on == ["s1"]
    assert inv.steps[0].capability == "ping_sweep"
    assert inv.steps[1].capability == "host_service_scan"


def test_loader_rejects_template_with_forward_reference(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "workflow_name: bad\n"
        "steps:\n"
        "  - step_id: s1\n"
        "    capability: foo\n"
        "    depends_on: [s99]\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError) as exc:
        WorkflowTemplateLoader(tmp_path).load_all()
    assert "depends on unknown" in str(exc.value)


def test_loader_rejects_duplicate_step_id(tmp_path):
    bad = tmp_path / "dup.yaml"
    bad.write_text(
        "workflow_name: dup\n"
        "steps:\n"
        "  - { step_id: s1, capability: a }\n"
        "  - { step_id: s1, capability: b }\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError) as exc:
        WorkflowTemplateLoader(tmp_path).load_all()
    assert "duplicate step_id" in str(exc.value)


def test_loader_rejects_duplicate_workflow_name(tmp_path):
    (tmp_path / "a.yaml").write_text(
        "workflow_name: same\nsteps: [{step_id: s1, capability: x}]\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "workflow_name: same\nsteps: [{step_id: s1, capability: y}]\n",
        encoding="utf-8",
    )
    with pytest.raises(TemplateError) as exc:
        WorkflowTemplateLoader(tmp_path).load_all()
    assert "duplicate workflow_name" in str(exc.value)


def test_loader_requires_top_level_keys(tmp_path):
    (tmp_path / "missing.yaml").write_text("steps: []\n", encoding="utf-8")
    with pytest.raises(TemplateError):
        WorkflowTemplateLoader(tmp_path).load_all()


# ---------------------------------------------------------------------------
# Compiler — substitution and validation
# ---------------------------------------------------------------------------

def _registry_with(*names: str) -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for n in names:
        reg.register_tool(
            {"name": n, "description": f"{n} stub", "parameters": {}},
            handler=lambda text, args, _n=n: f"{_n}:{args}",
        )
    return reg


def test_compiler_substitutes_required_slot():
    reg = _registry_with("host_service_scan")
    tpl = load_templates()["own_machine_open_services"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    compiled = compiler.compile(tpl, {"target_host": "10.0.0.5"}, turn_id="t1")
    assert compiled.missing_slots == []
    plan = compiled.plan
    assert isinstance(plan, ToolPlan)
    assert plan.mode == "tool"
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.capability_name == "host_service_scan"
    assert step.args["target"] == "10.0.0.5"
    assert step.args["profile"] == "quick"   # default fallback


def test_compiler_uses_default_for_missing_optional():
    reg = _registry_with("host_service_scan")
    tpl = load_templates()["own_machine_open_services"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    compiled = compiler.compile(tpl, {"target_host": "127.0.0.1"})
    assert compiled.plan.steps[0].args["profile"] == "quick"


def test_compiler_reports_missing_required_slots():
    reg = _registry_with("ping_sweep", "host_service_scan")
    tpl = load_templates()["lab_network_inventory"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    compiled = compiler.compile(tpl, {})
    assert compiled.missing_slots == ["target_subnet"]
    assert compiled.plan.mode == "clarify"
    assert "target_subnet" in compiled.plan.reply


def test_compiler_carries_step_output_references_unchanged():
    reg = _registry_with("ping_sweep", "host_service_scan")
    tpl = load_templates()["lab_network_inventory"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    compiled = compiler.compile(tpl, {"target_subnet": "192.168.56.0/24"})
    plan = compiled.plan
    assert len(plan.steps) == 2
    # ${s1.first_live_host} must be carried verbatim — the executor
    # injects upstream output at runtime.
    assert "${s1.first_live_host}" in plan.steps[1].args["target"]
    assert plan.steps[1].depends_on == ["s1"]
    # DAG node_id preserved.
    assert plan.steps[0].node_id == "s1"
    assert plan.steps[1].node_id == "s2"


def test_compiler_rejects_unknown_capability():
    reg = _registry_with("ping_sweep")    # host_service_scan absent
    tpl = load_templates()["lab_network_inventory"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    with pytest.raises(CompileError) as exc:
        compiler.compile(tpl, {"target_subnet": "10.0.0.0/24"})
    assert "host_service_scan" in str(exc.value)


def test_compiler_works_without_registry():
    """Compiler should run even if no registry is provided (skips capability
    existence check). Useful for tests that only want substitution output."""
    tpl = load_templates()["own_machine_open_services"]
    compiler = WorkflowTemplateCompiler(registry=None)
    compiled = compiler.compile(tpl, {"target_host": "127.0.0.1"})
    assert compiled.plan.steps[0].args["target"] == "127.0.0.1"


def test_compiler_propagates_descriptor_side_effect_level():
    reg = CapabilityRegistry()
    reg.register_tool(
        {"name": "host_service_scan", "description": "x", "parameters": {}},
        handler=lambda t, a: "ok",
        metadata={"side_effect_level": "read", "connectivity": "local"},
    )
    tpl = load_templates()["own_machine_open_services"]
    compiler = WorkflowTemplateCompiler(registry=reg)
    compiled = compiler.compile(tpl, {"target_host": "127.0.0.1"})
    assert compiled.plan.steps[0].side_effect_level == "read"
    assert compiled.plan.steps[0].connectivity == "local"


# ---------------------------------------------------------------------------
# TemplateWorkflow integration through WorkflowOrchestrator
# ---------------------------------------------------------------------------

def _make_fake_app():
    """A minimal stand-in app for orchestrator construction."""
    app = MagicMock()
    app.capability_registry = _registry_with("ping_sweep", "host_service_scan")
    # ContextStore stand-in: get_active_workflow returns None.
    app.context_store = MagicMock()
    app.context_store.get_active_workflow.return_value = None
    app.memory_service = None
    # Executors
    app.ordered_tool_executor = MagicMock()
    app.ordered_tool_executor.execute.return_value = "ordered-executed"
    app.task_graph_executor = MagicMock()
    app.task_graph_executor.execute.return_value = "graph-executed"
    # Config: parallel engine enabled
    app.config = MagicMock()
    app.config.get.side_effect = lambda key: {
        "routing.execution_engine": "parallel",
    }.get(key)
    return app


def test_orchestrator_registers_yaml_templates_at_startup():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    assert "lab_network_inventory" in orch.list_templates()
    assert "own_machine_open_services" in orch.list_templates()


def test_orchestrator_run_template_single_step_uses_ordered_executor():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    result = orch.run_template(
        "own_machine_open_services",
        slots={"target_host": "127.0.0.1"},
        session_id="s",
        turn_id="t1",
    )
    assert result.handled is True
    assert result.response == "ordered-executed"
    app.ordered_tool_executor.execute.assert_called_once()
    app.task_graph_executor.execute.assert_not_called()


def test_orchestrator_run_template_multi_step_uses_graph_executor():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    result = orch.run_template(
        "lab_network_inventory",
        slots={"target_subnet": "192.168.56.0/24"},
        session_id="s",
        turn_id="t1",
    )
    assert result.handled is True
    assert result.response == "graph-executed"
    app.task_graph_executor.execute.assert_called_once()
    app.ordered_tool_executor.execute.assert_not_called()


def test_orchestrator_run_template_missing_slots_does_not_execute():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    result = orch.run_template(
        "lab_network_inventory",
        slots={},                       # no target_subnet
        session_id="s",
        turn_id="t1",
    )
    assert result.handled is True
    assert "target_subnet" in result.response
    app.ordered_tool_executor.execute.assert_not_called()
    app.task_graph_executor.execute.assert_not_called()


def test_orchestrator_unknown_template_returns_unhandled():
    from core.workflow_orchestrator import WorkflowOrchestrator
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    result = orch.run_template("does_not_exist", slots={}, session_id="s")
    assert result.handled is False
    assert "Unknown workflow template" in result.response


def test_orchestrator_skips_yaml_load_when_directory_empty(tmp_path, monkeypatch):
    """Empty templates dir is fine — no templates registered, no crash."""
    from core.workflows import template_loader
    from core.workflow_orchestrator import WorkflowOrchestrator
    monkeypatch.setattr(template_loader, "default_template_dir", lambda: str(tmp_path))
    app = _make_fake_app()
    orch = WorkflowOrchestrator(app)
    assert orch.list_templates() == []
