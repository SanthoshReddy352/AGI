"""Track 1.2 — WorkingArtifact scope precedence.

The original bug: an `explicit` artifact from N turns back silently survived
against a more recent auto-scope save, so pronoun targets ("read it") could
return a stale file. The fix introduces strict precedence ranks
`last_write > explicit > auto > inferred`, where a real file mutation
always wins over any earlier pronoun anchor.

These tests assert the precedence at the storage layer directly, so a
future change to the file-workspace handler can't silently bypass the
contract without breaking this guard.
"""
from __future__ import annotations

import pytest

from core.stores import (
    ARTIFACT_SCOPE_RANK,
    ContextStore,
    WorkingArtifact,
    artifact_scope_rank,
)


@pytest.fixture
def store(tmp_path):
    s = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = s.start_session({"source": "scope-tests"})
    return s, session_id


def _save(store, session_id, path, scope):
    store.save_artifact(
        session_id,
        WorkingArtifact(
            content="",
            output_type="file",
            capability_name="test",
            artifact_type="file",
            source_path=path,
            scope=scope,
        ),
    )


def test_rank_order_is_inferred_auto_explicit_last_write_session():
    assert ARTIFACT_SCOPE_RANK["inferred"] == 1
    assert ARTIFACT_SCOPE_RANK["auto"] == 2
    assert ARTIFACT_SCOPE_RANK["explicit"] == 3
    assert ARTIFACT_SCOPE_RANK["last_write"] == 4
    assert ARTIFACT_SCOPE_RANK["session"] == 5


def test_unknown_scope_defaults_to_auto_rank():
    assert artifact_scope_rank("not_a_real_scope") == ARTIFACT_SCOPE_RANK["auto"]
    assert artifact_scope_rank("") == ARTIFACT_SCOPE_RANK["auto"]


def test_auto_save_does_not_displace_explicit(store):
    s, session_id = store
    _save(s, session_id, "/tmp/explicit.txt", "explicit")
    _save(s, session_id, "/tmp/noisy_auto.txt", "auto")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/explicit.txt"
    assert artifact.scope == "explicit"


def test_last_write_displaces_stale_explicit(store):
    """The Track 1.2 fix — a fresh file mutation must always win over a
    stale pronoun target so "read it" returns the just-written file."""
    s, session_id = store
    _save(s, session_id, "/tmp/stale_explicit.txt", "explicit")
    _save(s, session_id, "/tmp/fresh_write.txt", "last_write")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/fresh_write.txt"
    assert artifact.scope == "last_write"


def test_same_rank_save_wins_later(store):
    s, session_id = store
    _save(s, session_id, "/tmp/first.txt", "explicit")
    _save(s, session_id, "/tmp/second.txt", "explicit")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/second.txt"


def test_explicit_does_not_displace_last_write(store):
    """Once `last_write` is set, a later `explicit` (e.g. user names a
    different file without writing) does not steal the slot from the
    actually-written file. The user must perform another write to bump."""
    s, session_id = store
    _save(s, session_id, "/tmp/just_written.txt", "last_write")
    _save(s, session_id, "/tmp/just_named.txt", "explicit")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/just_written.txt"


def test_last_write_displaces_earlier_last_write(store):
    s, session_id = store
    _save(s, session_id, "/tmp/first_write.txt", "last_write")
    _save(s, session_id, "/tmp/second_write.txt", "last_write")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/second_write.txt"


def test_session_pin_outranks_everything(store):
    s, session_id = store
    _save(s, session_id, "/tmp/pinned.txt", "session")
    _save(s, session_id, "/tmp/later_write.txt", "last_write")
    _save(s, session_id, "/tmp/later_explicit.txt", "explicit")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/pinned.txt"


def test_empty_session_starts_with_no_artifact(store):
    s, session_id = store
    assert s.get_artifact(session_id) is None


def test_first_save_always_wins_against_empty_slot(store):
    """No precedence floor when the slot is empty — any first save lands,
    even an `inferred`-scope one."""
    s, session_id = store
    _save(s, session_id, "/tmp/guess.txt", "inferred")
    artifact = s.get_artifact(session_id)
    assert artifact is not None
    assert artifact.source_path == "/tmp/guess.txt"
    assert artifact.scope == "inferred"
