# Project Friday — Cloud Integration & Architecture Guide

> **Purpose:** Map every decision required to ADD cloud API support to FRIDAY
> while KEEPING and SIMPLIFYING local inference as a first-class mode.
>
> **Critical correction from v1 of this document:**
> This is NOT about "converting FRIDAY from local-model to cloud-inference."
> The end state is a DUAL-PROVIDER architecture where users choose between
> cloud (for speed/quality) and local (for offline/privacy/air-gap) with
> a single config toggle.
>
> The simplification work described here (removing intent recognizer,
> consolidating stores, stripping the planning engine, etc.) benefits BOTH
> modes. A 3,295-line regex parser is dead weight whether your model runs
> on a local GGUF or an API endpoint.
>
> Every "remove" step in this document should be read as: "Remove this
> compensating infrastructure. It was needed for the weak 4B model. It is
> no longer needed for ANY capable model — cloud OR local."
>
> Each section explains **what** to change, **why** the current design is
> over-engineered (for either provider), and **how** to do it right.

---

## Table of Contents

1. [The Core Problem: FRIDAY's Architecture Was Born from Constraint](#1-the-core-problem-fridays-architecture-was-born-from-constraint)
2. [Phase 0: Kill the Infrastructure Weight](#2-phase-0-kill-the-infrastructure-weight)
3. [Phase 1: Unify the Model Layer](#3-phase-1-unify-the-model-layer)
4. [Phase 2: Replace the Routing Stack with Prompt Engineering](#4-phase-2-replace-the-routing-stack-with-prompt-engineering)
5. [Phase 3: Replace the Planning Engine with Tool Calling](#5-phase-3-replace-the-planning-engine-with-tool-calling)
6. [Phase 4: Simplify Memory by 80%](#6-phase-4-simplify-memory-by-80)
7. [Phase 5: Consolidate Stores (6 → 1 or 2)](#7-phase-5-consolidate-stores-6--1-or-2)
8. [Phase 6: The Delegation & Sub-agent Problem](#8-phase-6-the-delegation--sub-agent-problem)
9. [Phase 7: Remove the Desktop GUI, Own the Terminal](#9-phase-7-remove-the-desktop-gui-own-the-terminal)
10. [Phase 8: Security, Consent & Guardrails](#10-phase-8-security-consent--guardrails)
11. [What Stays — FRIDAY's Real Value](#11-what-stays--fridays-real-value)
12. [The Target Architecture (Diagram)](#12-the-target-architecture)
13. [Resume Worthiness Assessment](#13-resume-worthiness-assessment)

---

## 1. The Core Problem: FRIDAY's Architecture Was Born from Constraint

**The honest truth:** FRIDAY's architecture is a direct consequence of the 0.8B/4B
GGUF models it was built for. The models are too weak to:

- Route intent reliably (hence the 3,295-line `IntentRecognizer`)
- Plan tool calls (hence the `QwenPlanner`, `PlannerEngine`, `ReplanController`)
- Maintain conversation state (hence the `MemoryBroker` + `ContextStore` + 5 facades)
- Understand context references (hence the `ContextResolver`)

So you built infrastructure to compensate. Every layer you added was rational
for the 4B model you were running. But a cloud model (DeepSeek V4, Claude Sonnet,
GPT-4o, Gemini 2.5 Pro) can do ALL of this natively.

**The result:** FRIDAY's architecture, when hooked to a cloud API, would deliver
worse performance than a 500-line Python script that just pipes user input to the
model and routes the tool call response back. The infrastructure wouldn't help —
it would only add latency and token waste.

---

## 2. Phase 0: Kill the Infrastructure Weight

### What to remove entirely

These files/modules were built to compensate for a weak local model. A cloud
model handles their job better and faster. Remove them:

| Component | Lines | Why Remove |
|-----------|-------|------------|
| `core/intent_recognizer.py` | 3,295 | A capable model can classify intent with a single prompt. You're maintaining 3,295 lines of regex for something any half-decent LLM does in one inference call. |
| `core/planning/intent_engine.py` | 112 | Replaced by model tool-calling. |
| `core/planning/planner_engine.py` | 247 | Replaced by model tool-calling. |
| `core/planning/qwen_planner.py` | 363 | Built specifically for Qwen3. A capable model doesn't need a meta-planner. |
| `core/planning/replan_controller.py` | 265 | Capable models don't hallucinate tool call structure this badly. |
| `core/planning/workflow_coordinator.py` | 73 | Replaced by model-driven tool orchestration. |
| `core/routing_tuner.py` | - | Routing tuning was a hack for unreliable intent detection. |
| `core/lexical_router.py` | - | Fuzzy matching for a weak model's failure cases. |
| `core/embedding_router.py` | - | Semantic fallback before the LLM call. A capable model IS the LLM call. |
| `core/mixture_of_agents.py` | - | Local MoA architecture. Irrelevant with a single strong model. |
| `core/task_graph_executor.py` | 441 | DAG-based parallel execution. A capable model can sequence tool calls itself. |
| `core/workflow_orchestrator.py` | 1,042 | LangGraph workflows for a model too weak to follow simple state machines. |
| `core/safety/website_policy.py` | - | Capable models have their own safety filters. Yours is a second opinion that overrides better judgment. |
| `core/reasoning/model_router.py` | - | Two-model architecture (chat + tool) collapses to one. |
| `core/reasoning/route_scorer.py` | - | Determines which model to use. Answer: the one cloud model. |
| `core/reasoning/agentic_services/` | 200+ | Two extra "modes" (research, focus) that a capable model handles inline. |

**Total lines removed: ~7,000+.**

### What to keep but drastically simplify

| Component | Keep | Simplify |
|-----------|------|----------|
| `core/tool_catalog.py` (243 lines) | Essential | Cut the auto-generated JSON cache layer. Static tool definitions are fine. |
| `core/prompt_builder.py` (101 lines) | Essential | Simplify to 30 lines — just format user input + system prompt. |
| `core/model_manager.py` (192 lines) | Keep | Rewrite to manage cloud provider config instead of GGUF model paths. |
| `core/response_finalizer.py` | Keep | Still useful for post-processing model output. |
| `core/turn_manager.py` (139 lines) | Keep | Thin wrapper that invokes model, routes tool calls. |
| `core/router.py` (1,113 lines) | **Replace** | Go from 1,113 lines to ~200 — just match tool name and invoke. No intent recognition, no fallback chains, no embedding layer. |

---

## 3. Phase 1: Unify the Model Layer

### Current state

```yaml
models:
  chat:
    path: models/Qwen3.5-0.8B-Q4_K_M.gguf
    n_ctx: 8192
    temperature: 0.7
  tool:
    path: models/Qwen3.5-4B-Q4_K_M.gguf
    n_ctx: 8192
    temperature: 0.1
```

Two models, different configurations, different inference paths, sync model
loading, CPU threading, local GGUF management, an inference-lock system
(threading.Lock on every model call), and a "tool model" that gets called
as a sub-LLM to decide routing.

### Target state

```yaml
provider:
  mode: cloud           # "cloud" | "local" | "auto"

  cloud:
    name: openai_compat
    base_url: https://api.opencode-zen.com/v1
    model: deepseek/deepseek-v4-flash-free
    # Or pick any provider:
    # model: anthropic/claude-sonnet-4
    # model: openai/gpt-4o-mini
    # model: google/gemini-2.5-pro-exp-03-25
    max_tokens: 4096
    temperature: 0.3

  local:
    model: models/Qwen3.5-4B-Q4_K_M.gguf
    n_gpu_layers: 0
    context_length: 8192
    max_tokens: 2048
    temperature: 0.3
```

**Why:**
- One model (cloud or local) is smarter than two weak models working together.
- In cloud mode: no model preloading (save seconds on startup), no inference locks
  (the API handles concurrency), the model handles tool calling natively.
- In local mode: same simplified architecture, still uses GGUF inference, but now
  with a clean provider abstraction instead of dual-model configs.
- In "auto" mode: try cloud first, fall back to local on network failure.
- The config string change between cloud providers is instant.
- The config switch between cloud and local is a single line change.

### The `/no_think` problem

FRIDAY appends `/no_think` to every tool model prompt to suppress chain-of-thought
on latency-critical calls. This is a Qwen3-specific hack. A cloud model like
DeepSeek V4 or Claude Sonnet handles tool calls efficiently without this
workaround. Remove the `/no_think` append entirely.

---

## 4. Phase 2: Replace the Routing Stack with Prompt Engineering

> **Note:** This simplification benefits BOTH cloud and local modes. Even with
> a 7B+ local model that supports function calling, the new stack applies.
> The current routing pipeline compensates for a SPECIFIC weak model (0.8B+4B
> Qwen3.5 GGUF), not for local models in general.

### Current routing pipeline

```
User Input
  → STT typo normalization (text_normalize.py)
  → IntentRecognizer.plan() [3,295 lines of regex]
    → Splits compound clauses
    → Matches each against 40+ tool parsers
    → Returns action plan or []
  → EmbeddingRouter (semantic fallback)
  → LexicalRouter (fuzzy STT-typo fallback)
  → Tool model inference (4B Qwen3.5)
  → Fallback to chat model (0.8B Qwen3.5)
```

Each turn hits 3-5 of these layers. The 4B model call is the most expensive,
but even the regex layers add measurable latency (compiling/resolving patterns
against a 3,295-line file).

### Target routing pipeline

```
User Input
  → API call with system prompt + tools schema
  → Model responds with tool_use or text
  → If tool_use: execute tool, feed result back, loop
  → If text: return response
```

That's it. **Three steps, one LLM call per turn.**

**Why this works:**
- A cloud model with tool-calling (OpenAI-style function calling,
  Anthropic's tool_use, Gemini's function_declaration) does routing AND
  planning in a single inference step.
- The model decides which tool to call AND supplies the arguments.
- You get structured JSON output for free — no `tool_json_response: true` hack.
- The model handles uncertainty by asking the user directly (no custom
  `Clarify` capability needed).

### What the new router.py looks like (target: ~200 lines)

```python
class Router:
    def route(self, text: str, session_id: str) -> str:
        # 1. Build context + system prompt
        messages = self._build_messages(text, session_id)

        # 2. Call model with tool definitions
        response = self.llm.create(messages, tools=TOOL_DEFINITIONS)

        # 3. Handle tool calls
        if response.tool_calls:
            for call in response.tool_calls:
                result = self.execute_tool(call.name, call.args)
                messages.append({"role": "tool", "content": result})
            # Let model synthesize final answer
            response = self.llm.create(messages)

        return response.content
```

No intent recognizer. No embedding layer. No lexical fuzzy fallback. No
two-model hierarchy. No `_plan_actions()`. No `_find_best_route()`. No
`_continue_active_workflow()`. No `_finalize_response()` chain. No
`_should_use_tool_model()` heuristics. No `_is_tool_oriented_text()` guesswork.

---

## 5. Phase 3: Replace the Planning Engine with Tool Calling

### Current system

FRIDAY has a 5-layer planning stack:

1. `IntentEngine.classify()` — determine if this is a tool call or chat
2. `PlannerEngine.plan()` — build a `ToolPlan` with steps
3. `ContextResolver.try_rescue()` — second-guess the plan when pronouns are
   involved (Track 1.4)
4. `PlanValidator.validate()` — third-guess the plan (safety)
5. `PlanRepair.try_repair()` — fourth-guess the plan (if invalid)
6. `TurnOrchestrator` — the outer coordinator that runs steps 1-5

Each layer exists because the small local model couldn't reliably produce
well-formed tool calls on the first try. The `QwenPlanner` exists because
the 4B model needed a meta-prompt and JSON output constraints to produce
anything usable.

### Target system

```
System prompt:
  "You are an AI assistant with access to tools.
   When the user makes a request, decide if a tool is needed.
   If so, call it with the correct arguments.
   If not, answer from your knowledge."
```

That's the plan engine. It's the model tool-calling API. No plan validation,
no plan repair, no second-guessing. If the model calls a tool with bad args,
the error response feeds back and it fixes itself.

**But what about pronouns?** The `ContextResolver` was built to handle "what's
in it?" after the user said "read my.txt". With a cloud model, this is handled
by including recent context in the message history. The model tracks the last
file it read and answers the follow-up. It's a solved problem — every chat
application does this with message history, not with a dedicated pronoun
resolution engine.

**The PlanValidator / PlanRepair** layer was a smart hack for the 4B model.
Today, it's dead code that adds latency and complexity. The cloud model either
produces valid tool calls or the API rejects them — you don't need to validate
before sending.

---

## 6. Phase 4: Simplify Memory by 80%

### Current memory architecture

FRIDAY has **6 memory/storage subsystems**:

| Store | Backend | Purpose |
|-------|---------|---------|
| `MemoryStore` | ChromaDB + SQLite | Vector embeddings + metadata |
| `SemanticMemory` | SQLite (aliased via MemoryStore) | Key-value facts |
| `MemoryFacade` | wraps SemanticMemory | Single write path facade (Track 2) |
| `MemoryBroker` | aggregates all stores | Context bundle builder |
| `Mem0` | REST service (port 8181) | Long-term memory (parallel store!) |
| `EpisodicMemory` | SQLite | Turn history |
| `ProceduralMemory` | SQLite | How-to knowledge |
| `PersonaManager` | YAML + SQLite | User profile facts |
| `ContextStore` | SQLite (16 tables) | Original monolithic store |

**Problems:**
- A single user fact ("My name is Tricky") is stored in 4+ places
- The Track 2 `MemoryFacade` exists specifically to deduplicate writes
  across these stores — because the previous architecture wrote the same
  fact 6 times with different normalizations
- Mem0 runs as a separate server process on port 8181, adding operational
  surface area, yet is IGNORED by the facade (the docstring literally says
  "the Mem0 store we ignore")
- ChromaDB requires a sentence-transformer model loaded in memory (~90MB)
  just to do semantic search across ~200 user facts
- `ContextStore` is being "extracted into 5 sub-stores" in a Track 5
  refactoring that adds more layers instead of removing them

### Target memory architecture

```
One SQLite database. Three tables:

1. sessions — turn history + session metadata
2. facts — key-value facts about the user (with vector embedding if needed)
3. artifacts — working state, file references, plans
```

**No ChromaDB.** No sentence-transformers. No Mem0 server. No MemoryFacade.
No EpisodicMemory. No ProceduralMemory. No PersonaManager.

**Why this works with a capable model:**

- **User facts:** Extract them from conversation with a single prompt.
  Model: "What facts about the user can you identify from this conversation?"
  No need for a separate embedding pipeline — the model already understands
  the text semantically.
- **Memory retrieval:** Use the model to decide what to recall. Instead of
  ChromaDB vector search, use FTS5 (built into SQLite) for keyword matching,
  and let the model's own context window handle relevance.
- **Session history:** The API's message list IS your memory. Truncate with
  a summarization call when context gets large.
- **No parallel stores:** If the model knows something, it says so. If it
  doesn't, it asks. You don't need 4 fallback stores to handle the case
  where one doesn't have the answer.

**When to use RAG for real:** Only if you're indexing external documents
(PDFs, codebases, documentation) that don't fit in context. For user memory,
the model's context window (128K+ with most modern models, cloud or local 7B+) is enough.

---

## 7. Phase 5: Consolidate Stores (6 → 1 or 2)

### Current state

```python
self.session_store = self.context_store._session_store
self.audit_store = self.context_store._audit_store
self.workflow_store = self.context_store._workflow_store
self.memory_store = self.context_store._memory_store
self.knowledge_graph_store = self.context_store._knowledge_graph_store
self.goal_store = self.context_store._goal_store
self.app_index_store = AppIndexStore(self.context_store.db_path)
self.file_index_store = FileIndexStore(self.context_store.db_path)
```

Eight store objects, each owning its own slice of a 16-table SQLite schema.
The `ContextStore` originally held 16 tables and is being split into sub-stores
in Track 5.1 — which means **more code, more files, more abstractions**.

**Why this was built:** The isolation was meant to keep concerns separated,
but it resulted in 8 objects that all wrap the same SQLite database. You
can query any table from any store — the separation is purely notional
overhead. Every cross-cutting concern (read facts AND session history for a
context bundle) requires diving through the facade layer.

**This simplification benefits BOTH modes.** Whether using cloud or local,
8 stores for one database is 7 too many.

### Target

```python
class Database:
    """Single SQLite connection with all tables."""
    sessions: SQLTable
    turns: SQLTable
    facts: SQLTable
    tools: SQLTable
    audit: SQLTable
```

One store object. One connection. Every query can JOIN across any concern.
The model generates the SQL if needed — or just use simple key-value lookups
driven by the model's decisions about what to read.

**The KnowledgeGraphStore and GoalStore** are good examples of what happens
when architecture runs ahead of necessity. You built an entity-relationship
knowledge graph for a local assistant. Unless FRIDAY is managing hundreds of
related entities across sessions, a simple facts table with a `category` column
handles everything the graph does.

---

## 8. Phase 6: The Delegation & Sub-agent Problem

### Current delegation system

FRIDAY has 4 delegation mechanisms running in parallel:

1. **`Delegate` class** (83 lines) — background thread router-subprocess
2. **`DelegationManager`** — formal sub-agent system for personas
3. **`MixtureOfAgents`** — multi-model voting ensemble
4. **`ResearchAgent` (7 files, 3,510 lines)** — full sub-agent for research

None of these are delegation in the modern sense. They're threading wrappers
over the same router. FRIDAY doesn't spawn independent agents with their own
tools, context, and model calls — it runs the same CommandRouter in a
background thread.

### Target: real sub-agent delegation

A cloud model can delegate to sub-agents using tool calling itself:

```python
# Model calls this tool when it decides a task needs a sub-agent
tools: [{
    "name": "delegate_task",
    "description": "Run a task in a sub-agent with its own tools",
    "parameters": {
        "goal": "Task description",
        "toolsets": ["file", "terminal", "web"],
        "context": "Relevant background info"
    }
}]
```

This is what Hermes Agent's `delegate_task` does — it's a tool the model calls
when it recognizes a task that benefits from isolation. FRIDAY predetermines
when delegation happens (research vs. focus mode) based on intent classification.
A cloud model can decide this dynamically.

**Remove:**
- `Delegate` class (threading hack, no real isolation)
- `MixtureOfAgents` (useless with one strong model)
- `ResearchAgent` module (the cloud model does research inline, or calls
  a web-search tool and reads results)
- `ResearchPlanner` / `ResearchMode` / `FocusMode` (one strong model
  doesn't need 3 separate "modes")

---

## 9. Phase 7: Remove the Desktop GUI, Own the Terminal

### Current GUI

PyQt6 HUD at 2,878 lines with:
- Conical gradients, glow effects, animated rings
- Audio device selector combo box
- Scrollable transcript window
- Theme toggling
- Voice activity display
- Live event stream

**The honest assessment:** It's impressive for a desktop app but wrong for
this project. A CLI agent needs:
- Fast startup (the GUI adds ~2s to boot)
- Terminal-native output rendering
- Ability to pipe commands and compose with other tools

FRIDAY already has a `--text` mode for CLI. But the CLI is more of an
afterthought — the core architecture assumes the GUI exists.

### Target: CLI-first

- Move all output to stdout with terminal rendering
- Use prompt_toolkit or Textual for interactivity if needed
- Remove PyQt6 dependency entirely (saves ~50MB of libs_backup)
- The HUD's event stream can become a terminal status bar
- Audio device selection becomes a `--mic` flag, not a dropdown

**The modules/voice_io (12 files, 4,088 lines)** is FRIDAY's biggest
module. Voice is important. But 4,000+ lines for STT/TTS/voice control
with fallback paths, barge-in detection, clap detection, noise VAD, audio
device enumeration, Vosk model management, and whisper config... this is
complexity that pays off only when voice is the *primary* interface.

For a cloud API agent, voice can be:
- A separate thin CLI: `friday --listen` that streams mic input, sends
  to cloud STT, pipes text to model, reads response via cloud TTS
- Not bolted into every turn of the conversation loop

---

## 10. Phase 8: Security, Consent & Guardrails

### Current security

FRIDAY has:
- `ToolGuardrails` — tool-level safety checks
- `URLSafety` — URL whitelisting
- `PathSecurity` — file path traversal checks
- `WebsitePolicy` — web access policy
- `ConsentService` — user consent tracking
- `PermissionService` — tool permission model

**Problem:** These are good but they're additive — each one is another
layer the model can't reason about but the code must enforce. With
a capable model that respects prompt-level safety instructions, many
of these become redundant or should be handled through the system prompt.

### Target

```
System prompt rules (when they're static and clear):
- "Never execute destructive file operations without confirmation"
- "Ask before accessing external URLs"
- "Do not read files outside /home/user"

Code-level policies (when rules aren't enough):
- PathSecurity (filesystem access is code-enforceable)
- ConsentService (user interaction pattern)

Remove:
- ToolGuardrails (the model follows tool descriptions)
- URLSafety (use prompt rules + one-line URL sanity check)
- WebsitePolicy (replaced by model judgment)
```

**The consent guardrails** are FRIDAY's one clear win over most agents:
the `ask_first` permission mode and the `confirm_low`/`confirm_high` routing
thresholds are genuinely well-thought-out UX for local agents. Keep the consent
flow. Just implement it as 50 lines of prompt injection + yes/no pattern
matching instead of a pipeline of guardrail modules.

---

## 11. What Stays — FRIDAY's Real Value

Not everything should be deleted. FRIDAY has real engineering in these areas:

### Keep and polish

**1. Persona System (YAML-based, clean separation)**
The persona YAML files are a genuinely good design. System prompt configuration
outside code. Tone, dos/donts, verbosity — all runtime-configurable. Modern
agents (Claude Code with CLAUDE.md, Cursor with .cursorrules) are converging on
exactly this pattern. Keep it. Extend it.

**2. Event Bus**
`core/event_bus.py` — a simple pub/sub for internal events. This is good
architecture. Extensions subscribe, the core publishes, no coupling. Keep it.

**3. Extension System (`core/extensions/`)**
The loader/protocol/decorators pattern for plugins. Clean, testable, and lets
third-party features wire in without touching core code. Keep the pattern,
simplify the adapter layer (the protocol/decorator/adapter/loader 4-file split
is over-engineered for what it does).

**4. YAML Workflow Templates**
The workflow YAML files (file_create_with_content.yaml, dns_enum_owned_domain.yaml)
are a good idea for codifying multi-step procedures. For a cloud model, make
these optional — the model can follow the template or improvise.

**5. The TTS/STT Integration**
12 files and 4K lines, but the voice pipeline itself (wake word → STT →
process → TTS) is genuinely complete. For the dual-mode architecture, add
cloud STT/TTS (Whisper API, ElevenLabs/OpenAI TTS) as the default and keep
local whisper-tiny + Piper as offline fallback. Simplify the pipeline from
4K lines to ~800.

**6. The Security Modules (SecurityTools)**
The nmap wrappers, port scanning, network inventory — these are real value
for a Kali Linux-based assistant. Keep them as tools the cloud model can
call when needed. They're self-contained.

**7. The Tests**
155 test files, 29K lines. Unusual for a solo project. The tests are one of
FRIDAY's strongest differentiators and you should maintain this investment.

**8. The Scheduler (`core/scheduler.py`)**
Background task scheduling, cron-style. Useful in any agent. Keep it.

---

## 12. The Target Architecture

```
┌─────────────────────────────────────────────────┐
│                   FRIDAY Agent                    │
├─────────────────────────────────────────────────┤
│                                                   │
│  ┌──────────────┐    ┌──────────────────────┐    │
│  │  System Prompt  │    │   Tool Definitions    │    │
│  │  (Persona YAML) │    │   (static JSON list)  │    │
│  └──────┬───────┘    └──────────┬───────────┘    │
│         │                       │                │
│         └───────┬───────────────┘                │
│                 │                                │
│         ┌───────▼───────┐                        │
│         │   LLM Provider  │                    │
│         │   (Dual-mode)   │                    │
│         │   ├─ Cloud API   │                    │
│         │   └─ Local GGUF  │                    │
│         └───────┬───────┘                        │
│                 │                                │
│         ┌───────▼───────┐                        │
│         │  Tool Executor │                        │
│         │  + Result Loop │                        │
│         └───────┬───────┘                        │
│                 │                                │
│   ┌─────────────┼─────────────┐                  │
│   │             │             │                  │
│   ▼             ▼             ▼                  │
│ File    Security   Browser   Voice   ...tools    │
│ Tools    Tools   Auto (Selenium)  (API)          │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │  Database (single SQLite)                 │    │
│  │  ├─ sessions + turns                     │    │
│  │  ├─ user facts (FTS5)                    │    │
│  │  └─ audit log                            │    │
│  └──────────────────────────────────────────┘    │
│                                                   │
│  ┌──────────────────────────────────────────┐    │
│  │  Event Bus + Extension Loader + Scheduler │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Lines of code target

| Layer | Current (est.) | Target |
|-------|---------------|--------|
| Core routing + planning | ~10,000 | ~1,500 |
| Memory + stores | ~5,000 | ~1,500 |
| Module system | ~25,000 | ~8,000 |
| GUI | ~3,300 | 0 (CLI only) |
| Voice pipeline | ~4,000 | ~800 |
| Tests | ~29,000 | ~15,000 |
| **Total** | **~76,000*** | **~27,000** |

* Excluding the .venv (351K lines total, ~76K project code)

A 64% reduction in code for a system that performs better in every dimension.
That's not a bug — it's the sign of architecture that was compensating for
weak hardware rather than enabling strong models.

---

## 13. Resume Worthiness Assessment

You asked. Here's the honest answer.

### Yes, it's resume-worthy — if you frame it right

**What NOT to lead with:**
- "Built a 76,000-line local AI assistant"
- "6-store memory architecture with ChromaDB, FTS5, and semantic search"
- "3,295-line regex intent recognizer"
- "Built my own planning engine, workflow orchestrator, and DAG executor"
- "100 commits in 7 days"

These sound like a developer who solves problems by adding more code rather than
finding the right abstraction. The 100-commits-in-7-days cadence shows sprinting
rather than engineering discipline (I see commits at 10:55 PM, 9:48 PM — you
were rushing).

**What to lead with:**
- "Designed and built an end-to-end voice-enabled AI assistant with 27 integrated
  capabilities (browser automation, security scanning, smart home control, code
  execution, document intelligence, research agent, and 22 more)"
- "Implemented a YAML-based persona system that separates agent identity from
  code, inspired by production patterns used in Claude Code and Cursor"
- "Wrote 155 automated tests (29K lines) for an AI agent — stronger test
  coverage than most open-source agent projects"
- "Built a complete voice pipeline (wake word → STT → NLU → TTS) that works
  entirely offline"
- "Architected a plugin system with event bus allowing third-party extensions
  to wire into any point in the conversation lifecycle"
- "Self-taught: learned PyQt6, system-level audio on Linux, ONNX runtime
  deployment, LangGraph, and ChromaDB during implementation"

**The hard truth about resume value:**

FRIDAY is more impressive as a *learning project* than as a *portfolio
product*. The breadth of what you touched is genuinely rare — voice, GUI,
security, automation, memory systems, embeddings, model quantization, browser
automation. A hiring manager reading that list will say "this person gets
things done across the stack."

But the architecture decisions (custom intent recognizer, custom planner,
custom DAG executor, custom workflow engine, 8 stores, 6 memory subsystems)
will signal inexperience to senior engineers. They'll see "didn't know when to
use existing solutions" rather than "architected a complex system."

**What would make it an A+ resume project:**
Taking what you built, strip it down to the dual-provider architecture described
in this document, and ship it as a clean, well-documented, testable CLI agent.
The result would be:
- 27K lines instead of 76K (shows you can refactor)
- Dual-provider architecture with cloud API support (shows modern API design)
- Clean separation of concerns (shows design maturity)
- Still has all the unique modules (security, browser, voice, home automation)
- Can actually be used by others — cloud mode needs no GPU, local mode still works

A lean, working agent that someone can set up in 5 minutes with an API key is
infinitely more resume-valuable than an ambitious behemoth that needs 2GB of
local models and takes 30 seconds to answer a question.

---

## Summary: Decision Table

| Area | Current Approach | Dual-Provider Target | Effort | Impact |
|------|-----------------|---------------------|--------|--------|
| Model layer | 2 local GGUF models | 1 provider abstraction (cloud OR local) | Low | Maximum |
| Intent routing | 3,295-line regex file | Model tool-calling (any capable model) | Medium | Maximum |
| Planning | 5-layer pipeline | Model tool-calling | Medium | Maximum |
| Memory | 6 stores + Chroma + Mem0 | 1 SQLite FTS5 | High | High |
| Stores | 8 store objects | 1 database class | Medium | Medium |
| Delegation | 4 systems (none real) | 1 tool-based delegate | Low | Medium |
| GUI | PyQt6 HUD (2.8K lines) | CLI-only (prompt_toolkit) | Medium | Medium |
| Voice | 4K lines, local models | Dual: cloud API OR local fallback | Medium | Medium |
| Personas | YAML, well-designed | Keep as-is | None | High |
| Tests | 155 files (29K lines) | Prune, keep solid core | Low | High |
| Scheduler | Working cron system | Keep as-is | None | Medium |

### First 3 things to do (highest ROI)

1. **Add cloud API support** — Create the provider abstraction + LLMProvider
   interface. Wire it alongside the existing local model. Now users can choose
   between fast/cloud and offline/local with a config toggle.

2. **Remove the IntentRecognizer + QwenPlanner** — Comment them out, wire
   user input directly to the model with tool definitions. If answers are
   better without them (they will be, regardless of provider), delete the files.

3. **Consolidate memory** — Kill Mem0 server. Kill ChromaDB. Migrate to
   SQLite FTS5. One store, one connection, one set of queries. Save ~200MB
   of process memory. Benefits BOTH cloud and local modes.
