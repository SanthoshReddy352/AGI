# Project Friday: Cloud-Only Rebuild

## Target Audience, Market Gaps, and the Complete CLI-First Rebuild Plan

> **Answering:** What if FRIDAY dropped local inference entirely? No GGUF.
> No llama-cpp-python. No dual-provider complexity. Just a clean, fast,
> cloud-API agent that works entirely from the terminal.
>
> This document explores a PURE cloud-only strategy — kill local inference,
> strip the architecture to its core, and rebuild FRIDAY as a CLI-first agent
> that's competitive with Hermes Agent, Claude Code, and ChatGPT Desktop.
>
> **Critical honesty:** This sacrifices offline capability. Security
> researchers in air-gapped environments, privacy professionals with legal
> restrictions, and field pentesters without internet access are NOT the
> audience for this version. That's a conscious trade-off.
>
> The question is: does the trade-off make FRIDAY good enough to win in the
> segments it CAN serve?

---

## Table of Contents

1. [Part 1: Why Cloud-Only?](#part-1-why-cloud-only)
2. [Part 2: What We're Killing — The Full Purge List](#part-2-what-were-killing--the-full-purge-list)
3. [Part 3: Target Audience & Market Gaps](#part-3-target-audience--market-gaps)
4. [Part 4: Competitive Landscape](#part-4-competitive-landscape)
5. [Part 5: The Rebuild — Phase by Phase](#part-5-the-rebuild--phase-by-phase)
6. [Part 6: Implementation Timeline](#part-6-implementation-timeline)
7. [Part 7: Risks & Mitigations](#part-7-risks--mitigations)
8. [Part 8: Resume Worthiness](#part-8-resume-worthiness)
9. [Part 9: The Hard Questions](#part-9-the-hard-questions)

---

# Part 1: Why Cloud-Only?

## The Argument for Cutting Local Entirely

The dual-provider approach (keep local, add cloud) sounds reasonable on
paper. In practice, it adds complexity without clear payoff:

**1. Maintaining two inference paths doubles your CI surface.**

- When a test fails, is it a cloud API issue or a llama-cpp-python issue?
- When a tool call format changes, do you fix it in the cloud provider
  adapter, the local provider adapter, or both?
- When a cloud model supports streaming but local doesn't, does your
  entire response pipeline handle both?

**2. Local inference has never been FRIDAY's strength.**

The 0.8B/4B Qwen3.5 GGUF models produce "occasionally coherent" answers.
Upgrading to a 7B+ local model requires a GPU with 8GB+ VRAM — which
contradicts FRIDAY's "runs on any Kali machine" positioning. A 4B model
running on CPU takes 10-30 seconds per answer. That's not competitive
with ANY modern agent, cloud or local.

**3. The "offline use case" is narrow and shrinking.**

Who actually runs an AI assistant without internet?
- Security researchers in air-gapped environments: They need file analysis
  tools, not chat. FRIDAY isn't built for air-gap even today (it downloads
  models, checks for updates, uses ChromaDB embeddings).
- Pentesters in the field: Most have cellular hotspots or phone tethering.
- Privacy professionals: They use dedicated air-gap machines or VMs, not
  voice-activated desktop assistants.

The offline use case is real but it's a DIFFERENT PRODUCT. FRIDAY is a
voice-enabled desktop agent. Those two features (voice, desktop GUI)
already assume significant hardware and OS integration — adding "must
also work without internet" constrains architecture without matching
user behavior.

**4. Every dollar of engineering on local inference is a dollar NOT spent on tools, speed, and UX.**

FRIDAY has 27 modules, 76K lines of code, and 155 test files. The core
local inference stack (llama-cpp-python, model_manager, dual-model routing)
is maybe 2,000 lines. But the COMPENSATING infrastructure it requires
(intent recognizer, planning engine, 8 stores, fallback chains) is 20,000+
lines. All of it exists because the local model wasn't smart enough to
call a tool correctly.

If you remove local inference, you remove the root cause of the complexity.
Not the symptoms — the cause.

**5. Cloud API costs are negligible for personal use.**

A heavy user making 500 queries/day with GPT-4o-mini (~$0.15/1M input,
~$0.60/1M output) at ~500 tokens average per turn:
- Input: 500 × 500 = 250K tokens/day = $0.037/day
- Output: 500 × 200 = 100K tokens/day = $0.06/day
- Total: ~$0.10/day = $3/month

With DeepSeek V4 Flash (free tier) or Groq (free tier), it costs $0.

The "I don't want to pay for API calls" argument sounds principled but
translates to "I'd rather wait 30 seconds per answer than pay $3/month."
For most users, that's a bad trade.

---

# Part 2: What We're Killing — The Full Purge List

This is the complete list of everything that gets deleted or rewritten
in a cloud-only rebuild. No half-measures.

## Deleted Entirely

| File/Directory | Lines | Why It Dies |
|---------------|-------|-------------|
| `core/llm_providers/` | ~200 | Local GGUF inference engine. Cloud API replaces it. |
| `core/intent_recognizer.py` | 3,295 | Regex intent parsing. Cloud model does this with a system prompt. |
| `core/planning/` (7 files) | ~1,600 | PlannerEngine, QwenPlanner, ReplanController, ContextResolver, PlanValidator, PlanRepair, WorkflowCoordinator. All replaced by model tool-calling. |
| `core/embedding_router.py` | ~150 | Semantic fallback layer. Not needed. |
| `core/lexical_router.py` | ~100 | STT typo fuzzy matching. Not needed. |
| `core/routing_tuner.py` | ~200 | Threshold tuning for unreliable intent detection. |
| `core/routing_state.py` | ~150 | State machine for routing layers. |
| `core/mixture_of_agents.py` | ~200 | Multi-model ensemble. One good model > two weak ones. |
| `core/task_graph_executor.py` | 441 | DAG executor for multi-step plans. Model sequences tool calls. |
| `core/workflow_orchestrator.py` | 1,042 | LangGraph workflows. Over-engineering for a capable model. |
| `core/context_store/` (9 files) | ~2,500 | 16-table SQLite schema split into 8 sub-stores. One database, one class. |
| `core/memory/` (facade, semantic, episodic, procedural, graph, embeddings) | ~1,000 | 6 memory subsystems. One facts table + FTS5. |
| `core/memory_service.py` | 436 | Mem0 integration (separate server process). Gone. |
| `core/session_rag.py` | ~150 | ChromaDB RAG. Gone. |
| `core/reasoning/` (model_router, route_scorer, agentic_services) | ~500 | Two-model architecture collapses to one. No research/focus modes. |
| `core/delegate.py` | 83 | Threading hack for sub-agent. Replaced by tool call. |
| `core/conversation_agent.py` | 197 | Dead code. |
| `core/lock_monitor.py` | ~100 | GUI-dependent. |
| `core/screen_lock.py` | ~100 | GUI-dependent. |
| `core/mcp_client.py` | ~200 | MCP protocol support. Not core. |
| `core/safety/tool_guardrails.py` | ~200 | Model follows tool descriptions. |
| `core/safety/website_policy.py` | ~100 | Model judgment replaces policy. |
| `core/safety/url_safety.py` | ~100 | One-line sanity check replaces it. |
| `core/kernel/consent.py` | ~100 | Prompt rule. |
| `core/kernel/permissions.py` | ~100 | Prompt rule. |
| `HUD/` (PyQt6 GUI) | ~3,300 | CLI-first. PyQt6 dependency dropped. |
| `voice/` modules (12 files) | ~4,088 | Replaced with cloud STT/TTS API calls (~500 lines). |
| `assistant_context.py` | ~200 | Redundant. |
| `shell_prefix.py` | ~50 | Not needed. |
| `text_normalize.py` | ~100 | STT typo correction. Cloud STT doesn't need it. |
| `clap_detector.py` | ~690 | Gimmick feature. ~50-line optional module if kept. |
| `wake_word/` | ~400 | Local wake word. Cloud doesn't need local wake detection. |

**Total lines removed: ~22,000 across ~60+ files.**

## Simplified (Not Deleted)

| File | Current Lines | Target | Why Keep |
|------|-------------|--------|----------|
| `core/router.py` | 1,113 | ~200 | Matches tool names, calls model, returns response. No intent recognition, no fallback chains. |
| `core/model_manager.py` | 192 | ~50 | Manages cloud provider config + connection test. |
| `core/app.py` | 1,117 | ~300 | Removes store construction, planning engine wiring. Keeps event bus + tool initialization. |
| `core/prompt_builder.py` | 101 | ~30 | Just format user input + system prompt. |
| `core/memory_broker.py` | 160 | ~50 | Thin context builder from single database. |
| `core/turn_manager.py` | 139 | ~50 | Invokes model, routes tools. |
| `core/kernel/runtime.py` | 258 | ~100 | Remove ServiceContainer complexity. |
| `core/plugin_manager.py` | 97 | ~60 | Standardize extension interface. |
| `core/extensions/` (loader, protocol) | ~300 | ~200 | Extension system is good. Remove adapter layer. |

## What Stays Unchanged (or Nearly)

- `core/event_bus.py` — Clean pub/sub. Keep.
- `core/config.py` — Add provider config. Keep.
- `core/logger.py` — Keep.
- `core/persona_manager.py` — YAML persona system. Keep, it's good.
- `core/scheduler.py` — Background task scheduling. Keep.
- `core/tool_execution.py` — Keep.
- `core/tool_result.py` — Keep.
- `core/tool_catalog.py` — Rewrite to output JSON schemas. Keep the concept.
- `core/response_finalizer.py` — Keep.
- `core/tracing.py` — Keep if useful.
- `core/session_summarizer.py` — Keep.
- `core/task_runner.py` — Keep.
- `core/interrupt_bus.py` — Keep.
- `core/safety/path_security.py` — Keep. Actual filesystem isolation.
- `core/safety/approval.py` — Keep. User consent.

**All 27 modules (browser, security, smart home, etc.)** — Keep as tools,
rewrite to single-ToolFile standard format.

---

# Part 3: Target Audience & Market Gaps

## Who This Version of FRIDAY Serves

### PRIMARY: Desktop Power Users with Internet

**Who they are:**
- Developers, sysadmins, DevOps engineers
- Power users who work at a terminal all day
- People who want a ChatGPT-like assistant but NATIVE to their system
- Users of Claude Code, Cursor, or GitHub Copilot who want a more
  general-purpose assistant

**What FRIDAY gives them that nothing else does:**
- System-native tool execution (open apps, write files, run commands,
  browse local directories)
- 27 integrated capabilities in one agent (not 27 separate tools)
- Voice interface that works with their actual desktop apps
- Runs entirely in the terminal they already live in

**Market gap:** Claude Code is amazing at code but doesn't manage your
smart home. ChatGPT Desktop is chat-only and doesn't touch your filesystem.
Hermes Agent is general-purpose but voice is immature. FRIDAY fills the
"general-purpose desktop agent with voice" gap.

### SECONDARY: Kali Linux / Security Researchers (Connected)

**Who they are:**
- Pentesters who work with internet access (most of them)
- Security tool users who want AI-assisted scanning
- People already running Kali as their daily driver

**What FRIDAY gives them:**
- Native nmap/wrapper/port-scan tools that the model can orchestrate
- File system awareness for log analysis
- Terminal-native output that doesn't fight their workflow
- No GPU requirement — runs on the same laptop they already carry

**Market gap:** No existing agent has security-specific tooling built in.
Claude Code doesn't know how to run nmap. ChatGPT doesn't know Metasploit.
FRIDAY can be the "Kali agent" by default.

### TERTIARY: AI Hobbyists / Tinkerers

**Who they are:**
- People who want to understand how agents work
- Developers looking for a hackable starting point
- People who tried AutoGPT / BabyAGI and want something that actually works

**What FRIDAY gives them:**
- Clean, 27K-line codebase they can read in a weekend
- YAML-based personas they can customize without touching code
- Plugin system for adding capabilities

## Who This Version Does NOT Serve (And That's OK)

- **Air-gapped security researchers** — They need file-analysis tools,
  not a chat agent. A different product.
- **Privacy absolutists** — They won't use any cloud API. FRIDAY isn't
  for them.
- **People with no internet** — The agent won't work at all. Honest
  limitation.
- **Desktop GUI lovers** — CLI-only. If you need a window, this isn't it.

## Market Gaps FRIDAY Fills

| Gap | Who Has It | Why FRIDAY Wins |
|-----|-----------|----------------|
| General-purpose CLI agent | No one owns it | Hermes is good but voice is weak. Claude Code is code-only. ChatGPT Desktop is chat-only. |
| Voice-native desktop assistant | No one owns it | Siri/Google/Alexa can't do system tasks. FRIDAY can. |
| Security-aware AI agent | No one owns it | Kali-specific tooling, pentest workflows, nmap wrappers. |
| Locally-installed but cloud-powered | No one owns it | "Desktop ChatGPT with actual tool access." |
| Hackable agent with module system | No one owns it | Open source, YAML personas, plugin API, 27K lines you can read. |

---

# Part 4: Competitive Landscape

## Direct Competitors

| Product | Strengths | Weaknesses vs Cloud-Only FRIDAY |
|---------|----------|--------------------------------|
| **Claude Code** | Excellent coding, prompt engineering, file awareness | Code-only. Can't do system tools, browser, smart home, voice. |
| **ChatGPT Desktop** | Great chat, native OS integration in macOS | macOS only. Limited tool ecosystem. Closed source. |
| **Hermes Agent** | General-purpose, good CLI UX, skill system | Voice is immature. No security tooling. |
| **Gemini Desktop** | Google ecosystem, good chat | Windows/Mac only. Limited tool execution. |
| **Open Interpreter** | Code execution, open source | No voice. No smart home. No browser automation. Unreliable for non-code. |

## How FRIDAY Wins

1. **Only general-purpose voice agent for Linux** — This alone is a
   differentiator. No other agent lets you say "open Firefox, run nmap
   scan on this subnet, and play ambient music" in one sentence.

2. **Security tooling is built in, not optional** — A Kali user doesn't
   need to install 5 plugins. FRIDAY already has nmap, port scanning,
   network inventory, DNS tools, and file analysis as FIRST-CLASS tools.

3. **27 capabilities, one install** — The breadth is a feature. Most
   agents have 5-10 tools. FRIDAY has browser automation, smart home,
   code execution, file operations, security scanning, document reading,
   web search, image analysis, and voice — all in one binary.

4. **YAML personas make it hackable** — You can teach FRIDAY a new
   personality without writing Python. That's rare and valuable.

5. **155 test files** — Unusual for a solo project. Shows engineering
   discipline. Attracts contributors.

---

# Part 5: The Rebuild — Phase by Phase

## Phase 0: Audit & Inventory (Week 1)

### What to do
- Create git tag `v1.0` before touching anything
- Inventory every file: keep, simplify, or delete
- Measure current startup time, time-to-first-answer, latency per turn
- Document every cloud API endpoint you'll need
- Set up API keys for primary and backup providers
- Create baseline tests that should pass throughout the rebuild

### Deliverable: CLEAN_SLATE.txt with full inventory + baseline metrics

---

## Phase 1: Kill the Local Model Layer (Week 2)

### What changes

The model layer goes from:
```
Two local GGUF files (0.8B + 4B)
├── llama-cpp-python inference engine (~200 lines)
├── threading.Lock per model call
├── Model preloading at startup (2-10 seconds)
├── Inference queue with timeout
├── CPU threading config
└── Tool model called as sub-LLM
```

To:
```
One cloud API endpoint
├── HTTP POST with messages + tools
├── JSON response with content + optional tool_calls
├── Zero startup time (no model loading)
├── No inference locks (API handles concurrency)
├── Streaming token response (typewriter effect)
└── One model handles chat + tool calling natively
```

### Implementation

**Step 1.1: Create cloud provider abstraction**

```python
# core/provider.py — ~80 lines

from abc import ABC, abstractmethod
from typing import Optional
import requests

class LLMProvider(ABC):
    @abstractmethod
    def create(self, messages: list, tools: Optional[list] = None,
               stream: bool = False) -> dict:
        ...

class OpenAICompatProvider(LLMProvider):
    """Works with OpenAI, OpenRouter, Together, Groq, etc."""
    def __init__(self, config: dict):
        self.base_url = config["base_url"]
        self.model = config["model"]
        self.api_key = config["api_key"]
        self.max_tokens = config.get("max_tokens", 4096)

    def create(self, messages, tools=None, stream=False):
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
```

**Step 1.2: Update config.yaml**

```yaml
provider:
  type: openai_compat
  base_url: https://api.opencode-zen.com/v1
  model: deepseek/deepseek-v4-flash-free
  api_key_env: FRIDAY_API_KEY
  max_tokens: 8192
  temperature: 0.3
  timeout_s: 30
```

**Step 1.3: Rewrite model_manager.py**

The ModelManager becomes a thin provider wrapper:
- Read provider config from config.yaml
- Instantiate the chosen provider class
- Test connection on startup (HEAD request or simple chat call)
- Expose `generate(messages, tools, stream)` that delegates to provider
- Remove: GGUF path resolution, dual-model config, inference locks,
  model preloading, CPU threading settings

### Files to modify:
- `core/provider.py` (NEW)
- `core/model_manager.py` (rewrite, ~50 lines)
- `core/config.py` (add provider section)
- `config.yaml` (cloud-only config)
- `.env.example` (add FRIDAY_API_KEY)

### Files to delete:
- `core/llm_providers/` directory (all local inference providers)

---

## Phase 2: Kill the Intent Recognizer + All Routing Layers (Week 2-3)

### The routing pipeline goes from:

```
User Input
  → Text normalizer (typo correction for STT)
  → IntentRecognizer.plan() [3,295 lines of regex]
    → Splits compound clauses
    → Matches against 40+ tool parsers
    → Returns action plan or []
  → EmbeddingRouter (semantic fallback)
  → LexicalRouter (fuzzy STT-typo fallback)
  → Tool model inference (4B Qwen3.5)
  → Fallback to chat model (0.8B Qwen3.5)
  → Routing state machine (maintains current turn state)
```

### To:

```
User Input
  → API call with system prompt + tool definitions
  → Model responds with tool_use or text
  → If tool_use: execute tool, feed result back, loop
  → If text: return response to user
```

### Three steps. One LLM call per turn.

```python
# core/router.py — ~200 lines

class Router:
    def __init__(self, model_manager, tools: dict):
        self.llm = model_manager
        self.tools = tools

    def route(self, text: str, session_id: str) -> str:
        messages = self._build_messages(text, session_id)
        tool_defs = self._get_tool_definitions()

        response = self.llm.generate(messages, tools=tool_defs)

        if response.get("tool_calls"):
            for call in response["tool_calls"]:
                result = self._execute_tool(call["name"], call["args"])
                messages.append({"role": "tool", "content": result})
            response = self.llm.generate(messages)

        return response["content"]
```

### Files to delete (all at once):
- `core/intent_recognizer.py`
- `core/embedding_router.py`
- `core/lexical_router.py`
- `core/routing_tuner.py`
- `core/routing_state.py`
- `core/text_normalize.py`

---

## Phase 3: Kill the Planning Engine (Week 3)

### The planning engine goes from 5-layer stack to zero:

The planning engine IS the model's tool-calling API.

**What gets deleted:**
- `core/planning/planner_engine.py` (247 lines)
- `core/planning/intent_engine.py` (112 lines)
- `core/planning/qwen_planner.py` (363 lines)
- `core/planning/replan_controller.py` (265 lines)
- `core/planning/plan_validator.py` (~200 lines)
- `core/planning/plan_repair.py` (~150 lines)
- `core/planning/context_resolver.py` (~150 lines)
- `core/planning/workflow_coordinator.py` (73 lines)
- `core/planning/slot_extractors.py` (~100 lines)
- `core/planning/json_repair.py` (~100 lines)
- `core/planning/turn_orchestrator.py` (476 lines)
- `core/mixture_of_agents.py` (~200 lines)
- `core/task_graph_executor.py` (441 lines)
- `core/workflow_orchestrator.py` (1,042 lines)

**What stays:** Nothing. The model handles planning, error recovery,
argument validation, pronoun resolution, and tool sequencing.

---

## Phase 4: Simplify Memory by 80% (Week 3-4)

### Current: 6 memory subsystems + ChromaDB + Mem0 server

| Store | Backend | Purpose |
|-------|---------|---------|
| MemoryStore | ChromaDB + SQLite | Vector embeddings + metadata |
| SemanticMemory | SQLite | Key-value facts |
| MemoryFacade | wraps SemanticMemory | Single write path facade |
| MemoryBroker | aggregates all stores | Context bundle builder |
| Mem0 | REST service (port 8181) | Long-term memory |
| EpisodicMemory | SQLite | Turn history |
| ProceduralMemory | SQLite | How-to knowledge |
| PersonaManager | YAML + SQLite | User profile |
| ContextStore | SQLite (16 tables) | Original monolithic store |

**Problems:**
- Same fact stored in 4+ places
- Mem0 server runs separately and IS IGNORED by the facade
- ChromaDB loads a 90MB sentence-transformer model for 200 facts
- 8 store objects all wrap the SAME SQLite database

### Target: One SQLite database, three tables

```python
# core/database.py — ~200 lines

class Database:
    """Single SQLite connection with all tables."""
    sessions: SQLTable
    turns: SQLTable
    facts: SQLTable
    audit: SQLTable
```

**No ChromaDB.** No sentence-transformers. No Mem0 server. No MemoryFacade.
No EpisodicMemory. No ProceduralMemory.

**How memory works with a cloud model:**
- **User facts:** Extract with a single prompt: "What facts about the user
  can you identify from this conversation?" The model outputs structured JSON.
- **Memory retrieval:** The model's context window (128K+) handles relevance.
  SQLite FTS5 for keyword search when needed.
- **Session history:** The API message list IS your memory. Summarization
  call when context gets large.

### Files to delete:
- `core/memory_service.py` (Mem0 integration)
- `core/memory/facade.py` (simplify or delete)
- `core/memory/semantic.py`
- `core/memory/episodic.py`
- `core/memory/procedural.py`
- `core/memory/graph.py`
- `core/memory/embeddings.py`
- `core/session_rag.py`
- `core/stores/` directory (all 9 files)
- `core/context_store.py` and all sub-stores

---

## Phase 5: Kill the GUI, Own the Terminal (Week 4)

### Current: PyQt6 HUD at 2,878 lines

Conical gradients, glow effects, audio device selector, scrollable
transcript, theme toggling, voice activity display, animated rings.

### Target: CLI-first with prompt_toolkit

```python
# cli/interface.py — ~150 lines

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

session = PromptSession(history=FileHistory("~/.friday_history"))

while True:
    user_input = await session.prompt_async("friday> ")
    if user_input == "/exit":
        break
    response = await agent.process(user_input)
    print(response)
```

**What gets deleted:**
- `HUD/` directory (PyQt6 GUI, ~3,300 lines)
- `PyQt6` dependency from requirements.txt (saves ~50MB)
- `core/lock_monitor.py`
- `core/screen_lock.py`

**What gets added:**
- `cli/` directory with prompt_toolkit interface
- Streaming response display (typewriter effect)
- Colored output rendering
- `/commands` for agent control
- Pipe support (`echo "nmap scan" | friday`)

---

## Phase 6: Replace Voice Pipeline with Cloud APIs (Week 4)

### Current: 12 files, 4,088 lines

Local whisper-tiny STT, Piper/pyttsx3 TTS, VAD, noise filtering,
barge-in detection, clap detection, wake word, audio device management,
Vosk model management.

### Target: 2 files, ~400 lines, cloud APIs

```python
# voice/stt.py — ~50 lines

class CloudSTT:
    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1", file=f
            )
        return transcript.text

# voice/tts.py — ~40 lines

class CloudTTS:
    def speak(self, text: str):
        response = self.client.audio.speech.create(
            model="tts-1", voice="alloy", input=text
        )
        response.stream_to_file("/tmp/friday_tts.mp3")
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "/tmp/friday_tts.mp3"])
```

**Why cloud STT/TTS is better:**
- Whisper API: $0.006/min, near-perfect accuracy, no model download
- OpenAI TTS: $0.015/1K chars, natural voice, multiple voices
- No VAD tuning, no noise filtering, no model management
- Response time: 200-500ms vs 2-5s for local whisper-tiny

**Files to delete:**
- `voice/` directory (12 files, 4,088 lines)

**Files to create:**
- `voice/stt.py` (cloud STT wrapper, ~50 lines)
- `voice/tts.py` (cloud TTS wrapper, ~40 lines)
- `voice/listener.py` (mic recording, ~100 lines)

---

## Phase 7: Simplify Security Layer (Week 5)

### Current: 6 security modules

| Module | Purpose |
|--------|---------|
| ToolGuardrails | Tool-level safety checks |
| URLSafety | URL whitelisting |
| PathSecurity | File path traversal checks |
| WebsitePolicy | Web access policy |
| ConsentService | User consent tracking |
| PermissionService | Tool permission model |

### Target: 2 modules

| Module | Purpose |
|--------|---------|
| PathSecurity | Filesystem isolation (code-enforceable) |
| approval.py | User consent flow |

**What gets deleted:**
- `ToolGuardrails` — The model follows tool descriptions
- `URLSafety` — Prompt rule + one-line sanity check
- `WebsitePolicy` — Model judgment replaces it
- `PermissionService` — Prompt rule

---

## Phase 8: Consolidate Tools & Delegation (Week 5-6)

### Standardize all 27 modules to single-ToolFile format

Each module exports a list of `ToolDef` objects:

```python
# tools/browser.py — ToolFile standard

tools = [
    ToolDef(
        name="browser_navigate",
        description="Navigate to a URL in the browser",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to navigate to"}
            },
            "required": ["url"]
        },
        handler=navigate,
    ),
    # ... more browser tools
]
```

### Replace 4 delegation systems with 1

Current: Delegate class, DelegationManager, MixtureOfAgents, ResearchAgent
Target: Single `delegate_task` tool that spawns sub-agents via API

```python
tools = [{
    "name": "delegate_task",
    "description": "Run a task in a sub-agent with its own tools",
    "parameters": {
        "goal": "Task description",
        "toolsets": ["file", "terminal", "web"],
    }
}]
```

---

# Part 6: Implementation Timeline

## Phase Overview

```
Week 1:  [Audit + Setup]   Inventory, freeze deps, API keys, baseline
Week 2:  [Provider + Route]  Cloud provider, kill intent recognizer, new router
Week 3:  [Memory + Plan]     Unify database, delete planning engine, kill stores
Week 4:  [CLI + Voice]       CLI-first, cloud STT/TTS, kill GUI
Week 5:  [Tools + Security]  Standardize modules, simplify security
Week 6:  [Delegation + Docs] Sub-agent system, README, quickstart
```

## Detailed Week-by-Week

### Week 1: Pre-Rebuild Audit

| Day | Task |
|-----|------|
| 1 | Git tag v1.0, create clean branch |
| 2 | Inventory all 463 Python files into KEEP / SIMPLIFY / DELETE |
| 3 | Set up cloud API keys (primary: DeepSeek V4 Flash, backup: Groq/GPT-4o-mini) |
| 4 | Run all 155 tests, record which pass/fail |
| 5 | Measure baseline: startup time, time-to-first-answer, latency per turn |
| 6 | Config file draft: cloud-only provider structure |
| 7 | Document EVERYTHING that will be deleted, with reasons |

**Deliverable:** CLEAN_SLATE.md with full inventory + baseline metrics

### Week 2: Cloud Provider + Routing

| Day | Task | Files |
|-----|------|-------|
| 1 | Create `core/provider.py` with OpenAI-compatible provider | 1 new |
| 2 | Update `config.yaml` + `.env.example` for cloud-only config | 2 files |
| 3 | Rewrite `model_manager.py` as thin provider wrapper | 1 file |
| 4 | Rewrite `core/router.py` (1,113 → 200 lines, gated tool-calling) | 1 file |
| 5 | DELETE: intent_recognizer, embedding_router, lexical_router, routing_state | 10+ files |
| 6 | DELETE: text_normalize, shell_prefix, assistant_context | 3 files |
| 7 | RUN TESTS, fix regressions | Varies |

**Week 2 deliverable:** FRIDAY runs entirely on cloud API. Routing is 200 lines.
13+ files deleted. Tool calling works through model-native function calling.

### Week 3: Memory + Planning Purge

| Day | Task | Files |
|-----|------|-------|
| 1 | Create `core/database.py` (single SQLite, sessions + turns + facts + audit) | 1 new |
| 2 | DELETE: context_store directory (9 files), all memory subsystems (6 files) | 15+ files |
| 3 | DELETE: planning engine (10+ files) | 10+ files |
| 4 | DELETE: workflow_orchestrator, task_graph_executor, mixture_of_agents | 3 files |
| 5 | DELETE: memory_service (Mem0), session_rag (ChromaDB), reasoning/ | 6+ files |
| 6 | Simplify: MemoryBroker (160→50), MemoryFacade (359→delete) | 2 files |
| 7 | RUN TESTS, fix regressions | Varies |

**Week 3 deliverable:** One SQLite database. Planning engine gone.
ChromaDB + Mem0 gone. Memory is one facts table. ~35 files deleted.

### Week 4: CLI + Voice

| Day | Task | Files |
|-----|------|-------|
| 1 | Create `cli/interface.py` with prompt_toolkit | 1 new |
| 2 | DELETE: HUD/ directory (PyQt6 GUI, ~3,300 lines) | 10+ files |
| 3 | DELETE: lock_monitor, screen_lock | 2 files |
| 4 | DELETE: voice/ directory (12 files, 4,088 lines) | 12 files |
| 5 | Create: voice/stt.py (cloud), voice/tts.py (cloud), voice/listener.py | 3 new |
| 6 | Remove PyQt6 dependency from requirements.txt | 1 file |
| 7 | RUN TESTS, fix regressions | Varies |

**Week 4 deliverable:** CLI-first agent. Cloud STT/TTS (400 lines total).
PyQt6 dependency removed. ~25 files deleted, 4 files created.

### Week 5: Tools + Security

| Day | Task | Files |
|-----|------|-------|
| 1 | Standardize all 27 modules to single-ToolFile format | 15+ files |
| 2 | DELETE: overlapping modules (mcp_client, comms, awareness, triggers) | 8+ files |
| 3 | DELETE: tool_guardrails, url_safety, website_policy, consent_service | 5 files |
| 4 | Simplify: PathSecurity + approval.py | 2 files |
| 5 | Simplify: turn_manager, prompt_builder, plugin_manager | 3 files |
| 6 | Clean up: Remove dead code from app.py, kernel files | 3+ files |
| 7 | RUN TESTS, fix regressions | Varies |

**Week 5 deliverable:** 27 modules → ~18. Security is 2 files.
All modules use standard ToolFile format.

### Week 6: Delegation + Documentation + Release

| Day | Task | Files |
|-----|------|-------|
| 1 | Implement delegate_task tool (sub-agent spawning) | 2 files |
| 2 | DELETE: Delegate class, research_agent module, agentic_services | 5+ files |
| 3 | Write comprehensive README.md | 1 file |
| 4 | Create quickstart: "FRIDAY in 2 minutes with an API key" | 1 file |
| 5 | Create Kali-focused landing page in docs | 1 file |
| 6 | Final latency benchmark vs baseline | 0 |
| 7 | Git tag v2.0 — release | 0 |

**Week 6 deliverable:** Release v2.0.0 — "FRIDAY: Cloud-Only Edition."
Working CLI agent. README, docs, quickstart done. Ready for launch.

---

## Summary: Before vs After

| Metric | Current (v1.0) | Target (v2.0 Cloud-Only) | Reduction |
|--------|---------------|--------------------------|-----------|
| Project Python files | ~463 | ~150 | 68% |
| Project Python lines | ~76,000 | ~20,000 | 74% |
| Dependencies | ~30 | ~12 | 60% |
| Startup time | 2-10s | <0.5s | 90%+ |
| Time to first answer | 10-30s | 1-2s | 90%+ |
| Answer quality | "occasionally coherent" | ChatGPT-grade | Massive |
| Stores | 8 | 1 | 88% |
| Memory subsystems | 6 | 1 | 83% |
| Voice pipeline lines | 4,088 | ~400 | 90% |
| GUI lines | 3,300 | 0 (CLI) | 100% |
| Planning engine lines | ~2,500 | 0 | 100% |
| Security modules | 6 | 2 | 67% |
| Delegation systems | 4 | 1 | 75% |
| Test files | 155 | ~100 | 35% |
| Local inference | Yes (2 models) | No | 100% |
| Requires internet | Optional | Required | Trade-off |

---

# Part 7: Risks & Mitigations

## Risk Matrix

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| 1 | **Cloud API cost increases** | Medium | High | Support multiple providers (OpenRouter, Together, Groq free tier). Config change, not code change. |
| 2 | **Cloud API latency is worse than local** | Low | Medium | Benchmark first. DeepSeek V4 Flash and Groq have <500ms response times. Most users have <50ms to API. |
| 3 | **Users want offline mode** and cloud-only is a blocker | Medium | Medium | Accept this upfront. Document as a trade-off. The value proposition is speed/quality, not offline. |
| 4 | **API keys are a UX barrier** | High | Medium | Support free-tier providers (Groq, DeepSeek V4 Flash). One-time setup in README. |
| 5 | **Mass deletion breaks everything** | High | High | Delete in waves. Run tests after each wave. Keep git tags for rollback. |
| 6 | **Tests fail after deletion** | High | Medium | Prune tests that tested deleted components. Keep tests for remaining architecture. |
| 7 | **Community backlash for dropping local** | Medium | Low | Release as v2.0 "Cloud Edition." v1.0 branch still works. Clear messaging. |

## Rollback Plan

If the rebuild causes critical issues:
1. Git checkout `v1.0` — the old architecture is preserved
2. The cloud-only branch can be maintained separately
3. No data loss: the SQLite database schema is a subset of the original

---

# Part 8: Resume Worthiness

## The Honest Assessment

**Yes — more resume-worthy than the current architecture.**

### Why it's better for a resume:

**1. 20K lines instead of 76K.** A lean codebase signals engineering
discipline. The original shows "I can build complex systems." The
rebuild shows "I can SIMPLIFY complex systems." That's rarer.

**2. Cloud API integration.** Modern AI development is about APIs, not
model hosting. Showing you can work with OpenAI/Anthropic/Groq APIs
signals you know how modern AI products are built.

**3. CLI-first design.** Terminal-native tools (ripgrep, jq, fzf) are
respected in engineering culture. A CLI agent reads as "serious tool,"
not "college project."

**4. The breadth remains.** You still have 18 modules, 20K lines,
security tooling, browser automation, smart home, voice, and 100 tests.
The breadth is preserved — the fat is gone.

### What to lead with:

- "Built a ChatGPT-grade CLI agent with 18 integrated capabilities
  (browser, security, smart home, code execution, voice, research)"
- "Architected a 74% code reduction from 76K to 20K lines while improving
  answer quality from 'occasionally coherent' to ChatGPT-grade"
- "Designed a cloud-API provider abstraction that supports OpenAI,
  Anthropic, Groq, Together, and OpenRouter with 1 config change"
- "Implemented a YAML-based persona system separating agent identity
  from code, inspired by Claude Code's CLAUDE.md pattern"
- "Built 100 automated tests for an AI agent — stronger coverage than
  most open-source agent projects"

### What NOT to lead with:

- "76,000-line local AI assistant" (sounds like you over-engineered)
- "Built my own planning engine" (sounds like NIH syndrome)
- "100 commits in 7 days" (sounds like rushing, not discipline)

---

# Part 9: The Hard Questions

## Is This Just "Another OpenAI Wrapper"?

It would be if you just did `while True: input() → API → print()`.
FRIDAY is not that because:

1. **18 integrated tools** — browser automation, security scanning, smart
   home control, code execution, file operations, web search, document
   reading, voice — each with real implementation, not just API wrappers.

2. **Tool system architecture** — The router, tool executor, result
   handler, error recovery, and tool-to-model feedback loop is real
   engineering. It's not trivial to let a model browse the web, scan
   a network, open Firefox, and control your lights in one session.

3. **Persona system** — YAML-based identity management outside code.
   This is a genuinely good design that Claude Code is converging on.

4. **Test infrastructure** — 100 tests for an agent is rare. Most "AI
   agent" projects have 0 tests.

5. **6-week rebuild** — The ability to take 76K lines of working code,
   identify what matters, drop the rest, and ship a leaner product IS
   the skill employers hire for.

## Is the Offline Sacrifice Worth It?

For this version: **Yes.** Here's the honest calculation:

- Offline users are a tiny fraction of the total addressable market
- The engineering cost of supporting offline (dual-provider, local
  inference, offline fallback) is ~30% of the total codebase
- That 30% doesn't improve the online experience AT ALL
- For the 95% of users who have internet, cloud-only is strictly better
  in every dimension: speed, quality, reliability, simplicity

If offline matters, build a separate "FRIDAY Lite" that runs on a
Raspberry Pi with a 1B model for basic chat. Don't conflate the products.

## Is This Project Worth Continuing?

**Yes, but only if you commit to one architecture.**

FRIDAY's biggest problem has never been the code quality — it's the
ARCHITECTURAL INDECISION. Dual-model (0.8B+4B). Dual-provider (cloud+local).
8 stores. 6 memory systems. 4 delegation mechanisms. The code works but
it tries to be everything to everyone.

The cloud-only rebuild forces a decision:
- CLI (not GUI)
- Cloud API (not local)
- One SQLite database (not 8 stores)
- 18 modules (not 27)
- 20K lines (not 76K)

A focused, decisive, limited-scope product that does one thing well
beats an ambitious, sprawling, feature-everywhere product that does
everything poorly.

FRIDAY's unique value is: "ChatGPT for your terminal, with 18 tools,
that respects your system." That's worth building. Just stop trying to
also be "offline AI assistant" and "GUI desktop app" and "multi-model
orchestrator" and "LangGraph workflow engine" at the same time.

---

## Appendix: Target Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│                   FRIDAY Agent                    │
├─────────────────────────────────────────────────┤
│                                                   │
│  ┌─────────────┐   ┌─────────────────────────┐   │
│  │  CLI (prompt  │   │  Cloud API Provider      │   │
│  │  _toolkit)    │──▶│  (OpenAI-compatible)     │   │
│  │  streaming,  │   │  - DeepSeek / Claude /   │   │
│  │  colors,     │   │    GPT-4o-mini / Groq    │   │
│  │  history     │   └───────────┬─────────────┘   │
│  └──────┬──────┘               │                 │
│         │                      │                 │
│         └──────┬───────────────┘                 │
│                │                                 │
│         ┌──────▼───────┐                         │
│         │  Tool Executor │                         │
│         │  + Result Loop │                         │
│         └──────┬───────┘                         │
│                │                                 │
│    ┌───────────┼──────────────┐                  │
│    │           │              │                  │
│    ▼           ▼              ▼                  │
│ File    Security   Browser   Voice   ...tools    │
│ Tools    Tools   Auto      (Cloud               │
│          (nmap,   (Selenium) STT/TTS)            │
│           scan)                                   │
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
