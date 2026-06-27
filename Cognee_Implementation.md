# Cognee Integration — Implementation Tracker

> **Status:** Living document — updated as implementation proceeds.
> **Created:** 2026-06-25
> **Last updated:** 2026-06-27 (Cloud graph sync + switch-without-restart + FTS5 money shot)
> **Owner:** Namma Agent (D:\AGI)
> **Driving goal:** Win the WeMakeDevs × Cognee hackathon (see Section 1.5).
> **Source material:**
> - `C:\Users\santh\Desktop\Cognee\Cognee_Complete_Project_Report.md` (Cognee v1.2.1 reference — accurate)
> - `C:\Users\santh\Desktop\Cognee-NammaAgent-Integration\Cognee_NammaAgent_Integration_Plan.md` (proposed integration)
> - Hackathon: https://www.wemakedevs.org/hackathons/cognee

---

## 0. How to read / maintain this file

This is the **single source of truth** for the Cognee add-on. Every phase has
sub-processes with a status box. As work lands, flip the box and append a dated
line to the **Changelog** at the bottom. Never delete history — append.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## 1. Verdict (read this first)

**Yes — adding Cognee will make Namma Agent meaningfully better, *if* implemented
in the corrected order below.**

Namma Agent's memory today is a single SQLite file with **FTS5/BM25 keyword
search only**. That genuinely misses semantic recall ("the thing I said about the
data layer" when you now say "database architecture"), entity/relationship graphs,
and cross-session linking. Cognee's vector + graph + relational stores fill exactly
those gaps, and the proposed design is **non-destructive** (sidecar alongside
SQLite, graceful degradation) — which is the right call.

**But the integration plan, as written, has real anomalies (Section 3) that would
degrade or break the system if implemented verbatim.** The most important
correction: Namma Agent is **already MCP-capable** and Cognee **ships its own MCP
server**, so the lowest-risk path is to integrate over MCP *first* (now trivial —
the MCP settings UI was just added), and only then pursue the heavier embedded-SDK
integration. See Section 4 for the corrected phasing.

---

## 1.5 Hackathon mode — LOCKED PLAN (2026-06-25)

**Event:** "The Hangover Part AI: Where's My Context?" — WeMakeDevs × Cognee.
**Window:** **June 29 → July 5, 2026** (prior work is allowed → we start now).
**Win condition:** use Cognee for memory, visibly exercising all four ops
(`remember`, `recall`, `improve`/memify, `forget`). Top judging weight =
**"Best Use of Cognee — depth of memory-lifecycle API engagement"** + Presentation.

### Locked decisions
- **Tracks:** **Both hardware tracks** — Best Use of Open Source (self-hosted →
  MacBook) **and** Best Use of Cognee Cloud (→ iPhone 17). **One codebase**; the
  cloud submission is produced by a config switch (free dev plan code `COGNEE-35`).
  *(Blog/social side tracks: skipped.)*
- **Integration:** **Containerized Cognee via the MCP UI** (revised 2026-06-25 —
  see changelog). Namma launches `cognee/cognee-mcp:main` through its existing
  stdio MCP client (`docker run -i`), so **Cognee's deps never enter Namma's
  venv**. Reason for the change from "embedded SDK": the dev machine is **Python
  3.14.5** (Cognee's native deps lack 3.14 wheels and pin older
  fastapi/pydantic/sqlalchemy that clash with Namma) — embedding it in-process
  would risk **breaking Namma**, violating the non-degradation guarantee. Depth is
  unaffected (all four ops still used; judges can't see in-process vs container).
  - **Hybrid models:** embeddings = local Ollama `nomic-embed-text` (free);
    extraction LLM = **Groq** (cloud, fast — machine is CPU-only 16 GB, so local 8B
    extraction is too slow). Still fully OS-track eligible (Cognee itself is
    self-hosted open-source).
  - **Memory Graph view** data source: TBD after probing what `cognee-mcp` exposes
    (graph search tool vs. add a Cognee REST container). Decide at Day 3.
  - **Cloud track mechanism — VERIFIED (2026-06-26):** the `cognee-mcp` image
    supports Cognee Cloud natively via `--serve-url https://<instance>.cognee.ai`
    + `--serve-api-key` (or `COGNEE_API_KEY` env). It calls `cognee.serve()` at
    startup so ALL ops route to the cloud (cloud handles its own DB + embeddings).
    → Cloud track = a second MCP server entry with those flags; **Namma code +
    Memory tab unchanged**. Confirms "one codebase, both tracks." Live run pending
    a real account (platform.cognee.ai, dev plan `COGNEE-35`) at Day 5.
- **Hero feature:** **Memory Graph as a new top-level view/tab, alongside Projects
  and Learning Room.** A *light* Cognee touch in the Learning Room is the secondary
  demo beat (graph primary).

### The hero feature — "Memory" tab (top-level, like Projects / Learning Room)
A living Cognee knowledge graph of the user's life/projects, with all four ops
visible and demoable:
- **remember()** — agent stores facts/turns/docs into Cognee (reuse existing capture).
- **recall()** — "Ask my memory anything" with **reworded** queries → the before/after
  vs FTS5 money shot.
- **improve()/memify** — "Consolidate" button merges/dedupes; graph visibly tightens.
- **forget()** — "Forget this" → node disappears from the graph live.
- **graph render** — reuse `PathFlowCanvas` / `render_diagram` to draw the graph.

UI wiring: new `webui/src/views/MemoryGraphView.jsx`, a sidebar entry next to
Projects + Learning Room (see `Sidebar.jsx`), backend endpoints for graph data +
the four ops (likely `/api/memory/graph`, `/api/memory/recall`, etc.).

### Non-degradation guarantee (answer to "won't this hurt Namma?")
Off by default (`cognee.enabled: false`) → identical to today. Lazy import,
graceful fallback to SQLite+FTS5 (SQLite stays source of truth → no data loss),
async/off-reply-path ingest (no latency), additive UI only, optional/isolated deps.
**Acceptance test 6.1 (off-state parity) is mandatory before merge.**

### One-week schedule (criteria-mapped)
| When | Focus | Maps to |
|---|---|---|
| **Pre (Jun 25–28)** `[x]` | **DONE** — Cognee runs containerized via MCP (no Namma deps); hybrid Groq+Ollama config proven; `remember`/cognify `status=completed` ~28s; recall ~1s. | Technical Excellence |
| **Day 1 (Jun 29)** `[x]` | **DONE early** — Namma `MCPManager` connects cognee, registers 11 tools (`mcp_cognee_remember/recall/forget/...`); end-to-end remember→recall validated through Namma's own client. | Best Use of Cognee |
| **Day 2 (Jun 30)** `[x]` | **DONE early** — **Memory tab** built (top-level, next to Projects/Learning Room): "Ask my memory" recall + Remember + Forget, via `/api/memory/*` proxying the cognee MCP client. Hero proven: recall answered "…building Namma Agent, …loves Python" from the graph. | Impact, UX |
| **Day 3 (Jul 1)** `[x]` | **DONE** — live **Obsidian-style graph render** in the Memory tab: dark canvas, force-directed physics, glowing nodes, group legend + Forces sliders. Data via `visualize_graph_ui` → parse embedded `nodes`/`links`. Verified: 17–26 entities rendering. | Creativity, Best Use |
| **Day 4 (Jul 2)** `[x]` | **DONE** — Auto-ingestion (chats → background cognify, opt-in `cognee.auto_ingest`) + prompt steering when cognee connected; graph render **theme-adaptive** (light/dark); **light Learning-Room touch** — a completed module's recap is pushed into the Cognee graph (opt-in `cognee.ingest_learning`, default on) so the Memory graph grows from what you study. | Best Use (all 4 ops) |
| **Day 5 (Jul 3)** `[~]` | **Switch BUILT** — Settings → Cognee → **Backend** picks Self-hosted (Track A) or **Cognee Cloud** (Track B); cloud writes `--serve-url`+key (key → gitignored `.env.cognee.cloud`, never config) and upserts the single `cognee` entry, so Memory tab/code are unchanged. Remaining: live verify against a real platform.cognee.ai instance (needs account). | Both tracks |
| **Day 6 (Jul 4)** `[ ]` | Polish UX, README, record 2-min demo video, write submissions. | Presentation |
| **Day 7 (Jul 5)** `[ ]` | Buffer + **submit both tracks**. | — |

> Maps onto Phases 1–4 below (compressed). Phase 5 (deep Learning Room) is
> post-hackathon unless time allows. Phase 0 (MCP path) = optional bonus flex.

---

## 2. Pre-flight findings

### 2.1 Is Namma Agent MCP-capable? — YES (verified)

| Evidence | Location |
|---|---|
| Stdio JSON-RPC 2.0 MCP client (persistent process, proper handshake) | `namma_agent/mcp/client.py` |
| MCP manager — connects servers, registers tools as `mcp_<server>_<tool>` | `namma_agent/mcp/manager.py` |
| Wired into the service under the `mcp` toolset | `namma_agent/service.py` (`_build_mcp`) |
| Config-driven servers | `config.yaml` → `mcp.servers` (+ `config.local.yaml` overlay) |
| Tests pass | `namma_agent/tests/test_mcp.py` (6 passed) |

### 2.2 MCP settings UI — DONE (this session)

The user-requested **MCP category** with **Config** and **Servers** sections is
implemented and browser-verified:

| Piece | Location | Notes |
|---|---|---|
| `ToolRegistry.unregister()` | `core/tools.py` | lets reload drop a removed server's tools |
| `service.mcp_detail()` / `service.reload_mcp()` | `service.py` | config JSON + servers/tools; live reconnect, no restart |
| `GET /api/mcp`, `POST /api/mcp/reload` | `server/api.py` | |
| `fetchMcp`, `reloadMcp` | `webui/src/api.js` | (per-tool toggle reuses existing `toggleTool`) |
| **MCP → Config** tab (JSON editor, Save & reconnect) | `webui/src/components/Settings.jsx` (`McpConfigTab`) | writes `mcp` block to `config.local.yaml` |
| **MCP → Servers** tab (servers + tools, per-tool toggles, Reconnect) | `Settings.jsx` (`McpServersTab`) | toggle = same disable mechanism as Toolsets |

**Consequence for Cognee:** Phase 0 below (MCP-server path) is now a *config
edit*, not a code change.

---

## 3. Anomalies in the proposed plan (must address before/while implementing)

These are flagged in priority order. Each is something that would **degrade,
break, or inflate cost** if the plan were implemented verbatim.

### A. Embedding-provider gap — **HIGH** (would silently break init)
The plan sets `cognee.llm.type: auto` and `cognee.embedding.type: auto`
("inherit from main provider"). But Cognee **requires an embedding model**, and
Namma Agent's default brain is **Anthropic/Claude, which has no embeddings API**.
"Auto-inherit" therefore cannot work for the embedding model whenever the main
provider can't embed (Anthropic, most OpenAI-compat chat endpoints).
**Fix:** embeddings must be configured **explicitly** — OpenAI `text-embedding-3-*`
(needs `OPENAI_API_KEY`), or local `ollama`/`fastembed`. Never silently inherit
embeddings from a chat-only provider. Surface a clear setup error if missing.

### B. Recall on every turn uses an LLM call — **HIGH** (latency + cost)
Plan §6.2 / Phase 2.3 inject a "Cognee context block" into `_build_messages` on
**every turn**. Cognee `recall()` **defaults to `GRAPH_COMPLETION`, an
LLM-powered call**. That adds a full extra LLM round-trip (seconds + tokens) to
every single turn's prompt assembly. The plan's "~50–200 ms" figure only holds
for raw vector retrieval (`CHUNKS`).
**Fix:** for prompt-context injection use the cheap retrieval types
(`CHUNKS` / vector-only), gate it behind relevance, and cache. Reserve
`GRAPH_COMPLETION` for explicit `cognee_recall`/`cognee_insights` tool calls.

### C. Auto-ingest of every turn via full pipeline — **HIGH** (cost explosion)
`features.auto_ingest_turns: true` with the permanent-memory pipeline runs
entity-extraction LLM calls + embeddings on **every** turn. The Cognee report
itself warns `cognify` "makes many sequential LLM calls."
**Fix:** default turns to **session memory** (`remember(data, session_id=...)` —
fast cache, no LLM). Promote to permanent (`cognify`/`improve`) only on explicit
save or during idle consolidation.

### D. API surface mismatch between the two docs — **MEDIUM** (rework)
The integration plan's pseudocode / Appendix B call `cognee.add()`,
`cognee.search()`, `cognee.graph()`, `cognee.extract_entities()`,
`cognee.insights()`, `cognee.improve(scope=...)`. The accurate report documents
the real v1.0 surface as `remember / recall / improve / forget / cognify /
search`. **`cognee.graph()`, `cognee.extract_entities()`, `cognee.insights()` do
not exist as top-level functions**, and `improve()` takes `dataset=/session_ids=`,
not `scope=`.
**Fix:** map the 7 proposed tools onto the *real* API: graph/entity/insight tools
become `recall`/`search` with `query_type` in
`{GRAPH_COMPLETION, CYPHER/NATURAL_LANGUAGE, TEMPORAL, SUMMARIES}` plus the
`cognify` pipeline. Validate every call against the installed version.

### E. Sync ↔ async bridge not addressed — **MEDIUM**
Cognee's API is fully `async`; Namma's tool handlers are **sync**
(`Handler = Callable[[dict], Any]`). The plan's `CogneeClient` even mixes sync and
async method signatures.
**Fix:** the wrapper owns a dedicated background event loop (or uses
`asyncio.run` per call off the request thread) so sync handlers can call async
Cognee without blocking the agent loop. Background ingestion uses the same thread
pattern as `memory_extract.py::capture_async`.

### F. Version pin is wrong — **MEDIUM**
`requirements.txt: cognee>=0.1.0` while current is **1.2.1** and the package is
**Beta** ("APIs may still evolve"). `>=0.1.0` can resolve to an incompatible
release.
**Fix:** pin to a tested minor, e.g. `cognee==1.2.*`, and keep Cognee deps behind
an **optional extra** so the base install stays lean (see anomaly G).

### G. Dependency footprint vs. "lean cloud-only" identity — **LOW/MEDIUM**
Cognee pulls in `lancedb, kuzu, litellm, instructor, pypdf, rdflib, networkx,
tiktoken, sqlalchemy, aiosqlite, …` — a heavy native stack for a project that
prides itself on being lean. Not a blocker (it's opt-in), but the base install
must not carry it.
**Fix:** ship as `pip install namma-agent[cognee]` / a documented separate install;
the running process imports Cognee lazily only when `cognee.enabled: true`.

### H. Kuzu concurrency under background writes — **LOW**
Default graph store (Kuzu) is file-locked and "not suitable for concurrent
multi-agent scenarios." Single-user Namma mitigates this, but concurrent async
background writes can still collide.
**Fix:** serialize Cognee writes through a single worker/queue; or use Neo4j if
concurrency ever matters.

### I. Documentation typos — **TRIVIAL**
"Coggee" (report §3.3 heading), "CoggeeClient" (plan §13.1). Cosmetic.

> **None of A–I change the verdict.** They change the *defaults and order*. The
> corrected plan is Section 4.

---

## 4. Corrected phase plan

> ⚠️ **SUPERSEDED ROADMAP (kept for history).** Phase 0 (MCP path) is **COMPLETE**
> and, per the **Phase 0.6 decision**, is the chosen integration. Phases **1–5
> below describe the *embedded-SDK* path we deliberately did NOT take** (it would
> import `cognee` into Namma's venv — broken on Python 3.14 + a degradation risk).
> They are **not the next steps.** The operative forward plan is the **§1.5
> hackathon schedule** (next = the **Memory graph tab**). Phases 1–5 remain only as
> reference for anyone who later wants deeper in-process integration.

> The integration plan's own Phases 1–5 are sound in spirit and kept below
> (Phases 1–5), **but** a new **Phase 0** is inserted first because the MCP path
> is now nearly free, and the anomaly fixes (Section 3) are folded into each phase.

### Phase 0 — MCP-server MVP (fastest, lowest-risk) — `[x]` COMPLETE (2026-06-26)
**Goal:** Get Cognee memory working through Namma's *existing* MCP client + the new
MCP UI, with **zero new Python deps in Namma's process**.

- `[x]` 0.1 Cognee MCP server runs out-of-process (stdio) via
  `docker run -i cognee/cognee-mcp:main` (its own venv/deps; cognee 1.1.0).
- `[x]` 0.2 Embeddings configured explicitly (anomaly A) — local Ollama
  `nomic-embed-text` via `/api/embed`; extraction = Groq 70B via `/v1`.
- `[x]` 0.3 Registered in **Settings → MCP → Config**, Save & reconnect (after the
  app was restarted to load the new `connect_timeout` code).
- `[x]` 0.4 **Servers** tab shows `cognee` connected with its 11 tools, toggleable.
- `[x]` 0.5 Smoke test passed: `remember`→cognify `status=completed` (~28–44s),
  reworded `recall` returns the fact in NL (~1s).
- `[x]` 0.6 **Decision: MCP path is the chosen integration** (not embedded SDK) —
  forced by Python 3.14 + dependency isolation; gives full depth (all ops) with zero
  risk to Namma. Phases 1–5 below are now *optional* deeper polish, not required.

**Deliverable:** ✅ Cognee semantic/graph memory usable from the agent with **no
Python code changes to Namma** — only config + the MCP UI + per-server timeouts.

### Phase 1 — Foundation (embedded SDK) — `[ ]`
*(Only if Phase 0.6 says deep integration is wanted.)*
- `[ ]` 1.1 Add Cognee as an **optional extra** (anomaly F/G): pin `cognee==1.2.*`.
- `[ ]` 1.2 Add `cognee` config block (anomaly A: **explicit** embedding provider;
  anomaly C: turns → session memory by default).
- `[ ]` 1.3 `namma_agent/core/cognee_client.py` — wrapper with **its own event
  loop** (anomaly E), lazy import, graceful-degradation (returns None/[] if off).
- `[ ]` 1.4 `namma_agent/tools/cognee.py` — register tools mapped to the **real**
  API (anomaly D). Start with `cognee_remember` + `cognee_recall`.
- `[ ]` 1.5 Wire `CogneeClient` into `NammaAgentService` (conditional on
  `cognee.enabled`); register tools under the `memory` toolset.
- `[ ]` 1.6 Turn ingestion → **session memory** (fast, no LLM) on each turn.
- `[ ]` 1.7 Test: remember/recall round-trip; verify graceful fallback when off.

**Deliverable:** Embedded `cognee_remember`/`cognee_recall`, opt-in, no latency on
the reply path, falls back cleanly.

### Phase 2 — Semantic memory — `[ ]`
- `[ ]` 2.1 One-time migration script for existing `facts` + recent `turns`
  (verify against real `db.all_facts()` / sessions API).
- `[ ]` 2.2 Hybrid `cognee_recall` — cheap vector first, FTS5 fallback.
- `[ ]` 2.3 **Cheap** context block in `_build_messages` (anomaly B: `CHUNKS`/
  vector only, relevance-gated, cached — **not** `GRAPH_COMPLETION`, **not** every
  turn unconditionally).
- `[ ]` 2.4 Background entity extraction during idle (anomaly C), not on the turn.
- `[ ]` 2.5 Optionally route `recall_facts`/`search_conversations` through Cognee.
- `[ ]` 2.6 Edge cases: empty/no-match/partial results.

**Deliverable:** Reworded queries find the right memory; no per-turn LLM tax.

### Phase 3 — Knowledge graph — `[ ]`
- `[ ]` 3.1 Configure graph store (Kuzu default; serialize writes — anomaly H).
- `[ ]` 3.2 `cognee_graph_query` via `recall`/`search` with
  `CYPHER`/`NATURAL_LANGUAGE`/graph query types (anomaly D — no `cognee.graph()`).
- `[ ]` 3.3 Cross-session entity linking (Cognee `cognify`).
- `[ ]` 3.4 `cognee_entities` via the cognify/extraction pipeline.
- `[ ]` 3.5 Optional graph-neighbor injection (cheap, gated).
- `[ ]` 3.6 Relationship trees rendered via existing `render_diagram`.

**Deliverable:** "What projects use Python?" / "How does X relate to Y?" answered
from the graph.

### Phase 4 — Advanced features — `[ ]`
- `[ ]` 4.1 `cognee_improve` (real signature `dataset=/session_ids=` — anomaly D).
- `[ ]` 4.2 `cognee_forget` (approval-gated; destructive=True).
- `[ ]` 4.3 `cognee_insights` via `recall(query_type=SUMMARIES/INSIGHTS-equiv)`.
- `[ ]` 4.4 Temporal classification (`TEMPORAL` retrieval).
- `[ ]` 4.5 Importance scoring → keep important facts in prompt.
- `[ ]` 4.6 Multi-user ACL only if/when Namma goes multi-user (else `user_id="default"`).

**Deliverable:** Full 7-tool set; periodic idle consolidation.

### Phase 5 — Learning Room deep integration — `[ ]`
- `[ ]` 5.1 Concept graph per learning topic.
- `[ ]` 5.2 Prerequisite inference from the graph.
- `[ ]` 5.3 Adaptive curriculum from known concepts.
- `[ ]` 5.4 Knowledge-gap analysis via `cognee_insights`.
- `[ ]` 5.5 Cross-topic concept linking.
- `[ ]` 5.6 Learning artifacts (diagrams/sims) become Cognee-searchable.

**Deliverable:** Self-adapting learning paths grounded in the learner's graph.

---

## 5. Configuration (LOCKED: free / self-hosted / Docker dev)

**Chosen stack (2026-06-25):** fully local & free — embeddings + extraction LLM via
**Ollama in Docker**; Cognee's stores are embedded **files** (LanceDB + Kuzu +
SQLite) → **no containers** for storage. Strongest "Best Use of Open Source"
narrative (runs 100% on your machine). For the Cloud track we later swap only the
provider/store env for Cognee Cloud — **same Namma code**.

> **Only Ollama needs Docker.** LanceDB (vectors), Kuzu (graph), SQLite (metadata)
> live under `data/cognee/` as plain files.

```yaml
# config.yaml — Cognee enhanced memory (optional; install: pip install 'cognee==1.2.*')
cognee:
  enabled: false                 # opt-in master switch
  vector_store: { type: lancedb, path: data/cognee/vectors }
  graph_store:  { type: kuzu,    path: data/cognee/graph }
  relational_store: { type: sqlite, path: data/cognee/metadata.db }
  llm:
    type: ollama                 # local extraction LLM (free). Hybrid fallback: a fast
    model: llama3.1:8b           # cloud model (e.g. Groq) if local extraction is too slow.
    endpoint: http://localhost:11434
  embedding:
    type: ollama                 # local, free (anomaly A: NEVER inherit from Claude)
    model: nomic-embed-text      # 768-dim
    endpoint: http://localhost:11434
  features:
    turns_to_session_memory: true   # turns → fast cache, NO per-turn LLM (anomaly C)
    cognify_on: explicit            # explicit | idle  (never every-turn)
    context_block: cheap            # CHUNKS/vector only, relevance-gated (anomaly B)
    entity_extraction: idle         # background, not on the turn
```

Cognee's own env (see `.env.cognee.example`) — verify exact var names against the
installed cognee version:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1:8b
LLM_ENDPOINT=http://localhost:11434
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
DB_PROVIDER=sqlite
VECTOR_DB_PROVIDER=lancedb
GRAPH_DATABASE_PROVIDER=kuzu
ENABLE_BACKEND_ACCESS_CONTROL=false
```

Docker (dev): only Ollama runs persistently (free local embeddings). Extraction is
Groq (cloud). Cognee itself is launched on demand by Namma's MCP client.

```bash
docker compose -f docker-compose.cognee.yml up -d
docker exec namma-cognee-ollama ollama pull nomic-embed-text    # embeddings (~275 MB, free)
docker pull cognee/cognee-mcp:main                              # Cognee MCP server image
```

Then in **Namma → Settings → MCP → Config**, register Cognee (copy `.env.cognee.example`
→ `.env.cognee` first, add your Groq key):

```json
{
  "servers": [
    {
      "name": "cognee",
      "command": ["docker","run","-i","--rm",
                  "--env-file","D:/AGI/.env.cognee",
                  "--add-host","host.docker.internal:host-gateway",
                  "-v","cognee-data:/cognee-data",
                  "cognee/cognee-mcp:main"],
      "enabled": true
    }
  ]
}
```

Save & reconnect → Cognee's tools appear in the **Servers** tab. *(Exact image
entrypoint/env var names must be verified against `cognee/cognee-mcp:main`.)*

**Blocker for runtime:** add `GROQ_API_KEY` / the Groq key into `.env.cognee`
(the user has the key; it's not yet in the repo `.env`).

---

## 6. Acceptance criteria

> Re-framed for the **MCP approach** we shipped (Cognee is never imported into
> Namma — it's an opt-in MCP server), so several criteria are met by construction.

- `[x]` Namma behaves **exactly** as today unless the cognee MCP server is added —
  it's opt-in config, not in `config.local.yaml` by default; **no `cognee` package
  in Namma's venv** at all.
- `[x]` Namma can't be broken by cognee deps (it's containerized; non-degradation
  guarantee holds by isolation).
- `[x]` Reworded recall succeeds — proven ("what language…/what is he building" →
  returned Python + Namma Agent).
- `[~]` Disabling cognee → existing SQLite/FTS5 memory untouched (toggle off in
  Servers tab; built-in memory tools always present). *Verify once both run together.*
- `[x]` Misconfig surfaces clearly (we hit + documented 404/405/validation errors)
  rather than silent failure; troubleshooting table in `docs/COGNEE.md`.
- `[x]` **All four memory-lifecycle ops demoable** — remember, recall, **improve
  (Consolidate → cognify)**, forget. The improve op was added (session buffer →
  consolidate) and **verified live on Cognee Cloud** (consolidate 2/2 → reworded
  recall returned "Kuzu" from the graph).
- `[x]` (Hero-feature criteria — Memory graph tab — built; graph render is
  self-hosted-only and degrades gracefully on Cloud, see Day 5 changelog.)

---

## 7. Changelog

- **2026-06-25** — Document created. Verdict: **implement (with corrections)**.
  Validated both source folders against the live codebase; flagged anomalies A–I.
  **Prerequisite complete:** Namma Agent confirmed MCP-capable and the
  **MCP settings UI (Config + Servers)** built & browser-verified — making Phase 0
  (MCP-server path) a config-only step. Cognee phases 0–5: **not started**.
- **2026-06-25 (later)** — **Hackathon plan locked** (Section 1.5). Decisions:
  both hardware tracks (one codebase + cloud config switch), **Embedded SDK**
  integration, hero = **Memory Graph as a top-level tab** alongside Projects +
  Learning Room (light Learning-Room touch secondary). Added criteria-mapped
  one-week schedule. Confirmed non-degradation guarantee + mandatory off-state
  parity test. Next action: pre-hackathon foundation (install Cognee + CogneeClient
  + remember/recall). **Build not yet started.**
- **2026-06-25 (later 2)** — **Embeddings stack locked: free / self-hosted / Docker.**
  Ollama (Docker) serves `nomic-embed-text` (embeddings, 768-dim) + `llama3.1:8b`
  (extraction); LanceDB/Kuzu/SQLite are embedded files (no containers). Added
  `docker-compose.cognee.yml` + `.env.cognee.example`; updated §5. Confirmed via
  the hackathon page that **no production/deployment is required** (demo + README
  focus) — matches "no production goals yet". Still pending before build: user's
  hardware check (run `llama3.1:8b` locally vs hybrid Groq extraction) + go-ahead
  to pull models / install cognee.
- **2026-06-25 (later 3)** — **Architecture pivot: containerized Cognee via MCP**
  (not embedded SDK). Triggers: dev machine is **Python 3.14.5** (Cognee native
  deps lack 3.14 wheels + pin clashing fastapi/pydantic/sqlalchemy → embedding
  would risk breaking Namma) and **CPU-only 16 GB** (chose Groq extraction over
  local 8B). Cognee now runs as `cognee/cognee-mcp:main`, launched by Namma's
  stdio MCP client via `docker run -i` — full dependency isolation, zero risk to
  Namma. Updated `docker-compose.cognee.yml` (Ollama only + cognee-data volume) and
  `.env.cognee.example` (Groq LLM + Ollama embeddings via host.docker.internal).
  **Blockers handed to user:** (1) start Docker Desktop (launched), (2) add Groq
  key to `.env.cognee`. Next: pull images, probe `cognee-mcp` tool surface, wire
  the MCP Config entry, then build the Memory Graph view.
- **2026-06-26 — Live integration validated against `cognee/cognee-mcp:main`
  (cognee 1.1.0). What works / what's blocked:**
  - ✅ Cognee MCP runs in Docker (27.8 GB image), isolated from Namma. Namma's
    stdio MCP client connects (~18–23 s cold start → needed a longer connect
    timeout). Tools exposed: `remember, recall, forget, cognify_file,
    visualize_graph_ui, list_datasets_json, list_dataset_data_json,
    get_client_info_json, create_dataset_json, upload_file_ui, open_cognee_workspace`.
    **No standalone `improve` tool; no graph-as-JSON tool** (graph viz = Cognee's
    own UI). Implications for the "4 ops" + Memory-graph hero feature noted.
  - ✅ Free local **embeddings via Ollama** `nomic-embed-text` (0.9 s, 768-dim) —
    once two gotchas were fixed: (1) `HUGGINGFACE_TOKENIZER` must be set (Ollama
    engine loads a HF tokenizer; default `None` → crash), (2) cognee's embedding
    *connection test* falsely times out → set `COGNEE_SKIP_CONNECTION_TEST=true`.
  - ✅ Container↔Ollama networking: `host.docker.internal` did NOT work; fix =
    run cognee on `--network agi_default` and use service name
    `http://namma-cognee-ollama:11434`.
  - ✅ Valid `LLMProvider` values: openai, ollama, anthropic, custom, gemini,
    mistral, azure, bedrock, llama_cpp (NO "groq" → Groq = `custom` + endpoint;
    BAML extractor = `openai-generic` + endpoint).
  - ❌ **`cognify` (graph build) fails with Groq:** ~287 s then `status=errored`
    even for one sentence — consistent with Groq **free-tier rate limits** (cognify
    fires many LLM calls) and/or BAML. The litellm/recall path works with Groq; only
    the heavy extraction path fails.
  - 🔑 **Keys actually available:** Groq (`gsk_…`) and OpenCode (`sk-…`,
    OpenAI-compatible aggregator). **No real OpenAI key, no Google key.**
  - **Namma code changes made:** `MCPManager` now honours per-server
    `connect_timeout` (default 60 s) and `call_timeout` (default 120 s) — needed for
    cognee's slow cold start + long cognify. (`mcp/manager.py`.)
  - **Open decision (user's call):** which LLM backend for cognify — fully-local
    Ollama (reliable, best OS-track story, slow → pre-build offline) vs keep Groq
    (rate-limit/BAML debugging) vs OpenCode aggregator. **Awaiting answer.**
- **2026-06-26 (decision) — Extraction LLM = fully-local Ollama** (user's choice).
  Rationale: no rate limits / no cloud key, 100% self-hosted = strongest
  "Best Use of Open Source" story; cognify slowness hidden by pre-building demo
  memory offline. Also discovered `structured_output_framework` defaults to
  **`instructor`** (litellm), NOT BAML — so no BAML config needed; the Groq failure
  was the litellm path hitting free-tier limits. **Final `.env.cognee` is now
  secret-free:** `LLM_PROVIDER=ollama` (llama3.2:3b) + `EMBEDDING_PROVIDER=ollama`
  (nomic-embed-text), reached via `http://namma-cognee-ollama:11434` on
  `--network agi_default`, `COGNEE_SKIP_CONNECTION_TEST=true`,
  `HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5`. Pulling `llama3.2:3b`;
  full local cognify remember→recall test running. Next: confirm cognify
  `status=completed`, then wire the MCP Config entry in Namma + build the Memory view.
- **2026-06-26 (setup + docs) — Fresh-install reproducibility done.**
  - Docker state confirmed present: images `cognee/cognee-mcp:main` (27.8 GB) +
    `ollama/ollama` (8.29 GB); container `namma-cognee-ollama` up; models
    `nomic-embed-text` + `llama3.2:3b` pulled.
  - Added **one-command setup**: [`scripts/setup_cognee.ps1`](scripts/setup_cognee.ps1)
    + [`scripts/setup_cognee.sh`](scripts/setup_cognee.sh) (compose up, pull models,
    pull image, create `.env.cognee`).
  - `.env.cognee.example` rewritten to the fully-local stack (no secrets).
  - **Docs:** new [`docs/COGNEE.md`](docs/COGNEE.md) (setup + usage + the full
    troubleshooting table of gotchas); README "Optional system tools" + Documentation
    links; `namma_agent/requirements.txt` note that Cognee adds **no** pip deps.
  - **Dependencies verdict:** Cognee is containerized → **zero** new Python deps;
    only prerequisite is Docker. Fresh install = unchanged `pip install` + run the
    setup script.
  - **Security:** deleted secret-bearing backups (`.env.cognee*.bak`). User's Groq
    key now lives in the gitignored `.env` as `GROQ_API_KEY` — **unused by Cognee**
    (we went fully local); only relevant if a Groq provider is added for chat.
  - cognify happy-path validation still running on CPU (slow); result pending.
- **2026-06-26 (BREAKTHROUGH) — cognify works; the "slowness" was misconfig, not compute.**
  Root-caused the consistent ~288–305s `status=errored`: it was **instructor
  retry-backoff on two wrong URLs**, never real inference. Two one-line fixes:
  1. **`LLM_ENDPOINT` must end in `/v1`** — cognee's adapter uses an OpenAI client
     and POSTs to `{endpoint}/chat/completions`; without `/v1` → `404 page not found`
     → retries (64+128+128s ≈ 288s).
  2. **`EMBEDDING_ENDPOINT` must be the full `/api/embed` URL** — cognee POSTs the
     payload directly to it (no path appended); bare `…:11434` → root → `405`.
  Also: **`llama3.2:3b` is too weak** for cognee's structured extraction
  (`SummarizedContent` validation errors) — needs Groq 70B or local `qwen2.5:7b`+.
  **PROVEN working config (hybrid):** Groq `llama-3.3-70b-versatile` extraction +
  local Ollama `nomic-embed-text` embeddings → **`remember`/cognify completed in
  ~28s** (mostly the ~20s container cold start). Written to `.env.cognee`;
  `.env.cognee.example` + `docs/COGNEE.md` troubleshooting updated with all four
  gotchas. Native vs Docker Ollama makes no speed difference (CPU-bound; embeddings
  are light). Final remember→recall via Namma's own MCP client: validating.
- **2026-06-26 (FOUNDATION COMPLETE).** End-to-end proven inside Namma:
  - Namma's own client: `remember` (cognify) `status=completed` in **44s**, then
    semantic **`recall` in ~1s** returning the stored fact in natural language.
  - Namma's `MCPManager.register_into` connects cognee and registers **11 tools**
    (`mcp_cognee_remember/recall/forget/cognify_file/visualize_graph_ui/…`) using the
    new per-server `connect_timeout`/`call_timeout`.
  - Test artifacts removed; no secret in tracked files (key only in gitignored
    `.env`/`.env.cognee`).
  - **To enable live:** paste the cognee server JSON in Settings → MCP → Config
    (kept out of `config.local.yaml` by default so Namma's normal startup is
    unchanged — opt-in). **Next: build the Memory graph tab (hero feature).**
- **2026-06-26 (LIVE — PHASE 0 COMPLETE).** User pasted the cognee server into
  Settings → MCP → Config in the **running app**. First attempt failed
  (`handshake failed: server closed the connection`) — root cause: the app process
  was started **25 Jun 23:29**, ~2 h *before* the `connect_timeout` fix landed in
  `manager.py` (26 Jun 01:15), so it used the old 15 s timeout vs cognee's ~23 s cold
  start. **Fix = restart the app** to load current code. After restart: **Cognee
  connects successfully and its tools are live in the running app.** ✅
  Phase 0 done. Foundation + MVP complete and demoable (remember/recall/forget via
  the agent). **Remaining = hero feature: the Memory graph tab** (Days 2–4 in §1.5)
  + Cloud-track config switch (Day 5).
  - **Lesson logged:** code edits to the backend require an app restart to take
    effect (Python has no hot-reload); the frontend was already rebuilt into `dist`.
- **2026-06-26 (MCP UI polish — requested by user).** Implemented + browser-verified:
  1. **Whole-server on/off** in Settings → MCP → Servers — a switch per server that
     persists `mcp.servers[].enabled` and reconnects (a disabled server isn't
     launched at all, vs per-tool toggles). New `service.set_mcp_server_enabled` +
     `POST /api/mcp/server/toggle` + `toggleMcpServer` in api.js.
  2. **Collapsible tools under each server** (chevron, default collapsed).
  3. **Collapsible categories** in the **Toolsets** and **Skills** tabs (default
     collapsed, auto-expand while searching) — shared `Chevron`/`GroupHeader`.
  - **Concurrency fix:** `set_mcp_server_enabled`/`reload_mcp` now guarded by an
     `RLock` (`self._mcp_lock`) — a test exposed that two concurrent toggles
     race on the read-modify-write of `config.local.yaml` and could drop a
     server's flag. Clean sequential toggles verified: both servers preserved,
     persisted correctly, reconnect ~26s.
  - Verified live: Servers/Toolsets/Skills collapse+expand; server toggle off→on
     round-trip; clean reboot with both servers connected (github 26, cognee 11).
  - **Clarified the roadmap** (Section 4 banner): embedded-SDK Phases 1–5 are
     superseded; next real step is the **Memory graph tab** (§1.5).
  - ⚠️ **User must restart their app** to pick up these backend changes
     (the github-flag confusion earlier was a pre-restart stale process).
- **2026-06-26 (HERO FEATURE — Memory tab MVP).** Built + browser-verified the
  **Memory** top-level view (sidebar entry + `/memory` route, alongside Projects &
  Learning Room):
  - **Ask my memory** (recall), **Remember something** (permanent graph build or
    fast session), **Forget** (confirm-gated) — all proxy the connected cognee MCP
    client via new endpoints `GET /api/memory/status`, `POST /api/memory/recall|remember|forget`
    + `service.cognee_tool()`/`memory_status()` + api.js helpers.
  - Graceful: shows "Cognee offline" + a Settings hint when the server's disabled.
  - **End-to-end proven through the new path:** permanent remember → `status=completed`;
    recall answered "Santhosh is building Namma Agent … and he loves Python" from the graph.
  - Files: `webui/src/views/MemoryView.jsx` (new), `App.jsx` (route), `Sidebar.jsx`
    (nav + MemoryIcon), `service.py`, `server/api.py`, `api.js`.
  - **Track docs:** added `Cognee_Track_Plan.md` (phase→track mapping; both tracks
    from one codebase). **Next: live graph render (Day 3) — data-source spike.**
- **2026-06-26 (HERO — Obsidian-style knowledge graph).** Built + browser-verified.
  - **Data source:** `visualize_graph_ui` returns the full graph HTML in
    `structuredContent.html` with embedded `var nodes = [...]` / `var links = [...]`;
    `service.memory_graph()` pulls it (via new `StdioMCPClient.call_tool_raw`),
    extracts both arrays (balanced-bracket parse, multi-match to skip empty
    placeholders), resolves the agent dataset via `get_client_info_json`, and
    returns `{nodes, edges}`. New `GET /api/memory/graph` + `memoryGraph()`.
  - **Renderer:** `webui/src/components/MemoryGraph.jsx` — a dependency-free
    canvas force-directed graph (repel + link springs + gravity + cooling),
    drag/pan/wheel-zoom, hover-highlight neighbours, **always-dark** premium look,
    glow, degree-scaled nodes, labels. Floating panel: **Groups** legend
    (per-type colour + count + toggle), **Display** (labels), **Forces** sliders
    (center/repel/link/distance). Integrated as the hero of the Memory tab.
  - **Two bugs found + fixed:** (1) parser matched an empty `nodes=[]` placeholder
    before the real array → now scans all matches for the first non-empty;
    (2) **`json` wasn't imported** in `memory_graph` (only a local `_json`
    elsewhere) → `_balanced`'s `json.loads` raised `NameError`, swallowed by the
    broad `except` → silent empty graph. Added `import json`. Lesson: avoid
    over-broad `except` that hides `NameError`.
  - Verified: graph renders 17–26 entities / 22–35 links with real labels
    (santhosh, namma agent, python, project…), types coloured, panel functional.
  - **Note:** graph data lives in the cognee container's fs (DATA_DIRECTORY env not
    honoured) → resets on container restart; fine within a session, persistence fix
    still pending. **Next: auto-ingestion (chats → session memory + idle cognify) +
    prompt steering so the graph grows from normal chat; then Cloud track (Day 5).**
- **2026-06-26 (theme-adaptive graph + auto-ingestion).**
  - **Theme:** the Memory graph now follows the app theme — canvas bg + the overlay
    panel / zoom controls / HUD use theme-aware classes (`MemoryGraph.jsx`;
    `MemoryView` passes `dark={dark}`). Verified in BOTH light and dark in-browser.
  - **Auto-ingestion (opt-in `cognee.auto_ingest`, default off):** new
    `core/cognee_ingest.py` `CogneeIngestor` — one background worker + queue running
    permanent `remember` (cognify) one turn at a time (off the reply path, Kuzu-safe).
    `service` builds it (getter → live cognee client); `Agent` accepts
    `cognee_ingestor` and calls `ingest_async(user_input, reply)` right after
    `memory_extractor.capture_async` (`agent.py`). With the flag on + cognee connected,
    **the graph grows from normal chat** — answers the user's earlier question.
  - **Prompt steering:** when `mcp_cognee_recall` is registered, `_build_messages`
    appends a COGNEE MEMORY block telling the model to prefer Cognee recall/remember.
  - Documented in `config.yaml` (`cognee.auto_ingest` / `ingest_replies`).
    **All 476 tests pass.** Next: Cloud track (Day 5) / Learning-Room touch.
- **2026-06-26 (PERSISTENCE FIXED — the big one).** Memory now survives container/app
  restarts (was resetting every restart + "new chat shows empty").
  - **Root cause:** Cognee wrote its DBs to the in-container path
    (`/app/.venv/.../.cognee_system`), not the mounted `cognee-data` volume — my
    earlier env guess (`DATA_DIRECTORY`/`SYSTEM_DIRECTORY`) was wrong. The real
    pydantic-settings fields are **`DATA_ROOT_DIRECTORY` / `SYSTEM_ROOT_DIRECTORY` /
    `CACHE_ROOT_DIRECTORY`** (`cognee/base_config.py`). Plus a second blocker: the
    named volume is **root-owned** but Cognee runs **non-root** → `PermissionError`
    on `os.makedirs`.
  - **Fix:** point those three env vars at `/cognee-data/{data,system,cache}` in
    `.env.cognee`, and pre-create those dirs with write perms (`docker run ... busybox
    mkdir -p + chmod -R 777`). Added to `scripts/setup_cognee.ps1`/`.sh` +
    `.env.cognee.example`; `docs/COGNEE.md` troubleshooting updated.
  - **Verified:** remember in container A → stop A (`--rm`) → recall in a NEW
    container B on the same volume → returned the marker. **PERSISTED ✅.** Cleaned
    the test marker (`forget everything`).
  - **Note on the user's "new chat empty":** also a dataset effect — the model had
    stored the profile into a *custom* dataset on request, while default queries hit
    `namma_agent_memory`. Memory tab + auto-ingest + graph view all use the default
    dataset consistently, so with persistence fixed this is resolved for normal use.
  - **Doc honesty:** the Memory-graph-tab checklist box in `Cognee_Track_Plan.md` was
    stale (`[ ]`) — the tab IS built & verified (table row = DONE); ticked it.
  - ⚠️ **User action:** the running app's cognee container was launched with the OLD
    env (pre-fix) → **restart the app** so it picks up the new `.env.cognee`. The
    volume is already prepped. Then re-store the profile once — it will persist.
- **2026-06-26 (Cognee Settings tab).** Configure the whole integration from the UI —
  no file editing. New **Settings → MCP → Cognee** tab (`CogneeTab` in `Settings.jsx`):
  - **Connection/server:** status, one-click **Register Cognee server** (writes the
    standard docker command + connects), enable/disable toggle, Reconnect.
  - **Behaviour:** `auto_ingest` / `ingest_replies` toggles (instant, no reconnect).
  - **Models & embeddings:** LLM + embedding provider/model/endpoint/key/dims/tokenizer,
    edited live from `.env.cognee`, with presets (Hybrid / Fully-local / OpenAI).
    Save reconnects so changes take effect. API key is **write-only + masked**.
  - **Danger zone:** Forget everything (inline confirm).
  - Backend: `service.cognee_settings()` / `save_cognee_settings()` /
    `register_cognee_server()` (read/write `.env.cognee` without touching os.environ;
    flags → `config.local.yaml`, applied live to the ingestor); endpoints
    `GET/POST /api/cognee/config`, `POST /api/cognee/register`; `api.js` helpers.
  - Verified in-browser: tab loads real `.env.cognee` values (key masked), toggle
    persists to `config.local.yaml`, presets fill fields. **All 476 tests pass.**
- **2026-06-26 (Day 4 — light Learning-Room → Cognee touch).** The secondary demo
  beat: the Learning Room now grows the knowledge graph too, not just the Memory tab.
  - **Hook:** `mark_module_complete` already saves a module `recap` (concepts + the
    running example) to topic memory; it now ALSO queues that recap — prefixed with
    the topic + module titles for good entities — into Cognee via the existing
    background ingestor. So finishing a module makes its concepts appear in the
    Memory graph (cross-linked to the topic), with **zero latency on teaching**.
  - **New switch `cognee.ingest_learning` (default ON):** independent of per-turn
    `auto_ingest`. Safe-on because it only fires on a rare, explicit event (module
    completion) and still no-ops unless the cognee server is connected — so the
    non-degradation guarantee holds (a user without Cognee is unaffected).
  - **Files:** `core/cognee_ingest.py` (`learning_enabled` + `ingest_learning()` +
    shared `_enqueue`); `core/builtins.py` (`register_learning_tools` takes a lazy
    `get_cognee_ingestor`; `_ingest_learning_recap` helper in `mark_module_complete`);
    `service.py` (build ingestor with the flag, thread the getter, expose/save the
    flag in `cognee_settings`/`save_cognee_settings`); `config.yaml` doc;
    `webui/src/components/Settings.jsx` (Behaviour toggle). 
  - **Tests:** new `tests/test_cognee_ingest.py` (5 — gating on/off, disconnected
    no-op, short-text skip, per-turn gate) + 2 in `test_learning_v2.py` (completion
    pushes the recap with topic/module context; completion still works with no
    ingestor). **All 483 tests pass** (476 → 483); webui rebuilt clean.
  - **Next:** Cloud-track config switch (Day 5) — blocked on a platform.cognee.ai
    account (dev code `COGNEE-35`) for the key + instance URL.
- **2026-06-26 (Day 5 — Cloud config switch BUILT).** Track B is now one click, not a
  hand-edited docker command. Same Memory tab + code; only the single `cognee` MCP
  entry differs (Track A self-hosted vs Track B cloud serve mode).
  - **Mechanism:** `register_cognee_server(mode, serve_url, api_key)` upserts the lone
    `cognee` server. Cloud entry = `docker run -i --rm --env-file .env.cognee.cloud
    cognee/cognee-mcp:main --serve-url <instance>` (args after the image hit
    `cognee.serve()` → all ops route to the cloud; cloud owns DB+embeddings, so no
    `--network`/volume). Reusing the name `cognee` keeps `_cognee_client()`, the
    Memory tab, graph, and ingestor unchanged — the "swap one entry" narrative.
  - **Secret hygiene:** the cloud API key is written to a NEW gitignored
    `.env.cognee.cloud` (added to `.gitignore`), **never** into `config.local.yaml`'s
    command array. `cognee_settings()` now reports `mode`/`serve_url`/`cloud_key_set`
    (key masked); blank key on re-register preserves the saved one.
  - **UI:** Settings → MCP → Cognee → new **Backend** section — Self-hosted vs Cognee
    Cloud cards (active one badged), cloud URL + key inputs, Connect / Update / Switch
    buttons, platform.cognee.ai + `COGNEE-35` hint. Validation surfaces "URL required"
    / "key required first time".
  - **Files:** `service.py` (`_cloud_env_path`, generalized env read/write with a
    `path` arg, reworked `register_cognee_server`, cloud fields in `cognee_settings`),
    `server/api.py` (`CogneeRegisterBody` + endpoint passthrough), `webui/src/api.js`
    (`registerCogneeServer(body)`), `Settings.jsx` (Backend section + handlers),
    `.gitignore`, `docs/COGNEE.md` (rewritten Cloud section).
  - **Tests:** new `tests/test_cognee_cloud.py` (6 — local entry, cloud entry +
    key-outside-config, URL/key validation, blank-key preserve, cloud→local upsert).
    **All 489 tests pass** (483 → 489); webui rebuilt clean.
  - **Remaining (user-blocked):** live remember→recall against a real Cognee Cloud
    instance — needs an account at platform.cognee.ai (`COGNEE-35`). The switch +
    plumbing are done and tested; only the credential-bearing live run is pending.
- **2026-06-27 (Full end-to-end test pass + recording prep).** Ran the whole app live
  and prepared it for recording.
  - **Fixed the seeder:** `seed_demo_memory.py` now drives the **running app over HTTP**
    (`/api/memory/*`) instead of spawning its own container — the old version would
    `docker rm -f namma_cognee` and kill the app's connected container (and clash on the
    Kuzu lock locally). Now conflict-free on both backends.
  - **Backend switch verified live:** cloud→local via `/api/cognee/register` reconnected
    in ~33 s leaving exactly **one** `namma_cognee` container (the orphan/lock fix holds).
  - **Self-hosted (Track A) verified end-to-end:** seed (9 facts, cognify completed
    ~6–9 s each via Groq) → graph **59 nodes · 80 edges**; money shot (keyword **0 hits**
    vs Cognee → python / Aria / Kuzu); reworded recall correct; **fresh-chat turn calls
    `mcp_cognee_recall`** (shows as "Recalled from Cognee memory") and answers about the
    user; improve/consolidate grew the graph 70→84 with the new entities (rust/tally).
    App left running + seeded (59·80), `recall_context` off (recall stays visible).
  - **Cloud (Track B) snag:** remember currently fails with a **409 / database
    ProgrammingError** (Cognee Cloud–side), graph shows nodes but 0 edges. Not a Namma
    bug (connect + recall + graph-sync code all proven). Advice in `RECORDING_GUIDE.md`:
    record Track A first, retry the cloud later.
  - `RECORDING_GUIDE.md` updated with the verified money-shot queries + a Track-B note.
- **2026-06-27 (Cognee in real conversation + submission package).**
  - **#3 — "Namma remembers you in a fresh chat."** Strengthened the agent's COGNEE
    MEMORY steering so it reliably + **visibly** calls `mcp_cognee_recall` before
    answering anything about the user (great for "best use" judging). Added an opt-in
    airtight safety net `cognee.recall_context` (default off): for recall-style
    questions (`_RECALL_HINT` regex) the agent proactively pulls the answer from Cognee
    and injects it as a RELEVANT MEMORY block — bounded by a 12s threaded timeout, gated
    so normal chat is untouched. Flag plumbed through `service` → `Agent`, toggleable
    live in Settings → Cognee → Behaviour. (`core/agent.py`, `service.py`, `config.yaml`,
    `Settings.jsx`.) Tests: `test_cognee_recall_context.py` (6). **506 pass.**
  - **Submission package.** `SUBMISSION.md` (the writeup — hook, 4 ops table, money
    shot, mermaid architecture, both-tracks, rubric map), `DEMO_SCRIPT.md` (scene-by-
    scene 2–3 min video + the Track-B re-shoot), and `scripts/seed_demo_memory.py` (a
    reusable, config-driven demo seeder — one coherent story → a rich graph; `--reset`
    flag). These cover the Presentation criterion (previously unbuilt).
- **2026-06-27 (Cloud graph sync + switch-without-restart + the money shot).** Three
  follow-ups the user asked for; all landed + tested.
  - **Cloud graph render now works (Track B).** The earlier blocker — `visualize_graph_ui`
    needs the container's local sqlite, absent in serve mode — is solved by syncing from
    the **Cognee Cloud REST API**. Discovered via probing: `X-Api-Key` auth (NOT bearer),
    and `GET /api/v1/datasets/{id}/graph` returns `{nodes:[{id,label,type,properties}],
    edges:[{source,target,label}]}`. (CYPHER/TRIPLET/INSIGHTS search types are NOT usable
    on the cloud's Postgres graph backend — the dataset graph endpoint is the path.)
    `service._cloud_graph()` fetches the `namma_agent_memory` dataset graph, normalises
    labels (entity name → label; `TextSummary_<uuid>` → type), and returns the same
    `{nodes, edges}` shape; `memory_graph()` routes to it whenever the cognee server is in
    serve mode (`_cognee_serve_url()`). **Verified live: 24 nodes / 26 edges** with clean
    labels (santhosh, cognee cloud, wemakedevs hackathon…). Self-hosted path unchanged.
  - **Switching backends no longer needs a restart (root-caused).** `docker run --rm`
    containers do NOT die when the parent process is killed — they linger and hold the
    Kuzu file lock, so the next local launch failed until a full restart (found a 7-min
    orphan holding `/cognee-data/.../cognee_graph_kuzu`). Fix: name the container
    `namma_cognee`; `StdioMCPClient` force-removes that name on BOTH connect (clear stale)
    and close (kill orphan); `register_cognee_server` also sweeps any cognee container by
    image before reconnecting. (`mcp/client.py` `_docker_container_name`/`_docker_rm`;
    `service._stop_cognee_containers`.)
  - **Priority #2 — the FTS5 money shot.** New `service.memory_compare()` +
    `POST /api/memory/compare` + a **Keyword vs Semantic** panel in the Memory tab: the
    same query run through Namma's original SQLite keyword search (FTS5/BM25) beside
    Cognee's semantic recall — the before/after that justifies the whole integration.
  - **Tests:** +9 (`test_cognee_ops.py` compare ×3, `test_cognee_cloud.py` naming +
    serve-url + docker-name ×5, fixture now stubs Docker). **All 500 pass** (495 → 500);
    webui rebuilt clean. Probe scripts removed; no secrets in tracked files.
  - ⚠️ **User must restart their app** to load these backend changes (Python no hot-reload).
- **2026-06-26 (Track B LIVE-VERIFIED + the 4th op shipped).** The user connected to
  Cognee Cloud from the Settings UI; validated end-to-end + closed the 4-ops gap.
  - **Cloud connection proven** through Namma's own MCP client AND the running app:
    connect ~27s, 11 tools, `remember` (cognify) `status=completed`, and a **reworded
    `recall`** ("which event…") correctly returned **WeMakeDevs hackathon** from the
    cloud graph. Config the switch wrote is exactly right (`--serve-url` + key in the
    gitignored `.env.cognee.cloud`, never in config).
  - **4th op — Improve / Consolidate (priority #1) — BUILT + live-verified.** cognee-mcp
    has no `improve`/`memify` tool, so the op is realised the way Cognee's lifecycle
    does: fast `session` remembers are buffered, then **Consolidate** promotes them
    into the permanent graph via **cognify**. New `service.cognee_remember` (session
    buffering) / `cognee_consolidate` / `cognee_pending`; `POST /api/memory/consolidate`;
    `memoryConsolidate()`; **ConsolidatePanel** in the Memory tab ("N pending →
    Consolidate into graph"). Live on cloud: 2 session facts → consolidate 2/2 in ~11s
    → reworded recall ("which graph database do I prefer?") returned **Kuzu**. Now all
    four ops are visible + demoable.
  - **Track B graph limitation found + handled.** In cloud serve mode
    `visualize_graph_ui` / `list_datasets_json` / `get_client_info_json` fail with
    `sqlite3: unable to open database file` (they read the container's LOCAL sqlite,
    absent when the cloud owns the DB); recall's structured `INSIGHTS`/`CODE` modes
    aren't exposed either (only `GRAPH_COMPLETION` text). So the **force-directed graph
    render is self-hosted-only (Track A)**. `memory_graph()` now detects this and
    returns `cloud_limited` + a clear note; the Memory tab shows a tidy overlay instead
    of a silent empty graph. *(Cloud-track demo: show the graph on local/Track A or the
    Cognee Cloud dashboard; the 4 ops run against the managed cloud.)*
  - **Tests:** new `tests/test_cognee_ops.py` (6 — session buffer, permanent bypass,
    consolidate promote+clear, empty/offline/empty-input). **All 495 pass** (489 → 495);
    webui rebuilt clean. Probe scripts removed; no secrets in tracked files.
  - **Note:** a few demo facts were stored into the user's live cloud during testing
    (a Kuzu preference, a hackathon-presenting note, an earlier probe marker). Harmless;
    can be cleared with Forget-everything if a clean slate is wanted (no per-item delete
    in the MCP).
