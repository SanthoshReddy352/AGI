"""Deep-mode research pipeline (Step 5c).

Builds on the same primitives the quick pipeline uses, but adds:

  1. Domain detection (`domain.classify`) → tech / medical / finance /
     tech-buzz / general. Drives which source-plugins to invoke.
  2. Multi-source fetching in parallel: Wikipedia + DDG web search +
     (arxiv | pubmed | hackernews | yfinance) depending on domain.
  3. A longer synthesis prompt that mandates a `## Cross-Source
     Analysis` paragraph and a `## Conflicting Claims` section when
     sources disagree.
  4. Citation-validity scrubber identical to quick mode.
  5. Same on-disk shape: `00-summary.md` + `sources.md` + per-source
     `0N-…md` files, so `_on_research_done` doesn't special-case.

What this REPLACES vs the legacy `service.py` agentic loop:
  - 25 sequential LLM action-picks → 1 source-plan + 1 synth = 2 LLM
    calls total.
  - Per-source LLM summarisation (15+ calls) → text already cleaned by
    trafilatura, fed directly to the writer.
  - Self-contradictory single-paragraph outputs → an explicit section
    devoted to flagging conflicts.

The legacy `_run_research_locked` stays in `service.py` for now — this
file is opted-in via `service.run_research(topic, mode="deep")`.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime

from core.logger import logger

from . import domain as _domain
from .quick import (
    _ensure_folder, _slugify, _strip_dangling_citations, _write_outputs,
    _collect_wikipedia, _collect_web_urls, _extract_articles,
    _writer_candidates, _clamp_max_tokens, _run_writer, _source_bundle,
    _MAX_BODY_CHARS_PER_SOURCE,
)
from .service import ResearchReport, ResearchSource


# Larger budgets than quick — we have a 60-120s ceiling, not 20s.
_DEEP_WEB_LIMIT = 8
_DEEP_ARXIV_LIMIT = 3
_DEEP_PUBMED_LIMIT = 3
_DEEP_HN_LIMIT = 3
# Writer-call output budget, in *generated* tokens. The 4B tool model runs
# at ~2.7 tok/s on CPU, so this — not the prompt size — sets the wall-clock.
# Deep gets a bigger budget than quick (it earns the extra ~minute) for a
# longer Executive Summary + Key Findings. `_clamp_max_tokens` shrinks it if
# the source bundle ever crowds the context window.
_DEEP_SYNTH_MAX_TOKENS = 900


# ---------------------------------------------------------------------------
# Domain-source collectors — each returns a list[ResearchSource].
# ---------------------------------------------------------------------------


def _collect_arxiv(topic: str, limit: int = _DEEP_ARXIV_LIMIT) -> list[ResearchSource]:
    try:
        from modules.sources import arxiv as _arxiv  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[deep] arxiv unavailable: %s", exc)
        return []
    try:
        papers = _arxiv.search(topic, max_results=limit) or []
    except Exception as exc:
        logger.warning("[deep] arxiv search failed: %s", exc)
        return []
    out: list[ResearchSource] = []
    for p in papers:
        authors = ", ".join(p.get("authors", [])[:4])
        body_chunks = [
            f"Authors: {authors}" if authors else "",
            f"Published: {p.get('published','')}",
            "",
            p.get("summary", ""),
        ]
        body = "\n".join(c for c in body_chunks if c).strip()
        out.append(ResearchSource(
            title=p.get("title", "arxiv paper"),
            url=p.get("abs_url") or p.get("pdf_url", ""),
            snippet=p.get("summary", "")[:280],
            origin="arxiv",
            body=body[:_MAX_BODY_CHARS_PER_SOURCE],
            summary=body[:600],
        ))
    return out


def _collect_pubmed(topic: str, limit: int = _DEEP_PUBMED_LIMIT) -> list[ResearchSource]:
    try:
        from modules.sources import pubmed as _pubmed  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[deep] pubmed unavailable: %s", exc)
        return []
    try:
        papers = _pubmed.search(topic, max_results=limit) or []
    except Exception as exc:
        logger.warning("[deep] pubmed search failed: %s", exc)
        return []
    out: list[ResearchSource] = []
    for p in papers:
        authors = ", ".join(p.get("authors", [])[:4])
        body_chunks = [
            f"Authors: {authors}" if authors else "",
            f"Journal: {p.get('journal','')}",
            f"Published: {p.get('pubdate','')}",
            "",
            p.get("title", ""),
        ]
        body = "\n".join(c for c in body_chunks if c).strip()
        out.append(ResearchSource(
            title=p.get("title", "pubmed paper"),
            url=p.get("url", ""),
            snippet=p.get("title", "")[:280],
            origin="pubmed",
            body=body[:_MAX_BODY_CHARS_PER_SOURCE],
            summary=body[:600],
        ))
    return out


def _collect_hackernews(topic: str, limit: int = _DEEP_HN_LIMIT) -> list[ResearchSource]:
    try:
        from modules.sources import hackernews as _hn  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[deep] hackernews unavailable: %s", exc)
        return []
    try:
        hits = _hn.search(topic, limit=limit) or []
    except Exception as exc:
        logger.warning("[deep] hackernews search failed: %s", exc)
        return []
    out: list[ResearchSource] = []
    for h in hits:
        body = (
            f"HN score: {h.get('score', 0)} | Comments: {h.get('comments', 0)}\n"
            f"Submitter: {h.get('by', '')}\n"
            f"HN: {h.get('hn_url', '')}"
        )
        out.append(ResearchSource(
            title=h.get("title", "HN story"),
            url=h.get("url") or h.get("hn_url", ""),
            snippet=body[:280],
            origin="hackernews",
            body=body[:_MAX_BODY_CHARS_PER_SOURCE],
            summary=body[:600],
        ))
    return out


def _collect_yfinance(ticker: str) -> list[ResearchSource]:
    """Single-source: a stock quote for *ticker*."""
    if not ticker:
        return []
    try:
        from modules.sources import yfinance as _yf  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[deep] yfinance unavailable: %s", exc)
        return []
    try:
        q = _yf.quote(ticker)
    except Exception as exc:
        logger.warning("[deep] yfinance quote failed: %s", exc)
        return []
    if not q:
        return []
    last = q.get("last_price")
    prev = q.get("previous_close")
    body_lines = [
        f"Ticker: {q.get('ticker', ticker)}",
        f"Company: {q.get('name', '')}",
        f"Last price: {last} {q.get('currency','')}" if last else "",
        f"Previous close: {prev}" if prev else "",
        f"Market cap: {q.get('market_cap','')}",
    ]
    body = "\n".join(l for l in body_lines if l)
    return [ResearchSource(
        title=f"{q.get('name', ticker)} ({q.get('ticker', ticker)}) — live quote",
        url=f"https://finance.yahoo.com/quote/{q.get('ticker', ticker)}",
        snippet=body[:280],
        origin="yfinance",
        body=body[:_MAX_BODY_CHARS_PER_SOURCE],
        summary=body[:600],
    )]


# ---------------------------------------------------------------------------
# Synthesis (deep)
# ---------------------------------------------------------------------------


_DEEP_SYNTH_SYSTEM = (
    "You are a senior research analyst writing a long-form briefing that "
    "professionals would respect. Use ONLY facts stated in the sources you "
    "are given — never add a party, person, number, date, place, or claim "
    "that is not in the sources. Every factual sentence ends with an inline "
    "citation like [N] pointing to a real source index; cite the 1–3 MOST "
    "relevant sources per sentence and never dump more than three on one "
    "sentence. When two sources disagree, list both rather than picking one. "
    "Close every sentence — never stop mid-thought. Weave the sources "
    "together into flowing analysis; do not go source-by-source."
)


def _build_deep_prompt(topic: str, sources: list[ResearchSource],
                      domains) -> str:
    """Writer prompt for deep mode. The writer reads source text directly
    (the 4B tool model fits the bundle at 8K context) and produces a long
    Executive Summary plus Key Findings and any Conflicting Claims.
    """
    avail_list = ", ".join(f"[{n}]" for n in range(1, len(sources) + 1))
    bundle = _source_bundle(sources)

    domain_hints = []
    if domains.academic:
        domain_hints.append("technical")
    if domains.medical:
        domain_hints.append("medical")
    if domains.finance:
        domain_hints.append(f"finance (ticker: {domains.ticker})" if domains.ticker else "finance")
    if domains.tech_buzz:
        domain_hints.append("community/discussion")
    domain_str = ", ".join(domain_hints) or "general"

    return (
        f"Topic: \"{topic}\"\n"
        f"Detected domain(s): {domain_str}\n\n"
        f"You have {len(sources)} sources below, each numbered [N].\n\n"
        f"{bundle}\n\n"
        "Write a research briefing in Markdown with this exact section "
        "order. Omit a section entirely if it would be empty.\n\n"
        "## Executive Summary\n"
        "Write 3–4 dense paragraphs (about 14–18 sentences). A reader who "
        "reads ONLY this section must come away knowing everything material "
        "about the topic across ALL the sources: the central facts, the key "
        "numbers, dates and names, the most consequential mechanism or "
        "outcome, where the sources agree and disagree, and the practical "
        "takeaway. Weave the sources together into flowing analysis — do NOT "
        "go through them one by one. Reference at least 5 different sources "
        "(or all of them if fewer than 5).\n\n"
        "## Key Findings\n"
        "6–10 specific concrete bullets, each with its [N] citation — "
        "numbers, percentages, named studies or technologies wherever the "
        "sources provide them. No vague bullets.\n\n"
        "## Conflicting Claims\n"
        "If two sources state conflicting facts, list each conflict on its "
        "own bullet with BOTH citations: 'Claim X per [A]; contradicted by "
        "claim Y per [B].' If there are no conflicts, OMIT this section.\n\n"
        "CITATION RULES (strictly enforced):\n"
        f"- Cite ONLY these indices inline: {avail_list}.\n"
        "- Do NOT invent a citation for any index not in that list.\n"
        "- End every factual sentence with its citation.\n"
        "- Cite the 1–3 most relevant sources per sentence — never more than "
        "three. Use only facts present in the sources. Close every sentence.\n"
    )


def _extractive_deep_fallback(topic: str, sources: list[ResearchSource]) -> str:
    """When `router.get_llm()` is None, emit a per-source rundown so the
    user still gets something readable."""
    lines = [
        f"# Deep research: {topic}",
        "",
        "_LLM unavailable — emitted raw per-source extracts with citations._",
        "",
        "## Sources",
        "",
    ]
    for i, s in enumerate(sources, 1):
        body = (s.summary or s.snippet or s.body or "").strip()[:800]
        lines.append(f"[{i}] **{s.title}** ({s.origin}) — {s.url}")
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip()


def _synthesize_deep(app, topic: str, sources: list[ResearchSource], domains) -> str:
    if not sources:
        return f"No sources were available for '{topic}'."

    candidates = _writer_candidates(app)
    if not candidates:
        return _extractive_deep_fallback(topic, sources)

    prompt = _build_deep_prompt(topic, sources, domains)
    text = ""
    for llm, lock, role in candidates:
        budget = _clamp_max_tokens(
            llm, _DEEP_SYNTH_SYSTEM, prompt, desired=_DEEP_SYNTH_MAX_TOKENS,
        )
        logger.info(
            "[deep] synthesis: writer=%s sources=%d budget=%d",
            role, len(sources), budget,
        )
        text = _run_writer(llm, lock, role, prompt, budget, system=_DEEP_SYNTH_SYSTEM)
        if text:
            break
        logger.info("[deep] writer %s returned no text — trying next model", role)

    if not text:
        return _extractive_deep_fallback(topic, sources)

    text = _strip_dangling_citations(text, max_index=len(sources))
    # Truncation guard.
    if text and text[-1] not in ".!?\")]":
        last_period = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if last_period >= 0 and last_period < len(text) - 5:
            text = text[: last_period + 1] + "\n\n_(response truncated)_"
    return text


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_deep_research(app, topic: str, *, max_sources: int = 12) -> ResearchReport:
    """Multi-source deep briefing. Returns a `ResearchReport` matching
    quick-mode's shape so callers don't special-case the two modes.
    """
    started = time.monotonic()
    when = datetime.now()
    topic = (topic or "").strip()
    if not topic:
        return ResearchReport(
            topic="", folder="", summary_path="",
            error="No topic provided.",
        )

    domains = _domain.classify(topic)
    domain_names = []
    if domains.academic:
        domain_names.append("academic")
    if domains.medical:
        domain_names.append("medical")
    if domains.finance:
        domain_names.append(f"finance({domains.ticker})" if domains.ticker else "finance")
    if domains.tech_buzz:
        domain_names.append("tech_buzz")
    logger.info(
        "[deep] Starting topic=%r max_sources=%d domains=[%s]",
        topic, max_sources, ", ".join(domain_names) or "general",
    )

    folder = _ensure_folder(topic, when)

    sources: list[ResearchSource] = []

    # Anchor: Wikipedia.
    wiki = _collect_wikipedia(topic)
    if wiki is not None:
        sources.append(wiki)

    # Domain-specific source collectors (parallelizable, but each is
    # already only one HTTP round-trip + parse — serial keeps the
    # error reporting clear).
    if domains.academic:
        for s in _collect_arxiv(topic):
            sources.append(s)
    if domains.medical:
        for s in _collect_pubmed(topic):
            sources.append(s)
    if domains.tech_buzz:
        for s in _collect_hackernews(topic):
            sources.append(s)
    if domains.finance:
        for s in _collect_yfinance(domains.ticker):
            sources.append(s)

    # Web sources: leave room beyond the domain sources we already added.
    web_budget = max(0, max_sources - len(sources))
    web_urls_meta: list[dict] = []
    if web_budget:
        web_results = _collect_web_urls(topic, limit=_DEEP_WEB_LIMIT)
        web_urls_meta = web_results[:web_budget]
        web_urls = [r["url"] for r in web_urls_meta]
        extractions = _extract_articles(
            web_urls, max_workers=min(5, max(1, len(web_urls))),
        )
        by_url = {e["url"]: e for e in extractions}
        for r in web_urls_meta:
            e = by_url.get(r["url"])
            if not e or not (e.get("text") or "").strip():
                continue
            body = e["text"].strip()
            sources.append(ResearchSource(
                title=(e.get("title") or r.get("title") or r["url"]).strip(),
                url=r["url"],
                snippet=(r.get("snippet") or body[:280]).strip(),
                origin="web",
                body=body[:_MAX_BODY_CHARS_PER_SOURCE],
                summary=body[:600],
            ))

    if not sources:
        summary_path = os.path.join(folder, "00-summary.md")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write("_No usable sources were retrieved._\n\n")
            f.write("Tried: Wikipedia summary, DuckDuckGo search")
            if domains.academic:
                f.write(", arXiv search")
            if domains.medical:
                f.write(", PubMed search")
            if domains.tech_buzz:
                f.write(", Hacker News search")
            if domains.finance:
                f.write(f", Yahoo Finance ({domains.ticker or 'no ticker'})")
            f.write(".\n")
        duration = time.monotonic() - started
        logger.info("[deep] DONE (no sources) %.1fs → %s", duration, summary_path)
        return ResearchReport(
            topic=topic, folder=folder, summary_path=summary_path,
            sources=[], duration_s=duration, error="No usable sources",
        )

    synthesis = _synthesize_deep(app, topic, sources, domains)

    summary_path = _write_deep_outputs(folder, topic, synthesis, sources, when, domains)

    duration = time.monotonic() - started
    logger.info(
        "[deep] DONE topic=%r mode=deep in %.1fs (%d sources) → %s",
        topic, duration, len(sources), summary_path,
    )
    return ResearchReport(
        topic=topic, folder=folder, summary_path=summary_path,
        sources=sources, duration_s=duration,
    )


def _write_deep_outputs(folder, topic, synthesis, sources, when, domains):
    """Same shape as quick mode, plus a domain line in the front-matter."""
    usable = sum(1 for s in sources if s.body or s.summary or s.snippet)
    domain_str = ",".join([
        d for d, on in (
            ("academic", domains.academic),
            ("medical", domains.medical),
            ("finance", domains.finance),
            ("tech_buzz", domains.tech_buzz),
        ) if on
    ]) or "general"

    summary_path = os.path.join(folder, "00-summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"---\n")
        f.write(f"topic: {topic}\n")
        f.write(f"mode: deep\n")
        f.write(f"domains: {domain_str}\n")
        if domains.ticker:
            f.write(f"ticker: {domains.ticker}\n")
        f.write(f"generated_at: {when.isoformat(timespec='seconds')}\n")
        f.write(f"sources_usable: {usable}\n")
        f.write(f"sources_total: {len(sources)}\n")
        f.write(f"---\n\n")
        f.write(f"# {topic}\n\n")
        f.write(synthesis.strip())
        f.write("\n\n## References\n\n")
        for i, s in enumerate(sources, 1):
            origin = f" — _{s.origin}_" if s.origin else ""
            f.write(f"[{i}] [{s.title}]({s.url}){origin}\n")
        f.write("\n")

    with open(os.path.join(folder, "sources.md"), "w", encoding="utf-8") as f:
        f.write(f"# Sources for: {topic}\n\n")
        for i, s in enumerate(sources, 1):
            f.write(f"{i}. ({s.origin}) {s.url}\n")

    for i, s in enumerate(sources, 1):
        path = os.path.join(folder, f"{i:02d}-{_slugify(s.title)[:60]}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# [{i}] {s.title}\n\n")
            f.write(f"- URL: {s.url}\n- Source: {s.origin}\n\n")
            if s.summary:
                f.write("## Summary\n\n")
                f.write(s.summary.strip())
                f.write("\n\n")
            if s.body and s.body != s.summary:
                f.write("## Extracted body\n\n")
                f.write(s.body.strip())
                f.write("\n")
    return summary_path
