# Step tracker — Plan `plan/2026-05-23_22-13-37_plan.md` + Routing rewrite

**Status as of 2026-05-24 evening:** ALL steps complete. 707/707 across
the touched test surface. The legacy 1557-line agentic research loop
remains in `service.py` for backward-compat (`mode="speed|balanced|
quality"`) but `mode="quick"` and `mode="deep"` route to the new
composable pipelines.

Living checklist for the in-flight refactor. Update the **Status** column
as each step lands. "Done" rows include the test count and the
testing-guide T-entries that pin the behaviour.

## Steps

| # | Title | Status | Notes |
|---|-------|--------|-------|
| 1 | `/new` & `/clear` true reset (browser, shell, pending wipe, routing state) | ✅ done 2026-05-23 | 17 tests; T-11.0 |
| 2 | Brightness DBus signal (GNOME / KDE / XFCE panel refresh) | ✅ done 2026-05-23 | 10 tests; T-4.2b |
| 3 | Broaden existing intent parsers (brightness, volume, screenshot, time/date, focus, screen-lock) | ✅ done 2026-05-23 | 149 tests |
| 4 | Long-tail new parsers (weather, goals, triggers, HA, awareness, clipboard, code-eval, send_notification, active-window, vision long-tail, security extras) + `_KNOWLEDGE_Q_RE` negative lookaheads | ✅ done 2026-05-24 | 147 tests; T-4.10–T-4.15, T-5.5–T-5.8, T-6.4–T-6.5, T-13.3, T-14.5 |
| **4b** | **Routing rewrite — tool catalog + EmbeddingRouter rewire + planner few-shots + chat-side pre-flight reroute** | ✅ done 2026-05-24 | 18 tests, 553/553 across all touched suites. See §"Routing rewrite (Step 4b)" below. |
| 5a | **Port 7 free Python source tools** — wikipedia, arxiv, hackernews, pubmed, newspaper_extract (trafilatura-backed), yfinance, pdf_text_search | ✅ done 2026-05-24 | `modules/sources/` plugin registers 9 capabilities; intent patterns in `_parse_source_tools` + dedicated `_parse_newspaper_extract` ahead of `_parse_web_url_action`; catalog entries; 58 tests (live-network smokes for wiki/HN/PubMed/arxiv/trafilatura all green); knowledge-question regex tightened so "compare these screenshots" / "analyze my clipboard image" / "describe this picture" don't get poached. **612 / 612 across all touched suites.** |
| 5a-hotfix | **4-bug sweep from live session 2026-05-24 07:05–07:30** before resuming Step 5b. (1) `show_memories` overlays facade on stale user_profile so Santhosh wins over Tricky. (2) `/new` calls new `expire_all_workflows(outgoing_session_id)` so dangling research_planner can't hijack the next conversation. (3) `awaiting_readout` step ends quietly on "bye/exit/never mind/…" so the router can route to `shutdown_assistant` instead of reading the briefing. (4) `/web` falls back to Wikipedia when DDG returns empty. Audit added 9 catalog entries that the previous audit missed. 16 new tests in `tests/test_bugfix_2026_05_24.py`. | ✅ done 2026-05-24 |
| 5b | **Quick-mode research pipeline** — `wiki_summary → web_search → newspaper_extract × 5 in parallel → one-shot synthesis with citations` | ✅ done 2026-05-24 | New `modules/research_agent/quick.py` (~400 lines). `service.run_research(topic, mode='quick')` dispatches to the new pipeline; deep mode unchanged. Pipeline: Wikipedia anchor (always-non-empty) → DDG → trafilatura×5 parallel (5s instead of 15s serial) → one-shot LLM synth with strict citation rules → dangling-`[N]` scrubber → 00-summary.md with YAML front-matter + per-source `01-…md` files + `sources.md`. Extractive fallback when LLM unavailable. Failure card when both Wikipedia AND DDG return nothing. 13 new tests in `tests/test_research_quick_mode.py`; **513 / 513 across all touched suites**. |
| 5c | **Deep-mode research rewrite** — `wiki_anchor → domain dispatch (arxiv/pubmed/hn/yfinance) → web_search → newspaper × 8 → writer with contradiction handling` | ✅ done 2026-05-24 | New `modules/research_agent/domain.py` (regex classifier) + `modules/research_agent/deep.py` (~400 lines). Composable: wiki + domain sources + web parallel → one synthesis call with the 5-section Executive Summary / Key Findings / Cross-Source Analysis / Conflicting Claims (optional) / Open Questions template. Replaces the 25-iteration agentic loop with 2 LLM calls total (planning is now regex). `service.run_research(topic, mode="deep")` dispatches; legacy modes (speed/balanced/quality) still hit the old `_run_research_locked`. 30 new tests covering domain classifier + each per-domain collector + synth/citation/truncation + e2e + service dispatch. **543 / 543 across all touched suites.** |
| 5d | **Mode detection + intent wiring** | ✅ done 2026-05-24 | `_parse_research_topic` in `core/intent_recognizer.py` now tags `mode="quick"` for tldr/briefly/quick research/one-pager/summarize/overview phrasings, `mode="deep"` for deep dive/thorough/comprehensive/exhaustive/in-depth/literature review/detailed report phrasings + bare "research X" / "investigate X" / "study X" (new pipeline is now default). Comparative phrasings ("compare X vs Y", "contrast X with Y", "which is better X or Y") always tag deep. `research_planner.begin(topic, sid, mode=…)` skips the "any specific angle?" follow-up when mode is set. `_parse_mode` in the planner now also returns "quick"/"deep" so inline focus-reply overrides ("focus on RLHF, fast") work. `_DEFAULT_PLANNER_MODE` flipped to `"deep"`. `tl;dr X` clause-splitter guard added so the semicolon isn't treated as a clause separator. Catalog entry expanded with 17 example phrases. 49 new tests in `tests/test_research_mode_detection.py`; **615 / 615 across all touched suites.** |
| 5e | **Tests, testing-guide rows, Modification Log** | ✅ done 2026-05-24 | Added T-12.8–T-12.14 (per-source-tool entries for wikipedia / arxiv / hackernews / pubmed / newspaper / yfinance / pdf_text_search). End-to-end integration tests in `tests/test_research_e2e.py` (5 cases): intent → quick pipeline, intent → deep pipeline, plugin-handler explicit-mode short-circuit, catalog covers all Step-5 capabilities, catalog `research_topic` lists quick + deep + comparative phrasings. Modification Log row consolidates Steps 5a–5e. **707 / 707 across the full research + intent + plumbing surface.** |
| 5d-hotfix | **Connector-word regex regression (live session 17:35).** "quick research Tamil Nadu …" and "Deep Dive Quantum Computing …" fell through to chat because the Step 5d patterns required a connector word (`on|about|for|of`) between the verb and topic. Rewrote every quick/deep pattern as `verb(?:\s+(?:connectors))?\s+(.+)`. Also fixed catalog cross-check to consult `capability_registry` (was only reading the old `router._tools_by_name`, false-alarming on 17 valid entries). Removed catalog duplicate `list_calendar_events`. Added 3 missing news entries. 16 new regression tests; **657/657 across touched suites.** | ✅ done 2026-05-24 |

### Notes on the revised research plan

- Replaces original Stages 5-9 (truncation fix / Wikipedia anchor / contradiction writer / graceful degrade / template polish). All of those concerns are folded into 5b + 5c.
- Tool dependency strategy: pure-HTTP for wikipedia/arxiv/hackernews/pubmed (no extra deps), `trafilatura` for newspaper extraction (already installed), lazy-import for `yfinance` + `pypdf` (graceful error if missing).
- "Hits a snag" failure path is fixed by Stage 5b having Wikipedia as an always-non-empty fallback source.

## Routing rewrite (Step 4b)

Background: when IntentRecognizer (regex) misses, the request flows through
EmbeddingRouter → RouteScorer → Qwen-4B planner → LLM_Chat fallback. In
practice we still see chat-mis-routes on phrasings that *should* hit a
tool (`Fetch <URL>`, `Forget my love for coding` before Step 4 wired it,
etc.). Root causes:

1. **No single source of truth.** Each tool's `aliases` / `context_terms` /
   `description` are scattered across plugins and were auto-generated, not
   curated.
2. **EmbeddingRouter feeds on those weak strings.** A short
   `description` produces poor embeddings, so cosine similarity barely
   distinguishes tools.
3. **No example phrases.** Small models (Qwen 4B planner, Qwen 0.8B
   chat) benefit enormously from few-shot phrasing examples. They have
   none today.
4. **No second-chance check in chat.** Once the planner picks chat, the
   model commits and often refuses ("I can't access external URLs") — a
   classic signal we should have routed to a tool instead.

### Sub-steps

| ID | Title | Status |
|----|-------|--------|
| 4b-1 | `data/tool_catalog.yaml` — single curated source for the ~50 user-facing capabilities (`name`, `summary`, `example_phrases`, `parameters`, `category`) | ✅ done — 111 entries, ~9 phrases each on average |
| 4b-2 | Loader: `core/tool_catalog.py` — parse YAML, validate against the registered-capability set, expose `Catalog` with `iter_entries()` + `entry_for(name)` | ✅ done — `Catalog`, `CatalogEntry`, `load_catalog`, `get_catalog`, `bind_registry`, `reset_catalog_for_tests` |
| 4b-3 | Rewire `core/embedding_router.py` to embed `example_phrases` (plus `name` + `summary`) instead of `aliases + context_terms`. Index rebuilt at boot from the catalog. | ✅ done — catalog entries replace the legacy auto-noun cloud; tools missing from the catalog keep the legacy path |
| 4b-4 | Inject candidate few-shot examples into the Qwen-4B planner prompt | ✅ done — `compact_capability_cards` now adds `examples: [...]`; `plan_draft.j2` renders `Example phrasings → use <name>: "X", "Y"…` per card |
| 4b-5 | Chat-side pre-flight reroute in `modules/llm_chat/plugin.py` | ✅ done — `_preflight_reroute` calls `embedding_router.preflight_route(query, threshold=0.72)`; on hit, dispatches via `capability_executor` and returns; on miss, falls through to normal chat. `blocked_from_chat_preflight: true` in catalog blocks tools that need structured args. |
| 4b-6 | Tests: catalog schema validator, embedding-index rebuild test, planner few-shot prompt assertion, chat pre-flight reroute integration test | ✅ done — `tests/test_tool_catalog.py` (18/18 green) |
| 4b-7 | Testing guide rows + Modification Log entry | 🟡 in progress |

### Acceptance for 4b

- Re-running the prompts that mis-routed in the 2026-05-23 21:35–21:51
  log produces `source=intent` or `source=embedding` (NOT `source=chat`)
  for: "fetch https://…", "crawl https://…", "search my conversations
  for X", and the long-tail tools we wired in Step 4 but the *embedding
  pre-flight* should now catch *novel* phrasings we haven't written
  regex for.
- All 522 existing tests still pass.
- New catalog file is the only place a tool's example-phrases live —
  plugin `aliases` / `context_terms` are deprecated for new tools.

## Reading order

If you're picking this up cold: start with the plan
(`plan/2026-05-23_22-13-37_plan.md`), then this file, then the
testing-guide Modification Log rows (most recent first).
