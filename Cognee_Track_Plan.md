# Cognee Hackathon — Track Plan (phase → track mapping)

> **Companion to** [`Cognee_Implementation.md`](Cognee_Implementation.md) (the detailed tracker).
> **Created:** 2026-06-26 · **Event:** WeMakeDevs × Cognee, Jun 29 – Jul 5 2026.
> **Purpose:** make crystal clear *which work feeds which prize track*, so nothing
> is built twice and both submissions come from **one codebase**.

---

## The two tracks

| Track                            | Prize     | What it rewards                                 | Cognee backend                                              |
| ----------------------------------| -----------| -------------------------------------------------| -------------------------------------------------------------|
| **A — Best Use of Open Source**  | MacBook   | Building on **self-hosted, open-source** Cognee | Local: cognee-mcp container + Ollama + Kuzu/LanceDB/SQLite  |
| **B — Best Use of Cognee Cloud** | iPhone 17 | Using the **managed Cognee Cloud** platform     | Cloud: same container with `--serve-url` + `COGNEE_API_KEY` |

**The trick:** Namma talks to Cognee only through **MCP tools** (`remember/recall/forget`).
It doesn't care where Cognee runs. So ~95% of the work is **shared** — the only
track-specific difference is one MCP-server config entry (local vs cloud).

---

## Core principle: build once, submit twice

```
                       ┌─────────────────────────────┐
                       │   SHARED (serves BOTH)       │
                       │  • Namma + MCP integration   │
                       │  • Memory graph tab (hero)   │
                       │  • remember/recall/forget    │
                       └──────────────┬──────────────┘
                                      │ swap ONE config entry
                  ┌───────────────────┴───────────────────┐
            Track A (MacBook)                       Track B (iPhone)
        self-hosted .env.cognee                 cloud --serve-url + key
        "runs 100% on my machine"               "managed Cognee Cloud"
```

---

## Phase → track contribution

| Phase / work item                                                                 | Track A (OSS) | Track B (Cloud) | Status                       |
| -----------------------------------------------------------------------------------| :-------------:| :---------------:| ------------------------------|
| **Phase 0** — MCP integration (cognee-mcp via Namma's client)                     | ✅ shared      | ✅ shared        | **DONE**                     |
| MCP Settings UI (Config + Servers, server/tool toggles, collapsible)              | ✅ shared      | ✅ shared        | **DONE**                     |
| Hybrid local config (Groq extract + Ollama embed), all gotchas fixed              | ✅ **core**    | —               | **DONE**                     |
| Setup scripts + `docs/COGNEE.md` (self-hosted reproducibility)                    | ✅ **core**    | —               | **DONE**                     |
| **Memory tab** — "ask my memory" recall + remember + forget (proxy to cognee MCP) | ✅ shared      | ✅ shared        | **DONE (MVP)**               |
| Memory tab — **live Obsidian-style graph render**                                 | ✅ shared      | ✅ shared        | **DONE**                     |
| Auto-ingestion (chats → background cognify, opt-in) + prompt steering              | ✅ shared      | ✅ shared        | **DONE**                     |
| Graph render theme-adaptive (light/dark)                                          | ✅ shared      | ✅ shared        | **DONE**                     |
| Persistent memory (survives restarts) + Settings → Cognee tab (full UI config)    | ✅ shared      | ✅ shared        | **DONE**                     |
| Light Learning-Room Cognee touch (completed-module recaps → graph, opt-in)        | ✅ shared      | ✅ shared        | **DONE**                     |
| **Cloud config switch** — one-click Backend = Self-hosted / Cognee Cloud (`--serve-url` + key) | —    | ✅ **core**      | **BUILT** (live run pending account) |
| Demo video + README + submission (×2, one per track)                              | ✅             | ✅               | Day 6–7                      |

**Reading it:** "shared" rows are built once and carry both submissions. Only two
rows are *track-specific*: the **self-hosted config/docs** (Track A's open-source
proof) and the **cloud switch** (Track B's core). Everything else — especially the
**hero Memory tab** — is identical across both.

---

## Per-track checklist

### Track A — Best Use of Open Source (MacBook) — mostly done
- [x] Self-hosted Cognee running (cognee-mcp container, no cloud).
- [x] Free local embeddings (Ollama) + the open-source stack (Kuzu/LanceDB/SQLite).
- [x] All four ops usable from the agent.
- [x] One-command setup + docs so judges can reproduce it.
- [x] Memory graph tab (shared) — Obsidian-style graph + recall/remember/forget, theme-adaptive, **persistent** across restarts. (Built & verified.)
- [x] Memory used in real conversation — visible `mcp_cognee_recall` in chat + opt-in
      airtight recall injection (`cognee.recall_context`); fresh-chat "remembers you" beat.
- [x] Submission package drafted — `SUBMISSION.md`, `DEMO_SCRIPT.md`, `RECORDING_GUIDE.md`, `scripts/seed_demo_memory.py`.
- [x] **Full end-to-end test pass done (self-hosted)** — graph (59·80), money shot
      (keyword 0 vs Cognee python/Aria/Kuzu), reworded recall, fresh-chat recall (agent
      calls `mcp_cognee_recall`), improve/consolidate (graph grows), backend switch
      (one clean container). App seeded + running, ready to record.
- [ ] Record the demo video framed on "self-hosted, private, runs on your laptop."

### Track B — Best Use of Cognee Cloud (iPhone)
- [x] Cloud connection mechanism verified (`--serve-url`/`COGNEE_API_KEY`).
- [x] **Config switch built** — Settings → Cognee → Backend → Cognee Cloud: one-click
      registers the `cognee` entry in serve mode (key → gitignored `.env.cognee.cloud`,
      never config); switch back to self-hosted in the same panel. Tested offline (6 tests).
- [x] Signed up + connected — user added the cloud instance from the Backend panel; tools appear.
- [x] **Confirmed live:** remember→recall AND the improve/consolidate op against the cloud
      (reworded recall returned the stored fact from the cloud graph).
- [x] **Graph render works on cloud too** — serve mode can't run `visualize_graph_ui`, so
      Namma syncs the graph from the Cognee Cloud REST API (`/api/v1/datasets/{id}/graph`)
      and renders the same canvas. Verified live: 24 nodes / 26 edges from the cloud.
- [ ] Demo video framed on "managed Cognee Cloud, zero local infra."

---

## Timeline (from §1.5 of the tracker)

| Day | Work | Track served |
|---|---|---|
| **Pre / Day 1** | Phase 0 + MCP UI | both — **DONE** |
| **Day 2–3** | **Memory graph tab** (hero) | both |
| **Day 4** | Learning-Room touch; polish all 4 ops in the UI | both |
| **Day 5** | Cloud config switch + verify | B |
| **Day 6** | Two demo videos + two READMEs + submissions | A & B |
| **Day 7** | Buffer + submit both | A & B |

---

## Current position

**Shared foundation + Track A core + the full Memory tab (recall, remember, forget,
and the Obsidian-style knowledge-graph render) + auto-ingestion + the light
Learning-Room touch (completed-module recaps grow the graph) are DONE and live.**
Cognee is now exercised across the whole app — normal chat AND the Learning Room
both feed the graph — which directly lifts the "Best Use of Cognee" score. **Track B
(Cloud) is also built:** the Backend panel switches the single `cognee` entry between
self-hosted and Cognee Cloud (`--serve-url` + key), tested offline. The only thing
left is the **live cloud run**, blocked on a platform.cognee.ai account (dev code
`COGNEE-35`) for the key + instance URL — then record the two demo videos.
