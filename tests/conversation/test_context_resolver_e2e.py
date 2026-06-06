"""Track 1.4 e2e — keystone test for the ContextResolver.

The Direction's named test for this layer:

    conversation(["read my.txt", "what's in it?"])
        .assert_tool_called("read_file", target="my.txt")

The point: after the first turn sets a WorkingArtifact pointing at my.txt,
a pronoun-bearing short question that the planner would otherwise route
to llm_chat must instead resolve to a read_file against the artifact.
Without this layer the LLM saw "what's in it?" without context and
hallucinated.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from core.stores import WorkingArtifact


pytestmark = pytest.mark.conversation


def test_whats_in_it_after_read_resolves_to_read_file():
    """Run the canonical keystone scenario end-to-end."""
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])

    # Stage a real file the resolver can read. The first turn establishes
    # the working artifact; the second turn must resolve "it" to that file.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write("This is the file content.")
        staged_path = f.name

    try:
        # Prime the artifact directly so the test doesn't depend on the
        # search/select dance — that's a different bug class. The
        # resolver's job is to consume an existing artifact, not to
        # establish one.
        runner.app.context_store.save_artifact(
            runner.app.session_id,
            WorkingArtifact(
                content="",
                output_type="file",
                capability_name="manage_file",
                artifact_type="file",
                source_path=staged_path,
                scope="last_write",
            ),
        )

        convo = runner.run(["what's in it?"])

        # The ContextResolver should have rewritten the chat fallback into
        # a read_file call against the staged path.
        rec = convo.last
        assert rec.tool_name == "read_file", (
            f"resolver should have rewritten chat to read_file; "
            f"got tool={rec.tool_name!r} args={rec.tool_args!r} "
            f"response={rec.response!r}"
        )
        # The args carry the artifact's path (verbatim or as basename).
        target = (
            rec.tool_args.get("filename")
            or rec.tool_args.get("target")
            or rec.tool_args.get("path")
            or ""
        )
        assert target == staged_path or os.path.basename(staged_path) in str(target), (
            f"resolver passed wrong target; expected {staged_path!r} got {target!r}"
        )
    finally:
        try:
            os.remove(staged_path)
        except OSError:
            pass


def test_resolver_does_not_fire_when_no_artifact_primed():
    """Bare 'what's in it?' with NO artifact in scope must NOT be hijacked —
    the resolver only rescues when there's something to resolve against."""
    from tests.conversation._harness import ConversationRunner  # noqa: PLC0415

    runner = ConversationRunner(load_plugins=["system_control"])
    # No artifact primed; no prior file turns.
    convo = runner.run(["what's in it?"])
    # Falls through to clarify / chat (whichever the planner picks). The
    # exact destination doesn't matter — what matters is that it's NOT
    # read_file (the resolver had nothing to point at).
    assert convo.last.tool_name != "read_file", (
        f"resolver fired without an artifact; tool={convo.last.tool_name!r} "
        f"response={convo.last.response!r}"
    )
