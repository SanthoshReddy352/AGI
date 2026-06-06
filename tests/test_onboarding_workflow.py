"""Tests for first-run onboarding flow and update_user_profile capability.

Track 5.2b retired the standalone `OnboardingWorkflow` Python class — the
onboarding script now lives in `core/workflows/templates/user_onboarding.yaml`
and is driven by the template compiler's multi-turn slot-fill primitive.
These tests exercise that path end-to-end through `WorkflowOrchestrator`.

Covers:
  - Five-step happy path (name → role → location → preferences → comm_style)
  - "skip" answers record empty strings and advance the workflow
  - Workflow-level cancel mid-flow clears state cleanly
  - update_user_profile capability writes the correct namespace and field
  - read_profile / is_completed helpers behave correctly
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.assistant_context import AssistantContext
from core.capability_registry import CapabilityRegistry
from core.stores import ContextStore
from core.dialog_state import DialogState
from core.workflow_orchestrator import TemplateWorkflow, WorkflowOrchestrator
from modules.onboarding.extension import (
    PROFILE_FIELDS,
    PROFILE_NAMESPACE,
    OnboardingExtension,
    is_completed,
    read_profile,
    write_profile_field,
)


WORKFLOW_NAME = "user_onboarding"


class _CtxRegistry:
    """ExtensionContext stub that registers handlers in a real registry."""

    def __init__(self, app):
        self._app = app
        self.registry = app.capability_registry
        self.events = MagicMock()
        self.consent = MagicMock()

    def get_service(self, name):
        return getattr(self._app, name, None)

    def register_capability(self, spec, handler, metadata=None):
        self.registry.register_tool(spec, handler, metadata)


class _RegistryExecutor:
    """Lightweight OrderedToolExecutor stand-in for tests.

    Just invokes each plan step's capability handler from the registry,
    threading args through. Returns the last step's output as a string —
    this is the contract `TemplateWorkflow._advance_slot_fill` relies on
    when packaging the final response.
    """

    def __init__(self, registry):
        self._registry = registry

    def execute(self, plan, user_text, turn=None):
        if plan.mode in {"reply", "clarify"}:
            return plan.reply
        last = ""
        for step in plan.steps or []:
            handler = self._registry.get_handler(step.capability_name)
            if handler is None:
                continue
            last = handler(user_text, step.args or {}) or ""
        return last


class _CapabilityExecutorShim:
    """Tiny CapabilityExecutor stand-in for the template compiler's
    ``extract_with`` call path. Returns the raw string from the handler
    so the compiler can stamp it directly into the slot."""

    def __init__(self, registry):
        self._registry = registry

    def execute(self, capability_name, raw_text, args=None):
        handler = self._registry.get_handler(capability_name)
        if handler is None:
            return raw_text
        return handler(raw_text, args or {})


def build_test_app(tmp_path):
    app = SimpleNamespace()
    app.event_bus = MagicMock()
    app.dialog_state = DialogState()
    app.assistant_context = AssistantContext()
    app.context_store = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    app.session_id = app.context_store.start_session({"source": "onboarding-tests"})
    app.assistant_context.bind_context_store(app.context_store, app.session_id)
    app.memory_service = None
    app.capability_registry = CapabilityRegistry()
    app.capability_executor = _CapabilityExecutorShim(app.capability_registry)
    app.ordered_tool_executor = _RegistryExecutor(app.capability_registry)
    app.task_graph_executor = None
    app.config = None
    # Load the onboarding extension so its slot-fill extractors and
    # `complete_onboarding` handler are registered. The template's
    # capability-step lookup uses this registry.
    OnboardingExtension().load(_CtxRegistry(app))
    app.workflow_orchestrator = WorkflowOrchestrator(app)
    return app


def _start_onboarding(app):
    """Mirror what `GreeterExtension._begin_onboarding` does at first run."""
    return app.workflow_orchestrator.start_template_slot_fill(
        WORKFLOW_NAME, app.session_id,
    )


def _run_continue(app, user_text: str):
    return app.workflow_orchestrator.continue_active(user_text, app.session_id)


# ----------------------------------------------------------------------
# Workflow happy path
# ----------------------------------------------------------------------

def test_first_question_is_name_prompt(tmp_path):
    app = build_test_app(tmp_path)
    result = _start_onboarding(app)
    assert result.handled
    assert "what should i call you" in result.response.lower()


def test_onboarding_workflow_is_registered(tmp_path):
    app = build_test_app(tmp_path)
    assert WORKFLOW_NAME in app.workflow_orchestrator.workflows
    wf = app.workflow_orchestrator.workflows[WORKFLOW_NAME]
    assert isinstance(wf, TemplateWorkflow)


def test_happy_path_captures_all_five_fields(tmp_path):
    app = build_test_app(tmp_path)
    start = _start_onboarding(app)
    assert start.handled
    assert "what should i call you" in start.response.lower()

    # Step 1: name
    r1 = _run_continue(app, "Tricky")
    assert r1.handled
    assert "what do you do" in r1.response.lower()
    assert "tricky" in r1.response.lower()

    # Step 2: role
    r2 = _run_continue(app, "I'm building a personal AI assistant")
    assert r2.handled
    assert "where are you based" in r2.response.lower()

    # Step 3: location
    r3 = _run_continue(app, "Mumbai")
    assert r3.handled
    assert "tools or topics" in r3.response.lower()

    # Step 4: preferences
    r4 = _run_continue(app, "Python and local LLMs")
    assert r4.handled
    assert "talk to you" in r4.response.lower()

    # Step 5: comm_style — final
    r5 = _run_continue(app, "Concise")
    assert r5.handled
    assert "tricky" in r5.response.lower()
    assert "glad to meet you" in r5.response.lower()

    # Workflow marked completed; profile facts written; system flag set.
    final_state = (
        app.context_store.get_active_workflow(app.session_id, workflow_name=WORKFLOW_NAME)
        or {}
    )
    assert final_state.get("status") == "completed" or final_state == {}
    profile = read_profile(app.context_store)
    assert profile["name"] == "Tricky"
    assert profile["role"].lower().startswith("i'm building")
    assert profile["location"] == "Mumbai"
    assert profile["preferences"] == "Python and local LLMs"
    assert profile["comm_style"] == "Concise"
    assert is_completed(app.context_store) is True


def test_skip_answers_record_empty_and_advance(tmp_path):
    app = build_test_app(tmp_path)
    _start_onboarding(app)

    r1 = _run_continue(app, "skip")
    assert r1.handled
    # Even with empty name, advances to role question (and uses the
    # default placeholder "there" since user_name slot is empty).
    assert "what do you do" in r1.response.lower()

    _run_continue(app, "later")    # role
    _run_continue(app, "no")       # location
    _run_continue(app, "skip")     # preferences
    final = _run_continue(app, "skip")  # comm_style → final

    assert final.handled
    assert "glad to meet you" in final.response.lower()

    profile = read_profile(app.context_store)
    # Skipped answers persist as empty strings; read_profile filters them.
    assert profile == {}
    assert is_completed(app.context_store) is True


def test_workflow_cancel_clears_state_and_exits(tmp_path):
    app = build_test_app(tmp_path)
    _start_onboarding(app)

    # Answer first question normally
    _run_continue(app, "Tricky")

    # Cancel mid-workflow — orchestrator should handle it and clear state.
    cancel_result = _run_continue(app, "cancel")
    assert cancel_result.handled
    assert "cancel" in cancel_result.response.lower()
    assert app.context_store.get_active_workflow(app.session_id, workflow_name=WORKFLOW_NAME) in (None, {})


def test_extract_name_from_phrases(tmp_path):
    app = build_test_app(tmp_path)
    _start_onboarding(app)

    # Provide name via "My name is X" phrasing — extractor strips the lead-in.
    r = _run_continue(app, "My name is Cody Reddy")
    assert r.handled
    # The next question's greeting interpolation echoes the extracted name.
    assert "cody reddy" in r.response.lower()

    # Race through the rest so the capability step fires and writes the name.
    _run_continue(app, "Engineer")
    _run_continue(app, "Mumbai")
    _run_continue(app, "Python")
    _run_continue(app, "Concise")

    profile = read_profile(app.context_store)
    assert profile["name"] == "Cody Reddy"


# ----------------------------------------------------------------------
# update_user_profile capability
# ----------------------------------------------------------------------

class _StubCtx:
    """Minimal ExtensionContext stand-in for handler unit tests."""
    def __init__(self, store):
        self._store = store
        self.registry = MagicMock()
        self.events = MagicMock()
        self.consent = MagicMock()

    def get_service(self, name):
        return self._store if name == "context_store" else None

    def register_capability(self, *args, **kwargs):
        pass


def test_update_user_profile_writes_correct_namespace(tmp_path):
    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    store.start_session({"source": "tests"})
    ext = OnboardingExtension()
    ext.load(_StubCtx(store))

    ack = ext._handle_update_profile("", {"field": "name", "value": "Cody"})
    assert "cody" in ack.lower()
    assert read_profile(store)["name"] == "Cody"

    ack2 = ext._handle_update_profile("", {"field": "location", "value": "Mumbai"})
    assert "mumbai" in ack2.lower()
    assert read_profile(store)["location"] == "Mumbai"


def test_update_user_profile_rejects_unknown_field(tmp_path):
    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    store.start_session({"source": "tests"})
    ext = OnboardingExtension()
    ext.load(_StubCtx(store))

    ack = ext._handle_update_profile("", {"field": "favourite_color", "value": "blue"})
    assert "only remember" in ack.lower() or "which one" in ack.lower()
    assert read_profile(store) == {}


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def test_write_profile_field_ignores_unknown_field(tmp_path):
    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    store.start_session({"source": "tests"})
    write_profile_field(store, "not_a_field", "nope")
    assert read_profile(store) == {}


def test_profile_fields_constant_matches_yaml_template():
    """PROFILE_FIELDS is the contract between the extension and the YAML
    template's `complete_onboarding` args block. Keep them aligned."""
    template_path = os.path.join(
        os.path.dirname(__file__), "..", "core", "workflows",
        "templates", "user_onboarding.yaml",
    )
    import yaml
    with open(template_path) as fh:
        tpl = yaml.safe_load(fh)
    complete_step = next(
        s for s in tpl["steps"] if s.get("capability") == "complete_onboarding"
    )
    assert set(complete_step["args"].keys()) == set(PROFILE_FIELDS)
