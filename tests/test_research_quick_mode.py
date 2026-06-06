"""Step 5b — quick-mode research pipeline.

Network is fully stubbed:
  - modules.sources.wikipedia.summary_for_query → injectable dict
  - modules.web.plugin._ddg_search → injectable list
  - modules.sources.newspaper.extract_many → injectable per-URL extractions
  - app.router.get_llm() → stub LLM that returns canned synthesis

The pipeline shape (Wikipedia anchor → web → newspaper × N → 1-shot
synthesis → file writer) is the unit under test.
"""
from __future__ import annotations

import os
import re  # noqa: F401 — used in test_quick_pipeline_writes_summary_and_per_source_files
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ─────────────────────────────────────────────────────────────


def _stub_llm(canned: str):
    """A minimal `llm` stub matching the `create_chat_completion` shape
    the quick pipeline calls."""
    class _StubLLM:
        def create_chat_completion(self, messages, max_tokens=0, temperature=0):
            return {"choices": [{"message": {"content": canned}}]}
    return _StubLLM()


def _build_app(llm=None):
    """Minimal app stand-in with a router that exposes get_llm() +
    chat_inference_lock (a context manager). All other plugin services
    are intentionally absent — the quick pipeline must not depend on
    them."""
    lock = MagicMock()
    lock.__enter__ = MagicMock(return_value=None)
    lock.__exit__ = MagicMock(return_value=False)
    router = SimpleNamespace(get_llm=lambda: llm, chat_inference_lock=lock)
    return SimpleNamespace(router=router)


# ── slug / folder ───────────────────────────────────────────────────────


def test_slugify_normalizes_punctuation_and_spaces():
    from modules.research_agent.quick import _slugify
    assert _slugify("History of GPT") == "history-of-gpt"
    assert _slugify("Tamil Nadu 2026 — politics!") == "tamil-nadu-2026-politics"
    assert _slugify("   ") == "research"  # empty → fallback


def test_ensure_folder_creates_under_friday_research(tmp_path, monkeypatch):
    from modules.research_agent import quick as _q
    monkeypatch.setattr(_q, "_FRIDAY_RESEARCH_ROOT", str(tmp_path))
    from datetime import datetime
    folder = _q._ensure_folder("History of GPT", datetime(2026, 5, 24, 9, 30))
    assert os.path.isdir(folder)
    assert "2026-05-24_0930" in folder
    assert "history-of-gpt" in folder


# ── citation validator ────────────────────────────────────────────────


def test_strip_dangling_citations_removes_out_of_range():
    from modules.research_agent.quick import _strip_dangling_citations
    text = "Fact one [1]. Fact two [2][3]. Hallucinated [9]."
    out = _strip_dangling_citations(text, max_index=3)
    assert "[1]" in out and "[2]" in out and "[3]" in out
    assert "[9]" not in out


def test_strip_dangling_citations_leaves_valid_ones():
    from modules.research_agent.quick import _strip_dangling_citations
    text = "All valid [1][2][3]."
    assert _strip_dangling_citations(text, max_index=5) == text


# ── synthesis ──────────────────────────────────────────────────────────


def test_synthesize_uses_llm_when_available():
    from modules.research_agent.quick import _synthesize
    from modules.research_agent.service import ResearchSource

    app = _build_app(llm=_stub_llm("## Summary\nFact A [1]. Fact B [2]."))
    sources = [
        ResearchSource(title="Doc A", url="https://a", body="alpha"),
        ResearchSource(title="Doc B", url="https://b", body="beta"),
    ]
    out = _synthesize(app, "Topic X", sources)
    assert "Fact A" in out and "Fact B" in out


def test_synthesize_falls_back_when_no_llm():
    from modules.research_agent.quick import _synthesize
    from modules.research_agent.service import ResearchSource
    app = _build_app(llm=None)
    sources = [
        ResearchSource(title="Doc A", url="https://a", summary="alpha summary"),
    ]
    out = _synthesize(app, "Topic X", sources)
    # Extractive fallback includes the source title + body.
    assert "Doc A" in out
    assert "https://a" in out
    assert "alpha summary" in out


def test_synthesize_strips_dangling_citations():
    """LLM hallucinates a [9] citation when only 3 sources exist;
    the post-synth validator must strip it."""
    from modules.research_agent.quick import _synthesize
    from modules.research_agent.service import ResearchSource
    app = _build_app(llm=_stub_llm(
        "## Summary\n"
        "Real claim [1]. Hallucinated claim [9]. Another real [2][3]."
    ))
    sources = [
        ResearchSource(title=f"Src {i}", url=f"https://s{i}", body="x")
        for i in range(1, 4)
    ]
    out = _synthesize(app, "T", sources)
    assert "[9]" not in out
    assert "[1]" in out and "[2]" in out and "[3]" in out


def test_synthesize_marks_truncation_when_no_terminal_punctuation():
    from modules.research_agent.quick import _synthesize
    from modules.research_agent.service import ResearchSource
    # No terminal . ! ? in the canned output → guard kicks in.
    app = _build_app(llm=_stub_llm(
        "## Summary\nFirst sentence [1]. Second sentence cut off in the middle"
    ))
    sources = [ResearchSource(title="A", url="https://a", body="x")]
    out = _synthesize(app, "T", sources)
    assert "_(response truncated)_" in out


# ── end-to-end pipeline ──────────────────────────────────────────────


@pytest.fixture
def _stubbed_pipeline(tmp_path, monkeypatch):
    """Stub Wikipedia + DDG + newspaper so we can run the full pipeline
    without touching the network. Yields the temp friday-research root."""
    from modules.research_agent import quick as _q
    monkeypatch.setattr(_q, "_FRIDAY_RESEARCH_ROOT", str(tmp_path))

    # Wikipedia
    monkeypatch.setattr(
        "modules.sources.wikipedia.summary_for_query",
        lambda q: {
            "title": "GPT",
            "extract": "Generative Pre-trained Transformer is a family of language models developed by OpenAI.",
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/GPT"}},
        },
    )

    # DDG search
    monkeypatch.setattr(
        "modules.web.plugin._ddg_search",
        lambda q, max_results=5: [
            {"title": "A History of GPT", "url": "https://a.example/gpt", "snippet": "Snippet A"},
            {"title": "GPT-4 Technical Report", "url": "https://b.example/gpt4", "snippet": "Snippet B"},
            {"title": "Scaling Laws for LLMs", "url": "https://c.example/scaling", "snippet": "Snippet C"},
        ],
    )

    # Newspaper extractor
    bodies = {
        "https://a.example/gpt": "Body about the history of GPT and its iterations.",
        "https://b.example/gpt4": "GPT-4 technical report body content discussing scale.",
        "https://c.example/scaling": "Scaling laws body — Chinchilla, Kaplan, etc.",
    }

    def fake_extract_many(urls, max_workers=5):
        return [
            {"url": u, "title": f"Title-{i}", "text": bodies[u], "length": len(bodies[u])}
            for i, u in enumerate(urls, 1)
            if u in bodies
        ]
    monkeypatch.setattr("modules.sources.newspaper.extract_many", fake_extract_many)

    return tmp_path


def test_quick_pipeline_writes_summary_and_per_source_files(_stubbed_pipeline):
    from modules.research_agent.quick import run_quick_research

    app = _build_app(llm=_stub_llm(
        "## Summary\nGPT evolved from 117M to 175B parameters [1][2].\n\n"
        "## Key Findings\n- Transformer architecture [1]\n- Scaling laws matter [3]\n\n"
        "## Open Questions\n- Where does scaling end [3]"
    ))
    report = run_quick_research(app, "History of GPT", max_sources=5)

    # Report shape matches deep-mode ResearchReport.
    assert report.topic == "History of GPT"
    assert report.folder and os.path.isdir(report.folder)
    assert report.summary_path and os.path.isfile(report.summary_path)
    assert report.error == ""
    # 1 wikipedia + 3 web = 4 sources.
    assert len(report.sources) == 4
    assert report.sources[0].origin == "wikipedia"

    # 00-summary.md has the synthesis + references section.
    with open(report.summary_path, "r", encoding="utf-8") as f:
        body = f.read()
    assert "## Summary" in body
    assert "GPT evolved from 117M to 175B parameters" in body
    assert "## References" in body
    assert "wikipedia.org/wiki/GPT" in body

    # YAML front-matter present.
    assert body.startswith("---\n")
    assert "mode: quick" in body
    assert "sources_usable: 4" in body

    # sources.md exists with one URL per line.
    with open(os.path.join(report.folder, "sources.md"), "r") as f:
        urls = f.read()
    assert urls.count("https://") == 4

    # Per-source files exist (01-…, 02-…, 03-…, 04-…) plus 00-summary.md.
    per_source = sorted(
        f for f in os.listdir(report.folder)
        if f.endswith(".md") and re.match(r"\d{2}-", f) and not f.startswith("00-")
    )
    assert len(per_source) == 4
    assert per_source[0].startswith("01-")


def test_quick_pipeline_handles_no_wikipedia_anchor(_stubbed_pipeline, monkeypatch):
    """Wikipedia returns nothing — pipeline still uses web sources."""
    monkeypatch.setattr(
        "modules.sources.wikipedia.summary_for_query",
        lambda q: None,
    )
    from modules.research_agent.quick import run_quick_research
    app = _build_app(llm=_stub_llm("## Summary\nfindings [1]"))
    report = run_quick_research(app, "obscure topic", max_sources=3)
    assert report.error == ""
    # 0 wiki + 3 web extractions = 3.
    assert len(report.sources) == 3
    assert all(s.origin == "web" for s in report.sources)


def test_quick_pipeline_writes_failure_card_on_zero_sources(_stubbed_pipeline, monkeypatch):
    """Both Wikipedia AND web returned nothing — write a clear failure
    page instead of a blank 00-summary.md."""
    monkeypatch.setattr("modules.sources.wikipedia.summary_for_query", lambda q: None)
    monkeypatch.setattr("modules.web.plugin._ddg_search", lambda q, max_results=5: [])
    monkeypatch.setattr("modules.sources.newspaper.extract_many",
                        lambda urls, max_workers=5: [])

    from modules.research_agent.quick import run_quick_research
    app = _build_app(llm=_stub_llm("ignored"))
    report = run_quick_research(app, "unreachable_xyz_topic", max_sources=5)
    assert report.error == "No usable sources"
    with open(report.summary_path, "r") as f:
        body = f.read()
    assert "No usable sources" in body
    assert "Wikipedia summary" in body
    assert "DuckDuckGo" in body


def test_quick_pipeline_empty_topic_returns_error():
    from modules.research_agent.quick import run_quick_research
    app = _build_app(llm=_stub_llm("ignored"))
    report = run_quick_research(app, "", max_sources=5)
    assert report.error == "No topic provided."
    assert report.summary_path == ""


# ── service.run_research dispatch ───────────────────────────────────


def test_service_run_research_dispatches_to_quick_on_mode_quick(_stubbed_pipeline):
    """`service.run_research(topic, mode='quick')` must hit the new
    pipeline, NOT the agentic loop."""
    from modules.research_agent.service import ResearchAgentService

    app = _build_app(llm=_stub_llm("## Summary\nshort [1]"))
    svc = ResearchAgentService(app)
    report = svc.run_research("Quick test topic", max_sources=2, mode="quick")
    assert report.error == ""
    assert report.duration_s > 0
    # Look for the quick mode marker in the YAML front-matter.
    with open(report.summary_path) as f:
        body = f.read()
    assert "mode: quick" in body


# ── live-session regression: _ddg_search positional contract ─────────


def test_collect_web_urls_calls_ddg_with_correct_signature():
    """2026-05-24 17:42 bug: `_ddg_search` takes `max_results` positional;
    we were calling it with `limit=` kw and every web hit was silently
    dropped (TypeError caught by the broad `except`). This test calls
    the REAL `_collect_web_urls` against a stub that mimics the actual
    `_ddg_search(query, max_results)` signature — if the call site
    regresses to `limit=` again, the stub raises TypeError and the
    test catches it."""
    from modules.research_agent.quick import _collect_web_urls
    from unittest.mock import patch

    received = {}

    def fake_ddg(query, max_results):       # ← positional, no `limit` kw
        received["query"] = query
        received["max_results"] = max_results
        return [{"title": "x", "url": "https://x.example/y", "snippet": "z"}]

    with patch("modules.web.plugin._ddg_search", side_effect=fake_ddg):
        out = _collect_web_urls("hello world", limit=5)

    assert out and out[0]["url"] == "https://x.example/y"
    assert received == {"query": "hello world", "max_results": 5}


# ── DDG redirect-unwrap regression (live session 2026-05-24 17:58) ────
#
# DuckDuckGo's HTML interface wraps every link in
# `https://duckduckgo.com/l/?uddg=<encoded real URL>&rut=…`. Those
# wrappers don't 200 for trafilatura — every research mode lost every
# web hit until we unwrapped them at the search layer.


def test_unwrap_ddg_redirect_decodes_uddg_param():
    from modules.web.plugin import _unwrap_ddg_redirect
    wrapped = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fwww.example.com%2Fpath%2Fto%2Farticle"
        "&amp;rut=abcdef"
    )
    assert _unwrap_ddg_redirect(wrapped) == "https://www.example.com/path/to/article"


def test_unwrap_ddg_redirect_leaves_real_urls_untouched():
    from modules.web.plugin import _unwrap_ddg_redirect
    real = "https://example.com/x"
    assert _unwrap_ddg_redirect(real) == real
    assert _unwrap_ddg_redirect("") == ""


def test_unwrap_handles_malformed_wrapper():
    from modules.web.plugin import _unwrap_ddg_redirect
    # Looks like a DDG wrapper but no uddg param — return as-is.
    weird = "https://duckduckgo.com/l/?other=foo"
    assert _unwrap_ddg_redirect(weird) == weird


def test_ddg_search_unwraps_results():
    """Smoke test: when the duckduckgo-search library returns a wrapped
    href, `_ddg_search` should hand us the unwrapped URL."""
    from modules.web import plugin as web_plugin
    from unittest.mock import patch

    class _StubDDGS:
        def text(self, query, max_results):
            yield {
                "title": "Example",
                "href": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=xyz",
                "body": "snippet",
            }

    class _StubModule:
        DDGS = _StubDDGS

    with patch.dict("sys.modules", {"duckduckgo_search": _StubModule}):
        results = web_plugin._ddg_search("anything", 1)
    assert results
    assert results[0]["url"] == "https://example.com/a"


# ── 2026-05-24 18:08 regression: writer input MUST stay within ctx ────


def test_writer_prompt_size_stays_bounded_even_with_10_big_sources():
    """Guards the original 18:08 failure (`Requested tokens exceed context
    window`). The writer now reads source text directly, but each body is
    sliced to `_WRITER_BODY_CHARS` (< 1000) so 10 big sources can't blow the
    context window. `_clamp_max_tokens` is the runtime second line of
    defence; this test pins the prompt-side per-source cap."""
    from modules.research_agent.quick import _build_synth_prompt, _WRITER_BODY_CHARS
    from modules.research_agent.service import ResearchSource

    sources = [
        ResearchSource(
            title=f"Source {i}",
            url=f"https://example.com/{i}",
            body="X" * 3000,   # very long body to expose the old failure
            origin="web",
        )
        for i in range(1, 11)  # 10 sources, the live-session count
    ]
    prompt = _build_synth_prompt("topic", sources)
    # 10 sources × ~800 body chars + frame stays well inside the 8K window.
    assert len(prompt) < 12_000, (
        f"writer prompt is {len(prompt)} chars — too big, will crowd ctx "
        "when many sources come back"
    )
    # No single source body may exceed the per-source slice in the prompt.
    assert _WRITER_BODY_CHARS < 1000
    assert "X" * (_WRITER_BODY_CHARS + 1) not in prompt, (
        "a source body exceeded the per-source slice — writer cap broken"
    )


def test_compress_source_falls_back_to_snippet_when_no_llm():
    from modules.research_agent.quick import _compress_source
    from modules.research_agent.service import ResearchSource
    app = _build_app(llm=None)
    s = ResearchSource(
        title="A", url="https://a", body="long body…",
        summary="alpha summary",
    )
    out = _compress_source(app, s, 1)
    assert "[1]" in out
    assert "alpha summary" in out


def test_compress_source_tags_missing_citations():
    """If the LLM returns a bullet without the [N] tag, the helper
    must append it so the writer can still use the bullet."""
    from modules.research_agent.quick import _compress_source
    from modules.research_agent.service import ResearchSource

    # Stub LLM that returns bullets WITHOUT the citation tag.
    class _StubLLM:
        def create_chat_completion(self, messages, max_tokens, temperature):
            return {"choices": [{"message": {"content":
                "- fact one\n- fact two without tag\n- fact three"
            }}]}

    app = _build_app(llm=_StubLLM())
    s = ResearchSource(title="X", url="https://x", body="body here")
    out = _compress_source(app, s, 7)
    # Every bullet should now end in [7].
    for line in out.splitlines():
        if line.strip().startswith("-"):
            assert "[7]" in line, f"bullet missing [7]: {line!r}"


def test_compress_all_runs_in_parallel_and_keeps_order():
    from modules.research_agent.quick import _compress_all_sources
    from modules.research_agent.service import ResearchSource

    class _StubLLM:
        def create_chat_completion(self, messages, max_tokens, temperature):
            # Return the source title verbatim so we can check ordering.
            user_msg = messages[-1]["content"]
            # Pull the title from the prompt
            import re as _re
            m = _re.search(r'title:\s*"([^"]+)"', user_msg)
            title = m.group(1) if m else "?"
            return {"choices": [{"message": {"content": f"- says {title}"}}]}

    app = _build_app(llm=_StubLLM())
    sources = [
        ResearchSource(title=f"Title-{i}", url=f"https://x/{i}", body="b")
        for i in range(1, 5)
    ]
    out = _compress_all_sources(app, sources)
    assert len(out) == 4
    for i, bullet in enumerate(out, 1):
        assert f"Title-{i}" in bullet, f"order or content drift at {i}: {bullet!r}"
        assert f"[{i}]" in bullet
