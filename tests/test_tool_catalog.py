"""Tool catalog loader + chat pre-flight reroute tests (Step 4b)."""
from __future__ import annotations

import os
import textwrap
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── catalog loader ────────────────────────────────────────────────────────


def test_real_catalog_loads_without_warnings(caplog):
    """The shipped data/tool_catalog.yaml must parse cleanly."""
    from core.tool_catalog import load_catalog
    catalog = load_catalog()
    # We expect ~70+ tools — fail loud if the file is empty.
    assert len(catalog) > 40, f"catalog only has {len(catalog)} entries"
    # Every entry must have at least one example phrase to be useful.
    bare = [e.name for e in catalog if not e.example_phrases]
    assert not bare, f"catalog entries without example_phrases: {bare}"
    # Categories must not be empty.
    bare_cat = [e.name for e in catalog if not e.category]
    assert not bare_cat, f"catalog entries without category: {bare_cat}"


def test_catalog_no_duplicate_names():
    from core.tool_catalog import load_catalog
    catalog = load_catalog()
    names = catalog.names()
    assert len(names) == len(set(names)), "duplicate name in catalog"


def test_load_catalog_missing_file_returns_empty(tmp_path):
    from core.tool_catalog import load_catalog
    catalog = load_catalog(str(tmp_path / "nope.yaml"))
    assert len(catalog) == 0
    assert catalog.names() == []


def test_load_catalog_malformed_yaml_returns_empty(tmp_path):
    from core.tool_catalog import load_catalog
    f = tmp_path / "broken.yaml"
    f.write_text(":\n::not valid yaml\n", encoding="utf-8")
    catalog = load_catalog(str(f))
    assert len(catalog) == 0


def test_load_catalog_no_tools_key_returns_empty(tmp_path):
    from core.tool_catalog import load_catalog
    f = tmp_path / "wrong_shape.yaml"
    f.write_text("version: 1\n", encoding="utf-8")
    catalog = load_catalog(str(f))
    assert len(catalog) == 0


def test_load_catalog_drops_unnamed_entries(tmp_path, caplog):
    from core.tool_catalog import load_catalog
    f = tmp_path / "partial.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: foo
            category: x
            summary: a foo tool
            example_phrases: ["do foo"]
          - {category: y, summary: noop}     # no name → dropped
    """), encoding="utf-8")
    catalog = load_catalog(str(f))
    assert catalog.names() == ["foo"]


def test_load_catalog_drops_duplicates(tmp_path):
    from core.tool_catalog import load_catalog
    f = tmp_path / "dup.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: bar
            category: x
            summary: first
            example_phrases: ["a"]
          - name: bar
            category: x
            summary: dup
            example_phrases: ["b"]
    """), encoding="utf-8")
    catalog = load_catalog(str(f))
    assert catalog.names() == ["bar"]
    assert catalog.entry_for("bar").summary == "first"


def test_entry_is_safe_for_preflight_honours_flag(tmp_path):
    from core.tool_catalog import load_catalog
    f = tmp_path / "preflight.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: safe_tool
            category: x
            summary: safe
            example_phrases: ["go"]
          - name: needs_args_tool
            category: x
            summary: needs args
            example_phrases: ["set it"]
            blocked_from_chat_preflight: true
          - name: not_embed_tool
            category: x
            summary: not embeddable
            example_phrases: ["x"]
            embeddable: false
    """), encoding="utf-8")
    catalog = load_catalog(str(f))
    assert catalog.entry_for("safe_tool").is_safe_for_preflight is True
    assert catalog.entry_for("needs_args_tool").is_safe_for_preflight is False
    assert catalog.entry_for("not_embed_tool").is_safe_for_preflight is False


def test_iter_phrases_yields_all():
    from core.tool_catalog import load_catalog
    catalog = load_catalog()
    pairs = list(catalog.iter_phrases())
    # At least 5 phrases per tool on average — we ship many more.
    assert len(pairs) > 5 * len(catalog) // 2
    # Every (name, phrase) pair: phrase is non-empty, name is in catalog.
    names = set(catalog.names())
    for name, phrase in pairs:
        assert name in names
        assert phrase and isinstance(phrase, str)


def test_bind_registry_warns_on_stale_entries(tmp_path, caplog):
    from core.tool_catalog import load_catalog
    f = tmp_path / "stale.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: real_tool
            category: x
            summary: real
            example_phrases: ["go"]
          - name: never_registered_tool
            category: x
            summary: stale
            example_phrases: ["nope"]
    """), encoding="utf-8")
    catalog = load_catalog(str(f))

    import logging
    caplog.set_level(logging.WARNING)
    catalog.bind_registry({"real_tool": object()})

    assert any(
        "never_registered_tool" in record.getMessage()
        for record in caplog.records
    ), "expected a stale-entry warning"


def test_bind_registry_logs_missing_catalog_entries(tmp_path, caplog):
    from core.tool_catalog import load_catalog
    f = tmp_path / "tiny.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: a
            category: x
            summary: a
            example_phrases: ["a"]
    """), encoding="utf-8")
    catalog = load_catalog(str(f))

    import logging
    caplog.set_level(logging.INFO)
    catalog.bind_registry({"a": object(), "new_unmapped_tool": object()})

    assert any(
        "new_unmapped_tool" in record.getMessage()
        for record in caplog.records
    )


# ── EmbeddingRouter — uses catalog phrases when available ────────────────


class _FakeModel:
    """Deterministic stub that maps phrases → 384-dim vectors via hash.

    Identical strings → identical vectors → cosine 1.0. Different strings
    → orthogonal-ish vectors → cosine near 0. Good enough for testing
    "did the right phrases get indexed?" without loading MiniLM.
    """

    def encode(self, phrases, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False):
        import hashlib
        import numpy as np
        vecs = []
        for p in phrases:
            h = hashlib.sha256(p.encode("utf-8")).digest()
            # 384 bytes worth — repeat the 32-byte hash 12 times.
            buf = (h * 12)[:384]
            v = np.frombuffer(buf, dtype=np.uint8).astype(np.float32)
            n = np.linalg.norm(v) or 1.0
            v = v / n
            vecs.append(v)
        return np.array(vecs, dtype=np.float32)


def test_embedding_router_uses_catalog_phrases():
    """After build_index runs, every example_phrase from a catalog entry
    should appear in the router's _tool_phrases list."""
    from core.embedding_router import EmbeddingRouter
    from core.tool_catalog import get_catalog

    router = EmbeddingRouter()
    router._model = _FakeModel()  # bypass sentence-transformers load

    # Build a fake registry that includes one tool with a known catalog entry.
    tools_by_name = {
        "get_weather": {
            "spec": {"name": "get_weather", "description": "old description"},
        },
    }
    router.build_index(tools_by_name)

    catalog_phrases = set(
        p for n, p in get_catalog().iter_phrases() if n == "get_weather"
    )
    # Every catalog phrase for get_weather should be among indexed phrases.
    indexed = set(router._tool_phrases)
    missing = catalog_phrases - indexed
    assert not missing, f"catalog phrases not indexed: {missing}"


def test_embedding_router_preflight_skips_blocked_tools(tmp_path):
    """preflight_route() must return None for tools whose catalog entry
    has blocked_from_chat_preflight: true."""
    from core.embedding_router import EmbeddingRouter
    import core.tool_catalog as _tc

    f = tmp_path / "block.yaml"
    f.write_text(textwrap.dedent("""
        version: 1
        tools:
          - name: blocked_tool
            category: x
            summary: needs args
            example_phrases: ["do the blocked thing"]
            blocked_from_chat_preflight: true
    """), encoding="utf-8")
    _tc.reset_catalog_for_tests(str(f))

    router = EmbeddingRouter()
    router._model = _FakeModel()
    router.build_index({"blocked_tool": {"spec": {"name": "blocked_tool"}}})

    # Querying the exact phrase → cosine = 1.0 → would normally dispatch.
    raw = router.route("do the blocked thing")
    assert raw is not None and raw["tool"] == "blocked_tool"
    # But preflight_route honours the catalog gate.
    preflight = router.preflight_route("do the blocked thing")
    assert preflight is None

    _tc.reset_catalog_for_tests()  # restore default


# ── chat-side preflight integration ───────────────────────────────────────


def _make_chat_plugin_with_router(preflight_return):
    """Build LLMChatPlugin with a stub router returning *preflight_return*."""
    from modules.llm_chat.plugin import LLMChatPlugin

    embed_router = MagicMock()
    embed_router.preflight_route.return_value = preflight_return

    router = SimpleNamespace(
        embedding_router=embed_router,
        get_llm=lambda: None,
        chat_inference_lock=MagicMock(__enter__=lambda *a: None, __exit__=lambda *a: None),
    )

    executor = MagicMock()

    app = MagicMock()
    app.router = router
    app.capability_executor = executor
    app.register_capability = MagicMock()

    plugin = LLMChatPlugin.__new__(LLMChatPlugin)
    plugin.app = app
    plugin.name = "LLMChat"
    return plugin, embed_router, executor


def test_chat_preflight_dispatches_when_match():
    plugin, embed_router, executor = _make_chat_plugin_with_router(
        {"tool": "get_weather", "score": 0.81}
    )
    executor.execute.return_value = SimpleNamespace(
        ok=True, output="It's 24°C in Mumbai.", error=""
    )
    response = plugin.handle_chat("what's the weather in Mumbai", {})
    assert response == "It's 24°C in Mumbai."
    executor.execute.assert_called_once()
    args, _ = executor.execute.call_args
    assert args[0] == "get_weather"


def test_chat_preflight_falls_through_when_no_match():
    plugin, embed_router, executor = _make_chat_plugin_with_router(None)
    # No LLM loaded → falls back to "language model isn't loaded" path,
    # which proves preflight returned None and the normal chat code ran.
    response = plugin.handle_chat("write me an essay about elephants", {})
    assert "language model isn't loaded" in response.lower()
    executor.execute.assert_not_called()


def test_chat_preflight_surfaces_tool_failure():
    plugin, embed_router, executor = _make_chat_plugin_with_router(
        {"tool": "host_service_scan", "score": 0.78}
    )
    executor.execute.return_value = SimpleNamespace(
        ok=False, output="", error="Target not in authorized_scopes"
    )
    response = plugin.handle_chat("scan 8.8.8.8", {})
    assert "authorized_scopes" in response


def test_chat_preflight_skips_when_router_missing():
    """If the embedding router isn't wired (e.g. lightweight test app),
    preflight must be a no-op and chat proceeds normally."""
    from modules.llm_chat.plugin import LLMChatPlugin

    router = SimpleNamespace(
        get_llm=lambda: None,
        chat_inference_lock=MagicMock(__enter__=lambda *a: None, __exit__=lambda *a: None),
    )
    app = MagicMock()
    app.router = router
    app.capability_executor = MagicMock()

    plugin = LLMChatPlugin.__new__(LLMChatPlugin)
    plugin.app = app
    plugin.name = "LLMChat"

    response = plugin.handle_chat("hello", {})
    # We just want no crash — falls to the "language model isn't loaded" path.
    assert "language model isn't loaded" in response.lower()


# ── planner card injection ────────────────────────────────────────────────


def test_compact_capability_cards_injects_catalog_examples():
    """A tool with a catalog entry must get an `examples` field on its
    capability card, so the planner prompt can include few-shot phrasings."""
    from core.planning.qwen_planner import QwenPlanner
    from types import SimpleNamespace

    descriptors = [
        SimpleNamespace(
            name="get_weather",
            description="old short description",
            input_schema={"location": {}},
            side_effect_level="read",
            network_scope="online",
            requires_authorization=False,
        ),
        SimpleNamespace(
            name="tool_with_no_catalog_entry_xyz",
            description="something",
            input_schema={},
            side_effect_level="read",
            network_scope="local",
            requires_authorization=False,
        ),
    ]
    cards = QwenPlanner.compact_capability_cards(descriptors)

    weather_card = next(c for c in cards if c["name"] == "get_weather")
    assert "examples" in weather_card, "catalog entry should have produced examples"
    assert len(weather_card["examples"]) >= 3
    # Catalog summary takes precedence over a shorter description.
    assert weather_card["selector_hint"].startswith("Look up current weather")

    none_card = next(c for c in cards if c["name"] == "tool_with_no_catalog_entry_xyz")
    assert "examples" not in none_card or none_card["examples"] == []
