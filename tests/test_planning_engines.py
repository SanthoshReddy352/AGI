"""Tests for the v2 planning layer (IntentEngine, PlannerEngine, WorkflowCoordinator)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.capability_broker import ToolPlan, ToolStep  # noqa: E402
from core.planning.intent_engine import (  # noqa: E402
    HIGH_THRESHOLD,
    IntentEngine,
    IntentResult,
)
from core.planning.planner_engine import PlannerEngine  # noqa: E402
from core.planning.workflow_coordinator import (  # noqa: E402
    WorkflowCoordinator,
    WorkflowResume,
)


# ---------------------------------------------------------------------------
# IntentEngine
# ---------------------------------------------------------------------------

def test_intent_engine_returns_high_confidence_on_regex_match():
    recognizer = MagicMock()
    recognizer.plan.return_value = [
        {"tool": "launch_app", "args": {"app": "chrome"}, "domain": "launch_app"}
    ]
    scorer = MagicMock()
    engine = IntentEngine(recognizer, scorer)

    result = engine.classify("open chrome")

    assert isinstance(result, IntentResult)
    assert result.tool == "launch_app"
    assert result.args == {"app": "chrome"}
    assert result.confidence >= HIGH_THRESHOLD
    assert result.source == "regex"
    assert len(result.actions) == 1
    # Scorer should NOT be consulted when regex matches.
    scorer.find_best_route.assert_not_called()


def test_intent_engine_honors_calibrated_confidence_on_action():
    """A parser may downgrade confidence for an ambiguous match; the engine
    surfaces it (below HIGH_THRESHOLD) so the orchestrator can fall through
    instead of dispatching the regex result silently."""
    recognizer = MagicMock()
    recognizer.plan.return_value = [
        {"tool": "set_brightness", "args": {}, "domain": "brightness", "confidence": 0.55}
    ]
    engine = IntentEngine(recognizer, MagicMock())

    result = engine.classify("brightness")

    assert result.tool == "set_brightness"
    assert result.source == "regex"
    assert result.confidence == 0.55
    assert result.confidence < HIGH_THRESHOLD


def test_intent_engine_defaults_confidence_to_one_without_tag():
    """No `confidence` key → exact-regex match stays on the 1.0 fast path
    (backward-compatible: the common case is unchanged)."""
    recognizer = MagicMock()
    recognizer.plan.return_value = [{"tool": "get_time", "args": {}, "domain": "time"}]
    engine = IntentEngine(recognizer, MagicMock())

    result = engine.classify("what time is it")

    assert result.confidence == 1.0
    assert result.confidence >= HIGH_THRESHOLD


def test_intent_engine_falls_through_to_scorer_when_regex_misses():
    recognizer = MagicMock()
    recognizer.plan.return_value = []
    scorer = MagicMock()
    scorer.find_best_route.return_value = {"spec": {"name": "weather"}}
    engine = IntentEngine(recognizer, scorer)

    result = engine.classify("how is the weather")

    assert result.tool == "weather"
    assert result.source == "score"
    assert 0.0 < result.confidence < HIGH_THRESHOLD
    assert result.actions == [{"tool": "weather", "args": {}, "domain": "weather"}]


def test_intent_engine_returns_none_source_when_nothing_matches():
    recognizer = MagicMock()
    recognizer.plan.return_value = []
    scorer = MagicMock()
    scorer.find_best_route.return_value = None
    engine = IntentEngine(recognizer, scorer)

    result = engine.classify("blah blah blah")
    assert result.tool is None
    assert result.confidence == 0.0
    assert result.source == "none"
    assert result.actions == []


def test_intent_engine_handles_empty_text():
    engine = IntentEngine(MagicMock(), MagicMock())
    result = engine.classify("")
    assert result.tool is None
    assert result.source == "none"


def test_intent_engine_handles_recognizer_exception():
    recognizer = MagicMock()
    recognizer.plan.side_effect = RuntimeError("boom")
    scorer = MagicMock()
    scorer.find_best_route.return_value = None
    engine = IntentEngine(recognizer, scorer)

    result = engine.classify("anything")
    assert result.tool is None
    assert result.source == "none"


# ---------------------------------------------------------------------------
# PlannerEngine
# ---------------------------------------------------------------------------

def _build_planner(broker=None):
    if broker is None:
        broker = MagicMock()
        broker.app = SimpleNamespace(
            capability_registry=SimpleNamespace(has_capability=lambda n: False),
            consent_service=None,
            config=None,
        )
        # Track 3.2c: PlannerEngine no longer calls broker.build_plan;
        # it orchestrates the broker's per-step helpers. Make the
        # critical helpers return falsy so we hit the final clarify
        # branch — that lets us assert "slow path ran" by checking
        # the clean step fired.
        broker._clean.side_effect = lambda text, source="user": text
        broker._now.return_value = 0.0
        broker._plan_pending_online.return_value = None
        broker._try_continue_workflow.return_value = None
        broker._plan_actions.return_value = []
        broker._find_best_route.return_value = None
        broker._should_use_planner.return_value = False
        broker._maybe_learned_dispatch.return_value = None
        broker._maybe_lexical_route.return_value = None
        broker._maybe_confirm_intent.return_value = None
        broker._try_propose_online_consent.return_value = None
    return PlannerEngine(broker), broker


def test_planner_falls_back_to_broker_when_intent_low_confidence():
    """Track 3.2c: PlannerEngine's slow path orchestrates broker helpers
    directly. Low-confidence intent means the fast path is skipped, so
    the broker's `_clean` (always the first helper called in the slow
    path) must fire."""
    planner, broker = _build_planner()
    intent = IntentResult(tool=None, confidence=0.0, source="none")
    plan = planner.plan("hello", ctx=None, intent=intent)
    broker._clean.assert_called_once()
    # With all helpers returning None/empty, the slow path falls through
    # to the generic clarify.
    assert plan.mode == "clarify"


def test_planner_fast_path_when_intent_high_confidence_and_no_consent():
    """High-confidence intent with no consent gating bypasses the broker."""
    broker = MagicMock()
    broker.app = SimpleNamespace(
        capability_registry=SimpleNamespace(
            get_descriptor=lambda name: SimpleNamespace(
                connectivity="local", side_effect_level="read"
            )
        ),
        consent_service=SimpleNamespace(
            evaluate=lambda name, descriptor, text: SimpleNamespace(
                needs_confirmation=False
            )
        ),
        config=None,
    )
    planner = PlannerEngine(broker)

    intent = IntentResult(
        tool="launch_app",
        args={"app": "chrome"},
        confidence=1.0,
        source="regex",
        actions=[
            {"tool": "launch_app", "args": {"app": "chrome"}},
            {"tool": "play_music", "args": {"query": "lofi"}},
        ],
    )
    plan = planner.plan("open chrome and play lofi", ctx=None, intent=intent)
    # Track 3.2c: fast path bypasses ALL slow-path orchestration —
    # `_clean` (the slow path's first helper) must not fire.
    broker._clean.assert_not_called()
    assert plan.mode == "tool"
    assert [s.capability_name for s in plan.steps] == ["launch_app", "play_music"]
    assert plan.steps[0].args == {"app": "chrome"}
    # Each step gets a unique node_id so TaskGraphExecutor can reference it.
    assert plan.steps[0].node_id != plan.steps[1].node_id


def test_planner_fast_path_falls_back_when_consent_required():
    """If any action needs confirmation the planner falls back to the
    slow path. Track 3.2c: slow path is now the PlannerEngine's own
    orchestration of broker helpers — assert via `_clean` (slow-path
    hallmark) and the chat-fallback descriptor lookup."""
    broker = MagicMock()
    broker.app = SimpleNamespace(
        capability_registry=SimpleNamespace(
            get_descriptor=lambda name: SimpleNamespace(connectivity="online"),
            has_capability=lambda n: False,
        ),
        consent_service=SimpleNamespace(
            evaluate=lambda name, descriptor, text: SimpleNamespace(
                needs_confirmation=True
            )
        ),
        config=None,
    )
    broker._clean.side_effect = lambda text, source="user": text
    broker._now.return_value = 0.0
    broker._plan_pending_online.return_value = None
    broker._try_continue_workflow.return_value = None
    broker._plan_actions.return_value = []
    broker._find_best_route.return_value = None
    broker._should_use_planner.return_value = False
    broker._maybe_learned_dispatch.return_value = None
    broker._maybe_lexical_route.return_value = None
    broker._maybe_confirm_intent.return_value = None
    broker._try_propose_online_consent.return_value = None
    planner = PlannerEngine(broker)

    intent = IntentResult(
        tool="search_web",
        args={"query": "anything"},
        confidence=1.0,
        source="regex",
        actions=[{"tool": "search_web", "args": {"query": "anything"}}],
    )
    plan = planner.plan("search the web for anything", ctx=None, intent=intent)
    broker._clean.assert_called_once()
    assert plan.mode == "clarify"


# ---------------------------------------------------------------------------
# WorkflowCoordinator
# ---------------------------------------------------------------------------

def test_workflow_coordinator_get_active_delegates_to_store():
    store = MagicMock()
    store.get_active_workflow.return_value = {"workflow_name": "file_workflow"}
    orchestrator = MagicMock()

    coord = WorkflowCoordinator(orchestrator, store)
    assert coord.get_active("session-x") == {"workflow_name": "file_workflow"}
    store.get_active_workflow.assert_called_once_with("session-x", workflow_name=None)


def test_workflow_coordinator_get_active_returns_none_for_blank_session():
    coord = WorkflowCoordinator(MagicMock(), MagicMock())
    assert coord.get_active("") is None


def test_workflow_coordinator_try_resume_returns_response_when_handled():
    orchestrator = MagicMock()
    orchestrator.continue_active.return_value = SimpleNamespace(
        handled=True,
        response="created event for tomorrow at 10am",
        workflow_name="calendar_event_workflow",
        state={"step": 2},
    )
    coord = WorkflowCoordinator(orchestrator, MagicMock())

    result = coord.try_resume("tomorrow at 10am", "session-y")
    assert isinstance(result, WorkflowResume)
    assert result.handled is True
    assert "created event" in result.response
    assert result.name == "calendar_event_workflow"
    assert result.state == {"step": 2}


def test_workflow_coordinator_try_resume_handles_unhandled_result():
    orchestrator = MagicMock()
    orchestrator.continue_active.return_value = SimpleNamespace(
        handled=False, response="", workflow_name="", state={}
    )
    coord = WorkflowCoordinator(orchestrator, MagicMock())
    assert coord.try_resume("nothing pending", "session-z").handled is False


def test_workflow_coordinator_try_resume_swallows_orchestrator_errors():
    orchestrator = MagicMock()
    orchestrator.continue_active.side_effect = RuntimeError("db lock")
    coord = WorkflowCoordinator(orchestrator, MagicMock())
    assert coord.try_resume("foo", "session-q").handled is False
