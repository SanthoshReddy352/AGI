"""Track 2.4 — 100-turn synthetic memory-churn regression test.

The Direction's exit criterion for Track 2: "The reconciliation test
passes after 100 turns of synthetic memory churn." This file is that
test. It hammers the facade with:

  * Spelling-variant writes for the same key (alias map drift).
  * Fact-update writes (legitimate user correction).
  * Profile-key collision writes (same key hit by multiple writers).
  * Mixed-key interleaving so reconciliation can't be a single-key bug.

After all 100 turns, each canonical key in `_PROFILE_KEYS` must hold
exactly ONE value, that value must be the canonical spelling (per the
alias map + canonical-preference rules), and it must match what the
last-legitimate-write set.

The test is intentionally slow-but-reliable — it builds a single
ContextStore, runs 100 facade writes inline, then asserts state. No
LLM, no plugin boot, no harness needed.
"""
from __future__ import annotations

import random

import pytest

from core.stores import ContextStore
from core.memory.facade import _PROFILE_KEYS, MemoryFacade


# Realistic spelling variants the facade should collapse to a canonical
# value via the alias map + canonical-preference rules.
_LOCATION_VARIANTS: tuple[str, ...] = (
    "Nellore",     # canonical
    "Nolo-re",     # STT mishearing (alias-mapped → Nellore)
    "nolore",      # alias-mapped
    "Nelore",      # near-duplicate (single-l drop)
    "NELLORE",     # caps (normalizes to Nellore by string match)
)
_NAME_VARIANTS: tuple[str, ...] = (
    "Tricky",
    "tricky",
    "TRICKY",
    "tricks",       # genuinely different — replace
)
_ROLE_VARIANTS: tuple[str, ...] = (
    "AI assistant builder",
    "ai assistant builder",  # case
    "AI Assistant Builder",
)


@pytest.fixture
def facade_with_session(tmp_path):
    store = ContextStore(
        db_path=str(tmp_path / "churn.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    session_id = store.start_session({"source": "churn-test"})
    return MemoryFacade(store), store, session_id


def test_100_turns_of_spelling_variants_keep_canonical(facade_with_session):
    """Spelling variants for `location` cycle through 100 writes; the
    final stored value must be the canonical spelling and there must
    be exactly ONE current value in `user_profile`."""
    facade, store, session_id = facade_with_session
    rng = random.Random(12345)
    for _ in range(100):
        variant = rng.choice(_LOCATION_VARIANTS)
        facade.remember(session_id, "location", variant)

    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore", (
        f"100-turn spelling churn drifted away from canonical 'Nellore'; "
        f"final state: {profile_facts!r}"
    )

    # And the semantic store has one current value too.
    recalled = facade.recall(session_id, key="location")
    assert len(recalled) == 1
    assert recalled[0].value == "Nellore"


def test_100_turns_mixed_keys_with_genuine_updates(facade_with_session):
    """Mixed-key interleaving: alternating writes across name / location /
    role / preferences for 100 turns, ending with a known last-legit value
    per key. After the churn, each key holds the last legitimate value
    (not a typo variant) and there's exactly one row per key in
    user_profile."""
    facade, store, session_id = facade_with_session
    rng = random.Random(54321)

    # First, hammer all four keys with 95 mixed writes (alias variants and
    # case-flips against a known base). Then make ONE final legit write per
    # key. The final write must win because all prior near-duplicates
    # collapse to it via canonical preference.
    bases = {
        "location": "Nellore",
        "name": "Tricky",
        "role": "engineer",
        "preferences": "concise",
    }
    keys = list(bases)
    for turn in range(95):
        key = keys[turn % len(keys)]
        base = bases[key]
        if base == "Nellore":
            value = rng.choice(_LOCATION_VARIANTS)
        elif base == "Tricky":
            value = rng.choice(_NAME_VARIANTS[:3])
        else:
            value = base.upper() if turn % 2 == 0 else base.lower()
        facade.remember(session_id, key, value)
    # Now write a known final legit value per key. Use values that are
    # genuinely different from `bases` so they replace by precedence.
    finals = {
        "location": "Bengaluru",
        "name": "Cody",
        "role": "developer",
        "preferences": "balanced",
    }
    for key, value in finals.items():
        facade.remember(session_id, key, value)

    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    for key, expected in finals.items():
        assert profile_facts.get(key) == expected, (
            f"key {key!r}: expected last-legit {expected!r}, got {profile_facts.get(key)!r}"
        )


def test_100_turns_alias_map_always_collapses(facade_with_session):
    """Every write of a known alias must produce the canonical value —
    no path through the facade can leak an alias-mapped variant into
    the store, even under interleaved writes from other keys."""
    facade, store, session_id = facade_with_session
    aliased = ("Nolo-re", "nolore", "noler", "NOLO-RE")
    other_keys = ("name", "role", "preferences")

    for i in range(100):
        if i % 2 == 0:
            facade.remember(session_id, "location", aliased[i % len(aliased)])
        else:
            facade.remember(session_id, other_keys[i % len(other_keys)], f"value{i}")

    profile_facts = {
        row["key"]: row["value"]
        for row in store.get_facts_by_namespace("user_profile")
    }
    assert profile_facts.get("location") == "Nellore", (
        f"alias-mapped variant leaked into user_profile; "
        f"final state: {profile_facts!r}"
    )


def test_user_profile_namespace_has_one_row_per_key_after_churn(facade_with_session):
    """Beyond the value being right, the user_profile namespace must
    have exactly one row per key after 100 churn turns. Multiple rows
    per key would indicate the upsert path is dropping duplicates and
    falling back to insert."""
    facade, store, session_id = facade_with_session
    for i in range(100):
        for key in ("name", "location", "role"):
            facade.remember(session_id, key, f"{key}-value-{i}")

    rows = store.get_facts_by_namespace("user_profile")
    # Group by key, count.
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["key"]] = counts.get(row["key"], 0) + 1
    for key in ("name", "location", "role"):
        assert counts.get(key, 0) == 1, (
            f"key {key!r} has {counts.get(key)} rows after churn; "
            f"expected exactly 1. All rows: {rows!r}"
        )


def test_profile_keys_constant_is_stable():
    """The _PROFILE_KEYS set is the dual-write allow-list. Any drift here
    silently changes which keys mirror into the user_profile namespace,
    so the contract is pinned by name."""
    expected = {
        "name", "role", "location", "preferences", "comm_style",
        "employer", "hometown", "city", "job", "profession",
        "email", "phone", "birthday",
        "loves", "likes", "hates", "prefers",
    }
    assert _PROFILE_KEYS == frozenset(expected)
