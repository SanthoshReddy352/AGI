"""Phase 8 tests — PlanArchive save/retrieve, MemoryBroker integration,
TemplateWorkflow archives successful runs."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory.embeddings import HashEmbedder
from core.memory.plan_archive import PlanArchive, PlanRecord
from core.turn_context import TurnContext, turn_scope


@pytest.fixture
def archive(tmp_path) -> PlanArchive:
    # Use the deterministic hash embedder so similarity is reproducible
    # without downloading the BGE model.
    return PlanArchive(str(tmp_path / "test.db"), embedder=HashEmbedder(dimensions=64))


# ---------------------------------------------------------------------------
# PlanArchive.save / retrieve_similar
# ---------------------------------------------------------------------------

def test_save_returns_row_id(archive):
    rid = archive.save(
        user_text="scan my lab subnet 192.168.56.0/24",
        workflow_name="lab_network_inventory",
        slot_values={"target_subnet": "192.168.56.0/24"},
        plan_shape=["ping_sweep", "host_service_scan"],
    )
    assert rid > 0


def test_save_rejects_empty_user_text(archive):
    rid = archive.save(user_text="", workflow_name="lab_network_inventory")
    assert rid == 0


def test_save_rejects_empty_workflow_name(archive):
    rid = archive.save(user_text="scan it", workflow_name="")
    assert rid == 0


def test_retrieve_similar_finds_exact_match(archive):
    archive.save(
        user_text="scan my lab subnet 192.168.56.0/24",
        workflow_name="lab_network_inventory",
        slot_values={"target_subnet": "192.168.56.0/24"},
        plan_shape=["ping_sweep", "host_service_scan"],
    )
    results = archive.retrieve_similar("scan my lab subnet 192.168.56.0/24", top_k=3)
    assert len(results) == 1
    assert results[0].workflow_name == "lab_network_inventory"
    # Hash embedder produces identical vectors for identical text → score ≈ 1.0.
    assert results[0].score == pytest.approx(1.0, abs=1e-6)


def test_retrieve_similar_filters_unapproved_runs(archive):
    archive.save(
        user_text="bad run",
        workflow_name="lab_network_inventory",
        user_approved=False,
    )
    archive.save(
        user_text="good run",
        workflow_name="lab_network_inventory",
        user_approved=True,
    )
    # Default filter: only_approved=True.
    results = archive.retrieve_similar("bad run", top_k=3)
    assert all(r.user_text == "good run" for r in results)


def test_retrieve_similar_filters_failed_runs(archive):
    archive.save(user_text="failed attempt", workflow_name="x", outcome="failure")
    archive.save(user_text="succeeded attempt", workflow_name="x", outcome="success")
    results = archive.retrieve_similar("failed attempt", top_k=3)
    assert all(r.outcome == "success" for r in results)


def test_retrieve_similar_respects_top_k(archive):
    for i in range(5):
        archive.save(
            user_text=f"scan target number {i}",
            workflow_name="lab_network_inventory",
        )
    results = archive.retrieve_similar("scan target number 0", top_k=2)
    assert len(results) == 2


def test_retrieve_similar_supports_workflow_filter(archive):
    archive.save(user_text="inventory", workflow_name="lab_network_inventory")
    archive.save(user_text="enumerate", workflow_name="web_app_recon_lab")
    results = archive.retrieve_similar(
        "inventory", top_k=5, workflow_name="lab_network_inventory",
    )
    assert all(r.workflow_name == "lab_network_inventory" for r in results)


def test_retrieve_similar_returns_empty_when_db_missing(tmp_path):
    archive = PlanArchive(
        str(tmp_path / "doesnotexist.db"),
        embedder=HashEmbedder(dimensions=64),
    )
    assert archive.retrieve_similar("anything") == []


def test_retrieve_similar_returns_empty_for_blank_query(archive):
    archive.save(user_text="some prior plan", workflow_name="x")
    assert archive.retrieve_similar("") == []


def test_record_to_exemplar_shape(archive):
    archive.save(
        user_text="scan 192.168.56.0/24",
        workflow_name="lab_network_inventory",
        slot_values={"target_subnet": "192.168.56.0/24"},
        plan_shape=["ping_sweep", "host_service_scan"],
    )
    r = archive.retrieve_similar("scan", top_k=1)[0]
    ex = r.to_exemplar()
    assert ex == {
        "task": "scan 192.168.56.0/24",
        "workflow": "lab_network_inventory",
        "filled_slots": {"target_subnet": "192.168.56.0/24"},
        "plan_shape": ["ping_sweep", "host_service_scan"],
        "outcome": "success",
    }


def test_all_includes_non_approved_records(archive):
    archive.save(user_text="a", workflow_name="x", user_approved=False)
    archive.save(user_text="b", workflow_name="x", user_approved=True, outcome="failure")
    archive.save(user_text="c", workflow_name="x", user_approved=True)
    rows = archive.all()
    assert {r.user_text for r in rows} == {"a", "b", "c"}


def test_schema_initialized_lazily(tmp_path):
    arch = PlanArchive(str(tmp_path / "lazy.db"), embedder=HashEmbedder(dimensions=64))
    # The DB file should not exist until first save.
    assert not (tmp_path / "lazy.db").exists()
    arch.save(user_text="something", workflow_name="x")
    assert (tmp_path / "lazy.db").exists()


# ---------------------------------------------------------------------------
# MemoryBroker integration — retrieved_examples appears in bundle
# ---------------------------------------------------------------------------

def test_memory_broker_returns_retrieved_examples_when_archive_wired(archive):
    from core.memory_broker import MemoryBroker

    archive.save(
        user_text="scan my lab subnet 192.168.56.0/24",
        workflow_name="lab_network_inventory",
        slot_values={"target_subnet": "192.168.56.0/24"},
        plan_shape=["ping_sweep", "host_service_scan"],
    )

    store = MagicMock()
    store.summarize_session.return_value = ""
    store.get_workflow_summary.return_value = ""
    store.semantic_recall.return_value = []
    store.recent_memory_items.return_value = []
    store.get_session_state.return_value = {}
    pm = MagicMock()
    pm.get_active_persona.return_value = {}

    broker = MemoryBroker(store, pm, plan_archive=archive)
    bundle = broker.build_context_bundle("scan my lab subnet 192.168.56.0/24", "s1")
    examples = bundle["retrieved_examples"]
    assert len(examples) == 1
    assert examples[0]["workflow"] == "lab_network_inventory"
    assert examples[0]["plan_shape"] == ["ping_sweep", "host_service_scan"]


def test_memory_broker_returns_empty_examples_without_archive():
    from core.memory_broker import MemoryBroker

    store = MagicMock()
    store.summarize_session.return_value = ""
    store.get_workflow_summary.return_value = ""
    store.semantic_recall.return_value = []
    store.recent_memory_items.return_value = []
    store.get_session_state.return_value = {}
    pm = MagicMock()
    pm.get_active_persona.return_value = {}

    broker = MemoryBroker(store, pm, plan_archive=None)
    bundle = broker.build_context_bundle("anything", "s1")
    assert bundle["retrieved_examples"] == []


def test_memory_broker_returns_empty_examples_for_empty_query(archive):
    from core.memory_broker import MemoryBroker

    archive.save(user_text="prior plan", workflow_name="x")
    store = MagicMock()
    store.summarize_session.return_value = ""
    store.get_workflow_summary.return_value = ""
    store.semantic_recall.return_value = []
    store.recent_memory_items.return_value = []
    store.get_session_state.return_value = {}
    pm = MagicMock()
    pm.get_active_persona.return_value = {}

    broker = MemoryBroker(store, pm, plan_archive=archive)
    bundle = broker.build_context_bundle("", "s1")
    assert bundle["retrieved_examples"] == []


# ---------------------------------------------------------------------------
# TemplateWorkflow archives on success; not on refuse/timeout
# ---------------------------------------------------------------------------

def _make_app_with_archive(tmp_path):
    from core.capability_registry import CapabilityRegistry
    from core.kernel.consent import ConsentService
    from core.planning.replan_controller import ReplanController

    app = MagicMock()
    reg = CapabilityRegistry()
    reg.register_tool(
        {"name": "ping_sweep", "description": "x", "parameters": {"subnet": "..."}},
        handler=lambda t, a: "ok",
        metadata={"side_effect_level": "read", "network_scope": "lab"},
    )
    reg.register_tool(
        {"name": "host_service_scan", "description": "x",
         "parameters": {"target": "...", "profile": "...", "ports": "..."}},
        handler=lambda t, a: "ok",
        metadata={"side_effect_level": "read", "network_scope": "lab"},
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
    app.consent_service = ConsentService()
    app.replan_controller = ReplanController(workflow_total_timeout_sec=60)
    app.event_bus = MagicMock()
    app.tts = MagicMock()
    app.comms = None
    app.plan_archive = PlanArchive(
        str(tmp_path / "wf.db"),
        embedder=HashEmbedder(dimensions=64),
    )
    return app


def test_workflow_archives_successful_run(tmp_path):
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_archive(tmp_path)
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    ctx = TurnContext(turn_id="t", session_id="sess1", trace_id="tr", source="voice",
                      text="scan my lab subnet 192.168.56.0/24")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success", "summary": "live host"}
        ctx.observations["s2"] = {"status": "success", "summary": "open port"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="sess1",
            user_text="scan my lab subnet 192.168.56.0/24",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "continue"
    rows = app.plan_archive.all()
    assert len(rows) == 1
    r = rows[0]
    assert r.workflow_name == "lab_network_inventory"
    assert r.slot_values == {"target_subnet": "192.168.56.0/24"}
    assert r.plan_shape == ["ping_sweep", "host_service_scan"]
    assert r.outcome == "success"
    assert r.user_approved is True
    assert r.session_id == "sess1"


def test_workflow_does_not_archive_refused_run(tmp_path):
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_archive(tmp_path)
    app.ordered_tool_executor.execute.side_effect = ["refused"]
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="voice", text="x")
    with turn_scope(ctx):
        ctx.observations["s1"] = {
            "status": "failure",
            "errors": ["target out of scope"],
        }
        orch = WorkflowOrchestrator(app)
        orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "8.8.8.0/24"},
            session_id="s",
            user_text="scan 8.8.8.0/24",
            with_replanning=True,
        )
    assert app.plan_archive.all() == []


def test_workflow_does_not_archive_run_without_user_text(tmp_path):
    """A workflow run with no original user text (e.g. resume flow) must
    not pollute the archive with empty-string embeddings."""
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_archive(tmp_path)
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="voice", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success"}
        ctx.observations["s2"] = {"status": "success"}
        orch = WorkflowOrchestrator(app)
        orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            user_text="",
            with_replanning=True,
        )
    assert app.plan_archive.all() == []


def test_workflow_archive_disabled_when_app_has_no_archive(tmp_path):
    """A workflow with no app.plan_archive must still complete successfully
    — the archive is optional, not required."""
    from core.workflow_orchestrator import WorkflowOrchestrator

    app = _make_app_with_archive(tmp_path)
    app.plan_archive = None
    app.ordered_tool_executor.execute.side_effect = ["sweep ok", "scan ok"]
    ctx = TurnContext(turn_id="t", session_id="s", trace_id="tr", source="voice", text="x")
    with turn_scope(ctx):
        ctx.observations["s1"] = {"status": "success"}
        ctx.observations["s2"] = {"status": "success"}
        orch = WorkflowOrchestrator(app)
        result = orch.run_template(
            "lab_network_inventory",
            slots={"target_subnet": "192.168.56.0/24"},
            session_id="s",
            user_text="x",
            with_replanning=True,
        )
    assert result.state["final_decision"] == "continue"


# ---------------------------------------------------------------------------
# End-to-end: save → retrieve → exemplar → QwenPlanner prompt injection
# ---------------------------------------------------------------------------

def test_retrieved_examples_flow_into_qwen_prompt(archive):
    """Confirms the prompt template actually renders the exemplar list."""
    from core.planning.qwen_planner import QwenPlanner
    import jinja2 as _j2

    archive.save(
        user_text="inventory my lab subnet 192.168.56.0/24",
        workflow_name="lab_network_inventory",
        slot_values={"target_subnet": "192.168.56.0/24"},
        plan_shape=["ping_sweep", "host_service_scan"],
    )
    examples = [r.to_exemplar() for r in archive.retrieve_similar("inventory subnet")]
    assert examples, "archive should return at least one exemplar"

    # Render plan_draft.j2 directly (planner is not actually invoked).
    env = _j2.Environment(
        loader=_j2.FileSystemLoader(os.path.join(
            os.path.dirname(__file__), "..", "core", "planning", "prompts",
        )),
        autoescape=False,
    )
    rendered = env.get_template("plan_draft.j2").render(
        user_text="inventory my subnet",
        capabilities=[],
        target_context="",
        permission_context="",
        retrieved_examples=examples,
    )
    assert "Similar prior approved plans" in rendered
    assert "inventory my lab subnet" in rendered
    assert "ping_sweep -> host_service_scan" in rendered
