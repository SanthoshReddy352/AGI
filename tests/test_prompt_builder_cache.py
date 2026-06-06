"""P3.21 — PromptBuilder and PromptCache."""
import time
import pytest
from core.prompt_builder import PromptBuilder, friday_prompt, build_default_messages, FRIDAY_IDENTITY
from core.prompt_caching import PromptCache


# ── PromptBuilder ──────────────────────────────────────────────────────────

def test_build_empty():
    pb = PromptBuilder()
    assert pb.build() == ""


def test_add_section_appears_in_build():
    pb = PromptBuilder().add_section("FOO", "bar content")
    result = pb.build()
    assert "<FOO>" in result
    assert "bar content" in result
    assert "</FOO>" in result


def test_multiple_sections_ordered():
    pb = (PromptBuilder()
          .add_section("A", "first")
          .add_section("B", "second"))
    result = pb.build()
    assert result.index("first") < result.index("second")


def test_remove_section():
    pb = (PromptBuilder()
          .add_section("A", "keep")
          .add_section("B", "remove me"))
    pb.remove_section("B")
    assert "remove me" not in pb.build()
    assert "keep" in pb.build()


def test_build_messages_structure():
    pb = friday_prompt()
    msgs = pb.build_messages("hello")
    roles = [m["role"] for m in msgs]
    assert "system" in roles
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "hello"


def test_friday_prompt_contains_identity():
    pb = friday_prompt()
    system = pb.build()
    assert "FRIDAY" in system
    assert "ASSISTANT_IDENTITY" in system


def test_build_default_messages_with_facts():
    msgs = build_default_messages("who am I?", user_facts="Name: Santhosh")
    system_content = next(m["content"] for m in msgs if m["role"] == "system")
    assert "USER_FACTS" in system_content
    assert "Santhosh" in system_content


def test_empty_section_skipped():
    pb = PromptBuilder().add_section("A", "").add_section("B", "real")
    assert "<A>" not in pb.build()
    assert "<B>" in pb.build()


def test_section_names():
    pb = friday_prompt()
    assert "ASSISTANT_IDENTITY" in pb.section_names()


def test_has_section():
    pb = friday_prompt()
    assert pb.has_section("ASSISTANT_IDENTITY")
    assert not pb.has_section("NONEXISTENT")


# ── PromptCache ────────────────────────────────────────────────────────────

def test_cache_put_and_get():
    c = PromptCache()
    c.put("key1", "value1")
    assert c.get("key1") == "value1"


def test_cache_miss_returns_none():
    c = PromptCache()
    assert c.get("missing") is None


def test_cache_ttl_expiry():
    c = PromptCache()
    c.put("k", "v", ttl=1)
    time.sleep(1.1)
    assert c.get("k") is None


def test_cache_invalidate():
    c = PromptCache()
    c.put("k", "v")
    c.invalidate("k")
    assert c.get("k") is None


def test_cache_invalidate_all():
    c = PromptCache()
    c.put("a", "1")
    c.put("b", "2")
    c.invalidate_all()
    assert c.size() == 0


def test_cache_size():
    c = PromptCache()
    c.put("a", "1")
    c.put("b", "2")
    assert c.size() == 2
