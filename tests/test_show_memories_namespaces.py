"""P0.4 — `show_memories` merges user_profile + per-session facts."""
from types import SimpleNamespace

import pytest

from modules.memory_manager.plugin import MemoryManagerPlugin


class _FakeFact:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class _FakeFacade:
    def __init__(self, rows):
        self._rows = rows

    def list_all(self, session_id, limit=20):
        return list(self._rows[:limit])


class _FakeContextStore:
    def __init__(self, profile_rows):
        self._profile = profile_rows

    def get_facts_by_namespace(self, ns):
        if ns == "user_profile":
            return list(self._profile)
        return []


def _make_plugin(profile_rows=(), session_facts=()):
    # Build a stand-in app that doesn't need the full FridayApp boot.
    fake_app = SimpleNamespace(
        context_store=_FakeContextStore(profile_rows),
        memory_broker=SimpleNamespace(facts=_FakeFacade(session_facts)),
        session_id="sess1",
        register_capability=lambda *a, **k: None,
    )
    plugin = MemoryManagerPlugin.__new__(MemoryManagerPlugin)
    plugin.app = fake_app
    plugin.name = "memory_manager"
    return plugin


def test_returns_friendly_empty_when_nothing_stored():
    """2026-05-23 rewrite: bullet-list output replaced by a natural
    paragraph. The empty-state message is now a one-liner that invites
    the user to share something — still no facts shown, but the
    phrasing changed."""
    p = _make_plugin()
    out = p._handle_show_memories("", {}).lower()
    # Either phrasing is OK as long as we admit we don't have anything.
    assert "don't have" in out or "nothing" in out


def test_shows_user_profile_section():
    profile = [{"key": "name", "value": "Santhosh"},
               {"key": "role", "value": "engineer"}]
    p = _make_plugin(profile_rows=profile)
    out = p._handle_show_memories("", {})
    # Paragraph form — no bullet list, no markdown header.
    assert "**About you:**" not in out
    assert "  -" not in out
    assert "Santhosh" in out
    assert "engineer" in out
    # Should read like a sentence, not a list dump.
    assert out.count("\n") <= 1


def test_shows_session_facts_section():
    facts = [_FakeFact("loves", "cars"), _FakeFact("likes", "jazz")]
    p = _make_plugin(session_facts=facts)
    out = p._handle_show_memories("", {})
    assert "**You told me:**" not in out
    assert "cars" in out
    assert "jazz" in out


def test_merges_both_sections():
    profile = [{"key": "name", "value": "Santhosh"}]
    facts = [_FakeFact("loves", "cars")]
    p = _make_plugin(profile_rows=profile, session_facts=facts)
    out = p._handle_show_memories("", {})
    # Profile clause must come before the memory clause in the paragraph.
    assert "Santhosh" in out
    assert "cars" in out
    assert out.index("Santhosh") < out.index("cars")


def test_skips_blank_profile_values():
    profile = [{"key": "name", "value": "Santhosh"},
               {"key": "location", "value": "   "}]
    p = _make_plugin(profile_rows=profile)
    out = p._handle_show_memories("", {})
    assert "Santhosh" in out
    assert "location" not in out  # blank value suppressed


def test_limit_arg_is_parsed_and_respected():
    facts = [_FakeFact(f"k{i}", f"v{i}") for i in range(10)]
    p = _make_plugin(session_facts=facts)
    out = p._handle_show_memories("", {"limit": 3})
    # Composer renders up to 5 memories; with limit=3 we should see 3
    # and only 3 of them.
    seen = sum(1 for i in range(10) if f"k{i}" in out)
    assert seen == 3


def test_non_numeric_limit_defaults_to_20():
    facts = [_FakeFact(f"k{i}", f"v{i}") for i in range(5)]
    p = _make_plugin(session_facts=facts)
    out = p._handle_show_memories("", {"limit": "bad"})
    seen = sum(1 for i in range(5) if f"k{i}" in out)
    assert seen == 5


def test_context_store_exception_does_not_crash():
    class BadCS:
        def get_facts_by_namespace(self, ns):
            raise RuntimeError("db down")
    facts = [_FakeFact("loves", "cars")]
    fake_app = SimpleNamespace(
        context_store=BadCS(),
        memory_broker=SimpleNamespace(facts=_FakeFacade(facts)),
        session_id="sess1",
        register_capability=lambda *a, **k: None,
    )
    plugin = MemoryManagerPlugin.__new__(MemoryManagerPlugin)
    plugin.app = fake_app
    plugin.name = "memory_manager"
    out = plugin._handle_show_memories("", {})
    assert "cars" in out
