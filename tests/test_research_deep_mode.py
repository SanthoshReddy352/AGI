"""Step 5c — deep-mode research pipeline.

Same hermetic-network pattern as quick-mode tests: every external
fetcher (Wikipedia, arXiv, PubMed, HN, yfinance, DDG, newspaper) is
stubbed at the module-attribute level. The pipeline shape — domain
detection → multi-source fetch → synthesis → writer — is the unit
under test.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── domain classifier ──────────────────────────────────────────────────


@pytest.mark.parametrize("topic,expected", [
    ("transformer scaling laws", {"academic"}),
    ("arxiv paper on rotary position embedding", {"academic"}),
    ("rlhf benchmark performance", {"academic"}),
    ("CRISPR Cas9 clinical trial", {"medical"}),
    ("long covid treatment vaccines", {"medical"}),
    ("price of MSFT", {"finance"}),
    ("$AAPL valuation", {"finance"}),
    ("stock TSLA market cap", {"finance"}),
    ("hn discussion about rust 1.99", {"tech_buzz"}),
    ("hacker news take on the openai launch", {"tech_buzz"}),
    ("tamil nadu 2026 election", set()),    # general — no extras
    ("history of the linux kernel", set()),  # general (no domain keywords match)
])
def test_domain_classify_picks_right_flags(topic, expected):
    from modules.research_agent.domain import classify
    dom = classify(topic)
    detected = set()
    if dom.academic:
        detected.add("academic")
    if dom.medical:
        detected.add("medical")
    if dom.finance:
        detected.add("finance")
    if dom.tech_buzz:
        detected.add("tech_buzz")
    assert detected == expected, (
        f"topic={topic!r}: got {detected}, expected {expected}"
    )


def test_domain_classify_extracts_ticker():
    from modules.research_agent.domain import classify
    assert classify("price of MSFT").ticker == "MSFT"
    assert classify("$AAPL valuation").ticker == "AAPL"
    assert classify("quote GOOG").ticker == "GOOG"


def test_active_sources_includes_wiki_and_web_always():
    from modules.research_agent.domain import classify
    dom = classify("just some random topic")
    assert "wikipedia_summary" in dom.active_sources()
    assert "web_search" in dom.active_sources()


def test_active_sources_adds_per_domain_tools():
    from modules.research_agent.domain import classify
    dom = classify("transformer scaling laws crispr stock MSFT hn buzz")
    srcs = dom.active_sources()
    for required in ("wikipedia_summary", "web_search", "arxiv_search",
                     "pubmed_search", "hackernews_search", "yfinance_quote"):
        assert required in srcs, f"missing {required}"


# ── deep-mode collectors ──────────────────────────────────────────────


def test_collect_arxiv_normalises_papers():
    from modules.research_agent import deep
    with patch("modules.sources.arxiv.search", return_value=[
        {"id": "x", "title": "Mixture of Experts", "authors": ["A", "B"],
         "summary": "MoE routes tokens to experts.",
         "published": "2024-01-08", "pdf_url": "http://x/pdf",
         "abs_url": "http://arxiv.org/abs/2401.04088"},
    ]):
        out = deep._collect_arxiv("moe", limit=1)
    assert len(out) == 1
    s = out[0]
    assert s.title == "Mixture of Experts"
    assert s.origin == "arxiv"
    assert "MoE routes tokens" in s.body
    assert "Authors: A, B" in s.body
    assert s.url.startswith("http")


def test_collect_pubmed_normalises_papers():
    from modules.research_agent import deep
    with patch("modules.sources.pubmed.search", return_value=[
        {"pmid": "1", "title": "Foo", "journal": "Nature",
         "pubdate": "2024", "authors": ["X"], "url": "https://pubmed/1"},
    ]):
        out = deep._collect_pubmed("crispr", limit=1)
    assert len(out) == 1
    assert out[0].origin == "pubmed"
    assert "Nature" in out[0].body
    assert out[0].url == "https://pubmed/1"


def test_collect_hackernews_normalises_hits():
    from modules.research_agent import deep
    with patch("modules.sources.hackernews.search", return_value=[
        {"title": "Rust 1.99", "url": "https://rust", "score": 250,
         "comments": 42, "by": "graydon", "hn_url": "https://hn/1"},
    ]):
        out = deep._collect_hackernews("rust", limit=1)
    assert len(out) == 1
    assert out[0].origin == "hackernews"
    assert "HN score: 250" in out[0].body
    assert "Rust 1.99" in out[0].title


def test_collect_yfinance_returns_quote():
    from modules.research_agent import deep
    with patch("modules.sources.yfinance.quote", return_value={
        "ticker": "MSFT", "name": "Microsoft", "last_price": 420.50,
        "previous_close": 418.00, "currency": "USD", "market_cap": 3.1e12,
    }):
        out = deep._collect_yfinance("MSFT")
    assert len(out) == 1
    s = out[0]
    assert "MSFT" in s.title and "Microsoft" in s.title
    assert s.origin == "yfinance"
    assert "420.5" in s.body


# ── synthesis ────────────────────────────────────────────────────────


def _stub_llm(canned: str):
    class _StubLLM:
        def create_chat_completion(self, messages, max_tokens=0, temperature=0):
            return {"choices": [{"message": {"content": canned}}]}
    return _StubLLM()


def _build_app(llm=None):
    lock = MagicMock()
    lock.__enter__ = MagicMock(return_value=None)
    lock.__exit__ = MagicMock(return_value=False)
    router = SimpleNamespace(get_llm=lambda: llm, chat_inference_lock=lock)
    return SimpleNamespace(router=router)


def test_synthesize_deep_includes_domain_hint_in_prompt():
    """When domains.academic is True, the prompt must mention 'technical'."""
    from modules.research_agent.deep import _build_deep_prompt
    from modules.research_agent.domain import classify
    from modules.research_agent.service import ResearchSource
    sources = [ResearchSource(title="A", url="https://a", body="x")]
    prompt = _build_deep_prompt(
        "transformer scaling laws", sources,
        classify("transformer scaling laws"),
    )
    assert "technical" in prompt.lower()


def test_synthesize_deep_strips_dangling_citations():
    from modules.research_agent.deep import _synthesize_deep
    from modules.research_agent.service import ResearchSource
    from modules.research_agent.domain import classify
    app = _build_app(llm=_stub_llm(
        "## Executive Summary\nReal [1]. Hallucinated [9]. Another [2]."
    ))
    sources = [
        ResearchSource(title="A", url="https://a", body="x"),
        ResearchSource(title="B", url="https://b", body="y"),
    ]
    out = _synthesize_deep(app, "T", sources, classify("T"))
    assert "[1]" in out and "[2]" in out
    assert "[9]" not in out


def test_synthesize_deep_falls_back_when_no_llm():
    from modules.research_agent.deep import _synthesize_deep
    from modules.research_agent.service import ResearchSource
    from modules.research_agent.domain import classify
    app = _build_app(llm=None)
    sources = [
        ResearchSource(title="A", url="https://a", summary="alpha", origin="arxiv"),
    ]
    out = _synthesize_deep(app, "T", sources, classify("T"))
    assert "A" in out and "alpha" in out and "arxiv" in out


# ── end-to-end deep pipeline ─────────────────────────────────────────


@pytest.fixture
def _deep_stubs(tmp_path, monkeypatch):
    """Stub every external source so we can run the deep pipeline
    hermetically."""
    from modules.research_agent import quick as _q
    monkeypatch.setattr(_q, "_FRIDAY_RESEARCH_ROOT", str(tmp_path))

    # Wikipedia
    monkeypatch.setattr(
        "modules.sources.wikipedia.summary_for_query",
        lambda q: {
            "title": "Wiki Anchor",
            "extract": "Wiki anchor body about " + q + ".",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/X"}},
        },
    )

    # DDG
    monkeypatch.setattr(
        "modules.web.plugin._ddg_search",
        lambda q, max_results=8: [
            {"title": "Web A", "url": "https://a.example/x", "snippet": "snip A"},
            {"title": "Web B", "url": "https://b.example/x", "snippet": "snip B"},
            {"title": "Web C", "url": "https://c.example/x", "snippet": "snip C"},
        ],
    )

    # Newspaper extract
    bodies = {
        f"https://{c}.example/x": f"Body text for source {c.upper()}"
        for c in ("a", "b", "c")
    }
    monkeypatch.setattr(
        "modules.sources.newspaper.extract_many",
        lambda urls, max_workers=5: [
            {"url": u, "title": f"Title-{u[-7:]}", "text": bodies[u], "length": len(bodies[u])}
            for u in urls if u in bodies
        ],
    )

    # Domain sources (no-ops by default; specific tests override).
    monkeypatch.setattr("modules.sources.arxiv.search", lambda q, max_results=5: [])
    monkeypatch.setattr("modules.sources.pubmed.search", lambda q, max_results=5: [])
    monkeypatch.setattr("modules.sources.hackernews.search", lambda q, limit=10: [])
    monkeypatch.setattr("modules.sources.yfinance.quote", lambda t: None)

    return tmp_path


def test_deep_pipeline_writes_summary_with_deep_yaml_and_per_source_files(_deep_stubs):
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm(
        "## Executive Summary\nClaim 1 [1]. Claim 2 [2][3]. Claim 3 [4].\n\n"
        "## Key Findings\n- thing one [1]\n- thing two [3]\n\n"
        "## Cross-Source Analysis\n\n"
        "Para 1 covers the field [1][2].\n\n"
        "## Open Questions\n- where next [4]"
    ))
    report = run_deep_research(app, "history of the kernel", max_sources=8)

    assert report.error == ""
    assert report.folder and os.path.isdir(report.folder)
    # 1 wiki + 3 web = 4 sources.
    assert len(report.sources) == 4

    with open(report.summary_path) as f:
        body = f.read()
    assert "mode: deep" in body
    assert "domains:" in body
    assert "## Executive Summary" in body
    assert "## References" in body

    # Per-source files: 01..04 + 00-summary.
    files = sorted(os.listdir(report.folder))
    per_source = [f for f in files if re.match(r"\d{2}-", f) and not f.startswith("00-")]
    assert len(per_source) == 4


def test_deep_pipeline_pulls_arxiv_when_academic(_deep_stubs, monkeypatch):
    monkeypatch.setattr("modules.sources.arxiv.search", lambda q, max_results=3: [
        {"id": "1", "title": "Paper One", "authors": ["A"], "summary": "abstract one",
         "published": "2024", "pdf_url": "", "abs_url": "https://arxiv.org/abs/1"},
    ])
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm("## Executive Summary\n[1]"))
    report = run_deep_research(app, "transformer scaling laws", max_sources=12)
    origins = [s.origin for s in report.sources]
    assert "arxiv" in origins, f"arxiv must be invoked for academic topics; got {origins}"


def test_deep_pipeline_pulls_pubmed_when_medical(_deep_stubs, monkeypatch):
    monkeypatch.setattr("modules.sources.pubmed.search", lambda q, max_results=3: [
        {"pmid": "1", "title": "Foo", "journal": "Nature", "pubdate": "2024",
         "authors": ["X"], "url": "https://pubmed/1"},
    ])
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm("## Executive Summary\n[1]"))
    report = run_deep_research(app, "long covid treatment", max_sources=12)
    assert any(s.origin == "pubmed" for s in report.sources)


def test_deep_pipeline_pulls_yfinance_when_finance(_deep_stubs, monkeypatch):
    monkeypatch.setattr("modules.sources.yfinance.quote", lambda t: {
        "ticker": "MSFT", "name": "Microsoft", "last_price": 420.0,
        "previous_close": 418.0, "currency": "USD", "market_cap": 3e12,
    })
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm("## Executive Summary\n[1]"))
    report = run_deep_research(app, "price of MSFT", max_sources=12)
    assert any(s.origin == "yfinance" for s in report.sources)


def test_deep_pipeline_pulls_hackernews_when_buzz(_deep_stubs, monkeypatch):
    monkeypatch.setattr("modules.sources.hackernews.search", lambda q, limit=3: [
        {"title": "Rust 1.99", "url": "https://rust", "score": 250,
         "comments": 42, "by": "x", "hn_url": "https://hn/1"},
    ])
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm("## Executive Summary\n[1]"))
    report = run_deep_research(app, "hn discussion rust", max_sources=12)
    assert any(s.origin == "hackernews" for s in report.sources)


def test_deep_pipeline_failure_card_when_zero_sources(_deep_stubs, monkeypatch):
    monkeypatch.setattr("modules.sources.wikipedia.summary_for_query", lambda q: None)
    monkeypatch.setattr("modules.web.plugin._ddg_search", lambda q, max_results=8: [])
    from modules.research_agent.deep import run_deep_research
    app = _build_app(llm=_stub_llm("ignored"))
    report = run_deep_research(app, "unreachable_topic", max_sources=12)
    assert report.error == "No usable sources"
    with open(report.summary_path) as f:
        body = f.read()
    assert "No usable sources" in body


def test_deep_pipeline_empty_topic_returns_error():
    from modules.research_agent.deep import run_deep_research
    report = run_deep_research(_build_app(llm=None), "", max_sources=8)
    assert report.error == "No topic provided."


# ── service dispatch ────────────────────────────────────────────────


def test_service_run_research_dispatches_to_deep_on_mode_deep(_deep_stubs):
    from modules.research_agent.service import ResearchAgentService
    app = _build_app(llm=_stub_llm("## Executive Summary\n[1]"))
    svc = ResearchAgentService(app)
    report = svc.run_research("history of unix", max_sources=4, mode="deep")
    assert report.error == ""
    with open(report.summary_path) as f:
        body = f.read()
    assert "mode: deep" in body
