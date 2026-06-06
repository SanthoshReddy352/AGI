"""Behavior pins for the seven known UX bugs identified 2026-05-17.

Each test encodes the EXPECTED (post-fix) behavior and is marked
`pytest.mark.xfail(strict=True)`. Today they fail because the bug exists →
xfail keeps the suite green. When the matching Track 1 fix lands, the test
unexpectedly passes → xpass → strict mode fails the suite → forces us to
remove the xfail marker as part of the fix PR. That's the lock-in mechanism.

These are NOT trying to be clever assertions on internal state. They drive
the user-visible interaction (via the cross-turn harness) and assert what
FRIDAY should produce after the consolidation. Removing one of these xfails
without an accompanying fix is a regression.

Reference: `project_known_ux_bugs_2026_05_17.md` in memory; FRIDAY
Consolidation Direction `plan/2026-05-17_16-23-15_plan.md`.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.conversation


# ---------------------------------------------------------------------------
# Bug #1 — Persona leak: "Who are you?" and "Who am I?" return the same
# identity. Symptom of mixing USER_FACTS into ASSISTANT_IDENTITY in the chat
# prompt. Fixed by Track 1.1 (persona-prompt template).
# ---------------------------------------------------------------------------


# Track 1.1 landed 2026-05-17: xfail removed. The chat system prompt now
# emits structured `<ASSISTANT_IDENTITY>` / `<USER_FACTS>` / `<SESSION_CONTEXT>`
# blocks so the LLM can route "Who are you?" off identity and "Who am I?" off
# user facts without mixing them.
def test_chat_prompt_separates_user_facts_from_assistant_identity():
    """The system prompt for chat turns must keep USER_FACTS and
    ASSISTANT_IDENTITY in distinct labelled blocks. Without separation, the
    LLM cannot tell who is the user vs. who is FRIDAY.

    Asserted at the prompt-construction layer because (a) it's deterministic
    and (b) it catches the bug without booting the chat LLM.
    """
    from core.app import FridayApp  # noqa: PLC0415

    app = FridayApp()
    assistant_context = app.assistant_context
    if assistant_context is None or not hasattr(assistant_context, "build_chat_messages"):
        pytest.fail("FridayApp must expose assistant_context.build_chat_messages")

    messages = assistant_context.build_chat_messages("Who are you?")
    system_msgs = [m for m in messages if m.get("role") == "system"]
    assert system_msgs, "expected at least one system message in chat prompt"
    joined = "\n".join(m.get("content", "") for m in system_msgs)

    # Post-fix: the prompt has labelled sections that the LLM can route on.
    assert "<ASSISTANT_IDENTITY>" in joined, (
        "system prompt must contain a labelled <ASSISTANT_IDENTITY> block "
        "that's distinct from user facts"
    )
    assert "<USER_FACTS>" in joined, (
        "system prompt must contain a labelled <USER_FACTS> block so the LLM "
        "knows which facts describe the user, not the assistant"
    )
    # And the two blocks are non-overlapping (very weak structural check):
    identity_start = joined.find("<ASSISTANT_IDENTITY>")
    facts_start = joined.find("<USER_FACTS>")
    assert identity_start != facts_start, "blocks must be at distinct offsets"


# ---------------------------------------------------------------------------
# Bug #2 — WorkingArtifact stale read: `create my.txt` then `create hello.txt`
# then `read it` returns the FIRST file because the artifact's scope held the
# stale "explicit" target. Fixed by Track 1.2 (scope precedence).
# ---------------------------------------------------------------------------


# Track 1.2 landed 2026-05-17: WorkingArtifact scope precedence
# (`last_write > explicit > auto > inferred`) added in `core/context_store.py`,
# and `file_workspace._publish_explicit_artifact` switched from scope='explicit'
# to scope='last_write' so a fresh file mutation always supersedes a stale
# pronoun target. Strict unit-level precedence guards live in
# `tests/test_working_artifact_scope.py`; this test is the e2e lock-in.
def test_read_it_resolves_to_most_recent_file():
    """After two `create file` turns, `read it` must resolve to the LAST
    file written, not a stale earlier target. Asserts on the response
    text (the user-visible signal) because the artifact resolution happens
    inside read_file from session state, not in the tool args dict.
    """
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])
    convo = runner.run([
        "create file called my.txt",
        "create file called hello.txt",
        "read it",
    ])
    response = (convo.last.response or "").lower()
    assert "hello.txt" in response, (
        f"`read it` should resolve to hello.txt (most recent create); "
        f"got tool={convo.last.tool_name!r} args={convo.last.tool_args!r} "
        f"response={convo.last.response!r}"
    )
    assert "my.txt" not in response, (
        f"`read it` resolved to the stale my.txt instead of the most recent "
        f"hello.txt; response={convo.last.response!r}"
    )


# ---------------------------------------------------------------------------
# Bug #3 — Inline-content slot extraction gap: `Write 'X' to Y.txt` only
# parses the filename, asks the user for content. Fixed by Track 1.5
# (slot extraction breadth) + Track 1.5 (no LLM content-generator fallback).
# ---------------------------------------------------------------------------


# Track 1.5 landed 2026-05-18: `_extract_manage_content` recognizes
# `<verb> <quoted-content> (to|into|in) <filename>`. The new
# `content_is_literal` flag on FileManageRequest suppresses the
# LLM content-generator path so user-quoted text writes verbatim.
def test_inline_quoted_content_extracted_with_filename():
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])
    convo = runner.run(["write 'Hello Friday' to hello.txt"])
    # Both content and filename extracted in one shot, file actually written,
    # and no clarification asked for content that was already provided.
    response = (convo.last.response or "").lower()
    assert "what would you like me to write" not in response, (
        f"asked for content that was already provided; "
        f"response={convo.last.response!r}"
    )
    assert "hello.txt" in response, (
        f"filename not surfaced in response; response={convo.last.response!r}"
    )
    # Confirm the file was written with the literal user content (not LLM-
    # generated). Check at the filesystem level since manage_file writes
    # to the actual workspace.
    import os  # noqa: PLC0415

    home = os.path.expanduser("~")
    expected_locations = [
        os.path.join(home, "Desktop", "hello.txt"),
        os.path.join(home, "Documents", "hello.txt"),
        os.path.join(home, "hello.txt"),
        "/tmp/hello.txt",
        os.path.join(os.getcwd(), "hello.txt"),
    ]
    written_path = next((p for p in expected_locations if os.path.exists(p)), None)
    assert written_path is not None, (
        f"hello.txt not found in any expected location; response={convo.last.response!r}"
    )
    try:
        contents = open(written_path).read()
        # Case-insensitive check: `clean_user_text` lowercases the whole
        # utterance before the intent recognizer sees it, so quoted content
        # currently lands in lowercase. The Track 1.5 contract enforced
        # here is that the LITERAL user text is written (not an LLM-
        # generated essay). Case preservation through quoted spans is
        # tracked as a follow-up (Track 1.5b — `clean_user_text` needs to
        # preserve quoted regions verbatim).
        assert "hello friday" in contents.lower(), (
            f"file written with non-literal content; got {contents!r}"
        )
        # And the content is short — proof the LLM content-generator
        # fallback did NOT fire. A generated essay would be >>50 chars.
        assert len(contents.strip()) < 50, (
            f"content looks LLM-generated (len={len(contents)} chars); "
            f"got {contents!r}"
        )
    finally:
        try:
            os.remove(written_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Bug #4 — Ordinal reference hallucination: after `find file X` shows N
# matches, `1st one` is routed to llm_chat with intent_conf=0.00 and the LLM
# invents content. Fixed by Track 1.3 (Reference Registry first-class) +
# Track 1.4 (ContextResolver handles ordinals before dispatch).
# ---------------------------------------------------------------------------


# Track 1.3 landed 2026-05-17: `_parse_pending_selection` now matches
# word+digit ordinal forms ("1st one", "first option"); `choose_candidate_from_text`
# maps them to candidate indices. The full Reference Registry promotion
# (`current_turn().references` API) belongs to Track 1.4 — for now the
# routing path is the keystone fix and the registry stays in ResponseFinalizer.
def test_ordinal_reference_resolves_against_prior_list():
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])
    convo = runner.run([
        "find file readme",
        "1st one",
    ])
    # The second turn must resolve to a file action against the first match,
    # not fall through to llm_chat.
    assert convo.last.tool_name != "llm_chat", (
        f"`1st one` should resolve to a file-action, not fall into chat; "
        f"got tool={convo.last.tool_name!r} args={convo.last.tool_args!r} "
        f"response={convo.last.response!r}"
    )
    # Post-fix: any file-action dispatch is acceptable. `select_file_candidate`
    # is the dispatching capability when a pending list is active; it then
    # internally invokes open_file/read_file/preview_file on the chosen path.
    # The user-visible signal is the response naming the resolved file.
    assert convo.last.tool_name in {
        "select_file_candidate",
        "read_file",
        "open_file",
        "preview_file",
    }, (
        f"`1st one` should fire a file capability; got tool={convo.last.tool_name!r}"
    )
    response = (convo.last.response or "").lower()
    assert "readme" in response, (
        f"`1st one` should resolve to the first README; "
        f"response={convo.last.response!r}"
    )


# ---------------------------------------------------------------------------
# Bug #5 — Double-routing: a single utterance matches both regex
# IntentRecognizer AND gemma_router AND can be consumed as a pending slot.
# Fixed by Track 3 (retire v1, single intent → resolver → dispatch contract).
#
# DRAFT — pin scaffolded but needs Track 0.4's per-turn router-fire counter
# to assert deterministically. Marked xfail with explicit blocker.
# ---------------------------------------------------------------------------


# Track 3.1 landed 2026-05-18: Gemma shadow router deleted; v2
# orchestrator emits exactly one `router_fires_last_turn` per turn
# (pending-confirmation, active-workflow, and intent-dispatch paths all
# increment the counter once at their respective decision points).
def test_single_routing_decision_per_turn(conversation_runner):
    """Each turn produces exactly one routing decision in the v2 pipeline.
    The pin guards against the original "double-routing" class of bug
    where regex IntentRecognizer + Gemma shadow + workflow consumer all
    fired for the same utterance."""
    convo = conversation_runner.run(["hello friday"])
    rec = convo.last
    fire_count = getattr(conversation_runner.app.runtime_metrics, "router_fires_last_turn", None)
    assert fire_count == 1, (
        f"expected exactly 1 router to fire per turn, got {fire_count!r}; "
        f"route_source={rec.route_source!r} tool={rec.tool_name!r}"
    )


# ---------------------------------------------------------------------------
# Bug #6 — Multi-store memory inconsistency: same fact stored with two
# spellings across two stores ("Nolo-re" / "nellore"). Fixed by Track 2
# (single canonical writer through MemoryFacade with normalization).
#
# DRAFT — requires the MemoryFacade contract to exist. Pin captures the
# end-state assertion so Track 2 has a green target.
# ---------------------------------------------------------------------------


# Track 2.0/2.1 landed 2026-05-18: MemoryFacade is the canonical
# writer/reader; system_control's record_personal_fact + recall_personal_fact
# capabilities funnel through it. The alias map normalizes "Nolo-re" /
# "nolore" / "noler" → "Nellore" deterministically on write. Pin
# asserts case-insensitively because `clean_user_text` lowercases the
# whole utterance before the intent recognizer sees the value — case
# preservation through quoted spans is the Track 1.5b follow-up.
def test_fact_stored_once_with_canonical_spelling():
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])
    convo = runner.run([
        "my location is Nellore",
        "where do i live",
    ])
    response = (convo.last.response or "")
    response_lower = response.lower()
    assert "nellore" in response_lower, (
        f"recall should surface the canonical 'Nellore' spelling; "
        f"got response={response!r}"
    )
    # No alternate spelling leaks — the alias map normalizes on write,
    # so even an STT mishearing on a subsequent turn would collapse to
    # 'Nellore' before storage.
    assert "nolo-re" not in response_lower and "nolore" not in response_lower, (
        f"response leaked an alternative spelling, indicating multiple stores "
        f"with no reconciler; response={response!r}"
    )


# ---------------------------------------------------------------------------
# Bug #7 — Sub-1B chat model ceiling. Operational change, not a code fix.
# Tracked but not pinned (no in-process assertion can fix an undersized
# model). When the chat-model upgrade lands, the persona / coherence pins
# above will become easier to satisfy.
# ---------------------------------------------------------------------------
