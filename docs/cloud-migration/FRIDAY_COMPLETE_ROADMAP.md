# Project Friday: The Complete Roadmap

## Target Audience, Architecture Overhaul, and the Path to "Best in Segment"

> **Answering:** Who needs FRIDAY? How do you reach them? What exactly must
> change — down to the code — to make FRIDAY competitive while keeping its
> offline soul? What stays? What goes? Why each decision?
>
> **Critical clarification:** This is NOT a "replace local with cloud" document.
> The end state is a DUAL-PROVIDER architecture where FRIDAY supports BOTH
> local models (for offline, privacy, and air-gapped use) AND cloud API models
> (for speed, quality, and convenience). The user chooses. The architecture
> supports both without doubling the code.
>
> The simplification work (removing intent recognizer, 8 stores, planning
> engine, etc.) benefits BOTH modes equally. Whether you run a 4B GGUF or
> GPT-4o, you don't need 3,295 lines of regex intent parsing.
>
> This document covers everything. Every overhaul step. Every audience
> segment. Every marketing angle. Every architectural decision explained
> with "why" and "what changes."

---

## Table of Contents

- [Part 1: Target Audience Analysis](#part-1-target-audience-analysis)
- [Part 2: Market Positioning & Competition](#part-2-market-positioning--competition)
- [Part 3: Go-To-Market Strategy](#part-3-go-to-market-strategy)
- [Part 4: The Overhaul — Phase by Phase](#part-4-the-overhaul--phase-by-phase)
- [Part 5: What Makes FRIDAY "Best in Segment"](#part-5-what-makes-friday-best-in-segment)
- [Part 6: Implementation Timeline](#part-6-implementation-timeline)
- [Part 7: Risks & Mitigations](#part-7-risks--mitigations)
- [Appendix: Current Codebase Inventory](#appendix-current-codebase-inventory)

---

# Part 1: Target Audience Analysis

## 1.1 The Four Audiences FRIDAY Can Own

### Audience A: The Security Researcher / Penetration Tester (PRIMARY)

**Profile:**
- Runs Kali Linux or Parrot OS
- Uses nmap, gobuster, dig, burpsuite daily
- Needs hands-free command execution during physical assessments
- Takes screenshots and notes they want auto-organized
- Has 8-16GB RAM, no NVIDIA GPU
- Technical enough to use CLI, wants a voice layer on top

**Why FRIDAY fits:**
- Security tools module: nmap scanning, port analysis, DNS enumeration,
  gobuster directory busting, all with structured observation output
- Audit logging: every security command is logged with timestamp + scope
- Voice control: "Friday, scan the local network" while keeping hands
  on keyboard or hardware
- Runs on Kali (tested) — no porting needed
- No cloud dependency: can work fully air-gapped

**Pain points FRIDAY solves:**
- Remembering nmap flags for every scan type
- Copy-pasting scan results into reports
- Typing while wearing gloves or holding equipment
- Context-switching between terminal, browser, and note-taking app

**Willing to pay:** $5-15/month if it saves 2+ hours/week on reporting.

**Size estimate:** ~200K active Kali users globally. Even 1% = 2,000 users.

**FRIDAY features they use:**
- security_tools (all of it)
- voice_io (STT + TTS for hands-free)
- system_control/screenshot
- sources/workspace_agent (report generation)
- world_monitor (CVE/news feeds)
- triggers (automated scans on schedule)

### Audience B: The Desktop Power User (MASS MARKET)

**Profile:**
- Runs Windows or Linux desktop
- Uses computer for work, not software development
- Wants to control their PC by voice
- Opens apps, manages files, checks weather, controls smart home
- Has 8-16GB RAM, integrated graphics
- Non-technical or moderately technical

**Why FRIDAY fits:**
- Desktop automation: launch apps, control volume/brightness, take
  screenshots, manage files — all by voice or text
- GUI HUD: visual feedback, not just a terminal
- Smart home: Philips Hue control
- Document intelligence: reads PDFs, DOCX, answers questions
- Cross-platform setup scripts (Windows PowerShell + Linux bash)

**Pain points FRIDAY solves:**
- "Where did I save that file?" → "Friday, find the invoice from March"
- "I need to read this PDF but my hands are busy" → "Friday, summarize this"
- Repetitive desktop tasks that require 3+ clicks
- Smart home control without pulling out a phone

**Willing to pay:** $0-5/month (free tier essential). Monetize via premium
features (cloud inference, more storage, advanced automations).

**Size estimate:** Potentially millions. But hard to reach without
marketing budget. Start with Linux power users on Reddit/HN.

**FRIDAY features they use:**
- system_control (app launcher, file search, brightness, volume,
  screenshots, system info)
- voice_io (wake word + STT + TTS)
- document_intel (RAG over documents)
- smart_home (light control)
- weather
- web (search)
- news_feed
- dictation
- focus_session
- task_manager

### Audience C: The AI Enthusiast / Hobbyist (EARLY ADOPTER)

**Profile:**
- Follows AI developments, uses ChatGPT, tries local models
- Has a computer with moderate specs, runs Ollama or LM Studio
- Wants to understand how agents work under the hood
- Contributes to open source, files issues, wants to customize
- Values local-first, data sovereignty, open source

**Why FRIDAY fits:**
- 155 tests, well-documented architecture
- YAML personas (hackable without touching code)
- Plugin system (add your own modules)
- YAML workflow templates (define multi-step procedures)
- Runs fully offline
- Clean code with architecture docs

**Pain points FRIDAY solves:**
- ChatGPT is a black box — FRIDAY is inspectable
- Other agents don't have voice or desktop integration
- Wants to tinker and customize

**Willing to pay:** $0. Will contribute code or documentation.
Valuable for: bug reports, community growth, word-of-mouth.

**FRIDAY features they use:**
- Everything, but they'll rip it apart and rebuild it

### Audience D: The Privacy-Conscious Professional (NICHE)

**Profile:**
- Lawyer, doctor, journalist, or researcher
- Handles sensitive data that cannot be sent to cloud APIs
- Needs AI assistance but data sovereignty is non-negotiable
- Has a workstation with decent CPU, possibly a GPU
- Willing to sacrifice answer quality for privacy

**Why FRIDAY fits:**
- Fully offline capable — no data leaves the machine
- Local model inference with llama.cpp
- Document intelligence reads PDFs without uploading them
- No accounts, no telemetry, no tracking
- Audit trail for every action

**Pain points FRIDAY solves:**
- "I can't use ChatGPT — my employer's data policy forbids it"
- "I need AI to help with document analysis but can't upload to cloud"
- "I need an assistant that works on my air-gapped machine"

**Willing to pay:** $10-30/month for a polished offline experience.
Small market but high willingness to pay.

**FRIDAY features they use:**
- All features in offline mode
- document_intel
- security_tools/audit (compliance logging)
- system_control (file management)

---

## 1.2 Audience Prioritization Matrix

| Criterion | Security Researcher | Desktop Power User | AI Hobbyist | Privacy Pro |
|-----------|-------------------|-------------------|-------------|-------------|
| **Market size** | Small (~200K) | Huge (millions) | Medium | Tiny |
| **Willingness to pay** | Medium ($5-15/mo) | Low ($0-5/mo) | $0 | High ($10-30/mo) |
| **FRIDAY's advantage over competitors** | Strong (nobody does this) | Strong (nobody does this either) | Medium (many open agents) | Medium (Ollama + plugins get close) |
| **Ease of reaching them** | High (Kali forums, Reddit r/netsec, DEF CON) | Low (broad audience, high CAC) | Medium (HN, GitHub, Reddit) | Low (fragmented) |
| **Retention** | High (workflow dependency) | Low (novelty wears off) | Low (move to next project) | Medium (once set up, stays) |
| **Cloud migration benefit** | Low (want offline) | High (want speed) | Medium | None (need offline) |
| ****PRIORITY** | **#1** | **#3** | **#2** | **#4** |

**Strategic recommendation:** Build for security researchers first. The
features that make FRIDAY good for them (voice control, security tools,
audit logging, offline-capable, desktop integration) also make it good
for everyone else. But marketing to security researchers is easier and
more targeted than marketing to "desktop users" broadly.

---

# Part 2: Market Positioning & Competition

## 2.1 Competitive Landscape

| Product | Primary Use | Token Cost | Voice | Security Tools | Desktop Control | Offline | Price |
|---------|------------|-----------|-------|---------------|----------------|---------|-------|
| **FRIDAY** | Versatile assistant | High (local) | Yes | Yes | Yes | Yes | Free |
| **Hermes Agent** | CLI productivity | Low (cloud) | No | No | No | No | Free (BYOK) |
| **Claude Code** | Software development | Medium (cloud) | No | No | No | No | $20/mo |
| **ChatGPT Desktop** | General chat | Medium (cloud) | Yes (basic) | No | Limited | No | $0-20/mo |
| **Ollama** | Local model runner | N/A | No | No | No | Yes | Free |
| **Open Interpreter** | Code execution | High (local) | No | No | Partial | Yes | Free |
| **Mycroft/Neon** | Voice assistant | N/A | Yes | No | Partial | Yes | Free |

## 2.2 FRIDAY's Competitive Advantages

| Advantage | Competitors that DON'T have this |
|-----------|--------------------------------|
| Security tools (nmap, gobuster, DNS enum, audit) | Every single one |
| Hands-free voice control for desktop operations | Only ChatGPT Desktop (basic) |
| Full offline capability with local models | Only Ollama + Open Interpreter (neither has voice or security tools) |
| Plugin system for third-party extensions | Only Hermes Agent (MCP) |
| 155-test suite for a local agent | None |
| YAML persona system | Only Claude Code (CLAUDE.md, less featureful) |
| Desktop file indexing with RAG | Only ChatGPT Desktop (proprietary) |
| Wake word + STT + TTS pipeline working locally | Only Mycroft (abandoned) |

## 2.3 Where FRIDAY Cannot Compete

| Dimension | FRIDAY's problem | Competitor's advantage |
|-----------|-----------------|----------------------|
| **Token efficiency** | Infrastructure-heavy architecture | Hermes Agent: 2-3x more efficient |
| **Code generation quality** | Local models are weaker | Claude Code: purpose-built for this |
| **Git/PR workflows** | Not specialized | Claude Code: deep GitHub integration |
| **Speed of new features** | Single developer | Hermes Agent: team of engineers |
| **Startup time** | Module discovery + model loading | Hermes Agent: ~200ms |
| **API ecosystem** | Hand-rolled integrations | Both have built-in tool ecosystems |

## 2.4 The Positioning Statement

> **FRIDAY is the only AI assistant that combines voice control, security
> tools, desktop automation, and full offline capability in a single open-source
> package. It's not the fastest agent, and it's not the best at writing code.
> But it's the only one you can take into a server room, use hands-free while
> holding a screwdriver, and have it scan the network, take notes, and open
> the document you need — all without an internet connection.**

---

# Part 3: Go-To-Market Strategy

## 3.1 Channels for Each Audience

### Security Researchers (PRIORITY #1)

| Channel | Strategy | Effort | Expected Reach |
|---------|---------|--------|---------------|
| **r/netsec** | Post "I built a voice-controlled Kali assistant with nmap integration" with demo video | High | 50K+ views |
| **r/Kalilinux** | Tutorial post: "Turn Kali into Jarvis with FRIDAY" | Medium | 20K+ views |
| **r/hacking** | Cross-post from netsec | Low | 10K+ views |
| **GitHub** | Tag with kali, nmap, security-tools, voice-assistant | Low | Organic |
| **YouTube demo** | 5-min video: "FRIDAY voice-controlling nmap + generating reports" | High | 10K+ views if picked up |
| **DEF CON / BSides** | Submit to tool demo or lightning talk | Medium | Direct engagement |
| **HackerOne / Bugcrowd forums** | Post as productivity tool for pentesters | Medium | Targeted |
| **Kali documentation** | Get listed on kali.org/tools or similar | High effort | High authority |

### AI Hobbyists (PRIORITY #2)

| Channel | Strategy | Effort | Expected Reach |
|---------|---------|--------|---------------|
| **Hacker News** | "Show HN: I wrote a 76K-line AI assistant that works offline" | Low (post is free) | 100K+ if it trends |
| **r/LocalLLaMA** | "FRIDAY: fully offline voice assistant with 27 modules" | Medium | 30K+ views |
| **GitHub** | Good README, architecture docs, contribution guide | Low | Organic |
| **Twitter/X** | Short demo clips with code snippets | Medium | Variable |
| **YouTube (tech review)** | Reach out to NetworkChuck, TechnoTim, etc. | Very high | 100K+ if covered |

### Desktop Power Users (PRIORITY #3, after architecture overhaul)

| Channel | Strategy | Effort | Expected Reach |
|---------|---------|--------|---------------|
| **Product Hunt** | Launch after dual-provider + polish | Medium | 10K+ views |
| **YouTube (general tech)** | "I replaced Alexa with an AI assistant on my PC" | Very high | 50K+ if viral |
| **Reddit r/selfhosted** | "Self-hosted AI assistant that controls my desktop" | Medium | 20K+ views |
| **Reddit r/opensource** | "Open source alternative to ChatGPT Desktop" | Medium | 30K+ views |

### Privacy Professionals (PRIORITY #4, long tail)

| Channel | Strategy | Effort | Expected Reach |
|---------|---------|--------|---------------|
| **r/privacy** | "Fully offline AI assistant — no data leaves your PC" | Low | 20K+ views |
| **Tech blogs** | Pitch to Ars Technica / The Register for offline AI coverage | Very high | Variable |

## 3.2 Pricing Strategy

| Tier | Price | Features | Target Audience |
|------|-------|----------|----------------|
| **Free** | $0 | FRIDAY with local models, all modules, CLI + HUD | Everyone |
| **Cloud (bring your own key)** | $0 | Same FRIDAY, plug your own API key | Enthusiasts |
| **FRIDAY Cloud** | $5-10/mo | Hosted inference (shared queue), no hardware needed | Desktop users |
| **FRIDAY Pro** | $15-20/mo | Dedicated inference, priority support, custom personas, advanced automations | Security pros, privacy pros |
| **Enterprise** | Custom | Self-hosted cloud, audit compliance, SSO, SLA | Organizations |

**Key insight:** FRIDAY's best monetization path is NOT selling software.
It's selling **convenience**. The software is free. People pay to NOT
set up models, NOT configure dependencies, NOT troubleshoot. The hosted
inference tier sells the one thing power users don't have: time.

## 3.3 Branding & Messaging

### Taglines by audience

| Audience | Tagline |
|----------|---------|
| Security researcher | "Your Kali assistant. Voice-controlled. Offline-capable. YAML-configurable." |
| Desktop power user | "The AI assistant that actually controls your computer." |
| AI hobbyist | "27 modules, 155 tests, 100% open source. The most complete local agent." |
| Privacy pro | "ChatGPT-grade assistance. Zero data leaves your machine." |

### The FRIDAY brand identity

- **Logo:** A stylized morning star / AI symbol
- **Color:** Dark theme with cyan/blue accents (already done in HUD)
- **Tone:** Capable, honest, no-bullshit (matches your personal style)
- **Mascot:** None. FRIDAY is a tool, not a friend. Keep it professional.
- **Slogan:** "The AI assistant that does more."

---

# Part 4: The Overhaul — Phase by Phase

## Phase 0: Pre-Migration Audit (Week 1)

### What to do before changing anything

**Step 0.1: Inventory every file and categorize it**

Create a `MIGRATION_STATUS.md` tracking every Python file in the project.
Tag each as: KEEP, REMOVE, SIMPLIFY, or MERGE.

**Reason:** You have 463 files (project-only). You need to know which ones
matter before you start deleting.

**Implementation:**
```bash
cd Friday_Linux
find . -name "*.py" -not -path "./.venv/*" -not -path "*__pycache__*" > /tmp/all_files.txt
# Go through each one and tag it
```

**Step 0.2: Freeze requirements.txt**

Pin every dependency to its current version so you can revert if a cloud
provider integration breaks something.

**Reason:** The current requirements.txt is unpinned. Cloud API clients
(openai, anthropic) may conflict with llama-cpp-python versions.

**Implementation:**
```bash
pip freeze > requirements-pinned.txt
```

**Step 0.3: Run all 155 tests and record baseline**

```bash
pytest tests/ --tb=short --junitxml=test-baseline.xml
```

**Reason:** You need to know nothing broke DURING the migration.
Run tests after every phase.

**Step 0.4: Document the current latency baseline**

Measure: time from user input to response for 10 common queries.
Record the numbers. The migration should make these 5-20x faster.

---

## Phase 1: Add Cloud API as a Second Provider (Week 2, Highest ROI)

### What changes

The model layer goes from:

```
One path only: local GGUF files (0.8B + 4B)
├── llama-cpp-python inference
├── inference lock (threading.Lock per model)
├── model preloading at startup (2-10 seconds)
├── tool model called as sub-LLM for routing
└── chat model called as conversational fallback
```

To:

```
Two paths, user chooses:

┌── Local path (simplified — intent recognizer removed, stores consolidated)
│   ├── Still uses llama-cpp-python for GGUF inference
│   ├── Still loads 1 model (not 2)
│   ├── Uses same simplified Router with gated tool-calling
│   └── For users who need offline / air-gapped / privacy mode
│
└── Cloud path (NEW)
    ├── HTTP POST with messages + tools
    ├── JSON response with content + optional tool_calls
    ├── Zero startup time (no model loading)
    ├── One model handles both chat AND tool calling natively
    └── For users who want speed and quality
```

**The config toggles:**

```yaml
# config.yaml
provider:
  mode: cloud   # "cloud" | "local" | "auto" (auto = cloud with local fallback)

  cloud:
    type: openai_compat     # openai | anthropic | openrouter | opencode-zen
    base_url: https://api.opencode-zen.com/v1
    model: deepseek/deepseek-v4-flash-free
    max_tokens: 8192

  local:
    model: models/Qwen3.5-4B-Q4_K_M.gguf
    n_gpu_layers: 0
    max_tokens: 2048
```

The "auto" mode is interesting: try cloud first, if network is unavailable
or API returns an error, fall back to local. Gives privacy users the best
of both worlds — cloud quality when possible, offline when not.

**Why NOT just replace local?**
Security researchers need air-gap operation. Privacy professionals legally
can't send data to external APIs. Users in field operations (pentesting)
may not have internet. Killing local inference would lose those audiences.

**What DID I do wrong in the first version of this document?**
I called this "Swap the Model" and implied cloud would replace local. That's
wrong. Cloud is an ADDITIONAL mode, not a replacement. The simplification
work (intent recognizer deletion, store consolidation, planning engine
removal) benefits BOTH modes. This is important.

### Implementation

**Step 1.1: Create a provider abstraction with multiple backends**

New file: `core/provider.py`

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Message:
    role: str          # "user" | "assistant" | "tool" | "system"
    content: str       # text content (can be empty if tool_calls)
    tool_calls: list[dict] | None = None  # populated by assistant messages
    tool_call_id: str | None = None       # populated by tool messages

@dataclass
class ProviderResponse:
    content: str
    tool_calls: list[dict] | None = None
    usage: dict | None = None  # {"prompt_tokens": N, "completion_tokens": N}

class LLMProvider(ABC):
    @abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> ProviderResponse:
        ...

class OpenAICompatProvider(LLMProvider):
    """Works with: OpenAI, OpenRouter, DeepSeek, Together, Groq, vLLM, etc."""
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.session = httpx.AsyncClient()

    async def chat(self, messages, tools=None, **kwargs):
        body = {
            "model": self.model,
            "messages": [m.__dict__ for m in messages],
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.3),
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        resp = await self.session.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]
        return ProviderResponse(
            content=msg.get("content", "") or "",
            tool_calls=msg.get("tool_calls"),
            usage=data.get("usage"),
        )
```

**Step 1.2: Update config.yaml with dual-provider structure**

```yaml
# FRIDAY v2.0 — Dual-provider configuration
# Choose cloud for speed, local for offline/privacy.

provider:
  mode: cloud           # "cloud" | "local" | "auto"

  cloud:
    type: openai_compat # openai | anthropic | openrouter | opencode-zen | together | groq
    base_url: https://api.opencode-zen.com/v1
    model: deepseek/deepseek-v4-flash-free
    api_key_env: FRIDAY_API_KEY  # reads from this env var or .env
    max_tokens: 8192
    temperature: 0.3
    timeout_s: 30

  local:
    model: models/Qwen3.5-4B-Q4_K_M.gguf
    n_gpu_layers: 0
    context_length: 8192
    max_tokens: 2048
    temperature: 0.3
```

**Step 1.3: Update model_manager.py**

The ModelManager becomes a provider router:
- Check `provider.mode` in config
- If mode is "cloud" or "auto": instantiate cloud provider, test connection
- If mode is "local": load the local GGUF model (simplified — no dual-model loading)
- If mode is "auto": try cloud first, fall back to local on failure
- Remove: dual-model preloading, 0.8B tool model, inference locks per model
- Keep: local llama-cpp-python inference for when mode is "local" or cloud fails

**Why not remove local inference entirely?**
Because killing local mode kills your core audience. Security researchers
who work air-gapped or in the field NEED local. Privacy pros legally
CANNOT use cloud APIs. Keep local as a first-class mode. Just simplify it.

**What makes sense after:**
- Cloud mode: answer quality goes from "occasionally coherent" to
  "competitive with ChatGPT"
- Local mode: still slower, still lower quality — but the architecture is
  now clean, maintainable, and 50% less code
- "Auto" mode: best of both worlds — try cloud, fall back to local
- Latency in cloud mode drops from 10-30s to 1-3s for typical queries
- Latency in local mode stays the same but the code is simpler

**Files to modify:**
- `core/model_manager.py` (rewrite to dual-provider router, ~80 lines)
- `core/config.py` (add dual-provider config structure)
- `config.yaml` (add dual-provider structure)
- `.env` or `.env.example` (add FRIDAY_API_KEY)

**Files to keep (local inference is still a valid mode):**
- `core/llm_providers/` — keep local providers, wrap them behind the same
  LLMProvider interface used by cloud providers
- `core/mixture_of_agents.py` — only remove if you're sure you won't use it

---

## Phase 2: Kill the Intent Recognizer (Week 2, Day 2-3)

### What changes

The 3,295-line `core/intent_recognizer.py` goes from:
```
Input text
  → normalize_for_routing()
  → _clean_text()
  → _is_knowledge_question() (43-line regex)
  → _split_into_clauses()
  → _parse_clause() (calls 20+ parser methods)
    → _parse_system_action, _parse_file_action, _parse_launch_action,
      _parse_vision_action, _parse_research_action, _parse_web_action,
      _parse_weather_action, _parse_smart_home_action, ...
  → Returns list of actions or []
```

To:
```
Nothing. Deleted.
```

Modern model tool-calling replaces every single regex parser. The model
sees tool definitions with names, descriptions, and parameter schemas.
When the user says "open Firefox," the model sees the Firefox icon and
returns `tool_calls=[{"name": "launch_app", "args": {"app_name": "firefox"}}]`.

**Why this works:** The intent recognizer existed because the 4B local
model couldn't reliably produce tool calls. With a capable model — EITHER
a strong local model (LLaMA 3, Qwen 2.5 7B+) OR a cloud model with
function calling — the regex parser is unnecessary.

**This benefits BOTH modes:**
- **Cloud mode:** The cloud model's native tool-calling API handles routing
  with ~99% accuracy. No regex needed.
- **Local mode:** Even if local tool-calling is less reliable, a simpler
  fallback (a single "gated parse" that matches a few keywords) is more
  maintainable than the 3,295-line regex behemoth. And if you upgrade to
  a 7B+ local model with function-calling support, the regex is just dead
  weight either way.

**What makes sense after:** 
- 3,295 lines of regex you don't maintain anymore
- No more false positives from pattern matching
- No more "STT typo correction" normalization pipeline
- No more `_resolve_references()` for pronoun resolution
- Adding a new tool = adding a JSON schema, not writing a parser

**What to do instead of the intent recognizer:**

Create a `TOOL_DEFINITIONS` constant (single file, ~200 lines):

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "Launch a desktop application by name. "
                           "Handles any app installed on the system.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Application name to launch, e.g. 'firefox', 'terminal'"
                    }
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files on the filesystem by name or content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Filename or content to search for"
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional directory to search in (default: home)"
                    }
                },
                "required": ["query"]
            }
        }
    },
    # ... one entry per capability, ~50 entries
]
```

Each tool definition is ~15 lines of JSON. Total: ~750 lines.
That replaces 3,295 lines of Python.

**Note:** Keep the tool handler CALLBACKS (the actual Python functions
that do the work). Those are in `modules/` and are well-written. Just
remove the REGEX that routes to them.

**Files to remove:**
- `core/intent_recognizer.py` (3,295 lines)
- `core/intent_recognizer.py` is imported by `core/router.py` — you
  must update the import

**Files to modify:**
- `core/router.py` (massive simplification, see Phase 3)
- `core/planning/intent_engine.py` (112 lines — replace with simple
  tool-call dispatch or remove entirely)

---

## Phase 3: Replace the Router (Week 2, Days 3-5)

### What changes

Current router.py (1,113 lines):

```
CommandRouter.process_text(text)
  → normalize_for_routing()
  → _find_best_route() [deterministic matching]
  → _plan_actions() [intent recognizer call]
  → _try_embedding_route() [semantic fallback]
  → _infer_with_tool_llm() [4B model for tool selection]
  → _keyword_fallback() [regex routing]
  → _continue_active_workflow() [workflow check]
  → llm_chat fallback
```

New router.py (~200 lines):

```python
class Router:
    """Routes user input to tools via cloud model tool-calling."""

    def __init__(self, provider: LLMProvider, tool_executor, tools: list[dict]):
        self.provider = provider
        self.tool_executor = tool_executor
        self.tools = tools
        self.context_builder = ContextBuilder()

    async def route(self, text: str, session_id: str) -> str:
        # 1. Build message history
        messages = self.context_builder.build(text, session_id)

        # 2. Call model with tool definitions
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools,
            max_tokens=4096,
        )

        # 3. Handle tool calls (loop until model responds with text)
        while response.tool_calls:
            for call in response.tool_calls:
                result = await self.tool_executor.execute(
                    call["function"]["name"],
                    json.loads(call["function"]["arguments"]),
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                })
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools,
            )

        # 4. Return final text response
        self.context_builder.save(text, response.content, session_id)
        return response.content
```

That's it. ~35 lines of actual logic. No routing chain. No fallback stack.
No intent recognition. No embedding layer. No lexical layer. No tool model
sub-call. No workflow pre-emption. No multi-action plan detection.

The model handles ALL of that.

**Why this works:**
- In CLOUD mode: the cloud model validates tool arguments, produces
  native tool_calls in JSON, handles multi-step sequences. All the
  routing layers are dead weight.
- In LOCAL mode: a simpler Router with a single gated fallback
  (not 7 stages) is easier to maintain. If the local model can't
  produce tool calls, try a single keyword match. If that fails,
  fall back to chat-only mode. That's 2 fallback stages, not 7.

**What makes sense after:**
- 900 lines of routing logic disappear
- No more `RoutingDecision` / `RoutingState` state machine
- No more `route_scorer.py`, `embedding_router.py`, `lexical_router.py`
- Adding a new tool = adding a JSON schema to the TOOLS list
- Latency drops from multiple round-trips to 1-2 API calls

**Files to remove:**
- `core/embedding_router.py` (semantic fallback is unnecessary)
- `core/lexical_router.py` (the model understands typos)
- `core/route_scorer.py` (was choosing between models)
- `core/routing_tuner.py` (was tuning thresholds for weak models)
- `core/routing_state.py` (state machine for routing decisions)
- `core/text_normalize.py` (STT typo correction — model handles this)

**Files to modify:**
- `core/router.py` (rewrite from 1,113 to ~200 lines)
- `core/tool_catalog.py` (simplify — now just format tool definitions
  for the API, not for multiple routing systems)

**Files to keep (for now):**
- `core/response_finalizer.py` — still useful for post-processing
- `core/tool_result.py` — still useful for classifying tool output

---

## Phase 4: Strip the Planning Engine (Week 3)

### What changes

The entire `core/planning/` directory (7 files, ~1,600 lines) goes from:

```
TurnOrchestrator.handle()
  → _build_context_bundle()
  → try_resume_workflow()
  → IntentEngine.classify()
  → PlannerEngine.plan()
    → QwenPlanner.plan() (if use_qwen_planner)
    → or CapabilityBroker.build_plan()
  → ContextResolver.try_rescue()
  → PlanValidator.validate()
  → PlanRepair.try_repair()
  → execute()
  → _curate_memory()
```

To:

```
route() [from Phase 3]
  → provider.chat(messages, tools)
  → tool_executor.execute(call)
  → provider.chat(messages + tool_result)
  → response.content
```

The planning engine is replaced by the ROUTER (which works with either
provider). In cloud mode, the model selects, validates, and sequences
tools natively. In local mode, the simplified Router tries tool-calling
and falls back gracefully. In neither case do you need 7 planning files.

**Why this works:**
- The model selects tools. It doesn't need a QwenPlanner to tell it
  which tool to call.
- The model validates arguments. It doesn't need PlanValidator to
  check if the app name exists.
- The model handles context. It doesn't need ContextResolver to
  resolve "it" to "the file I just read."
- The model recovers from errors. If a tool fails, the model sees the
  error and retries or explains. No PlanRepair needed.

**What makes sense after:**
- No more QWEN_PLANNER_TIMEOUT_MS config (irrelevant)
- No more `routing.use_qwen_planner`, `routing.use_replanning` config
- No more `max_workflow_steps`, `max_step_retries` config
- No more `tool_json_response: true` hack (native tool-calling is better)
- No more `routing.execution_engine: parallel` (the model sequences calls)
- No more `/no_think` prompt injection (Qwen3-specific hack)

**What to keep from planning/:**
- `core/planning/schemas.py` — if it defines data structures used elsewhere
- `core/planning/observation.py` — if it's useful for tool result tracking
- Everything else: delete

**Files to remove:**
- `core/planning/planner_engine.py`
- `core/planning/intent_engine.py`
- `core/planning/qwen_planner.py`
- `core/planning/replan_controller.py`
- `core/planning/plan_validator.py`
- `core/planning/plan_repair.py`
- `core/planning/context_resolver.py`
- `core/planning/workflow_coordinator.py`
- `core/planning/workflow_coordinator.py` (workflow_state_manager etc.)
- `core/planning/turn_orchestrator.py` (replaced by simple Router)
- `core/planning/slot_extractors.py`
- `core/planning/json_repair.py` (the model outputs valid JSON natively)

**Note about workflows (YAML templates):**
The YAML workflow templates in `core/workflows/templates/` are actually
a good feature. Keep them, but make them OPTIONAL guides:
- A workflow YAML becomes a suggested tool sequence
- The model can FOLLOW the workflow or improvise
- This is superior to the current hard-coded LangGraph execution

Simplify `core/workflow_orchestrator.py` from 1,042 lines to ~100 lines
that just load and format the YAML into the system prompt.

---

## Phase 5: Unify Memory (Week 3-4)

### Current architecture (highly fragmented)

```
MemoryBroker
  → ContextStore (transitional facade, being extracted)
    → SessionStore (turns + sessions)
    → AuditStore (audit log)
    → WorkflowStore (workflows)
    → MemoryStore (facts + Chroma vector index)
    → KnowledgeGraphStore (entities + relationships)
    → GoalStore (goals)
    → IntentLearningStore (routing history)
  → MemoryFacade (writes through SemanticMemory)
    → SemanticMemory (key-value facts in SQLite)
    → _(mirrors to PersonaManager user_profile)_
  → Mem0 (REST service on port 8181 — PARALLEL store!)
  → PersonaManager (user profile from YAML + facts)

EpisodicMemory (turn recall)
ProceduralMemory (how-to knowledge)
```

### Target architecture

```
MemoryBroker (simplified)
  → SQLite Database (single connection)
    → sessions (session metadata)
    → turns (turn history with FTS5 search)
    → facts (key-value user facts with FTS5)
    → audit (audit log)
    → artifacts (working state)
```

**Implementation details:**

**Step 5.1: Create a single Database class**

```python
# core/database.py — ~200 lines

import sqlite3
import json
from pathlib import Path

class Database:
    def __init__(self, db_path: str = "data/friday.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()
        self._lock = threading.Lock()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                summary TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL,  -- 'user' | 'assistant' | 'tool'
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
                content, content=turns, content_rowid=id
            );

            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                session_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                source TEXT DEFAULT 'user',
                UNIQUE(key, session_id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                key, value, content=facts, content_rowid=id
            );

            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp REAL NOT NULL,
                details TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                type TEXT NOT NULL,  -- 'file' | 'search_result' | 'scan_result'
                data TEXT NOT NULL,  -- JSON payload
                created_at REAL NOT NULL,
                expires_at REAL
            );
        """)
```

**Why this replaces 8 store objects:**
- One connection = one set of transactions = no cross-store consistency bugs
- FTS5 is built into SQLite — no ChromaDB, no sentence-transformers
- The `metadata` JSON column stores anything the old stores tracked
- Simpler queries: `SELECT ... JOIN` instead of 8 facade method calls
- 200 lines instead of ~5,000 lines across 8 store files

**Step 5.2: Remove ChromaDB**

ChromabDB requires: `sentence-transformers/all-MiniLM-L6-v2` (90MB model),
Chroma server process, separate index directory (`data/chroma/`), and
the `chromadb` pip package.

Replace with SQLite FTS5:
- FTS5 does full-text search on facts and turn content
- Model does semantic matching (it already reads the text)
- For RAG queries, the model decides relevance — not a vector score

**When to keep ChromaDB (the honest answer):**
Only if you're indexing 10,000+ documents. For a personal assistant with
~500 documents and ~200 user facts, FTS5 is faster and simpler.

**Step 5.3: Remove Mem0**

Mem0 runs an HTTP server on port 8181. It's a parallel store that the
facade explicitly ignores. Kill it. Delete `scripts/start_mem0_server.sh`.

**Step 5.4: Simplify MemoryBroker**

Current `core/memory_broker.py` (160 lines) aggregates across:
- Persona manager (facts)
- ContextStore (session context)
- MemoryService (Mem0 + curated facts)
- Recent turns

New MemoryBroker (~50 lines):
```python
class MemoryBroker:
    def build_context(self, text: str, session_id: str) -> dict:
        db = self.database

        # Get recent turns for context
        recent = db.query(
            "SELECT role, content FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT 10",
            (session_id,)
        )

        # Get relevant facts
        facts = db.query(
            "SELECT key, value FROM facts WHERE session_id = ? ORDER BY updated_at DESC LIMIT 20",
            (session_id,)
        )

        return {"turns": recent, "facts": facts}
```

**What stays from the old memory system:**
- `MemoryFacade` (it's well-designed for a simple use case) — keep but
  simplify to just wrap the Database class
- `memory_nudger.py` (useful for proactive memory suggestions) — keep

**What's removed:**
- `core/memory/semantic.py` (functionality merged into Database)
- `core/memory/episodic.py` (functionality merged into turns table)
- `core/memory/procedural.py` (not needed with capable model)
- `core/memory/graph.py` (knowledge graph was over-engineered)
- `core/memory/embeddings.py` (ChromaDB dependency removed)
- `core/stores/` directory (all 9 files, consolidated)
- `core/memory_service.py` (Mem0 integration removed, simplify to
  wrapper over MemoryBroker)
- ContextStore (the transitional facade) — finally delete it

**What makes sense after:**
- Startup time: no ChromaDB connection, no sentence-transformers load
- Memory: ~200MB saved (Chroma + sentence-transformers + Mem0 process)
- Simplicity: one store class, one connection, one schema
- The "Nellore vs Nolo-re" bug (different spellings in different stores)
  never happens again — there's only one store

---

## Phase 6: Clean the Module System (Week 3-4)

### What changes

Current: 27 modules loaded via PluginManager scanning `modules/` directory.

Problem: Modules are inconsistent. Some export `setup(app)`, some export
a class. Some are extensions (greeter, onboarding), some are plugins. Some
register tools on init, some on a separate method.

**Step 6.1: Standardize module interface**

Every module must:
1. Export `def setup(app) -> ModuleInstance | None`
2. Register tools via `app.register_tool(spec, handler)` in setup
3. Be individually enable/disable-able in config.yaml

**Step 6.2: Make module loading lazy**

Current: all 27 modules load and initialize at startup, even disabled ones.

Target: load only enabled modules. Gate on `config.yaml`:
```yaml
modules:
  security_tools:
    enabled: true
  smart_home:
    enabled: false  # skip loading if no smart home setup
  voice_io:
    enabled: true
  browser_automation:
    enabled: true
  # etc.
```

**Step 6.3: Convert tool registration from regex to JSON schema**

Every module currently registers tools with:
```python
self.app.router.register_tool({
    "name": "launch_app",
    "description": "...",
    "parameters": {"app_name": "..."},
    "aliases": [...],       # legacy
    "patterns": [...],      # legacy
    "context_terms": [...], # legacy
})
```

Change to:
```python
self.app.register_tool({
    "name": "launch_app",
    "description": "...",
    "parameters": {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "App name"}
        },
        "required": ["app_name"]
    }
})
```

**Why:** The cloud model's tool-calling API uses this exact JSON schema format.
Remove the `aliases`, `patterns`, `context_terms` fields — those were for the
regex intent recognizer.

**Step 6.4: Merge overlapping modules**

| Current modules | Merge into | Reason |
|----------------|-----------|--------|
| `sources` + `web` + `news_feed` + `world_monitor` | `web_and_feeds` | All do network content fetching |
| `dictation` + `voice_io` | `voice` | Dictation is voice input mode |
| `focus_session` + `task_manager` + `goals` | `productivity` | All manage user workflow |
| `workspace_agent` + `sources` | part of core | Thin enough to inline |
| `greeter` + `onboarding` | `onboarding` | Both are first-run experience |

**Result:** 27 modules → ~18 modules. Less code, clearer boundaries.

**Step 6.5: Remove modules that don't work or aren't needed**

| Module | Problem | Action |
|--------|---------|--------|
| `mcp_client` | Partially implemented, no config | Remove until MCP support is needed |
| `comms` (Telegram/SMS) | Requires API keys, fragile | Remove or make optional with clear docs |
| `awareness` | OCR-based screen capture, high overhead | Simplify to a screenshot-on-demand tool |
| `triggers` | File-system watchers, partially implemented | Remove until stable |

---

## Phase 7: Voice Pipeline Simplification (Week 4)

### Current: 4,088 lines across 12 files

```
voice_io/
├── __init__.py
├── audio_devices.py    (357 lines)
├── clap_detector.py    (690 lines)
├── plugin.py           (245 lines)
├── register_autostart.py (136 lines)
├── register_wake.py    (163 lines)
├── safety.py           (45 lines)
├── stt.py              (1,613 lines)
├── tts.py              (464 lines)
├── voice_mode.py       (138 lines)
├── wake_detector.py    (66 lines)
└── wake_porcupine.py   (167 lines)
```

### Target: ~800 lines across 4 files (dual-mode: cloud or local)

**The voice module should work in TWO modes:**

1. **Cloud STT/TTS (default when online):** Fast, high-quality, near-human
   voice. STT via OpenAI Whisper API or Deepgram (~$0.006/min). TTS via
   OpenAI TTS or ElevenLabs.
2. **Local STT/TTS (offline/privacy mode):** Whisper-tiny or whisper-base
   for STT, Piper or pyttsx3 for TTS. Slower, lower quality, but works
   without internet.

**What changes:**

**STT:** The current 1,613-line STT module is excessive regardless of mode.
Simplify to:

```python
# voice/engine.py — ~200 lines total

from abc import ABC, abstractmethod

class STTEngine(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> str: ...

class CloudSTT(STTEngine):
    """OpenAI Whisper API or compatible. ~50 lines."""
    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1", file=f, language="en",
            )
        return transcript.text

class LocalSTT(STTEngine):
    """Whisper-tiny via faster-whisper. ~80 lines."""
    def __init__(self, model_size: str = "tiny"):
        self.model = WhisperModel(model_size, device="auto")

    def transcribe(self, audio_path: str) -> str:
        segments, _ = self.model.transcribe(audio_path, beam_size=1)
        return " ".join(seg.text for seg in segments)
```

**Keep local fallback** for offline mode (privacy users). But make it
a simple import, not 1,600 lines of VAD/noise/beam-search configuration.

**TTS:** Same dual-mode approach. Cloud TTS for speed/quality (OpenAI TTS,
ElevenLabs, or any compatible). Local TTS (Piper, pyttsx3) for offline use.

```python
# voice/engine.py (continued) — ~60 lines for TTS

class TTSEngine(ABC):
    @abstractmethod
    def speak(self, text: str): ...

class CloudTTS(TTSEngine):
    """OpenAI TTS or compatible. ~30 lines."""
    def speak(self, text: str):
        response = self.client.audio.speech.create(
            model="tts-1", voice="alloy", input=text,
        )
        response.stream_to_file("/tmp/friday_tts.mp3")
        subprocess.run(["ffplay", "-nodisp", "-autoexit", "/tmp/friday_tts.mp3"],
                      capture_output=True)

class LocalTTS(TTSEngine):
    """Piper TTS or pyttsx3 fallback. ~40 lines."""
    def speak(self, text: str):
        # Try Piper first, fall back to pyttsx3
        ...
```

**Wake word:** Keep local (openWakeWord or Porcupine runs at <1% CPU).
This is the one part of the voice pipeline that SHOULD be local — wake
word detection needs to work without a network round-trip.

**Files to remove/simplify:**
- `clap_detector.py` (690 lines) — clap detection is a novelty, not a
  core feature. Make it a 50-line optional module.
- `stt.py` (1,613 lines) → 80 lines (cloud) + 200 lines (local fallback)
- `tts.py` (464 lines) → 60 lines (cloud) + 100 lines (local fallback)
- `register_autostart.py` / `register_wake.py` — keep but move to a
  single `voice/setup.py`

**What makes sense after:**
- Voice quality goes from "robotic, slow" to "near-human, fast"
- STT accuracy goes from "frequent errors with small Whisper model"
  to "industry-best (Whisper API / Deepgram)"
- 3,200 lines of code disappear
- Latency per voice query drops from 5-15s to 1-3s

---

## Phase 8: GUI Removal or Repurpose (Week 4-5)

### What changes

The PyQt6 HUD (2,878 lines) has impressive visuals (gradients, glow effects,
animated rings). But it adds:
- 50MB+ dependency (PyQt6 + Qt shared libraries)
- ~2 seconds startup time
- Desktop-environment coupling (won't run headless)
- Sound device enumeration that requires PipeWire/WASAPI

**Option A: Remove GUI entirely (for server/headless/fast-startup use)**

If FRIDAY runs on a server, SSH session, or Kali with no desktop environment:
move to CLI-only. Use `prompt-toolkit` (already a dependency) for:
- Rich terminal output with colored response rendering
- Streaming token display (typewriter effect for cloud responses)
- Command history with up/down arrow
- Auto-completion for slash commands
- Status bar showing current tool execution

```python
# cli/main.py — ~150 lines

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

class FridayCLI:
    def run(self):
        session = PromptSession(history=FileHistory(".friday_history"))
        while True:
            text = session.prompt("FRIDAY> ")
            if text.strip() in ("exit", "quit"):
                break
            response = self.router.route(text, self.session_id)
            self._print_streaming(response)

    def _print_streaming(self, response: str):
        for char in response:
            print(char, end="", flush=True)
            time.sleep(0.02)  # typewriter effect
        print()
```

**Option B: Keep GUI but strip it to essentials (for desktop Kali/Windows users)**

If FRIDAY runs on a desktop where the HUD provides real value (visual status,
voice mode indicator, quick input), keep it but simplify:
- Gradient backgrounds and glow effects (static theming is fine)
- Audio device selector (use CLI flag or config)
- Animated router indicators (not useful)
- Event stream (use log file instead)
- Theme toggling (one theme, dark)

Keep in the HUD:
- Text input field
- Response display (scrollable)
- Simple conversation list
- Status indicator (processing/idle/listening)

**Result:** 2,878 lines → ~800 lines.

**What makes sense after:** Faster startup, smaller dependency tree,
works in headless/SSH environments, easier to maintain.

---

## Phase 9: Simplify Security (Week 5)

### What changes

Current security is scattered across 4+ files:
- `core/safety/tool_guardrails.py` — checks tool calls before execution
- `core/safety/website_policy.py` — URL whitelisting
- `core/safety/url_safety.py` — URL validation
- `core/safety/path_security.py` — filesystem path validation
- `core/approval.py` — user consent for actions
- `core/kernel/consent.py` — consent service
- `core/kernel/permissions.py` — permission service
- `modules/security_tools/safety.py` — additional checks

**The problem:** Every layer adds latency and complexity. Most of these
exist because the local model couldn't be trusted to make safe decisions.

**Target: Trust but verify**

1. **System prompt security rules** (handled by model):
   - "Never execute destructive operations without explicit confirmation"
   - "Ask before accessing any external URL"
   - "Do not read files outside user's home directory"
   - "Do not execute commands as root"

2. **Code-level enforcement** (only where necessary):
   - `PathSecurity` — filesystem access is code-enforceable
   - `approval.py` — user consent dialog is UI, not security

3. **Remove redundant layers**:
   - `ToolGuardrails` — cloud model follows tool descriptions
   - `URLSafety` — prompt rules cover this
   - `WebsitePolicy` — replaced by model judgment
   - `ConsentService` — simplify to a 50-line consent check
   - `PermissionService` — simplify to a 30-line permission check

**What stays:**
- `PathSecurity` — actual filesystem isolation
- `approval.py` — user consent flow (simplified)

**What makes sense after:**
- ~1,000 lines of security code removed
- A capable model makes better safety decisions than hand-rolled guardrails,
  regardless of whether it runs locally or in the cloud
- Less code = fewer bugs in the security layer itself

---

## Phase 10: Audit Trail & Observability (Week 5)

### What changes

Current: `AuditStore` (separate store, writes every action to `audit_events` table).

Keep it but simplify: the audit trail is genuinely valuable for security
researchers. Every tool execution, every approval, every error should be
logged.

**New audit approach:**

```python
# core/audit.py — ~80 lines

class AuditLogger:
    def log(self, session_id: str, action: str, details: dict):
        self.db.execute(
            "INSERT INTO audit (session_id, action, timestamp, details) VALUES (?, ?, ?, ?)",
            (session_id, action, time.time(), json.dumps(details)),
        )

    def get_report(self, session_id: str) -> list[dict]:
        return self.db.query(
            "SELECT * FROM audit WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        )
```

This replaces:
- `AuditStore` (extracted facade)
- `core/audit_trail.py`
- Security audit log file writer

**What makes sense after:** One audit function, one table, one interface.
The audit data is accessible for both the user (review) and the model
(context injection when the user asks "what did I do last session?").

---

## Phase 11: The Delegation & Sub-Agent System (Week 5-6)

### What changes

Current: 4 separate delegation mechanisms, none of which actually spawn
independent agents.

**Target:** One tool-based delegation mechanism.

```python
TOOLS.append({
    "type": "function",
    "function": {
        "name": "delegate_sub_task",
        "description": "Run a complex sub-task in an isolated agent with"
                       "its own tools and context. Use for: research,"
                       "complex file operations, multi-step fact-finding.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "Clear description of what the sub-agent should accomplish"
                },
                "context": {
                    "type": "string",
                    "description": "Background information, file paths, URLs the sub-agent needs"
                },
                "toolsets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools the sub-agent can use: web, file, terminal"
                }
            },
            "required": ["goal"]
        }
    }
})
```

**Handler:**
```python
async def handle_delegation(goal: str, context: str = "", toolsets: list = None):
    """Spawn a sub-agent to handle a complex task."""
    # Create a new agent session with its own context
    sub_session = await self.sub_agent_manager.spawn(
        goal=goal,
        context=context,
        tools=toolsets or ["web", "file"],
    )
    # Run until completion or timeout
    result = await sub_session.run(timeout_sec=120)
    return result.summary
```

**Remove:**
- `core/delegate.py` (threading hack, 83 lines)
- `core/mixture_of_agents.py` (MoA doesn't help with one strong model)
- `modules/research_agent/` (3,510 lines) — the model does research
  inline using web search tools. No need for a separate research mode.
  If deep research is needed, THAT becomes a delegation call.
- `modules/research_agent/quick.py`, `deep.py`, `searxng_client.py`
  — all replaced by tool-calling.
- `core/reasoning/agentic_services/` (research_planner, research_mode,
  focus_mode) — the model handles focus. Tell it "focus on X" and it does.

**What makes sense after:**
- One delegation mechanism instead of 4 partial implementations
- Research happens through web search tools + model reasoning
- The model decides WHEN to delegate (not hard-coded "modes")
- The research_agent module (3,510 lines) collapses to a single
  `web_search` tool + `delegate_sub_task` tool — ~100 lines of handler

---

## Phase 12: The Scheduler & Triggers (Week 6)

### What changes

Current: `core/scheduler.py` (cron-like task scheduling). Keep it — it's
valuable for security researchers ("scan the network every hour") and
desktop users ("remind me at 3pm").

Simplify the interface:
- Remove the `core/lock_monitor.py` (desktop lock detection — only useful
  if the GUI is running)
- Remove the `core/screen_lock.py` (same reason)
- Remove `modules/triggers/` (filesystem watchers — too fragile)

Target: Scheduler works with the simplified Database to store scheduled
tasks. When a task triggers, it calls the Router with the task prompt.

---

# Part 5: What Makes FRIDAY "Best in Segment"

## 5.1 The FRIDAY Differentiators (Post-Migration)

After the migration, FRIDAY has a unique feature set that NO OTHER agent
matches:

### Category A: Exclusively FRIDAY (No competitor has this)

| Feature | What it does | Why it matters |
|---------|-------------|----------------|
| **Voice-controlled nmap scanning** | "Friday, scan 192.168.1.0/24 for open ports" via voice | Pentesters keep hands on tools while scanning |
| **Security audit trail** | Every tool execution logged with scope + timestamp | Compliance, after-action reports |
| **Structured security observations** | nmap output → parsed JSON with hosts, ports, services | Can feed into reports or other tools |
| **YAML workflow templates** | Pre-defined multi-step procedures (DNS enum, web recon, network inventory) | Reproducible security methodology |
| **Desktop app launching by voice** | "Open Firefox, VS Code, and terminal" | Productivity, accessibility |
| **Voice dictation mode** | Continuous voice-to-text for writing | Accessibility, note-taking |
| **File indexing + RAG offline** | Index local PDFs/DOCX and answer questions about them | Privacy researchers, document-heavy professions |
| **Focus session timer** | Timed productivity sessions with voice control | ADHD, remote workers |
| **Goal tracking** | Set goals, track progress, check in via voice | Personal productivity |

### Category B: FRIDAY Does It Better (Competitors have it, FRIDAY's version
is more complete or more flexible)

| Feature | Competitors | FRIDAY's Advantage |
|---------|------------|-------------------|
| **Desktop control** | ChatGPT Desktop: limited | Screenshots, app launch, file management, brightness, volume — everything |
| **Plugin system** | Hermes Agent: MCP (external services) | FRIDAY: self-contained Python plugins, easier to write |
| **Personas** | Claude Code: CLAUDE.md (single file) | FRIDAY: YAML with tone, dos/donts, verbosity, formality, humor level |
| **Offline mode** | Ollama: yes, but no voice/tools | FRIDAY: offline WITH voice + tools + security scanning |
| **Cross-platform** | Most: Linux only | FRIDAY: Windows + Linux with setup scripts |
| **Test coverage** | Hermes: moderate. Claude: unknown | FRIDAY: 155 tests, 29K lines |

### Category C: Parity (FRIDAY matches competitors after migration)

| Feature | After migration |
|---------|----------------|
| **Answer quality** | Equal (same cloud models available) |
| **Tool-calling accuracy** | Equal (uses same API function calling) |
| **Latency** | Close (within 500ms for typical queries) |
| **Token efficiency** | Worse (heavier system prompt due to tool count) |
| **Browser automation** | On par (Playwright/Selenium — both work similarly) |
| **Web search** | On par (DuckDuckGo or Google API) |

## 5.2 The "Unfair Advantages"

These are things that can't be easily replicated by competitors:

1. **You're on Kali.** FRIDAY is built for and tested on Kali Linux.
   This is an accident of your development environment, but it's a
   moat. Nobody else's agent has nmap integration because nobody else
   has a Kali user as the developer.

2. **You know security.** The security tools module isn't a toy — it
   has nmap XML parsing, gobuster JSON parsing, dig output parsing,
   structured observations, scope enforcement, audit logging. A general
   agent like Hermes Agent COULD add nmap support. But it would need
   someone who understands pentesting to write it well.

3. **Voice + security.** No other agent combines voice control with
   security tools. Voice control for "scan the network" is a killer
   feature for physical pentesting. Nobody else is doing this.

4. **Cross-platform from day one.** FRIDAY has Windows PowerShell setup
   AND Linux bash setup. Claude Code is VS Code/JetBrains only. Hermes
   Agent is Linux-focused. FRIDAY runs on Windows, Linux, and potentially
   macOS with minor work.

## 5.3 Features to ADD for Best-in-Segment

These are gaps to fill for each audience:

### For Security Researchers (must-have)

| Feature | Priority | Implementation |
|---------|----------|---------------|
| **One-command Kali install** | P0 | Single bash command: `curl -sSL https:// getfriday.ai | bash` |
| **Report generator** | P0 | Convert structured scan data → markdown report with templates |
| **Results dashboard** | P1 | Terminal UI showing scan history, open ports per host, trends |
| **Multi-target scan orchestration** | P1 | Scan a list of targets sequentially, aggregate results |
| **CVE lookup integration** | P1 | "Friday, what CVEs affect Apache 2.4.49?" → search + read |
| **Exploit suggestion** | P2 | "Friday, what exploits exist for port 445?" |
| **MITRE ATT&CK mapping** | P2 | Map detected services/ports to ATT&CK techniques |
| **Session replay** | P2 | Replay an entire pentest session from audit log |

### For Desktop Power Users (nice-to-have)

| Feature | Priority | Implementation |
|---------|----------|---------------|
| **Clipboard integration** | P0 | "Friday, copy this to clipboard" |
| **Email integration** | P1 | "Friday, send an email to John about the meeting" |
| **Calendar integration** | P1 | "Friday, what's on my calendar today?" |
| **Ambient mode** | P2 | "Friday, what time is it?" without wake word (always-listening) |
| **Multi-monitor support** | P2 | "Friday, take a screenshot of monitor 2" |
| **Custom hotkeys** | P2 | Configurable keyboard shortcuts to trigger actions |

### For Platform Health (important for all users)

| Feature | Priority | Implementation |
|---------|----------|---------------|
| **Health check command** | P0 | `friday doctor` that checks all dependencies and config |
| **Auto-update** | P1 | `friday update` that pulls latest code and re-installs deps |
| **Error reporting** | P1 | When a tool fails, log the error with context for debugging |
| **Usage analytics (opt-in)** | P2 | "Most used tools" report for prioritization |
| **Backup/restore** | P2 | Database export + import for migration |

---

# Part 6: Implementation Timeline

## Phase Overview

```
Week 1:  [Pre-Audit]                Inventory, freeze deps, baseline tests
Week 2:  [Dual Provider + Routing]  Add cloud API support, simplify routing layers
Week 3:  [Memory + Planning]        Unify database, remove planning engine (benefits both modes)
Week 4:  [Modules + Voice]          Standardize modules, dual-mode voice (cloud + local)
Week 5:  [Security + Audit]         Simplify guardrails, consolidate audit
Week 6:  [Delegation + Polish]      Sub-agent system, scheduler fixes
Week 7:  [Docs + Launch]            README, docs, marketing, v2.0 release
```

## Detailed Week-by-Week

### Week 1: Pre-Migration Audit

| Day | Task | Lines Changed | Risk |
|-----|------|-------------|------|
| 1 | Inventory all 463 files, tag each as KEEP/REMOVE/SIMPLIFY | 0 | Low (documentation) |
| 2 | Freeze requirements.txt, create pinned version | 1 file | Low |
| 3 | Run all 155 tests, record baseline timings + failures | 0 | Low |
| 4 | Document current latency baseline (10 sample queries) | 0 | Low |
| 5 | Create MIGRATION_STATUS.md with full plan | 0 | Low |

**Week 1 deliverable:** MIGRATION_STATUS.md, test baseline, latency baseline.

### Week 2: Dual Provider + Routing

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Create `core/provider.py` with LLMProvider abstraction + cloud + local backends | 1 new file | Medium (API integration) |
| 2 | Update `config.yaml` + `model_manager.py` for dual-provider config | 2 files | Medium (config change) |
| 3 | Test: single turn with cloud model, single turn with local model | 0 | Medium |
| 4 | Rewrite `core/router.py` from 1,113 → 200 lines | 1 file | **High** (core change) |
| 5 | Delete: intent_recognizer, embedding_router, lexical_router, routing_state | 10+ files | **High** (mass deletion) |
| 6 | Convert tool registration from regex → JSON schema in first 5 modules | 5 files | Medium |
| 7 | Run tests, fix regressions | Varies | Medium |

**Week 2 deliverable:** FRIDAY supports dual-provider (cloud + local).
User chooses mode in config. Routing is 200 lines. 10+ files deleted.
Local mode still works.

### Week 3: Memory + Planning

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Consolidate all stores into `core/database.py` — sessions, turns, facts, audit | 15+ files | **High** (mass refactor) |
| 2 | Migrate ChromaDB data → SQLite FTS5, remove ChromaDB dependency | 5+ files | Medium |
| 3 | Kill Mem0 server, migrate data to SQLite | 3+ files | Low |
| 4 | Remove: planning engine (all 7 files), MixtureOfAgents | 10+ files | Medium |
| 5 | Simplify: MemoryBroker (160 → 50 lines), MemoryFacade (359 → 100 lines) | 2 files | Low |
| 6 | Simplify: SessionSummarizer, DialogueManager | 2 files | Low |
| 7 | Run tests, fix regressions | Varies | Medium |

**Week 3 deliverable:** One SQLite store. Planning files gone. Memory is
3 facades instead of 6. ChromaDB + Mem0 removed.

### Week 4: Modules + Voice

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Standardize single-ToolFile format across ALL modules | 15+ files | Medium |
| 2 | Remove: browser_automation duplicate controllers, action_plans | 8+ files | Low |
| 3 | Remove: mcp_client, comms, awareness, triggers | 8+ files | Low |
| 4 | Rewrite STT (1,613 → 280 lines) with dual-mode support | 2 files | Medium |
| 5 | Rewrite TTS (464 → 160 lines) with dual-mode support | 2 files | Low |
| 6 | Remove: clap_detector (690 lines → 50-line optional module) | 1 file | Low |
| 7 | Run tests, fix regressions | Varies | Medium |

**Week 4 deliverable:** 27 modules → ~18 modules. Voice pipeline simplified.
STT/TTS now use cloud APIs with local fallback.

### Week 5: Security + Audit

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Consolidate security into 2 files: PathSecurity + approval.py | 4 files | Medium |
| 2 | Create simplified AuditLogger (80 lines) | 1 new file | Low |
| 3 | Remove: tool_guardrails, url_safety, website_policy, consent_service | 5 files | Medium |
| 4 | Update security module to use new audit + tool schemas | 2 files | Low |
| 5 | Run tests, fix regressions | Varies | Medium |

**Week 5 deliverable:** Security layer is 3 files instead of 8. Audit is
one function. No redundant guardrails.

### Week 6: Delegation + Scheduler

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Implement sub-agent spawner tool | 2 files | Medium |
| 2 | Remove: Delegate class, MoA, research_agent module, agentic_services | 10+ files | Medium |
| 3 | Simplify: scheduler (remove lock_monitor, screen_lock, triggers) | 3 files | Low |
| 4 | GUI: apply Option B (strip to essentials) or Option A (remove) | 1 file | Medium |
| 5 | Run tests, fix regressions | Varies | Medium |

**Week 6 deliverable:** One delegation mechanism. Research works through
tool-calling + sub-agents. Scheduler is clean.

### Week 7: Documentation + Launch

| Day | Task | Files Changed | Risk |
|-----|------|-------------|------|
| 1 | Rewrite README.md for new architecture | 1 file | Low |
| 2 | Create quickstart: "FRIDAY in 2 minutes with an API key" | 2 files | Low |
| 3 | Create security researcher landing page (kali-specific install) | 1 file | Low |
| 4 | Audit and fix any remaining test failures | Varies | Low |
| 5 | Final latency benchmark + release | 0 | Low |

**Week 7 deliverable:** Release v2.0.0 — "FRIDAY: Dual-Provider Edition."
README, docs, quickstart done. Ready for marketing push.

## Total Summary

| Metric | Current | Target | Reduction |
|--------|---------|--------|-----------|
| Project Python files | ~463 | ~200 | 57% |
| Project Python lines | ~76,000 | ~27,000 | 64% |
| Dependencies (requirements.txt) | ~30 | ~15 | 50% |
| Startup time | 2-10s | <1s | 80%+ |
| Time to first answer | 10-30s | 1-3s | 80%+ |
| Answer quality | 4B local mode | Dual: cloud = ChatGPT-grade, local = same but cleaner | Both modes supported |
| Stores | 8 | 1 | 88% |
| Test files | 155 | ~120 | 22% (pruned) |
| Voice pipeline lines | 4,088 | ~800 | 80% |
| Modules | 27 | ~18 | 33% |

---

# Part 7: Risks & Mitigations

## Risk Matrix

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| 1 | **Cloud API cost increases** or free tier is discontinued | Medium | High | Keep local model support as optional fallback. Users can switch with `provider: local` in config. |
| 2 | **Deleting intent recognizer breaks 20+ tool parsers that had edge cases** | Medium | High | Run full test suite after deletion. Keep parsing logic in tool handlers (remove ONLY the regex dispatch, not the tool callbacks). |
| 3 | **Cloud API latency is worse than expected** | Low | Medium | Benchmark with multiple providers. Some models (DeepSeek V4 Flash, GPT-4o-mini) have <500ms response times. |
| 4 | **Users want offline mode** and cloud-only is a blocker | Medium | Medium | Keep `provider: local` as a config option. The local path calls the existing llama-cpp-python inference without all the routing layers. |
| 5 | **Database migration loses data** | Low | **High** | Export all tables to JSON before migration. Test migration on a copy of the database first. |
| 6 | **Tests break after massive deletion** | High | Medium | Delete files in waves. Run tests after each wave. Fix regressions before proceeding. |
| 7 | **Users resist the change** (too different from what they know) | Medium | Medium | Keep v1.0 as a git tag/branch. Release v2.0 as a clear "upgrade" with migration guide. |
| 8 | **Documentation doesn't keep up with code changes** | High | Low | Write docs DURING the overhaul, not after. Every deleted file gets a commit message explaining why. |

## Rollback Plan

If the dual-provider overhaul causes critical issues:

1. Revert to git tag `v1.0-local` (create this BEFORE starting migration)
2. The old architecture still works — no dependency on cloud API
3. Users can stay on v1.0 indefinitely while v2.0 stabilizes

---

# Appendix: Current Codebase Inventory

## Core Files (to keep, modify, or remove)

### KEEP (with minor simplification)

| File | Lines | Keep As |
|------|-------|---------|
| `main.py` | 175 | Rewrite – remove args.model references, add provider arg |
| `core/config.py` | ~200 | Keep – add provider section |
| `core/event_bus.py` | ~100 | Keep as-is |
| `core/logger.py` | ~80 | Keep as-is |
| `core/prompt_builder.py` | 101 | Simplify to 30 lines |
| `core/response_finalizer.py` | ~150 | Keep as-is |
| `core/persona_manager.py` | ~200 | Keep – well-designed |
| `core/plugin_manager.py` | 97 | Keep – standardize interface |
| `core/extensions/` (loader, protocol) | ~300 | Keep – extension system is good |
| `core/memory_broker.py` | 160 | Simplify to 50 lines |
| `core/memory/facade.py` | 359 | Simplify to ~100 lines (wrap Database) |
| `core/tool_execution.py` | ~200 | Keep – tool execution is still needed |
| `core/tool_result.py` | ~100 | Keep as-is |
| `core/tool_catalog.py` | 243 | Rewrite to output JSON schemas for API |
| `core/scheduler.py` | ~200 | Keep as-is |
| `core/tracing.py` | ~100 | Keep if useful |
| `core/turn_manager.py` | 139 | Simplify to ~50 lines (delegate to Router) |
| `core/session_summarizer.py` | ~100 | Keep – useful for context management |
| `core/task_runner.py` | ~200 | Keep – used by scheduler and background tasks |
| `core/interrupt_bus.py` | ~80 | Keep – clean design |

### SIMPLIFY (modify significantly)

| File | Lines | Target Lines | How |
|------|-------|-------------|-----|
| `core/router.py` | 1,113 | 200 | Replace with gated tool-calling (simplify to provider-agnostic) |
| `core/model_manager.py` | 192 | 50 | GGUF config → provider config |
| `core/app.py` | 1,117 | ~400 | Remove store construction, planning engine wiring |
| `core/kernel/runtime.py` | 258 | ~100 | Remove ServiceContainer complexity |
| `core/resource_monitor.py` | ~200 | ~50 | Remove model-specific resource tracking |
| `core/result_cache.py` | ~150 | ~50 | Simplify caching layer |
| `core/dialog_state.py` | ~200 | ~50 | Remove workflow state tracking |
| `core/dialogue_manager.py` | 156 | ~50 | Simplify to prompt building |
| `core/delegate.py` | 83 | 0 (remove, replace with tool) |
| `core/conversation_agent.py` | 197 | 0 (remove, dead code) |

### REMOVE entirely

| File | Lines | Reason |
|------|-------|--------|
| `core/intent_recognizer.py` | 3,295 | Replaced by model tool-calling |
| `core/planning/planner_engine.py` | 247 | Replaced by model tool-calling |
| `core/planning/intent_engine.py` | 112 | Replaced by model tool-calling |
| `core/planning/qwen_planner.py` | 363 | Qwen-specific, not needed for cloud |
| `core/planning/replan_controller.py` | 265 | Replaced by model error recovery |
| `core/planning/plan_validator.py` | ~200 | Replaced by model argument validation |
| `core/planning/plan_repair.py` | ~150 | Replaced by model error recovery |
| `core/planning/context_resolver.py` | ~150 | Replaced by model context window |
| `core/planning/workflow_coordinator.py` | 73 | Replaced by tool-calling |
| `core/planning/slot_extractors.py` | ~100 | Replaced by model |
| `core/planning/json_repair.py` | ~100 | Model outputs valid JSON natively |
| `core/planning/turn_orchestrator.py` | 476 | Replaced by Router |
| `core/embedding_router.py` | ~150 | Chrome/embedding fallback not needed |
| `core/lexical_router.py` | ~100 | Fuzzy matching not needed |
| `core/route_scorer.py` | ~100 | Two-model router not needed |
| `core/routing_tuner.py` | ~200 | Routing threshold tuning not needed |
| `core/routing_state.py` | ~150 | State machine not needed |
| `core/text_normalize.py` | ~100 | STT typo correction not needed |
| `core/mixture_of_agents.py` | ~200 | MoA architecture irrelevant |
| `core/memory_service.py` | 436 | Mem0 integration, not needed |
| `core/memory/semantic.py` | ~200 | Merged into database.py |
| `core/memory/episodic.py` | ~100 | Merged into database.py |
| `core/memory/procedural.py` | ~100 | Not needed with capable model |
| `core/memory/graph.py` | ~100 | Knowledge graph over-engineered |
| `core/memory/embeddings.py` | ~100 | ChromaDB removal |
| `core/stores/` (9 files) | ~2,500 | Merged into database.py |
| `core/workflow_orchestrator.py` | 1,042 | LangGraph workflows removed |
| `core/task_graph_executor.py` | 441 | DAG executor removed |
| `core/reasoning/` (4 files) | ~500 | Model router, scorer, defaults |
| `core/reasoning/agentic_services/` (3 files) | ~200 | Research/focus modes removed |
| `core/llm_providers/` (3 files) | ~200 | Local inference providers |
| `core/safety/tool_guardrails.py` | ~200 | Redundant |
| `core/safety/website_policy.py` | ~100 | Redundant |
| `core/safety/url_safety.py` | ~100 | Redundant |
| `core/kernel/consent.py` | ~100 | Simplify to prompt rule |
| `core/kernel/permissions.py` | ~100 | Simplify to prompt rule |
| `core/lock_monitor.py` | ~100 | GUI-dependent |
| `core/screen_lock.py` | ~100 | GUI-dependent |
| `core/session_rag.py` | ~150 | ChromaDB-dependent |
| `core/assistant_context.py` | ~200 | Partially redundant |
| `core/shell_prefix.py` | ~50 | Not needed |

**Total removal: ~16,000 lines across ~50 files.**

---

## Final Verdict

FRIDAY's architecture overhaul — adding cloud API support while keeping
and simplifying local inference — is the single highest-leverage thing you
can do for the project.

**This is NOT a cloud migration. It's a DUAL-PROVIDER architecture:**

- **Cloud mode** (when online): fast, high-quality answers. Competitive
  with Hermes Agent and Claude Code for general use.
- **Local mode** (when offline/air-gapped): same simplified architecture,
  still uses local GGUF models. Slower but works without internet.
- **Auto mode**: try cloud first, fall back to local on network failure.
- **The simplification work benefits both modes equally.** Intent recognizer,
  8 stores, planning engine, 7-layer routing — all gone regardless of mode.

**The numbers:**
- 64% less code (76K → 27K)
- 80% faster answers in cloud mode (10-30s → 1-3s)
- Local mode: same latency, but code is clean and maintainable
- From "occasionally coherent" to "ChatGPT-grade" when cloud is enabled
- From 8 stores to 1 database
- From 4 delegation mechanisms to 1
- From 27 modules to ~18
- Local inference preserved as a first-class mode

**The opportunity:**
No other AI agent targets the security researcher + desktop power user
intersection. FRIDAY can be the best agent for Kali users by a mile —
simply by being usable, fast, and well-documented.

**The risk:**
Don't do this migration halfway. If you keep the intent recognizer AND
add a cloud API, you get the worst of both worlds — cloud API latency
PLUS routing overhead. Cut deep. Cut clean. The code that remains will
be better for it.
