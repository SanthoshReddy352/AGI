"""Quick-mode research pipeline (Step 5b of plan).

Composable, deterministic, single LLM call. Replaces the agentic loop
in `service.py` for "quick research" / "tldr" / "briefly on X" /
"one-pager" phrasings.

Pipeline:
  1. Slug + create `~/Documents/friday-research/<ts>_<slug>/`
  2. Wikipedia anchor via `modules.sources.wikipedia.summary_for_query`
     (always-non-empty fallback for named entities — kills the
     "no search results → empty 00-summary.md" failure path).
  3. Web search via `modules.web._ddg_search` (with the same Wikipedia
     fallback we added in T-12.1b — so if DDG is rate-limited, we
     still surface something useful).
  4. `modules.sources.newspaper.extract_many(urls, max_workers=5)` —
     parallel fetch with trafilatura, ~3-5s total instead of 15s serial.
  5. One-shot LLM synthesis with strict citation rules.
  6. Citation validator strips dangling [N] references to indices that
     don't exist.
  7. Write `00-summary.md` (synthesis), `sources.md` (URL index), and
     one file per usable source.
  8. Return a `ResearchReport` shaped like the deep-mode one so
     `_on_research_done` callbacks don't have to special-case it.

Total wall-clock: ~15-20s on a warm cache (most time is the LLM call).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from core.logger import logger

from .service import ResearchReport, ResearchSource


_FRIDAY_RESEARCH_ROOT = os.path.join(
    os.path.expanduser("~"), "Documents", "friday-research"
)

# Per-source body cap kept on each ResearchSource (used by the per-source
# files and the legacy compression helpers).
_MAX_BODY_CHARS_PER_SOURCE = 3000

# Compression call output budget — used by the still-exported
# `_compress_*` helpers (deep.py / tests). Not on the synthesis hot path
# anymore: the writer reads source text directly (see `_build_synth_prompt`).
_COMPRESS_MAX_TOKENS = 280

# Per-source body slice fed DIRECTLY to the writer. We feed the 4B model
# the cleaned source text (no lossy 0.8B pre-compression) — at 8K context
# 10 sources × this cap still leaves comfortable headroom, and the writer
# gets higher-fidelity facts. Kept < 1000 so a single body can't dominate.
_WRITER_BODY_CHARS = 800

# Final writer (Executive Summary) output budget, in *generated* tokens.
# The 4B tool model runs at ~2.7 tok/s on CPU, so generation — not prompt
# size — sets the wall-clock. ~600 tokens ≈ a dense 12–15 sentence summary
# and lands inside ~3 minutes. `_clamp_max_tokens` shrinks this further if
# the prompt ever crowds the context window.
_SYNTH_MAX_TOKENS = 600


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def _slugify(topic: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", topic.strip().lower()).strip("-")
    return s[:60] or "research"


def _ensure_folder(topic: str, when: datetime) -> str:
    ts = when.strftime("%Y-%m-%d_%H%M")
    folder = os.path.join(_FRIDAY_RESEARCH_ROOT, f"{ts}_{_slugify(topic)}")
    os.makedirs(folder, exist_ok=True)
    return folder


# ---------------------------------------------------------------------------
# Source collection
# ---------------------------------------------------------------------------


def _collect_wikipedia(topic: str) -> Optional[ResearchSource]:
    """Anchor source — guaranteed non-empty for named entities."""
    try:
        from modules.sources import wikipedia  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[quick] wikipedia unavailable: %s", exc)
        return None
    summary = wikipedia.summary_for_query(topic)
    if not summary:
        return None
    extract = (summary.get("extract") or "").strip()
    if not extract:
        return None
    url = (
        (summary.get("content_urls") or {}).get("desktop", {}).get("page")
        or f"https://en.wikipedia.org/wiki/{summary.get('title', topic).replace(' ', '_')}"
    )
    return ResearchSource(
        title=str(summary.get("title") or topic),
        url=url,
        snippet=extract[:280],
        origin="wikipedia",
        body=extract[:_MAX_BODY_CHARS_PER_SOURCE],
        summary=extract[:600],  # quick anchor summary — no LLM needed
    )


def _collect_web_urls(topic: str, limit: int) -> list[dict]:
    """Top-N URLs from web_search (DDG)."""
    try:
        from modules.web.plugin import _ddg_search  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[quick] _ddg_search unavailable: %s", exc)
        return []
    try:
        # NOTE: `_ddg_search(query, max_results)` — positional, not `limit=`.
        # 2026-05-24 live-session bug: was passing `limit=` and silently
        # losing every web hit in quick + deep modes.
        results = _ddg_search(topic, limit) or []
    except Exception as exc:
        logger.warning("[quick] ddg search failed: %s", exc)
        return []
    return [r for r in results if r.get("url")]


def _extract_articles(urls: list[str], *, max_workers: int = 5) -> list[dict]:
    """Parallel trafilatura extract. Returns only entries with non-empty text."""
    if not urls:
        return []
    try:
        from modules.sources import newspaper  # noqa: PLC0415
    except Exception as exc:
        logger.debug("[quick] newspaper unavailable: %s", exc)
        return []
    extractions = newspaper.extract_many(urls, max_workers=max_workers)
    return [e for e in extractions if e and (e.get("text") or "").strip()]


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


_SYNTH_SYSTEM = (
    "You are a research analyst writing a single, comprehensive Executive "
    "Summary. Use ONLY facts stated in the sources you are given — never add "
    "a party, person, number, date, place, or claim that is not in the "
    "sources. Every factual sentence ends with an inline citation like [N] "
    "pointing to a real source index; cite the 1–3 MOST relevant sources for "
    "each sentence and never dump more than three on one sentence. Close "
    "every sentence — never stop mid-thought. Write flowing analytical prose "
    "that weaves the sources together; do not go source-by-source."
)


_COMPRESS_SYSTEM = (
    "You compress a single web source into dense, citation-ready bullets. "
    "Output ONLY 4-7 bullets of one sentence each, each ending with [N] "
    "(the index given). Each bullet states one specific concrete fact, "
    "number, name, or claim from the source. No filler, no preamble, no "
    "summary line at the start or end."
)


def _compress_source(app, source: ResearchSource, index: int) -> str:
    """Per-source LLM compression — turns ~3000 chars of cleaned body
    into ~4-7 citation-tagged bullets. Runs in parallel via the writer.

    Returns the bullet text (or the snippet/summary on LLM failure so
    the writer still has something to work with).
    """
    body = (source.body or source.summary or source.snippet or "").strip()
    if not body:
        return ""
    if len(body) > _MAX_BODY_CHARS_PER_SOURCE:
        body = body[:_MAX_BODY_CHARS_PER_SOURCE] + "…"

    router = getattr(app, "router", None)
    llm = router.get_llm() if router and hasattr(router, "get_llm") else None
    if llm is None:
        # No LLM — pre-format the snippet/summary as a single bullet so
        # the writer still has citation-tagged content.
        return f"- {(source.summary or source.snippet or body[:280]).strip()} [{index}]"

    prompt = (
        f"Source [{index}] — title: \"{source.title}\"\n"
        f"URL: {source.url}\n\n"
        f"Body:\n{body}\n\n"
        f"Compress this source into 4-7 dense bullets. Each bullet:\n"
        f"- starts with `- ` and ends with `[{index}]`\n"
        f"- states ONE specific concrete claim, number, name, or quote\n"
        f"- never says 'this article' / 'the source' — just the fact\n"
        f"Output ONLY the bullets, nothing else."
    )

    def _infer():
        try:
            if hasattr(llm, "create_chat_completion"):
                resp = llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": _COMPRESS_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=_COMPRESS_MAX_TOKENS,
                    temperature=0.2,
                )
                return (resp["choices"][0]["message"]["content"] or "").strip()
            resp = llm(prompt, max_tokens=_COMPRESS_MAX_TOKENS, temperature=0.2)
            return (resp["choices"][0].get("text") or "").strip()
        except Exception as exc:
            logger.warning("[quick] compress [%d] failed: %s", index, exc)
            return ""

    lock = getattr(router, "chat_inference_lock", None)
    if lock is not None:
        with lock:
            out = _infer()
    else:
        out = _infer()

    # If the model didn't include the citation tag, append it to every
    # bullet so the writer still has it.
    if out:
        fixed_lines = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith("-") and not line.startswith("*"):
                line = "- " + line
            if f"[{index}]" not in line:
                line = line.rstrip(".") + f" [{index}]."
            fixed_lines.append(line)
        return "\n".join(fixed_lines)
    return f"- {(source.summary or source.snippet or body[:280]).strip()} [{index}]"


def _compress_all_sources(app, sources: list[ResearchSource]) -> list[str]:
    """Parallel per-source compression with a small thread pool. Returns
    the bullet text in the SAME ORDER as `sources`."""
    from concurrent.futures import ThreadPoolExecutor  # noqa: PLC0415
    if not sources:
        return []
    workers = max(1, min(5, len(sources)))
    out: list[str] = [""] * len(sources)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="quick-compress") as ex:
        futures = {ex.submit(_compress_source, app, s, i + 1): i
                   for i, s in enumerate(sources)}
        for fut in futures:
            i = futures[fut]
            try:
                out[i] = fut.result(timeout=45)
            except Exception as exc:
                logger.warning("[quick] compress worker %d crashed: %s", i, exc)
                out[i] = ""
    return out


def _source_bundle(sources: list[ResearchSource], body_chars: int = _WRITER_BODY_CHARS) -> str:
    """Render the numbered source bundle fed to the writer.

    Each source contributes its cleaned text, sliced to ``body_chars`` so
    no single source can dominate the context window. Whitespace is
    collapsed to keep the token count tight.
    """
    chunks: list[str] = []
    for i, s in enumerate(sources, 1):
        text = (s.body or s.summary or s.snippet or "").strip()
        text = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", text))[:body_chars]
        chunks.append(f"### [{i}] {s.title}\nURL: {s.url}\n{text}")
    return "\n\n".join(chunks)


def _build_synth_prompt(topic: str, sources: list[ResearchSource]) -> str:
    """Render the writer prompt: a numbered source bundle plus a single
    instruction to produce one comprehensive Executive Summary.

    The writer reads source text directly (no pre-compression). The
    whole generation budget is spent on the Executive Summary — the one
    section the user actually wants — so it never truncates mid-report
    to make room for sections nobody reads.
    """
    avail_list = ", ".join(f"[{n}]" for n in range(1, len(sources) + 1))
    bundle = _source_bundle(sources)

    return (
        f"Topic: \"{topic}\"\n\n"
        f"You have {len(sources)} sources below, each numbered [N].\n\n"
        f"{bundle}\n\n"
        "Write ONE section, in Markdown:\n\n"
        "## Executive Summary\n"
        "Write 3 dense paragraphs (about 12–15 sentences total). A reader who "
        "reads ONLY this section must come away knowing every major point "
        "across ALL the sources above: the central facts, the key numbers, "
        "dates, and names, where the sources agree, any points where they "
        "disagree, and the practical takeaway. Weave the sources together "
        "into flowing analysis — do NOT go through them one by one. Reference "
        "at least 5 different sources (or all of them, if fewer than 5).\n\n"
        "CITATION RULES (strictly enforced):\n"
        f"- Cite ONLY these indices inline: {avail_list}.\n"
        "- Do NOT invent a citation for any index not in that list.\n"
        "- End every factual sentence with its citation, e.g. [3] or [2][5].\n"
        "- Cite the 1–3 most relevant sources per sentence — never more than "
        "three, and never list all sources on one sentence.\n"
        "- Use only facts present in the sources. Close every sentence.\n"
    )


def _writer_candidates(app):
    """Ordered (llm, lock, role) writer models, best-quality first.

    Prefers the 4B *tool* model — it writes far better, less-hallucinated
    summaries than the 0.8B chat model — and block-loads it (research runs
    in the background, so the load latency is acceptable). Falls back to the
    chat model. Returns an empty list when no model is available, so the
    caller can drop to the extractive raw-source fallback.
    """
    router = getattr(app, "router", None)
    mm = getattr(app, "model_manager", None) or getattr(router, "model_manager", None)
    out: list = []
    if mm is not None:
        for role, getter in (("tool", mm.get_tool_model), ("chat", mm.get_chat_model)):
            try:
                llm = getter()
            except Exception as exc:  # noqa: BLE001
                logger.debug("[quick] %s model load failed: %s", role, exc)
                llm = None
            if llm is not None:
                out.append((llm, mm.inference_lock(role), role))
        return out
    # No model_manager (e.g. unit-test stubs): fall back to router.get_llm().
    if router is not None and hasattr(router, "get_llm"):
        llm = router.get_llm()
        if llm is not None:
            out.append((llm, getattr(router, "chat_inference_lock", None), "chat"))
    return out


def _clamp_max_tokens(llm, *texts: str, desired: int, reserve: int = 320) -> int:
    """Shrink the generation budget so prompt + output never exceed the
    model's context window. This is the structural guard against the
    original 'Requested tokens exceed context window' failure — instead of
    erroring, synthesis just generates fewer tokens. Best-effort: if the
    llm lacks a real tokenizer (test stubs), return ``desired`` unchanged.
    """
    try:
        n_ctx = int(llm.n_ctx())
        used = sum(len(llm.tokenize(t.encode("utf-8"))) for t in texts if t)
        room = n_ctx - used - reserve
        if room < 64:
            return 64
        return max(64, min(int(desired), room))
    except Exception:
        return int(desired)


def _strip_dangling_citations(text: str, max_index: int) -> str:
    """Remove [N] references where N > max_index. Keeps valid ones."""
    def _repl(m):
        try:
            n = int(m.group(1))
        except (TypeError, ValueError):
            return m.group(0)
        return m.group(0) if 1 <= n <= max_index else ""

    return re.sub(r"\[(\d{1,3})\]", _repl, text)


def _extractive_fallback(topic: str, sources: list[ResearchSource]) -> str:
    """Used when no LLM is available (router.get_llm() → None). Just
    concatenates the per-source summaries with citation markers."""
    lines = [
        f"# Quick research: {topic}",
        "",
        f"_LLM unavailable — surfaced raw source summaries with citations._",
        "",
        "## Sources",
        "",
    ]
    for i, s in enumerate(sources, 1):
        body = (s.summary or s.snippet or s.body or "").strip()[:600]
        lines.append(f"[{i}] **{s.title}** — {s.url}")
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip()


def _run_writer(llm, lock, role: str, prompt: str, budget: int,
                system: str = _SYNTH_SYSTEM) -> str:
    """Single synthesis call against one model, holding its inference lock.
    Returns the stripped completion text, or '' on any failure."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    def _infer():
        try:
            if hasattr(llm, "create_chat_completion"):
                resp = llm.create_chat_completion(
                    messages=messages, max_tokens=budget, temperature=0.3,
                )
                return (resp["choices"][0]["message"]["content"] or "").strip()
            resp = llm(prompt, max_tokens=budget, temperature=0.3)
            return (resp["choices"][0].get("text") or "").strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[quick] writer call failed (%s): %s", role, exc)
            return ""

    if lock is not None:
        with lock:
            return _infer()
    return _infer()


def _synthesize(app, topic: str, sources: list[ResearchSource]) -> str:
    """LLM synthesis of one comprehensive, citation-disciplined Executive
    Summary.

    The writer reads the source text directly (the 4B tool model fits the
    bundle at 8K context) and spends its whole budget on the Executive
    Summary. Candidates are tried best-first (4B → 0.8B); only if every
    model yields empty text do we drop to the extractive raw-source dump.
    """
    if not sources:
        return f"No sources were available for '{topic}'."

    candidates = _writer_candidates(app)
    if not candidates:
        return _extractive_fallback(topic, sources)

    prompt = _build_synth_prompt(topic, sources)
    text = ""
    for llm, lock, role in candidates:
        budget = _clamp_max_tokens(llm, _SYNTH_SYSTEM, prompt, desired=_SYNTH_MAX_TOKENS)
        logger.info(
            "[quick] synthesis: writer=%s sources=%d budget=%d",
            role, len(sources), budget,
        )
        text = _run_writer(llm, lock, role, prompt, budget)
        if text:
            break
        logger.info("[quick] writer %s returned no text — trying next model", role)

    if not text:
        return _extractive_fallback(topic, sources)

    text = _strip_dangling_citations(text, max_index=len(sources))
    # Truncation guard.
    if text and text[-1] not in ".!?\")]":
        last_period = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if last_period >= 0 and last_period < len(text) - 5:
            text = text[: last_period + 1] + "\n\n_(response truncated)_"
    return text


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------


def _write_outputs(folder: str, topic: str, synthesis: str,
                   sources: list[ResearchSource], when: datetime) -> str:
    """Write 00-summary.md + sources.md + per-source files. Returns the
    summary path."""
    usable = sum(1 for s in sources if s.body or s.summary or s.snippet)
    summary_path = os.path.join(folder, "00-summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(f"---\n")
        f.write(f"topic: {topic}\n")
        f.write(f"mode: quick\n")
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

    # sources.md — just the URL index, useful for `cat sources.md | xargs open`
    with open(os.path.join(folder, "sources.md"), "w", encoding="utf-8") as f:
        f.write(f"# Sources for: {topic}\n\n")
        for i, s in enumerate(sources, 1):
            f.write(f"{i}. {s.url}\n")

    # Per-source files — index, title, URL, summary, body excerpt.
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


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run_quick_research(app, topic: str, *, max_sources: int = 5) -> ResearchReport:
    """One call — produces a complete `ResearchReport` for *topic* and
    writes it to disk. Shape matches the deep-mode report so callers
    (`research_planner._on_research_done`) don't need to special-case it.
    """
    started = time.monotonic()
    when = datetime.now()
    topic = (topic or "").strip()
    if not topic:
        return ResearchReport(
            topic="", folder="", summary_path="",
            error="No topic provided.",
        )

    logger.info("[quick] Starting topic=%r max_sources=%d", topic, max_sources)
    folder = _ensure_folder(topic, when)

    # 1. Wikipedia anchor.
    sources: list[ResearchSource] = []
    wiki = _collect_wikipedia(topic)
    if wiki is not None:
        sources.append(wiki)
        logger.info("[quick] wikipedia anchor: %s", wiki.title[:80])

    # 2. Web search → URLs.
    web_results = _collect_web_urls(topic, limit=max_sources)
    web_urls = [r["url"] for r in web_results][:max_sources]

    # 3. Parallel newspaper_extract.
    extractions = _extract_articles(web_urls, max_workers=min(5, max(1, len(web_urls))))

    # Build ResearchSources from extractions. Skip empties.
    by_url = {e["url"]: e for e in extractions}
    for r in web_results:
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
        if len(sources) >= max_sources + 1:  # +1 for the anchor
            break

    if not sources:
        # Even the Wikipedia anchor failed. Write a clean failure card
        # instead of a blank 00-summary.md.
        summary_path = os.path.join(folder, "00-summary.md")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# {topic}\n\n")
            f.write("_No usable sources were retrieved._\n\n")
            f.write("Tried: Wikipedia summary, DuckDuckGo search.\n")
        duration = time.monotonic() - started
        logger.info("[quick] DONE (no sources) %.1fs → %s", duration, summary_path)
        return ResearchReport(
            topic=topic, folder=folder, summary_path=summary_path,
            sources=[], duration_s=duration,
            error="No usable sources",
        )

    # 4. Synthesis.
    synthesis = _synthesize(app, topic, sources)

    # 5. Write outputs.
    summary_path = _write_outputs(folder, topic, synthesis, sources, when)

    duration = time.monotonic() - started
    logger.info(
        "[quick] DONE topic=%r mode=quick in %.1fs (%d sources) → %s",
        topic, duration, len(sources), summary_path,
    )
    return ResearchReport(
        topic=topic, folder=folder, summary_path=summary_path,
        sources=sources, duration_s=duration,
    )
