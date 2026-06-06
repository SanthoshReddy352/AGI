# FRIDAY Linux — Project Instructions

## 🚧 ACTIVE MIGRATION (v2 — Cloud-Only Rebuild)

FRIDAY is being rebuilt as a cloud-only (API-only brain) assistant in a new greenfield
`friday/` package. **While this migration is in progress, the authority on current state
is [`docs/cloud-migration/STATUS_V2.md`](docs/cloud-migration/STATUS_V2.md).** Read it
before doing any v2 work, and **track every v2 task there** (mark `[~]` when starting,
`[x]` when done, and update the "Last updated" line + change log).

- **Canonical plan / god document:** [`docs/cloud-migration/FRIDAY_V2_GOD_DOC.md`](docs/cloud-migration/FRIDAY_V2_GOD_DOC.md)
- **Live progress ledger:** [`docs/cloud-migration/STATUS_V2.md`](docs/cloud-migration/STATUS_V2.md)

The legacy architecture rules below (intent recognizer, stores, planning engine) still
describe the **old `core/` / `modules/` tree** and remain valid until Phase 8 (purge).
New v2 code lives under `friday/` and does **not** use the intent recognizer or the
planning stack. **This section is removed when the migration completes (Phase 9).**

## Knowledge Graph (RAG)

A pre-built knowledge graph of this codebase lives at `/home/tricky/Friday_Linux/graphify-out/`.

**Before answering any question about the codebase** (architecture, where something is defined, how components connect, what calls what), query the graph first:

```
/graphify query "<your question>"
```

Files in `graphify-out/`:
- `graph.json` — 2,797 nodes, 4,915 edges across the full project (excludes `libs_backup/`)
- `GRAPH_REPORT.md` — community map, god nodes, and surprising connections
- `graph.html` — interactive visualization (open in browser)

Use the graph to:
- Find which file/class owns a concept before reading code
- Trace call chains (e.g. how a voice turn flows from STT → Router → Capability → TTS)
- Identify which community a module belongs to before exploring that area
- Verify inferred relationships before acting on them (edges tagged INFERRED need confirmation)

**Key god nodes** (highest connectivity — touch these carefully):
1. `STTEngine` (110 edges) — `modules/voice_io/stt.py`
2. `FridayApp` (74 edges) — `core/app.py`
3. `TaskManagerPlugin` (74 edges) — `modules/task_manager/plugin.py`
4. `CommandRouter` (73 edges) — `core/router.py`
5. `BrowserMediaService` (73 edges) — `modules/browser_automation/service.py`

Keep the graph up to date: after adding or changing significant files, run `/graphify . --update` to incrementally re-extract only the changed files.

## Project Overview

FRIDAY is a local-first, cross-platform AI assistant (Linux + Windows). It uses a modular plugin architecture with a capability registry, a v2 turn orchestration pipeline, and a three-tier memory system (episodic, semantic, procedural).

## Persistence layout — `core/stores/` (Track 5.1, 2026-05-19)

The 1480-line god-class `core/context_store.py` was decomposed into **six domain stores** under `core/stores/`. **This is intentional, not a duplication bug.** If you see a class that looks like it could be one of the new stores, it's there because the Direction's "≤4 tables per store" rule required the split.

```
core/stores/
├── __init__.py                — re-exports everything
├── audit_store.py             — audit_events, online_permission_events, agent_messages, commitments
├── workflow_store.py          — workflows
├── memory_store.py            — facts, memory_items (+ owns Chroma vector index + HashEmbeddingFunction)
├── knowledge_graph_store.py   — entities, entity_facts, entity_relationships
├── goal_store.py              — goals, goal_progress
├── session_store.py           — sessions, turns, conversation_sessions, personas
│                                (+ WorkingArtifact dataclass + ARTIFACT_SCOPE_RANK)
├── context_store.py           — TRANSITIONAL FACADE (no own state; delegates to the 6 stores)
└── migrations/                — one .sql file per store
```

**Important rules to keep in mind:**

1. **`core/context_store.py` was deleted** in Track 5.1e. Don't try to "restore" it — the new home is `core/stores/context_store.py`. All imports go through `from core.stores import ContextStore` (or `WorkingArtifact`, `ARTIFACT_SCOPE_RANK`, etc.).

2. **`ContextStore` is a transitional facade**, not a god class. Every method is either a 1-line delegator to one of the 6 stores or a small (≤30-line) 2-store orchestrator (`append_turn`, `save_persona`, `save_workflow_state`). If you find yourself adding own-SQL or own-state to `ContextStore`, **stop** — it belongs in one of the domain stores.

3. **Write-ownership is strict; reads can cross stores.** Each store creates and writes its own tables only. Reads can go anywhere via raw SQL on the shared DB (e.g. `MemoryStore._candidates_for_fallback` reads `turns` from SessionStore). If you need to write across domains, write an orchestrator on the facade — don't duplicate writes between stores.

4. **`FridayApp` exposes both paths** during the transition:
   - `self.context_store` — the facade (backward-compat)
   - `self.session_store`, `self.audit_store`, `self.workflow_store`, `self.memory_store`, `self.knowledge_graph_store`, `self.goal_store` — direct store access (preferred for new code)
   - Both point at the same underlying instances. Writing through either path lands in the same SQLite tables and Chroma collection.

5. **`WorkingArtifact` and `ARTIFACT_SCOPE_RANK` live in `core/stores/session_store.py`.** The canonical import is `from core.stores import WorkingArtifact` (re-exported from the package). Some files still do `from core.stores.session_store import WorkingArtifact` — that also works.

6. **Method-length budget**: every store method is ≤30 lines per Direction §5.1. Long SQL bodies (`save_persona`, `store_memory_item`, `_fallback_semantic_recall`) were decomposed into ≤30-line helpers — `_persona_upsert_sql` + `_persona_upsert_params`, `_upsert_memory_item_row`, `_candidates_for_fallback` + `_rank_candidates`. Keep new methods within that budget.

7. **Adding a new table?** Pick the matching domain store, add the `CREATE TABLE` to its `migrations/<name>.sql`, add methods to that store class, add focused integration tests under `tests/stores/test_<name>_store.py`. **Don't add new tables to `ContextStore`** — that file is on a deprecation path.

8. **Track 5.1 history** lives in:
   - `STATUS.md` rows 5.1a–5.1e (status + retirements per sub-track)
   - `docs/testing_guide.md` modification log entries for 5.1a–5.1e
   - `responses/2026-05-19_*.md` per-commit response logs
   Read these before making structural changes to the storage layer.

## Intent Recognition — every tool needs a robust pattern

`core/intent_recognizer.py` is the **deterministic** routing layer. When a user utterance matches one of its `_parse_*` regexes, the turn orchestrator routes straight to the capability (`source=intent`, `intent_conf=1.00`). When nothing matches, the request falls through to the LLM planner / chat fallback — and **small chat models (Qwen 0.8B) will happily fabricate plausible-sounding success ("Brightness set to 60.") for tools that don't exist** or weren't matched.

**The rule:** every capability registered via `app.register_capability(...)` — whether brand new or one getting a fix — **must** also have an intent pattern in `core/intent_recognizer.py` unless it is intentionally LLM-routed only (rare).

`context_terms`, `aliases`, and `description` on the capability spec feed the LLM RouteScorer, **not** IntentRecognizer. Without an explicit regex pattern, a capability is at the mercy of the small chat model.

### How to wire a new tool

1. **Pick a parser** — group by domain. Reuse `_parse_environment`, `_parse_screen_lock`, `_parse_brightness`, etc. when the new tool fits; add a new `_parse_<domain>` method when it doesn't.
2. **Add the regex(es) inside that parser.** Multiple `re.search` calls are fine — one per phrasing family.
3. **Register the parser** in the `_parse_clause` chain, paying attention to ordering. Put narrow / explicit parsers BEFORE broad catch-alls. E.g. `_parse_screen_lock` runs before `_parse_help` so "lock screen" never matches a help query; `_parse_environment` runs before `_parse_file_action` so "find file foo.txt" wins on the index path.
4. **Return the canonical action dict**: `{"tool": "<name>", "args": {...}, "text": clause, "domain": "<domain>"}`. The `args` dict must match the capability's declared parameters.
5. **Gate on tool presence**: `if "<name>" not in getattr(self.router, "_tools_by_name", {}): return None`. This keeps the parser harmless when the capability isn't loaded (test apps, optional plugins).

### Robust patterns — cover at least these axes

- **Verb variants**: "set / change / make / put / turn" brightness to X.
- **Object variants** (with and without "the", "my", "your"): "lock screen" / "lock the screen" / "lock yourself" / "lock friday".
- **Word order**: "brightness 80" and "set 80 brightness", "rescan apps" and "apps rescan".
- **Spoken cardinals where numeric input is plausible**: "fifty" → 50, "max" → 100, "minimum" → 0 (see `_parse_brightness`).
- **Optional argument shapes**: "unlock screen" (no PIN → handler re-asks) and "unlock with pin 1234" (explicit PIN) must both route to the same tool.
- **Filler word tolerance**: "Friday rescan my apps" and "rescan apps please" should both match.

### Negative cases matter too

- Don't poach from existing routers. `_parse_environment.search_indexed_files` deliberately requires either `called <name>` OR a `name.ext` filename so it doesn't intercept "find the file design build final report" — which belongs to `_parse_file_action`.
- Never match on a single common word (`battery`, `volume`, `screenshot`) without a verb anchor — those bare words appear in unrelated sentences ("the battery in my car died") and cause false-positive routing.

### Tests are mandatory

For every new parser, add `tests/test_<domain>_intent.py` following the `_make_recognizer(tools=[...])` pattern in `tests/test_environment_intent.py` or `tests/test_wipe_memory_intent.py`. Parametrize the positive phrasings; include at least one negative phrasing that must NOT match. The 46-test `tests/test_environment_intent.py` is the canonical example.

### Don't forget the testing guide

When you add or fix an intent pattern, add or update the T-entry in `docs/testing_guide.md` — the **You say** field lists the natural phrasings the user can speak, which doubles as a live spec of what the parser must accept.

## Testing Guide

`docs/testing_guide.md` is the canonical command-first guide. **After any code change that touches user-visible behaviour, update it in the same response** — add or amend the relevant `T-N.M` entry, and append a row to the Modification Log at the bottom with today's date and a one-line summary.

Structure (don't restructure without a plan track):
- 23 sections (`1. Memory & Profile` … `22. Cross-session recall` + `23. Modification log`)
- Each test follows the fixed template: **You say / Expected / What it tests / Wrong behaviour / Verify**
- `Verify` must always be a runnable shell command — even pure-UI cases get `tail -5 logs/friday.log`
- Hermes-ported behaviour: tag the **What it tests** line with `[ported: hermes-agent/<source-path>]`

Track 5.3 P2.4 rewrite landed 2026-05-23; the prior 5,524-line guide is archived at `docs/archive/testing_guide_v1_2026-05-22.md`. Do **not** update the old `docs/manual_testing_guide.md` either — also archived for historical reference only.

## Response & Plan Logging

**After every query response**, save the exchange to `responses/` in the project root:
- Folder: `responses/`
- Filename: `YYYY-MM-DD_HH-MM-SS.md` (date/time the query was received)
- File must contain:
  - `## Prompt` — the exact user message
  - `## Response` — the full response/work produced

**In plan mode**, additionally save the plan to `plan/` in the project root:
- Folder: `plan/`
- Filename: `YYYY-MM-DD_HH-MM-SS_plan.md` (same timestamp as the query)
- File must contain the complete plan as produced by ExitPlanMode

Both folders must exist; create them if absent. These files are logs — never modify a saved file after writing it.

## Platform Notes

This is a cross-platform project (Linux + Windows). Platform-specific code must guard with `platform.system()` or `os.name`. Key patterns already in use:
- Subprocess spawning: `start_new_session=True` (Linux/macOS) vs `creationflags=DETACHED_PROCESS` (Windows)
- Venv python: `.venv/bin/python3` (Linux) vs `.venv/Scripts/python.exe` (Windows)
- `strftime("%-I")` is Linux-only — use `.lstrip("0")` on Windows-safe format instead
- Always pass `encoding="utf-8", errors="replace"` to `subprocess.run(..., text=True)`
