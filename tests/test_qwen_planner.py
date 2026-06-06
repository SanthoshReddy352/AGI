"""Phase 3 tests — Pydantic schemas, JSON repair, QwenPlanner with mocked model."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.planning.json_repair import repair_and_parse
from core.planning.qwen_planner import QwenPlanner, QwenPlannerError
from core.planning.schemas import (
    IntentClassification,
    Observation,
    ReplanDecision,
    SlotFill,
    ToolPlanV2,
    WorkflowSelection,
)


# ---------------------------------------------------------------------------
# JSON repair
# ---------------------------------------------------------------------------

def test_repair_parses_clean_json():
    assert repair_and_parse('{"a": 1}') == {"a": 1}


def test_repair_strips_markdown_fence():
    assert repair_and_parse('```json\n{"a": 1}\n```') == {"a": 1}
    assert repair_and_parse('```{"a":1}```') == {"a": 1}


def test_repair_strips_think_block():
    raw = "<think>let me think</think>\n{\"a\": 1}"
    assert repair_and_parse(raw) == {"a": 1}


def test_repair_strips_leading_prose():
    raw = 'Here is the JSON: {"intent_type":"chat","confidence":0.9}'
    out = repair_and_parse(raw)
    assert out["intent_type"] == "chat"


def test_repair_handles_trailing_comma():
    assert repair_and_parse('{"a":1, "b":2,}') == {"a": 1, "b": 2}


def test_repair_handles_python_literals():
    assert repair_and_parse('{"flag": True, "v": None}') == {"flag": True, "v": None}


def test_repair_handles_single_quotes_only():
    # No double quotes anywhere — safe to swap.
    assert repair_and_parse("{'a': 1}") == {"a": 1}


def test_repair_empty_raises():
    with pytest.raises(ValueError):
        repair_and_parse("")


def test_repair_no_object_raises():
    with pytest.raises(ValueError):
        repair_and_parse("just words, no JSON here")


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------

def test_intent_classification_accepts_minimal_payload():
    obj = IntentClassification.model_validate({
        "intent_type": "workflow",
        "domain": "cybersecurity_lab",
        "confidence": 0.8,
        "risk_level": "medium",
        "requires_authorization": True,
    })
    assert obj.intent_type == "workflow"
    assert obj.missing_slots == []


def test_intent_classification_rejects_unknown_intent():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        IntentClassification.model_validate({
            "intent_type": "magic",
            "domain": "x",
            "confidence": 0.1,
            "risk_level": "low",
            "requires_authorization": False,
        })


def test_tool_plan_v2_default_steps_empty():
    obj = ToolPlanV2.model_validate({"mode": "clarify"})
    assert obj.steps == []


def test_replan_decision_requires_valid_action():
    from pydantic import ValidationError
    obj = ReplanDecision.model_validate({"decision": "retry"})
    assert obj.decision == "retry"
    with pytest.raises(ValidationError):
        ReplanDecision.model_validate({"decision": "panic"})


# ---------------------------------------------------------------------------
# QwenPlanner — mocked model
# ---------------------------------------------------------------------------

def _make_planner(*responses: str) -> tuple[QwenPlanner, MagicMock]:
    """Return (planner, llm_mock). Each call to create_chat_completion returns
    the next response in sequence (or the last one repeated)."""
    llm = MagicMock()
    queue = list(responses)

    def chat(**kwargs):
        out = queue.pop(0) if queue else responses[-1]
        return {"choices": [{"message": {"content": out}}]}

    llm.create_chat_completion.side_effect = chat
    model_manager = MagicMock()
    model_manager.is_loaded.return_value = True
    model_manager.get_tool_model.return_value = llm
    model_manager.profile.return_value = MagicMock(temperature=0.1)

    planner = QwenPlanner(model_manager, timeout_ms=2000)
    return planner, llm


def test_classify_intent_happy_path():
    raw = json.dumps({
        "intent_type": "workflow",
        "domain": "cybersecurity_lab",
        "confidence": 0.86,
        "risk_level": "medium",
        "requires_authorization": True,
        "missing_slots": [],
        "reason_summary": "authorized lab scan",
    })
    planner, llm = _make_planner(raw)
    out = planner.classify_intent("scan 192.168.56.10 for open services")
    assert isinstance(out, IntentClassification)
    assert out.intent_type == "workflow"
    assert out.requires_authorization is True
    llm.create_chat_completion.assert_called_once()


def test_classify_intent_repairs_markdown_fence():
    raw = (
        "```json\n"
        '{"intent_type":"chat","domain":"general","confidence":0.5,'
        '"risk_level":"low","requires_authorization":false}\n'
        "```"
    )
    planner, llm = _make_planner(raw)
    out = planner.classify_intent("how's the weather")
    assert out.intent_type == "chat"
    assert llm.create_chat_completion.call_count == 1


def test_planner_retries_once_on_validation_error():
    # First response is missing the required `intent_type`. The planner
    # should retry once with the error appended; second response is valid.
    bad = json.dumps({"domain": "x", "confidence": 0.5, "risk_level": "low"})
    good = json.dumps({
        "intent_type": "chat", "domain": "x", "confidence": 0.5,
        "risk_level": "low", "requires_authorization": False,
    })
    planner, llm = _make_planner(bad, good)
    out = planner.classify_intent("anything")
    assert out.intent_type == "chat"
    assert llm.create_chat_completion.call_count == 2


def test_planner_raises_after_two_failures():
    bad = "not even close to JSON"
    planner, _ = _make_planner(bad, bad)
    with pytest.raises(QwenPlannerError):
        planner.classify_intent("anything")


def test_planner_raises_on_empty_response():
    planner, _ = _make_planner("", "")
    with pytest.raises(QwenPlannerError):
        planner.classify_intent("anything")


def test_select_workflow_renders_workflow_cards():
    raw = json.dumps({
        "intent_type": "workflow",
        "selected_workflow": "lab_network_inventory",
        "selected_capability": None,
        "confidence": 0.91,
        "missing_slots": [],
    })
    planner, llm = _make_planner(raw)
    out = planner.select_workflow(
        "inventory my lab subnet",
        workflows=[
            {"name": "lab_network_inventory",
             "description": "Read-only inventory of an authorized lab subnet.",
             "required_inputs": ["target_subnet"]},
            {"name": "web_app_recon_lab",
             "description": "Web app reconnaissance.",
             "required_inputs": ["base_url"]},
        ],
    )
    assert isinstance(out, WorkflowSelection)
    assert out.selected_workflow == "lab_network_inventory"
    # Confirm the rendered prompt actually contained both workflow names.
    sent = llm.create_chat_completion.call_args.kwargs["messages"][0]["content"]
    assert "lab_network_inventory" in sent
    assert "web_app_recon_lab" in sent
    assert "Read-only inventory" in sent


def test_fill_slots_happy_path():
    raw = json.dumps({
        "filled_slots": {"target_subnet": "192.168.56.0/24"},
        "missing_slots": [],
        "confidence": 0.9,
    })
    planner, _ = _make_planner(raw)
    out = planner.fill_slots(
        "inventory 192.168.56.0/24",
        selected={
            "name": "lab_network_inventory",
            "required_slots": ["target_subnet"],
            "optional_slots": ["scan_profile"],
        },
    )
    assert isinstance(out, SlotFill)
    assert out.filled_slots["target_subnet"] == "192.168.56.0/24"


def test_draft_plan_uses_compact_capability_cards():
    raw = json.dumps({
        "mode": "tool",
        "steps": [{
            "step_id": "s1",
            "capability": "host_service_scan",
            "args": {"target": "127.0.0.1"},
            "depends_on": [],
            "side_effect_level": "read",
        }],
        "missing_slots": [],
        "ask_user": "",
        "safety_notes": [],
        "confidence": 0.8,
    })
    planner, llm = _make_planner(raw)
    out = planner.draft_plan(
        "scan localhost",
        capabilities=[{
            "name": "host_service_scan",
            "selector_hint": "TCP service/version scan on authorized hosts",
            "risk": "read",
            "network_scope": "lab",
            "requires_authorization": True,
            "required_slots": ["target", "profile"],
        }],
    )
    assert isinstance(out, ToolPlanV2)
    assert out.mode == "tool"
    assert out.steps[0].capability == "host_service_scan"
    sent = llm.create_chat_completion.call_args.kwargs["messages"][0]["content"]
    assert "host_service_scan" in sent
    assert "scope=lab" in sent
    assert "requires_auth=True" in sent


def test_summarize_observation_returns_typed_object():
    raw = json.dumps({
        "step_id": "s1",
        "capability": "host_service_scan",
        "status": "success",
        "summary": "1 host, 1 open port",
        "structured_data": {"open_ports": [22]},
        "errors": [],
        "next_step_hints": [],
    })
    planner, _ = _make_planner(raw)
    out = planner.summarize_observation({"status": "success", "open_ports": [22]})
    assert isinstance(out, Observation)
    assert out.status == "success"
    assert out.structured_data["open_ports"] == [22]


def test_replan_returns_typed_decision():
    raw = json.dumps({
        "decision": "retry",
        "next_step_id": "s1",
        "updated_args": {"profile": "standard"},
        "question": "",
        "reason_summary": "first profile returned partial",
        "confidence": 0.7,
    })
    planner, _ = _make_planner(raw)
    out = planner.replan(
        workflow_state={"workflow_name": "lab_network_inventory"},
        observation={"status": "partial"},
    )
    assert isinstance(out, ReplanDecision)
    assert out.decision == "retry"
    assert out.updated_args["profile"] == "standard"


def test_planner_raises_when_tool_model_unavailable():
    model_manager = MagicMock()
    model_manager.is_loaded.return_value = False
    planner = QwenPlanner(model_manager, timeout_ms=500)
    with pytest.raises(QwenPlannerError):
        planner.classify_intent("anything")


# ---------------------------------------------------------------------------
# Compact card helpers
# ---------------------------------------------------------------------------

def test_compact_capability_cards_strips_full_descriptor():
    from dataclasses import dataclass

    @dataclass
    class _D:
        name: str
        description: str
        side_effect_level: str = "read"
        network_scope: str = "lab"
        requires_authorization: bool = True
        input_schema: dict | None = None

    cards = QwenPlanner.compact_capability_cards([
        _D(name="host_service_scan",
           description="Read-only TCP service/version scan...",
           input_schema={"target": "...", "profile": "..."}),
    ])
    assert cards[0]["name"] == "host_service_scan"
    assert cards[0]["risk"] == "read"
    assert cards[0]["network_scope"] == "lab"
    assert cards[0]["requires_authorization"] is True
    assert "target" in cards[0]["required_slots"]


def test_compact_workflow_cards_from_templates():
    from core.workflows import load_templates
    cards = QwenPlanner.compact_workflow_cards(load_templates())
    names = {c["name"] for c in cards}
    assert "lab_network_inventory" in names
    inv = next(c for c in cards if c["name"] == "lab_network_inventory")
    assert inv["required_inputs"] == ["target_subnet"]


# ---------------------------------------------------------------------------
# Prompt templates render with required variables
# ---------------------------------------------------------------------------

def test_all_prompt_templates_render():
    """Each Jinja template must accept its documented variable set."""
    planner, _ = _make_planner('{}')  # never actually invoked
    variables = {
        "intent_classification.j2": {"user_text": "do a thing"},
        "workflow_selection.j2": {"user_text": "x", "workflows": [], "retrieved_examples": []},
        "slot_fill.j2": {
            "user_text": "x",
            "selected": {"name": "n", "required_slots": ["a"], "optional_slots": ["b"]},
        },
        "plan_draft.j2": {
            "user_text": "x", "capabilities": [],
            "target_context": "", "permission_context": "", "retrieved_examples": [],
        },
        "plan_validate.j2": {"plan_json": "{}", "catalog_json": "{}"},
        "observation_summary.j2": {"observation_json": "{}"},
        "replan.j2": {
            "workflow_state_json": "{}", "observation_json": "{}",
            "policy_summary": "..."
        },
    }
    for tpl, vars_ in variables.items():
        rendered = planner._render(tpl, vars_)
        assert "SAFETY POLICY" in rendered
        assert "JSON:" in rendered
