"""Step 5e — end-to-end integration tests for the research pipeline.

These stitch the unit-test islands together so we can prove the full
flow works: intent parsing → handler dispatch → planner.begin() with
explicit mode → service.run_research(mode=…) → quick or deep pipeline
→ file output. Only the LLM and the outbound HTTP fetchers are stubbed
— everything between them is real code.
"""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── shared fixture ──────────────────────────────────────────────────


@pytest.fixture
def _net_stub(tmp_path, monkeypatch):
    """Stub every outbound network call + LLM. Returns the temp
    friday-research root."""
    from modules.research_agent import quick as _q
    monkeypatch.setattr(_q, "_FRIDAY_RESEARCH_ROOT", str(tmp_path))

    monkeypatch.setattr(
        "modules.sources.wikipedia.summary_for_query",
        lambda q: {
            "title": "Anchor",
            "extract": f"Anchor body for {q}.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/X"}},
        },
    )
    monkeypatch.setattr(
        "modules.web.plugin._ddg_search",
        lambda q, max_results=8: [
            {"title": "Web A", "url": "https://a.example/x", "snippet": "snip A"},
            {"title": "Web B", "url": "https://b.example/x", "snippet": "snip B"},
        ],
    )
    monkeypatch.setattr(
        "modules.sources.newspaper.extract_many",
        lambda urls, max_workers=5: [
            {"url": u, "title": f"t-{u[-7:]}", "text": f"body for {u}", "length": 20}
            for u in urls if "example" in u
        ],
    )
    # Stub the domain-specific source plugins so deep mode finds
    # nothing extra for the topics we use.
    monkeypatch.setattr("modules.sources.arxiv.search", lambda q, max_results=5: [])
    monkeypatch.setattr("modules.sources.pubmed.search", lambda q, max_results=5: [])
    monkeypatch.setattr("modules.sources.hackernews.search", lambda q, limit=10: [])
    monkeypatch.setattr("modules.sources.yfinance.quote", lambda t: None)

    return tmp_path


def _stub_llm(canned):
    class _LLM:
        def create_chat_completion(self, messages, max_tokens=0, temperature=0):
            return {"choices": [{"message": {"content": canned}}]}
    return _LLM()


def _build_app(llm):
    lock = MagicMock()
    lock.__enter__ = MagicMock(return_value=None)
    lock.__exit__ = MagicMock(return_value=False)
    router = SimpleNamespace(get_llm=lambda: llm, chat_inference_lock=lock)
    return SimpleNamespace(router=router)


# ── full quick-mode flow ────────────────────────────────────────────


def test_e2e_intent_to_quick_pipeline(_net_stub):
    """User types 'tldr GPT history'. Verify the whole chain runs and
    produces a `mode: quick` summary file with the synthesised content."""
    from core.intent_recognizer import IntentRecognizer
    from modules.research_agent.service import ResearchAgentService

    router = MagicMock()
    router._tools_by_name = {"research_topic": MagicMock()}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds

    ir = IntentRecognizer(router)
    plan = ir.plan("tldr GPT history")
    assert plan and plan[0]["tool"] == "research_topic"
    assert plan[0]["args"]["mode"] == "quick"

    topic = plan[0]["args"]["topic"]
    app = _build_app(_stub_llm(
        "## Summary\nGPT iterated from 2018 to 2026 [1][2]. Real claim [3]."
    ))
    svc = ResearchAgentService(app)
    report = svc.run_research(topic, max_sources=2, mode=plan[0]["args"]["mode"])
    assert report.error == ""
    assert os.path.isfile(report.summary_path)
    with open(report.summary_path) as f:
        body = f.read()
    assert "mode: quick" in body
    assert "GPT iterated" in body


# ── full deep-mode flow ─────────────────────────────────────────────


def test_e2e_intent_to_deep_pipeline(_net_stub):
    """User says 'deep dive on rotary position embedding'. Whole chain
    produces a `mode: deep` summary with the 5-section structure."""
    from core.intent_recognizer import IntentRecognizer
    from modules.research_agent.service import ResearchAgentService

    router = MagicMock()
    router._tools_by_name = {"research_topic": MagicMock()}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds

    ir = IntentRecognizer(router)
    plan = ir.plan("deep dive on rotary position embedding")
    assert plan and plan[0]["args"]["mode"] == "deep"

    topic = plan[0]["args"]["topic"]
    app = _build_app(_stub_llm(
        "## Executive Summary\nRoPE encodes relative position [1][2].\n\n"
        "## Key Findings\n- Sinusoidal rotations [1]\n- Length generalisation [2]\n"
    ))
    svc = ResearchAgentService(app)
    report = svc.run_research(topic, max_sources=4, mode="deep")
    assert report.error == ""
    with open(report.summary_path) as f:
        body = f.read()
    assert "mode: deep" in body
    assert "## Executive Summary" in body


# ── plugin handler explicit-mode short circuit ──────────────────────


def test_e2e_plugin_handler_short_circuits_focus_prompt(_net_stub):
    """The intent parser passed mode='quick' to the handler; the
    handler should call planner.begin(..., mode='quick') which skips
    the 'Any specific angle?' prompt and goes straight to research."""
    from modules.research_agent.plugin import ResearchAgentPlugin

    kicked_off = []

    class _Planner:
        def begin(self, topic, session_id, mode=None):
            kicked_off.append((topic, mode))
            return f"Researching '{topic}' in {mode or 'default'} mode."

    plugin = ResearchAgentPlugin.__new__(ResearchAgentPlugin)
    plugin.app = SimpleNamespace(
        router=SimpleNamespace(session_id="sess-1"),
    )
    plugin._get_planner = lambda: _Planner()
    plugin._extract_topic = lambda text: ""

    response = plugin.handle_research(
        "tldr GPT history",
        {"topic": "GPT history", "mode": "quick"},
    )
    assert "any specific angle" not in response.lower()
    assert kicked_off == [("GPT history", "quick")]


# ── catalog cross-check after step 5 ────────────────────────────────


def test_catalog_covers_all_step5_capabilities():
    """Every capability added in Steps 5a–5d must have a catalog entry."""
    from core.tool_catalog import load_catalog

    expected = {
        # Step 5a — 9 source tools
        "wikipedia_summary", "wikipedia_search", "arxiv_search",
        "hackernews_top", "hackernews_search", "pubmed_search",
        "newspaper_extract", "yfinance_quote", "pdf_text_search",
        # Step 5b/c — the existing research_topic capability (mode arg added)
        "research_topic",
    }
    catalog_names = set(load_catalog().names())
    missing = expected - catalog_names
    assert not missing, f"catalog missing Step-5 capabilities: {missing}"


def test_catalog_research_topic_lists_quick_and_deep_examples():
    """The catalog entry for research_topic must include both quick-mode
    and deep-mode example phrases so the embedding router + planner can
    learn the mode signal from them."""
    from core.tool_catalog import load_catalog
    entry = load_catalog().entry_for("research_topic")
    assert entry is not None
    phrases = " | ".join(entry.example_phrases).lower()
    # quick-mode signals
    assert "tldr" in phrases
    assert "briefly" in phrases or "brief on" in phrases
    assert "one-pager" in phrases or "one pager" in phrases
    # deep-mode signals
    assert "deep dive" in phrases
    assert "thorough" in phrases or "comprehensive" in phrases
    assert "literature review" in phrases
    # comparative signals
    assert " vs " in phrases or "which is better" in phrases
