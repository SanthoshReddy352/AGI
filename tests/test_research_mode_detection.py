"""Step 5d — mode detection at the intent layer + planner integration.

Three layers tested:
  1. `_parse_research_topic` in `core/intent_recognizer.py` —
     phrasing → mode={'quick'|'deep'|absent}.
  2. `research_planner._parse_mode` — inline focus-reply mode override
     recognises "quick"/"deep" as first-class modes.
  3. `research_planner.begin(topic, session_id, mode='quick')` —
     explicit-mode fast path skips the "any specific angle?" prompt.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_recognizer(tools=("research_topic",)):
    from core.intent_recognizer import IntentRecognizer
    router = MagicMock()
    router._tools_by_name = {t: MagicMock() for t in tools}
    router.context_store = None
    router.session_id = None
    ds = MagicMock()
    ds.pending_file_request = None
    ds.pending_file_name_request = None
    ds.pending_folder_request = None
    router.dialog_state = ds
    return IntentRecognizer(router)


# ── intent parser: quick phrasings ────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_topic_substr", [
    ("tldr history of GPT", "history of gpt"),
    ("tl;dr quantum dot displays", "quantum dot displays"),
    ("briefly on rotary position embedding", "rotary position embedding"),
    ("in brief on the linux kernel", "the linux kernel"),
    ("quick research on attention heads", "attention heads"),
    ("fast brief on transformer scaling", "transformer scaling"),
    ("rapid overview of mixture of experts", "mixture of experts"),
    ("quick rundown on RAG", "rag"),
    ("give me a one-pager on diffusion models", "diffusion models"),
    ("give me a short summary on CRISPR", "crispr"),
    ("summarize transformer scaling laws", "transformer scaling laws"),
    ("overview of rotary position embedding", "rotary position embedding"),
])
def test_quick_phrasings_route_with_mode_quick(phrase, expected_topic_substr):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    action = result[0]
    assert action["tool"] == "research_topic"
    assert action["args"].get("mode") == "quick", (
        f"phrase {phrase!r} expected mode='quick'; got {action['args'].get('mode')!r}"
    )
    assert expected_topic_substr in action["args"]["topic"].lower()


# ── intent parser: deep phrasings ─────────────────────────────────────


@pytest.mark.parametrize("phrase,expected_topic_substr", [
    ("research the history of GPT", "the history of gpt"),
    ("do a deep dive on rotary position embedding", "rotary position embedding"),
    ("do a literature review on CRISPR Cas9", "crispr cas9"),
    ("do a thorough deep dive on transformer scaling laws", "transformer scaling laws"),
    ("thorough briefing on long covid treatment", "long covid treatment"),
    ("comprehensive analysis of attention heads", "attention heads"),
    ("exhaustive research on linux kernel", "linux kernel"),
    ("in-depth analysis of rotary position embedding", "rotary position embedding"),
    ("in depth research on diffusion models", "diffusion models"),
    ("give me a detailed report on quantum dot displays", "quantum dot displays"),
    ("write a comprehensive briefing on RAG", "rag"),
    ("draft a long-form research report on jamba", "jamba"),
    ("literature review on transformer scaling", "transformer scaling"),
    ("detailed research on emergent abilities", "emergent abilities"),
])
def test_deep_phrasings_route_with_mode_deep(phrase, expected_topic_substr):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    action = result[0]
    assert action["tool"] == "research_topic"
    assert action["args"].get("mode") == "deep", (
        f"phrase {phrase!r} expected mode='deep'; got {action['args'].get('mode')!r}"
    )
    assert expected_topic_substr in action["args"]["topic"].lower()


# ── intent parser: comparative phrasings → always deep ───────────────


@pytest.mark.parametrize("phrase,both_sides", [
    ("compare RAG vs fine-tuning", ("rag", "fine-tuning")),
    ("compare transformers and CNNs", ("transformers", "cnns")),
    ("contrast LSTM with transformer", ("lstm", "transformer")),
    ("differentiate diffusion from VAE", ("diffusion", "vae")),
])
def test_comparative_phrasings_route_deep_with_combined_topic(phrase, both_sides):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    action = result[0]
    assert action["tool"] == "research_topic"
    assert action["args"].get("mode") == "deep"
    topic = action["args"]["topic"].lower()
    for side in both_sides:
        assert side in topic, f"missing {side!r} in topic={topic!r}"


# ── intent parser: legacy generic phrasings → NO mode (planner asks) ─


@pytest.mark.parametrize("phrase", [
    "brief me on quantum computing",            # generic "brief me on"
    "put together a briefing on GPT-4",
    "find research papers on attention",
])
def test_legacy_generic_phrasings_have_no_mode(phrase):
    """The legacy generic patterns must NOT set a mode — the
    research_planner asks the user for focus + depth in those cases."""
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    action = result[0]
    assert action["tool"] == "research_topic"
    assert "mode" not in action["args"], (
        f"phrase {phrase!r} unexpectedly carried mode={action['args'].get('mode')!r}"
    )


# ── planner _parse_mode — focus-reply override ────────────────────────


@pytest.mark.parametrize("reply,expected_mode", [
    ("general", "deep"),                            # default
    ("general but quick", "quick"),
    ("focus on RLHF, fast", "quick"),
    ("focus on attention, briefly", "quick"),
    ("rapid", "quick"),
    ("shallow", "quick"),
    ("focus on the founders, thorough", "deep"),
    ("focus on results, in detail", "deep"),
    ("focus on architecture, comprehensive", "deep"),
    ("speed", "speed"),                             # legacy still works
    ("balanced", "balanced"),
    ("quality", "quality"),
])
def test_parse_mode_picks_new_mode_names(reply, expected_mode):
    from core.reasoning.agentic_services.research_planner import (
        ResearchPlannerWorkflow,
    )
    wf = ResearchPlannerWorkflow.__new__(ResearchPlannerWorkflow)
    assert wf._parse_mode(reply) == expected_mode, (
        f"reply={reply!r}: got {wf._parse_mode(reply)!r}, expected {expected_mode!r}"
    )


# ── planner.begin(mode='quick'|'deep') skips focus prompt ────────────


def _make_planner_stub(researched: list):
    """Build a ResearchPlannerWorkflow with research_agent.start_research
    stubbed so we capture the (topic, mode, max_sources) it was called with.
    """
    from core.reasoning.agentic_services.research_planner import (
        ResearchPlannerWorkflow,
    )
    wf = ResearchPlannerWorkflow.__new__(ResearchPlannerWorkflow)

    saved = {}

    class _Mem:
        def save_workflow_state(self, sid, name, state):
            saved.update(state)

    wf._memory = lambda: _Mem()
    wf._save = lambda sid, ws: saved.update(ws)
    wf.app = SimpleNamespace(
        research_agent=SimpleNamespace(
            start_research=lambda topic, max_sources, mode, on_complete: (
                researched.append({"topic": topic, "mode": mode, "max_sources": max_sources})
                or SimpleNamespace(is_alive=lambda: False)
            )
        ),
        telegram_turn_active=False,
    )
    wf.name = "research_planner"
    return wf, saved


def test_begin_with_explicit_quick_mode_skips_focus_prompt():
    """begin(topic, sid, mode='quick') must immediately kick off
    research; the response should NOT contain the 'Any specific angle?'
    follow-up question."""
    researched: list = []
    wf, saved = _make_planner_stub(researched)
    response = wf.begin("history of GPT", "sess-1", mode="quick")
    assert "any specific angle" not in response.lower()
    assert len(researched) == 1
    assert researched[0]["mode"] == "quick"
    assert "history of gpt" in researched[0]["topic"].lower()


def test_begin_with_explicit_deep_mode_skips_focus_prompt():
    researched: list = []
    wf, saved = _make_planner_stub(researched)
    response = wf.begin("rotary position embedding", "sess-1", mode="deep")
    assert "any specific angle" not in response.lower()
    assert len(researched) == 1
    assert researched[0]["mode"] == "deep"


def test_begin_without_explicit_mode_still_asks_for_focus():
    """The legacy path — when the parser couldn't detect mode — must
    still ask the user for a focus."""
    researched: list = []
    wf, saved = _make_planner_stub(researched)
    response = wf.begin("quantum computing", "sess-1")
    assert "any specific angle" in response.lower()
    assert researched == [], "must NOT kick off research yet — waiting for focus"


# ── plugin handler dispatches mode through ────────────────────────────


def test_plugin_handler_passes_explicit_mode_to_planner():
    """`research_topic` capability handler must forward the parser-
    detected mode to the planner so the fast path fires."""
    from modules.research_agent.plugin import ResearchAgentPlugin

    captured = {}

    class _Planner:
        def begin(self, topic, session_id, mode=None):
            captured["topic"] = topic
            captured["session_id"] = session_id
            captured["mode"] = mode
            return "Researching '%s' in %s mode." % (topic, mode or "default")

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
    assert captured["topic"] == "GPT history"
    assert captured["mode"] == "quick"
    assert "quick" in response.lower()


# ── 2026-05-24 17:35 regression: connector word is OPTIONAL ────────────
#
# Live session bug: "quick research Tamil Nadu 2026 Political Landscape"
# and "Deep Dive Quantum Computing advancments about encryption" both
# fell through to chat because the regexes required an `on|about|for|of`
# connector word between the verb and the topic. Users type both shapes
# (with and without a connector) freely.


@pytest.mark.parametrize("phrase,expected_mode,expected_topic_substr", [
    # The live phrasings — must match.
    ("quick research Tamil Nadu 2026 Political Landscape", "quick", "tamil nadu 2026 political landscape"),
    ("Deep Dive Quantum Computing advancments about encryption", "deep", "quantum computing advancments"),
    # Other no-connector phrasings across the quick / deep families.
    ("quick research transformer scaling", "quick", "transformer scaling"),
    ("quick brief rust async", "quick", "rust async"),
    ("fast overview rotary position embedding", "quick", "rotary position embedding"),
    ("rapid rundown jamba architecture", "quick", "jamba architecture"),
    ("deep dive linux kernel", "deep", "linux kernel"),
    ("in-depth research diffusion models", "deep", "diffusion models"),
    ("comprehensive analysis emergent abilities", "deep", "emergent abilities"),
    ("thorough briefing long covid treatment", "deep", "long covid treatment"),
    ("literature review CRISPR Cas9", "deep", "crispr cas9"),
    ("detailed research neural architecture search", "deep", "neural architecture search"),
    ("write a detailed report rotary position embedding", "deep", "rotary position embedding"),
    # And the connector-present versions still work.
    ("quick research on python typing", "quick", "python typing"),
    ("deep dive on rust async", "deep", "rust async"),
    ("literature review on transformer scaling", "deep", "transformer scaling"),
])
def test_research_patterns_match_with_or_without_connector(phrase, expected_mode, expected_topic_substr):
    ir = _make_recognizer()
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    args = result[0]["args"]
    assert args.get("mode") == expected_mode, (
        f"{phrase!r}: got mode={args.get('mode')!r}, expected {expected_mode!r}"
    )
    assert expected_topic_substr in args["topic"].lower(), (
        f"{phrase!r}: topic={args['topic']!r} missing {expected_topic_substr!r}"
    )
