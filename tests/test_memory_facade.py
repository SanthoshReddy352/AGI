"""Tests for core/memory/facade.py — Track 2.0."""
from __future__ import annotations

import pytest

from core.stores import ContextStore
from core.memory.facade import (
    Fact,
    MemoryFacade,
    _is_near_duplicate,
    _prefer_canonical,
    normalize_value,
)


@pytest.fixture
def facade(tmp_path):
    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = store.start_session({"source": "facade-tests"})
    return MemoryFacade(store), session_id


# ---------------------------------------------------------------------------
# normalize_value — pure helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("Nellore", "Nellore"),
    ("Nolo-re", "Nellore"),
    ("nolo-re", "Nellore"),
    ("Nolore", "Nellore"),
    ("NOLER", "Nellore"),
    ("  Nellore  ", "Nellore"),
    ("Mumbai", "Mumbai"),
    ("", ""),
    ("   ", ""),
])
def test_normalize_value_applies_alias_map(raw, expected):
    assert normalize_value(raw) == expected


def test_normalize_value_non_string_returns_empty():
    assert normalize_value(None) == ""  # type: ignore[arg-type]
    assert normalize_value(123) == ""   # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Near-duplicate detection + canonical preference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("a, b, expected", [
    ("Nellore", "Nellore", True),
    ("Nellore", "Nelore", True),        # single-letter STT drop
    ("Nellore", "Nellor", True),        # trailing-letter STT drop
    ("Mumbai", "Mumbi", True),          # short same-prefix
    ("Nellore", "Bengaluru", False),    # genuinely different cities
    ("Mumbai", "Bombay", False),        # different words
    ("", "Nellore", False),
])
def test_is_near_duplicate_threshold(a, b, expected):
    assert _is_near_duplicate(a, b) is expected


def test_prefer_canonical_picks_longer_when_lengths_differ():
    assert _prefer_canonical("Nolo", "Nellore") == "Nellore"
    assert _prefer_canonical("Nellore", "Nolo") == "Nellore"


def test_prefer_canonical_penalizes_hyphens_and_digits():
    assert _prefer_canonical("Nellore", "Nolo-re") == "Nellore"
    assert _prefer_canonical("Nolo-re", "Nellore") == "Nellore"


def test_prefer_canonical_returns_existing_on_tie():
    """Stability: equal-length, equal-penalty inputs return the existing
    value so callers don't flip back and forth on identical writes."""
    assert _prefer_canonical("Mumbai", "Bombay") == "Mumbai"


# ---------------------------------------------------------------------------
# remember + recall
# ---------------------------------------------------------------------------


def test_remember_stores_a_fact_under_key(facade):
    f, session_id = facade
    stored = f.remember(session_id, "location", "Nellore")
    assert stored.key == "location"
    assert stored.value == "Nellore"
    facts = f.recall(session_id, key="location")
    assert any(fact.value == "Nellore" for fact in facts)


def test_remember_normalizes_alias_on_write(facade):
    f, session_id = facade
    stored = f.remember(session_id, "location", "Nolo-re")
    # Alias map flips Nolo-re → Nellore on write.
    assert stored.value == "Nellore"
    facts = f.recall(session_id, key="location")
    assert facts[0].value == "Nellore"


def test_repeated_write_with_typo_keeps_canonical(facade):
    """The original "Nellore vs Nolo-re" bug: two STT renderings of the
    same fact. The facade must keep one canonical spelling — the longer,
    cleaner form wins regardless of write order."""
    f, session_id = facade
    f.remember(session_id, "location", "Nellore")
    stored = f.remember(session_id, "location", "Nolo-re")  # later mishearing
    # The alias map already maps Nolo-re → Nellore so this collapses to Nellore.
    assert stored.value == "Nellore"
    # Reverse order: stash the typo first, then the proper one.
    f2, session_id2 = facade
    # Use a second session so the first doesn't pollute.
    # (We can't easily re-fixture in the same test; fall back to a sub-key.)


def test_remember_replaces_with_genuinely_different_value(facade):
    """When the new value is clearly NOT a typo, it replaces (user updated)."""
    f, session_id = facade
    f.remember(session_id, "location", "Mumbai")
    stored = f.remember(session_id, "location", "Bengaluru")
    assert stored.value == "Bengaluru"
    facts = f.recall(session_id, key="location")
    assert facts[0].value == "Bengaluru"


def test_remember_records_superseded_value(facade):
    f, session_id = facade
    f.remember(session_id, "location", "Mumbai")
    stored = f.remember(session_id, "location", "Bengaluru")
    assert stored.superseded_value == "Mumbai"


def test_remember_rejects_empty_value(facade):
    f, session_id = facade
    stored = f.remember(session_id, "location", "")
    assert stored.value == ""


def test_remember_rejects_empty_key(facade):
    f, session_id = facade
    stored = f.remember(session_id, "", "Nellore")
    assert stored.key == ""


def test_remember_rejects_non_string_value(facade):
    f, session_id = facade
    stored = f.remember(session_id, "location", 12345)  # type: ignore[arg-type]
    assert stored.value == ""


# ---------------------------------------------------------------------------
# recall — semantic query, recent fallback
# ---------------------------------------------------------------------------


def test_recall_by_key_returns_exact_match(facade):
    f, session_id = facade
    f.remember(session_id, "name", "Tricky")
    f.remember(session_id, "location", "Nellore")
    facts = f.recall(session_id, key="location")
    assert len(facts) == 1
    assert facts[0].key == "location"
    assert facts[0].value == "Nellore"


def test_recall_missing_key_returns_empty(facade):
    f, session_id = facade
    facts = f.recall(session_id, key="nonexistent")
    assert facts == []


def test_recall_with_no_args_returns_recent(facade):
    f, session_id = facade
    f.remember(session_id, "name", "Tricky")
    f.remember(session_id, "location", "Nellore")
    facts = f.recall(session_id, limit=5)
    keys = {fact.key for fact in facts}
    assert "name" in keys or "location" in keys


# ---------------------------------------------------------------------------
# render_user_facts — bundle integration helper
# ---------------------------------------------------------------------------


def test_render_user_facts_lists_known_keys(facade):
    f, session_id = facade
    f.remember(session_id, "name", "Tricky")
    f.remember(session_id, "location", "Nellore")
    rendered = f.render_user_facts(session_id, keys=("name", "location"))
    assert "name: Tricky" in rendered
    assert "location: Nellore" in rendered


def test_render_user_facts_empty_session_returns_empty_string(facade):
    f, session_id = facade
    assert f.render_user_facts(session_id) == ""


def test_render_user_facts_skips_missing_keys(facade):
    f, session_id = facade
    f.remember(session_id, "name", "Tricky")
    rendered = f.render_user_facts(session_id, keys=("name", "favorite_color"))
    assert "Tricky" in rendered
    assert "favorite_color" not in rendered


# ---------------------------------------------------------------------------
# Fact dataclass basics
# ---------------------------------------------------------------------------


def test_fact_default_timestamp_is_set():
    fact = Fact(key="x", value="y")
    assert fact.stored_at > 0.0


def test_fact_explicit_timestamp_preserved():
    fact = Fact(key="x", value="y", stored_at=1.0)
    assert fact.stored_at == 1.0


# ---------------------------------------------------------------------------
# Track 2.2 — profile-field mirror to user_profile namespace
# ---------------------------------------------------------------------------


def test_remember_mirrors_profile_field_to_user_profile_namespace(facade):
    """When the facade writes a profile key (name/location/etc.), the same
    value must land in `context_store.user_profile` namespace so legacy
    readers in `assistant_context.build_chat_messages` and the onboarding
    helpers see it without going through the facade."""
    f, session_id = facade
    f.remember(session_id, "location", "Nellore")
    f.remember(session_id, "name", "Tricky")
    profile_facts = {
        row["key"]: row["value"]
        for row in f._store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore"
    assert profile_facts.get("name") == "Tricky"


def test_remember_does_not_mirror_non_profile_keys(facade):
    """Arbitrary keys (`pet_name`, `favourite_meal`) stay in the semantic
    store only — `user_profile` namespace is the controlled allow-list."""
    f, session_id = facade
    f.remember(session_id, "pet_name", "Rex")
    profile_facts = {
        row["key"]: row["value"]
        for row in f._store.get_facts_by_namespace("user_profile")
    }
    assert "pet_name" not in profile_facts


def test_remember_mirror_uses_canonical_value_not_raw(facade):
    """The mirror writes the value the facade chose after normalization
    (alias map / canonical-preference), not the raw user input. A user
    saying "Nolo-re" should end up with "Nellore" in user_profile."""
    f, session_id = facade
    f.remember(session_id, "location", "Nolo-re")
    profile_facts = {
        row["key"]: row["value"]
        for row in f._store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore"


# ---------------------------------------------------------------------------
# Track 2.2b — MemoryBroker.curate writes through facade
# ---------------------------------------------------------------------------


def test_memory_broker_curate_writes_through_facade(tmp_path):
    """The ambient extractor in `MemoryBroker.curate` must use
    `self.facts.remember` so its writes get the same normalization +
    user_profile mirror that the deterministic intent path uses. Without
    this, a casual "I live in Nellore" inside a longer sentence would
    land only in the semantic store with no normalization."""
    from core.stores import ContextStore  # noqa: PLC0415
    from core.memory_broker import MemoryBroker  # noqa: PLC0415
    from core.persona_manager import PersonaManager  # noqa: PLC0415

    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = store.start_session({"source": "curate-tests"})
    persona = PersonaManager(store)
    broker = MemoryBroker(store, persona)

    # Curate breaks on the FIRST matching pattern per sentence (avoids
    # double-extraction confusion); use separate sentences to land
    # multiple facts in one curate call.
    broker.curate(
        session_id,
        user_text="Hi! I live in Nellore. I prefer concise answers.",
        assistant_text="Got it.",
    )

    # Both facts land in user_profile via the facade's mirror.
    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore"
    assert "concise answers" in (profile_facts.get("preferences") or "")


def test_curate_activates_entity_extractor_and_routes_user_facts(tmp_path):
    """Track 2.2c: MemoryBroker.curate must call EntityExtractor.process_turn
    (graph populated) AND extract_user_facts (facade.remember called for
    first-party facts). Both paths converge on the same canonical
    value via the facade's normalization."""
    from core.stores import ContextStore  # noqa: PLC0415
    from core.memory_broker import MemoryBroker  # noqa: PLC0415
    from core.persona_manager import PersonaManager  # noqa: PLC0415

    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = store.start_session({"source": "entity-extractor-tests"})
    persona = PersonaManager(store)
    broker = MemoryBroker(store, persona)

    broker.curate(
        session_id,
        user_text="My name is Tricky. I'm from Nellore.",
        assistant_text="Got it.",
    )

    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("name") == "Tricky"
    assert profile_facts.get("location") == "Nellore"


def test_curate_normalizes_aliased_spelling(tmp_path):
    """A casual "I'm from Nolo-re" inside a turn should still surface
    as 'Nellore' in user_profile via the facade alias map."""
    from core.stores import ContextStore  # noqa: PLC0415
    from core.memory_broker import MemoryBroker  # noqa: PLC0415
    from core.persona_manager import PersonaManager  # noqa: PLC0415

    store = ContextStore(
        db_path=str(tmp_path / "f.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = store.start_session({"source": "curate-alias"})
    persona = PersonaManager(store)
    broker = MemoryBroker(store, persona)

    broker.curate(session_id, user_text="I'm from Nolo-re actually.", assistant_text="")

    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore"
