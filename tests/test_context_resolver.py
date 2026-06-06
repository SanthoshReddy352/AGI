"""Unit tests for core/planning/context_resolver.py — Track 1.4 keystone."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.capability_broker import ToolPlan, ToolStep
from core.stores import WorkingArtifact
from core.planning.context_resolver import ContextResolver, ResolverDecision


def _app_with_artifact(source_path: str = "/tmp/sample.txt"):
    """Build a minimal app stub with a context_store that returns an artifact
    and a capability_registry that knows about `read_file`."""
    artifact = (
        WorkingArtifact(
            content="",
            output_type="file",
            capability_name="manage_file",
            artifact_type="file",
            source_path=source_path,
            scope="last_write",
        )
        if source_path
        else None
    )
    app = SimpleNamespace()
    app.context_store = SimpleNamespace(get_artifact=lambda sid: artifact)
    app.capability_registry = SimpleNamespace(has_capability=lambda name: name == "read_file")
    app.router = None
    return app


def _chat_plan(text: str = "what's in it?") -> ToolPlan:
    return ToolPlan(turn_id="t1", mode="chat", reply="", steps=[])


def _tool_plan(name: str = "get_time") -> ToolPlan:
    return ToolPlan(
        turn_id="t1",
        mode="tool",
        steps=[ToolStep(capability_name=name, args={})],
    )


# ---------------------------------------------------------------------------
# Rescue cases — should rewrite the plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("utterance", [
    "what's in it?",
    "What is in it",
    "read it",
    "show it",
    "open it",
    "preview it",
    "display it",
    "what's inside it",
    "contents of it",
    "read the file",
    "show that",
    "what is in this",
    "open same file",
])
def test_resolver_rewrites_chat_to_read_file_when_pronoun_and_artifact(utterance):
    app = _app_with_artifact("/home/u/notes.md")
    resolver = ContextResolver(app)
    decision = resolver.try_rescue(utterance, _chat_plan(utterance), session_id="s1")
    assert decision.applied
    rewrite = decision.rewrite
    assert rewrite.mode == "tool"
    assert len(rewrite.steps) == 1
    step = rewrite.steps[0]
    assert step.capability_name == "read_file"
    assert step.args == {"filename": "/home/u/notes.md"}
    assert "artifact" in decision.reason.lower()


def test_resolver_uses_artifact_path_verbatim():
    app = _app_with_artifact("/exact/path/with spaces/file.txt")
    decision = ContextResolver(app).try_rescue(
        "what's in it?", _chat_plan(), session_id="s1"
    )
    assert decision.applied
    assert decision.rewrite.steps[0].args["filename"] == "/exact/path/with spaces/file.txt"


# ---------------------------------------------------------------------------
# No-rescue cases — should leave the plan alone
# ---------------------------------------------------------------------------


def test_resolver_skips_when_plan_is_tool_mode():
    """A planner that already chose a tool wins; resolver must not override."""
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue(
        "read it", _tool_plan("get_weather"), session_id="s1"
    )
    assert not decision.applied
    assert decision.rewrite is None


def test_resolver_skips_when_no_artifact_in_scope():
    app = _app_with_artifact(source_path="")  # no artifact
    decision = ContextResolver(app).try_rescue(
        "what's in it?", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_resolver_skips_when_no_pronoun():
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue(
        "read my file aloud please", _chat_plan(), session_id="s1"
    )
    # "my file" isn't an artifact pronoun in our narrow MVP set.
    assert not decision.applied


def test_resolver_skips_when_no_read_verb():
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue(
        "tell me about it", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_resolver_skips_when_read_file_capability_absent():
    app = _app_with_artifact("/home/u/notes.md")
    app.capability_registry = SimpleNamespace(has_capability=lambda name: False)
    decision = ContextResolver(app).try_rescue(
        "read it", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_resolver_skips_when_text_is_empty():
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue("", _chat_plan(), session_id="s1")
    assert not decision.applied


def test_resolver_skips_when_plan_is_none():
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue("read it", None, session_id="s1")
    assert not decision.applied


def test_resolver_skips_when_session_id_is_empty():
    app = _app_with_artifact("/home/u/notes.md")
    decision = ContextResolver(app).try_rescue("read it", _chat_plan(), session_id="")
    assert not decision.applied


def test_resolver_rescues_clarify_mode_with_artifact_pronoun():
    """The broker's generic "I need a bit more detail" clarify is exactly
    the case the resolver exists to repair when an artifact is in scope."""
    app = _app_with_artifact("/home/u/notes.md")
    plan = ToolPlan(turn_id="t1", mode="clarify", reply="huh?")
    decision = ContextResolver(app).try_rescue("read it", plan, session_id="s1")
    assert decision.applied
    assert decision.rewrite.steps[0].capability_name == "read_file"


def test_resolver_skips_clarify_with_online_consent_prompt():
    """An online-consent clarify ("Search online for X? Say yes or no.") is a
    deliberate yes/no prompt — must NOT be overridden by the rescue path."""
    app = _app_with_artifact("/home/u/notes.md")
    plan = ToolPlan(
        turn_id="t1",
        mode="clarify",
        reply="Search online? Say yes or no.",
        requires_confirmation=True,
    )
    assert not ContextResolver(app).try_rescue("read it", plan, session_id="s1").applied


def test_resolver_skips_when_planner_mode_is_planner_or_refuse():
    """planner/refuse modes are explicit decisions — don't override."""
    app = _app_with_artifact("/home/u/notes.md")
    for mode in ("planner", "refuse", "workflow", "reply"):
        plan = ToolPlan(turn_id="t1", mode=mode, reply="")
        assert not ContextResolver(app).try_rescue("read it", plan, session_id="s1").applied


def test_resolver_handles_store_exception_gracefully():
    """A flaky context_store must not take down the turn."""
    app = SimpleNamespace()
    app.context_store = SimpleNamespace(get_artifact=MagicMock(side_effect=RuntimeError("db down")))
    app.capability_registry = SimpleNamespace(has_capability=lambda n: True)
    app.router = None
    decision = ContextResolver(app).try_rescue("read it", _chat_plan(), session_id="s1")
    assert not decision.applied


def test_resolver_decision_applied_property():
    assert ResolverDecision().applied is False
    assert ResolverDecision(rewrite=_tool_plan("read_file"), reason="x").applied is True


# ---------------------------------------------------------------------------
# Track 1.4b — ordinal rescue (migrated from intent_recognizer._resolve_references)
# ---------------------------------------------------------------------------


def _app_with_registry(refs: dict[str, str], artifact_path: str = ""):
    """Build a minimal app stub whose context_store returns named references."""
    app = _app_with_artifact(artifact_path)
    app.context_store.get_reference = lambda sid, key: refs.get(key, "")
    return app


@pytest.mark.parametrize("utterance, ordinal_key", [
    ("read the first one", "first"),
    ("show the second item", "second"),
    ("open the third result", "third"),
    ("read 1st one", "first"),
    ("show 2nd one", "second"),
    ("preview 3rd file", "third"),
    ("read the last one", "last"),
])
def test_resolver_rescues_ordinal_against_registry(utterance, ordinal_key):
    app = _app_with_registry({
        "first": "/path/first.txt",
        "second": "/path/second.txt",
        "third": "/path/third.txt",
        "last": "/path/last.txt",
    })
    decision = ContextResolver(app).try_rescue(utterance, _chat_plan(utterance), session_id="s1")
    assert decision.applied, f"resolver should rescue ordinal {ordinal_key!r}"
    step = decision.rewrite.steps[0]
    assert step.capability_name == "read_file"
    assert step.args["filename"] == f"/path/{ordinal_key}.txt"
    assert "ordinal" in decision.reason.lower()


def test_resolver_ordinal_rescue_skips_when_registry_empty():
    app = _app_with_registry({})  # nothing registered
    decision = ContextResolver(app).try_rescue(
        "read the first one", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_resolver_ordinal_rescue_skips_when_no_verb():
    """An ordinal alone ("the first one") with no read-verb is not enough."""
    app = _app_with_registry({"first": "/path/x.txt"})
    decision = ContextResolver(app).try_rescue(
        "the first one", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_pronoun_path_wins_over_ordinal_when_both_could_apply():
    """If the user said `read it` AND an ordinal happens to be in scope,
    the artifact pronoun takes priority (it's the most recently-set
    target). The test pins the priority order so future refactors don't
    silently flip it."""
    app = _app_with_registry({"first": "/path/ordinal.txt"}, artifact_path="/path/artifact.txt")
    decision = ContextResolver(app).try_rescue(
        "read it", _chat_plan(), session_id="s1"
    )
    assert decision.applied
    assert decision.rewrite.steps[0].args["filename"] == "/path/artifact.txt"


def test_ordinal_rescue_handles_registry_exception():
    app = _app_with_artifact("")  # no artifact
    app.context_store.get_reference = MagicMock(side_effect=RuntimeError("db down"))
    decision = ContextResolver(app).try_rescue(
        "read the first one", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


# ---------------------------------------------------------------------------
# Track 1.4b — pending-file-candidate rescue (path 3, no verb required)
# ---------------------------------------------------------------------------


def _app_with_pending(candidates: list[str]):
    """Build an app whose dialog_state has a pending_file_request with
    the given candidates and whose capability_registry exposes
    `select_file_candidate`."""
    app = SimpleNamespace()
    app.context_store = SimpleNamespace(
        get_artifact=lambda sid: None,
        get_reference=lambda sid, key: "",
    )
    app.capability_registry = SimpleNamespace(
        has_capability=lambda name: name in {"read_file", "select_file_candidate"}
    )
    app.dialog_state = SimpleNamespace(
        pending_file_request=SimpleNamespace(candidates=list(candidates))
    )
    app.router = None
    return app


def test_pending_selection_rescue_with_ordinal():
    app = _app_with_pending(["/path/a.pdf", "/path/b.txt", "/path/c.md"])
    decision = ContextResolver(app).try_rescue(
        "2nd one", _chat_plan(), session_id="s1"
    )
    assert decision.applied
    assert decision.rewrite.steps[0].capability_name == "select_file_candidate"
    assert "pending list" in decision.reason


def test_pending_selection_rescue_with_extension_only():
    """`choose_candidate_from_text` resolves bare-extension selections too —
    the resolver doesn't need its own pattern for `pdf`/`txt` etc."""
    app = _app_with_pending(["/path/a.pdf", "/path/b.txt"])
    decision = ContextResolver(app).try_rescue(
        "the pdf one", _chat_plan(), session_id="s1"
    )
    assert decision.applied
    assert decision.rewrite.steps[0].capability_name == "select_file_candidate"


def test_pending_selection_rescue_skips_when_no_pending_request():
    """No pending_file_request set → resolver leaves the plan alone."""
    app = _app_with_pending([])
    decision = ContextResolver(app).try_rescue(
        "the pdf one", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_pending_selection_rescue_skips_when_text_doesnt_match_any_candidate():
    app = _app_with_pending(["/path/a.pdf", "/path/b.txt"])
    decision = ContextResolver(app).try_rescue(
        "tell me a joke", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_pending_selection_rescue_skips_when_capability_absent():
    app = _app_with_pending(["/path/a.pdf"])
    app.capability_registry = SimpleNamespace(has_capability=lambda name: False)
    decision = ContextResolver(app).try_rescue(
        "1st one", _chat_plan(), session_id="s1"
    )
    assert not decision.applied


def test_pending_selection_rescue_does_not_require_verb():
    """Selection replies are nouns ("the pdf one") with no read-verb.
    Path 3 must fire WITHOUT triggering the read-verb gate that paths
    1 and 2 enforce."""
    app = _app_with_pending(["/path/notes.md"])
    decision = ContextResolver(app).try_rescue(
        "notes", _chat_plan(), session_id="s1"
    )
    assert decision.applied
    assert decision.rewrite.steps[0].capability_name == "select_file_candidate"
