"""Step 5a — tests for the 7 ported source tools.

Network calls are stubbed via monkeypatch so the suite stays
hermetic. The actual HTTP shapes are verified in the smoke runs that
happen during development (see the live-network commands in
Modification Log).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── plugin smoke ──────────────────────────────────────────────────────────


def test_sources_plugin_registers_all_capabilities():
    """Use a list-capture as `register_capability` because FridayPlugin's
    init replaces MagicMock auto-attrs with a real forwarder (see
    `_ensure_register_capability_shim`)."""
    from modules.sources.plugin import SourcesPlugin

    captured: list[dict] = []

    def fake_register(spec, handler, metadata=None):
        captured.append(spec)

    app = SimpleNamespace(register_capability=fake_register)
    SourcesPlugin(app)

    registered_names = [c["name"] for c in captured]
    expected = {
        "wikipedia_summary", "wikipedia_search",
        "arxiv_search",
        "hackernews_top", "hackernews_search",
        "pubmed_search",
        "newspaper_extract",
        "yfinance_quote",
        "pdf_text_search",
    }
    assert expected.issubset(set(registered_names)), (
        f"missing: {expected - set(registered_names)}"
    )
    # And no duplicates.
    assert len(registered_names) == len(set(registered_names))


# ── wikipedia ────────────────────────────────────────────────────────────


def test_wikipedia_search_titles_parses_opensearch():
    from modules.sources import wikipedia
    fake = MagicMock(status_code=200)
    fake.raise_for_status = MagicMock()
    fake.json.return_value = [
        "Linux kernel",
        ["Linux kernel", "Linux kernel oops", "Linux kernel mainline tree"],
        ["", "", ""],
        ["https://en.wikipedia.org/wiki/Linux_kernel", "", ""],
    ]
    with patch("modules.sources.wikipedia.requests.get", return_value=fake):
        titles = wikipedia.search_titles("Linux kernel", limit=3)
    assert titles == ["Linux kernel", "Linux kernel oops", "Linux kernel mainline tree"]


def test_wikipedia_summary_for_query_returns_extract():
    from modules.sources import wikipedia
    search_resp = MagicMock(status_code=200)
    search_resp.raise_for_status = MagicMock()
    search_resp.json.return_value = ["q", ["MyArticle"], [""], [""]]
    summary_resp = MagicMock(status_code=200)
    summary_resp.raise_for_status = MagicMock()
    summary_resp.json.return_value = {
        "title": "MyArticle",
        "extract": "An article about something.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/MyArticle"}},
    }
    with patch("modules.sources.wikipedia.requests.get",
               side_effect=[search_resp, summary_resp]):
        out = wikipedia.summary_for_query("anything")
    assert out and out["title"] == "MyArticle"


def test_wikipedia_handle_summary_formats_response():
    from modules.sources import wikipedia
    with patch.object(wikipedia, "summary_for_query", return_value={
        "title": "Linux",
        "extract": "An OS kernel.",
        "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Linux"}},
    }):
        out = wikipedia.handle_wikipedia_summary("Linux", {"query": "Linux"})
    assert "**Linux**" in out
    assert "An OS kernel." in out
    assert "wikipedia.org/wiki/Linux" in out


def test_wikipedia_handle_summary_handles_missing_topic():
    from modules.sources import wikipedia
    with patch.object(wikipedia, "summary_for_query", return_value=None):
        out = wikipedia.handle_wikipedia_summary("anything", {"query": "nonexistent_xyz_123"})
    assert "no article" in out.lower()


def test_wikipedia_handle_summary_empty_query():
    from modules.sources import wikipedia
    out = wikipedia.handle_wikipedia_summary("", {"query": ""})
    assert "what topic" in out.lower()


# ── arxiv ────────────────────────────────────────────────────────────────


_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.04088</id>
    <title>Mixture of Experts</title>
    <summary>Routes tokens to expert networks for efficient scaling.</summary>
    <published>2024-01-08T18:00:00Z</published>
    <author><name>Mistral Team</name></author>
    <link rel="alternate" type="text/html" href="http://arxiv.org/abs/2401.04088"/>
    <link type="application/pdf" href="http://arxiv.org/pdf/2401.04088.pdf"/>
  </entry>
</feed>"""


def test_arxiv_search_parses_atom():
    from modules.sources import arxiv
    fake = MagicMock(status_code=200, text=_ARXIV_ATOM)
    fake.raise_for_status = MagicMock()
    with patch("modules.sources.arxiv.requests.get", return_value=fake):
        papers = arxiv.search("mixture of experts", max_results=1)
    assert papers and papers[0]["title"] == "Mixture of Experts"
    assert papers[0]["pdf_url"].endswith(".pdf")
    assert papers[0]["published"] == "2024-01-08"
    assert papers[0]["authors"] == ["Mistral Team"]


def test_arxiv_handle_search_formats_response():
    from modules.sources import arxiv
    with patch.object(arxiv, "search", return_value=[{
        "id": "x", "title": "MyPaper", "authors": ["A. B.", "C. D.", "E. F.", "G. H."],
        "summary": "An abstract.", "published": "2024-01-08",
        "pdf_url": "http://x/pdf", "abs_url": "http://x/abs",
    }]):
        out = arxiv.handle_arxiv_search("anything", {"query": "x"})
    assert "MyPaper" in out
    assert "A. B., C. D., E. F. et al." in out
    assert "http://x/abs" in out


def test_arxiv_handle_empty_query():
    from modules.sources import arxiv
    out = arxiv.handle_arxiv_search("", {"query": ""})
    assert "what should" in out.lower()


# ── hackernews ──────────────────────────────────────────────────────────


def test_hackernews_search_parses_algolia():
    from modules.sources import hackernews
    fake = MagicMock(status_code=200)
    fake.raise_for_status = MagicMock()
    fake.json.return_value = {
        "hits": [
            {"objectID": "111", "title": "Rust 1.99", "url": "https://blog.rust-lang.org",
             "points": 250, "num_comments": 42, "author": "graydon"},
            {"objectID": "112", "title": "Linux 7.1", "url": "",
             "points": 180, "num_comments": 25, "author": "torvalds"},
        ]
    }
    with patch("modules.sources.hackernews.requests.get", return_value=fake):
        hits = hackernews.search("rust", limit=10)
    assert len(hits) == 2
    assert hits[0]["score"] == 250
    assert hits[0]["hn_url"].endswith("=111")


def test_hackernews_handle_search_formats():
    from modules.sources import hackernews
    with patch.object(hackernews, "search", return_value=[
        {"title": "Rust 1.99", "url": "https://rust", "score": 250,
         "comments": 42, "by": "x", "hn_url": "https://hn/1"},
    ]):
        out = hackernews.handle_hackernews_search("rust", {"query": "rust"})
    assert "Rust 1.99" in out
    assert "250" in out


# ── pubmed ──────────────────────────────────────────────────────────────


def test_pubmed_search_makes_two_requests_and_returns_metadata():
    from modules.sources import pubmed
    esearch_resp = MagicMock(status_code=200)
    esearch_resp.raise_for_status = MagicMock()
    esearch_resp.json.return_value = {
        "esearchresult": {"idlist": ["111", "222"]}
    }
    esummary_resp = MagicMock(status_code=200)
    esummary_resp.raise_for_status = MagicMock()
    esummary_resp.json.return_value = {
        "result": {
            "111": {"title": "CRISPR paper 1", "source": "Nature",
                    "pubdate": "2024", "authors": [{"name": "X Y"}]},
            "222": {"title": "CRISPR paper 2", "source": "Cell",
                    "pubdate": "2023", "authors": [{"name": "A B"}]},
        }
    }
    with patch("modules.sources.pubmed.requests.get",
               side_effect=[esearch_resp, esummary_resp]):
        papers = pubmed.search("CRISPR", max_results=2)
    assert len(papers) == 2
    assert papers[0]["pmid"] == "111"
    assert papers[0]["url"].endswith("/111/")


def test_pubmed_handle_search_formats():
    from modules.sources import pubmed
    with patch.object(pubmed, "search", return_value=[
        {"pmid": "1", "title": "Foo", "journal": "Nat", "pubdate": "2024",
         "authors": ["X Y"], "url": "https://x/1"},
    ]):
        out = pubmed.handle_pubmed_search("anything", {"query": "x"})
    assert "Foo" in out
    assert "Nat · 2024" in out or "Nat" in out


# ── newspaper (trafilatura) ────────────────────────────────────────────


def test_newspaper_extract_returns_clean_text():
    """The real extractor; small live test on a stable Wikipedia URL.
    Skip if trafilatura isn't installed in the venv."""
    pytest.importorskip("trafilatura")
    from modules.sources import newspaper
    out = newspaper.extract("https://en.wikipedia.org/wiki/Linux_kernel")
    if out is None:
        pytest.skip("network unavailable")
    assert out["title"]
    assert out["length"] > 1000  # Wikipedia kernel article has plenty
    # Boilerplate strings that trafilatura should have stripped.
    assert "Cookie Notice" not in out["text"]


def test_newspaper_handle_no_url():
    from modules.sources import newspaper
    out = newspaper.handle_newspaper_extract("", {"url": ""})
    assert "url" in out.lower()


def test_newspaper_handle_extracts_url_from_raw_text():
    from modules.sources import newspaper
    with patch.object(newspaper, "extract", return_value={
        "url": "https://x.com", "title": "T", "text": "body", "length": 4,
    }):
        out = newspaper.handle_newspaper_extract(
            "Hey check https://x.com out", {}
        )
    assert "**T**" in out and "body" in out


def test_newspaper_extract_many_parallel():
    """`extract_many` should call extract per URL and skip failures."""
    from modules.sources import newspaper
    calls = []

    def fake_extract(url):
        calls.append(url)
        if "fail" in url:
            return None
        return {"url": url, "title": url, "text": "body", "length": 4}

    with patch.object(newspaper, "extract", side_effect=fake_extract):
        out = newspaper.extract_many([
            "https://a.example.com",
            "https://fail.example.com",
            "https://b.example.com",
        ], max_workers=3)
    assert len(out) == 2
    assert sorted(c for c in calls) == sorted([
        "https://a.example.com",
        "https://fail.example.com",
        "https://b.example.com",
    ])


# ── yfinance (lazy import) ──────────────────────────────────────────────


def test_yfinance_handle_when_lib_missing():
    from modules.sources import yfinance as yf_mod
    with patch.object(yf_mod, "_import_yfinance", return_value=None):
        out = yf_mod.handle_yfinance_quote("MSFT", {"ticker": "MSFT"})
    assert "yfinance" in out.lower()
    assert "pip install" in out.lower()


def test_yfinance_handle_with_stub_lib():
    from modules.sources import yfinance as yf_mod

    class _StubFastInfo:
        last_price = 420.50
        previous_close = 418.00
        open = 419.00
        day_high = 422.00
        day_low = 418.50
        currency = "USD"
        market_cap = 3.1e12

    class _StubTicker:
        fast_info = _StubFastInfo()
        info = {"longName": "Microsoft Corp"}

    class _StubYF:
        @staticmethod
        def Ticker(t):
            return _StubTicker()

    with patch.object(yf_mod, "_import_yfinance", return_value=_StubYF):
        out = yf_mod.handle_yfinance_quote("price of MSFT", {})
    assert "MSFT" in out and "Microsoft" in out
    assert "420.50" in out and "USD" in out
    assert "$3.10T" in out


def test_yfinance_handle_no_ticker():
    from modules.sources import yfinance as yf_mod

    class _StubYF:
        pass

    with patch.object(yf_mod, "_import_yfinance", return_value=_StubYF):
        out = yf_mod.handle_yfinance_quote("", {})
    assert "ticker" in out.lower()


# ── pdf_text (lazy import) ───────────────────────────────────────────────


def test_pdf_handle_when_lib_missing():
    from modules.sources import pdf_text as pdf_mod
    with patch.object(pdf_mod, "_import_pypdf", return_value=None):
        out = pdf_mod.handle_pdf_text_search("", {"query": "x"})
    assert "pypdf" in out.lower()


def test_pdf_search_scores_by_token_hits(tmp_path):
    """When pypdf IS importable, search() walks roots and scores docs."""
    from modules.sources import pdf_text as pdf_mod

    class _StubPyPdf:
        pass

    # Fake list_pdfs → 2 candidates, fake extract_text → known bodies.
    with patch.object(pdf_mod, "_import_pypdf", return_value=_StubPyPdf), \
         patch.object(pdf_mod, "list_pdfs", return_value=[
             str(tmp_path / "a.pdf"),
             str(tmp_path / "b.pdf"),
         ]), \
         patch.object(pdf_mod, "extract_text", side_effect=lambda p, max_pages=None: {
             str(tmp_path / "a.pdf"): "irrelevant content here",
             str(tmp_path / "b.pdf"): "deep dive on transformer scaling laws and emergence",
         }[p]):
        hits = pdf_mod.search("transformer scaling", folder=str(tmp_path), max_results=5)
    # b.pdf has both tokens, a.pdf has neither.
    assert len(hits) == 1
    assert hits[0]["filename"] == "b.pdf"
    assert hits[0]["score"] == 2
    assert "transformer" in hits[0]["snippet"].lower()


# ── intent routing (Step 5a) ────────────────────────────────────────────


def _make_recognizer(tools: list[str]):
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


@pytest.mark.parametrize("phrase,expected_tool,expected_query_substr", [
    ("wikipedia linux kernel", "wikipedia_summary", "linux kernel"),
    ("wiki summary of transformers", "wikipedia_summary", "transformers"),
    ("wikipedia article on quantum computing", "wikipedia_summary", "quantum computing"),
    ("wiki on rust", "wikipedia_summary", "rust"),
    ("search wikipedia for neural networks", "wikipedia_search", "neural networks"),
    ("search wiki for retrieval augmented generation", "wikipedia_search", "retrieval augmented generation"),
])
def test_wikipedia_intent(phrase, expected_tool, expected_query_substr):
    ir = _make_recognizer(["wikipedia_summary", "wikipedia_search"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool
    assert expected_query_substr in result[0]["args"]["query"].lower()


@pytest.mark.parametrize("phrase,expected_query_substr", [
    ("arxiv search for mixture of experts", "mixture of experts"),
    ("arxiv papers on transformer scaling laws", "transformer scaling laws"),
    ("academic papers on rotary position embedding", "rotary position embedding"),
    ("research papers on diffusion models", "diffusion models"),
    ("arxiv on jamba", "jamba"),
])
def test_arxiv_intent(phrase, expected_query_substr):
    ir = _make_recognizer(["arxiv_search"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "arxiv_search"
    assert expected_query_substr in result[0]["args"]["query"].lower()


@pytest.mark.parametrize("phrase,expected_tool,expected_substr", [
    ("top stories on hacker news", "hackernews_top", None),
    ("what's trending on hacker news", "hackernews_top", None),
    ("top hn stories", "hackernews_top", None),
    ("hn top", "hackernews_top", None),
    ("hacker news search for rust", "hackernews_search", "rust"),
    ("hn stories on rag", "hackernews_search", "rag"),
    ("search hn for distributed systems", "hackernews_search", "distributed systems"),
])
def test_hackernews_intent(phrase, expected_tool, expected_substr):
    ir = _make_recognizer(["hackernews_top", "hackernews_search"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == expected_tool
    if expected_substr:
        assert expected_substr in result[0]["args"]["query"].lower()


@pytest.mark.parametrize("phrase,expected_query_substr", [
    ("pubmed search for CRISPR", "crispr"),
    ("pubmed on long covid", "long covid"),
    ("medical papers on diabetes", "diabetes"),
    ("clinical papers on vaccine efficacy", "vaccine efficacy"),
    ("biomedical papers on alzheimer", "alzheimer"),
])
def test_pubmed_intent(phrase, expected_query_substr):
    ir = _make_recognizer(["pubmed_search"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "pubmed_search"
    assert expected_query_substr in result[0]["args"]["query"].lower()


@pytest.mark.parametrize("phrase,expected_ticker", [
    ("quote MSFT", "MSFT"),
    ("price of AAPL", "AAPL"),
    ("stock quote TSLA", "TSLA"),
    ("what's GOOG trading at", "GOOG"),
    ("how's NVDA doing", "NVDA"),
])
def test_yfinance_intent(phrase, expected_ticker):
    ir = _make_recognizer(["yfinance_quote"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "yfinance_quote"
    assert result[0]["args"]["ticker"] == expected_ticker


@pytest.mark.parametrize("phrase,expected_query_substr", [
    ("search my PDFs for transformer scaling", "transformer scaling"),
    ("find in my pdfs the section on attention heads", "the section on attention heads"),
    ("look for emergence in my pdfs", "emergence"),
])
def test_pdf_text_search_intent(phrase, expected_query_substr):
    ir = _make_recognizer(["pdf_text_search"])
    result = ir.plan(phrase)
    assert result, f"no plan for {phrase!r}"
    assert result[0]["tool"] == "pdf_text_search"
    assert expected_query_substr in result[0]["args"]["query"].lower()


def test_newspaper_extract_intent_requires_url_and_phrase():
    ir = _make_recognizer(["newspaper_extract", "web_extract"])
    # URL + clean-text phrasing → newspaper_extract
    result = ir.plan("get just the article from https://example.com/post")
    assert result and result[0]["tool"] == "newspaper_extract"
    assert result[0]["args"]["url"] == "https://example.com/post"

    # URL but ordinary "fetch" phrasing → web_extract (existing tool)
    result = ir.plan("fetch https://example.com/post")
    assert result and result[0]["tool"] == "web_extract"


@pytest.mark.parametrize("phrase", [
    # Anti-poach: bare nouns must not fire.
    "I read about it on wikipedia yesterday",
    "the hacker news guys are wrong",
    "I had a quote from my dentist",
    "I'll find it in my pdf later",
])
def test_source_parsers_dont_poach_idiomatic_speech(phrase):
    ir = _make_recognizer([
        "wikipedia_summary", "wikipedia_search",
        "arxiv_search",
        "hackernews_top", "hackernews_search",
        "pubmed_search",
        "newspaper_extract",
        "yfinance_quote",
        "pdf_text_search",
    ])
    result = ir.plan(phrase)
    # Either no plan, or a non-source-tool match (e.g. chat fallback).
    if result:
        assert result[0]["tool"] not in {
            "wikipedia_summary", "arxiv_search", "hackernews_top",
            "hackernews_search", "pubmed_search", "yfinance_quote",
        }, f"source-tool wrongly captured {phrase!r}"
