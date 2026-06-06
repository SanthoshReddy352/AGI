# Project Friday: Cloud-Only Architecture Guide

> **Purpose:** Every architectural decision, implementation detail, and
> code pattern required to rebuild FRIDAY as a pure cloud-inference CLI
> agent. No local models. No GUI. No over-engineering.
>
> This document is the technical companion to FRIDAY_CLOUD_ONLY_REBUILD.md.
> It covers the actual code: what to write, what to delete, and how every
> piece connects.
>
> **Guiding principle:** If a component exists to compensate for the
> 4B local model's weaknesses, it gets deleted. If it enables unique
> capabilities (security tools, browser, smart home), it gets simplified.
> If it's clean and provider-agnostic (event bus, persona system, tests),
> it stays.

---

## Table of Contents

1. [The Core Architecture](#1-the-core-architecture)
2. [Provider Layer: How FRIDAY Talks to the Cloud](#2-provider-layer-how-friday-talks-to-the-cloud)
3. [Router: The Only Routing You Need](#3-router-the-only-routing-you-need)
4. [Tool System: From 27 Modules to 18 Standards](#4-tool-system-from-27-modules-to-18-standards)
5. [Memory: One Database, Three Tables](#5-memory-one-database-three-tables)
6. [CLI Interface: Prompt Toolkit, Streaming, Commands](#6-cli-interface-prompt-toolkit-streaming-commands)
7. [Voice Pipeline: Cloud STT/TTS](#7-voice-pipeline-cloud-stttts)
8. [Security: What Stays, What Goes](#8-security-what-stays-what-goes)
9. [Delegation & Sub-agents: 4 Systems → 1 Tool Call](#9-delegation--sub-agents-4-systems--1-tool-call)
10. [Event Bus & Extensions: The Parts Worth Keeping](#10-event-bus--extensions-the-parts-worth-keeping)
11. [Config File Reference](#11-config-file-reference)
12. [Dependency Comparison: Before vs After](#12-dependency-comparison-before-vs-after)

---

## 1. The Core Architecture

### High-level flow

```
User types command           Model responds via API
       │                             ▲
       ▼                             │
┌──────────────┐           ┌─────────────────┐
│  CLI Interface │──────▶  │  LLM Provider    │
│  (prompt_tk)   │  text   │  (cloud API)     │
│  streaming     │◀──────  │  tool_calls      │
│  /commands     │  stream └────────┬────────┘
└───────┬───────┘                   │
        │                           │
        │ ◄─────────────────────────┘
        │    (if tool_calls, execute
        │     and loop back)
        ▼
┌───────────────┐
│  Tool Executor │──▶ tools/browser.py
│  (thin wrapper)│──▶ tools/security.py
│  handles       │──▶ tools/smart_home.py
│  result loop   │──▶ tools/code_exec.py
└───────┬───────┘      ... (18 modules)
        │
        ▼
┌───────────────┐
│  Database      │
│  (single       │
│   SQLite,      │
│   4 tables)    │
└───────────────┘
```

### Module boundaries

```
friday/
├── main.py              # Entry point (~50 lines)
├── cli/
│   └── interface.py     # prompt_toolkit session (~150 lines)
├── core/
│   ├── provider.py      # Cloud API abstraction (~80 lines)
│   ├── router.py        # Gated tool-calling (~200 lines)
│   ├── database.py      # Single SQLite store (~200 lines)
│   ├── config.py        # Config loading (~50 lines)
│   ├── event_bus.py     # Pub/sub (~100 lines) — KEEP
│   ├── scheduler.py     # Cron tasks (~200 lines) — KEEP
│   ├── logger.py        # Logging (~50 lines) — KEEP
│   ├── tracing.py       # Optional tracing (~100 lines) — KEEP
│   ├── persona_manager.py # YAML personas (~200 lines) — KEEP
│   └── extensions/      # Plugin system (~200 lines) — SIMPLIFY
├── tools/               # 18 standard tool modules
│   ├── __init__.py      # Auto-discover tools (~30 lines)
│   ├── file_ops.py      # Read/write files
│   ├── browser.py       # Selenium/web automation
│   ├── security.py      # nmap, port scan, network
│   ├── code_exec.py     # Python/shell execution
│   ├── smart_home.py    # Philips Hue, etc.
│   ├── web_search.py    # Search + scrape
│   ├── document.py      # PDF/DOCX reading
│   ├── ... (10 more)
├── voice/
│   ├── stt.py           # Cloud STT (~50 lines)
│   ├── tts.py           # Cloud TTS (~40 lines)
│   └── listener.py      # Mic recording (~100 lines)
├── models/              # Keep only if needed for tools
├── tests/               # ~100 test files (pruned)
└── config.yaml          # Single config file
```

**File count target: ~85 files, ~20,000 lines**

---

## 2. Provider Layer: How FRIDAY Talks to the Cloud

### The LLMProvider abstraction

All cloud providers use OpenAI-compatible chat completions API. Even
Anthropic and Gemini have OpenAI-compatible proxies (OpenRouter,
Anthropic's adapter).

```python
# core/provider.py

from abc import ABC, abstractmethod
from typing import Optional, Iterator
import requests
import json


class LLMProvider(ABC):
    """Abstract interface for cloud LLM providers.

    Every method is synchronous. Streaming is available for UI rendering.
    Tool calling uses the OpenAI tools/function schema.
    """

    @abstractmethod
    def generate(
        self,
        messages: list,
        tools: Optional[list] = None,
        stream: bool = False,
    ) -> dict:
        ...

    @abstractmethod
    def test_connection(self) -> bool:
        """Verify API key and endpoint are working."""
        ...


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible API provider.

    Works with:
    - OpenAI (api.openai.com)
    - OpenRouter (openrouter.ai/api)
    - Together (api.together.xyz)
    - Groq (api.groq.com)
    - DeepSeek (api.deepseek.com)
    - Any v1/chat/completions endpoint
    """

    def __init__(self, config: dict):
        self.base_url = config["base_url"].rstrip("/")
        self.model = config["model"]
        self.api_key = config["api_key"]
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.3)
        self.timeout = config.get("timeout_s", 30)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    def generate(self, messages, tools=None, stream=False):
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": stream,
        }
        if tools:
            body["tools"] = tools

        resp = self._session.post(
            f"{self.base_url}/chat/completions",
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()

        if stream:
            return self._handle_stream(resp.iter_lines())
        return self._parse_response(resp.json())

    def _parse_response(self, data: dict) -> dict:
        choice = data["choices"][0]
        message = choice["message"]
        result = {"content": message.get("content", "")}
        if message.get("tool_calls"):
            result["tool_calls"] = [
                {
                    "name": tc["function"]["name"],
                    "args": json.loads(tc["function"]["arguments"]),
                    "id": tc["id"],
                }
                for tc in message["tool_calls"]
            ]
        finish = choice.get("finish_reason", "")
        if finish in ("length", "max_tokens"):
            result["truncated"] = True
        return result

    def _handle_stream(self, lines: Iterator[bytes]) -> dict:
        """Accumulate streaming response into final result."""
        content_parts = []
        tool_calls = []
        current_tool = None

        for line in lines:
            if not line:
                continue
            line = line.decode().strip()
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            chunk = json.loads(data_str)
            delta = chunk.get("choices", [{}])[0].get("delta", {})

            if delta.get("content"):
                content_parts.append(delta["content"])

            if delta.get("tool_calls"):
                for tc_delta in delta["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    while len(tool_calls) <= idx:
                        tool_calls.append({"name": "", "args": "", "id": ""})
                    tc = tc_delta.get("function", {})
                    tool_calls[idx]["name"] += tc.get("name", "")
                    tool_calls[idx]["args"] += tc.get("arguments", "")
                    if tc_delta.get("id"):
                        tool_calls[idx]["id"] = tc_delta["id"]

        result = {"content": "".join(content_parts)}
        if tool_calls:
            result["tool_calls"] = [
                {
                    "name": tc["name"],
                    "args": json.loads(tc["args"]) if tc["args"] else {},
                    "id": tc["id"],
                }
                for tc in tool_calls
                if tc["name"]
            ]
        return result

    def test_connection(self) -> bool:
        """Verify the API endpoint is reachable and key is valid."""
        try:
            resp = self.generate(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            return bool(resp.get("content"))
        except Exception:
            return False
```

### Provider discovery

Providers are configured by type in config.yaml. The system supports
extending to new providers without code changes:

```python
# core/model_manager.py — ~50 lines

PROVIDER_REGISTRY = {
    "openai_compat": OpenAICompatProvider,
    # Future: "anthropic": AnthropicProvider,
    # Future: "google": GeminiProvider,
}

class ModelManager:
    def __init__(self, config: dict):
        provider_config = config["provider"]
        provider_type = provider_config.pop("type")
        provider_class = PROVIDER_REGISTRY.get(provider_type)
        if not provider_class:
            raise ValueError(f"Unknown provider: {provider_type}")
        self.provider = provider_class(provider_config)

    def generate(self, messages, tools=None, stream=False):
        return self.provider.generate(messages, tools, stream)

    def test_connection(self):
        return self.provider.test_connection()
```

### Provider comparison

| Provider | Models | Cost | Latency | Notes |
|----------|--------|------|---------|-------|
| **DeepSeek V4 Flash** | Flash, R1 | Free tier | ~300ms | Best free option. |
| **Groq** | Llama 3, Mixtral | Free tier | ~200ms | Fastest inference. |
| **OpenRouter** | 200+ models | Pay-as-you-go | Varies | Access to any model. |
| **OpenAI** | GPT-4o-mini, GPT-4o | $0.15-2.50/M tokens | ~500ms | Most reliable. |
| **Together** | Llama 3, Qwen 2.5 | $0.10-0.80/M tokens | ~400ms | Good open models. |
| **Anthropic** | Claude Sonnet 4, Haiku | $0.25-3.00/M tokens | ~600ms | Best for code. |

### Why NOT to support local at all

Every line supporting local inference is a line that:
1. Adds a CI path that can fail differently from cloud
2. Needs a different API response parser
3. Has different latency characteristics
4. Can't stream the same way
5. Has different token counting
6. Has different error handling
7. May not support tool calling at all

The dual-provider approach doubles your maintenance surface for a feature
that serves <5% of your users (and those users need a different product).

---

## 3. Router: The Only Routing You Need

### The simplified router

```python
# core/router.py — ~200 lines

import json
from typing import Optional
from core.provider import LLMProvider
from core.database import Database


class Router:
    """Gated tool-calling router.

    This is the ONLY routing layer. No intent recognition.
    No embedding fallback. No lexical fuzzy match. No state machine.
    """

    def __init__(
        self,
        provider: LLMProvider,
        tools: dict,
        database: Database,
        system_prompt: str,
    ):
        self.llm = provider
        self.tools = tools
        self.db = database
        self.system_prompt = system_prompt

    def process_turn(
        self,
        user_input: str,
        session_id: str,
        stream_callback: Optional[callable] = None,
    ) -> str:
        """Process a single user turn. Handles multi-step tool calling."""
        messages = self._build_messages(user_input, session_id)
        tool_defs = self._get_tool_definitions()

        turn_count = 0
        while turn_count < 10:  # Safety limit on tool loops
            response = self.llm.generate(messages, tools=tool_defs)
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                # Normal chat response
                result = response.get("content", "")
                if stream_callback:
                    stream_callback(result)
                break

            # Execute each tool call in sequence
            for tc in tool_calls:
                tool_result = self._execute_tool(tc["name"], tc["args"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(tool_result),
                })
                if stream_callback:
                    stream_callback(f"\n[→ {tc['name']}] ")

            turn_count += 1

        # Store the turn in database
        self.db.save_turn(session_id, user_input, response)
        return result

    def _build_messages(self, text: str, session_id: str) -> list:
        messages = [{"role": "system", "content": self.system_prompt}]

        # Load recent session history
        history = self.db.get_recent_turns(session_id, limit=10)
        for turn in history:
            messages.append({"role": "user", "content": turn.user_input})
            messages.append({"role": "assistant", "content": turn.response})

        messages.append({"role": "user", "content": text})
        return messages

    def _get_tool_definitions(self) -> list:
        """Build OpenAI-compatible tool definitions from registered tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for name, tool in self.tools.items()
        ]

    def _execute_tool(self, name: str, args: dict) -> dict:
        handler = self.tools.get(name)
        if not handler:
            return {"error": f"Unknown tool: {name}"}
        try:
            return handler.execute(args)
        except Exception as e:
            return {"error": str(e)}
```

### What the new router does NOT have

- No `IntentRecognizer` call
- No `_plan_actions()` method
- No `_find_best_route()` method
- No `_continue_active_workflow()` method
- No `_finalize_response()` chain
- No `_should_use_tool_model()` heuristic
- No `_is_tool_oriented_text()` guesswork
- No `_plan_fallback()` recovery path
- No `TextNormalizer` pass
- No `EmbeddingRouter` call
- No `LexicalRouter` call
- No `RouteScorer` evaluation
- No `RoutingTuner` threshold check
- No `RoutingState` tracking

**The router has one job: send user input to the model, execute any tools
the model requests, return the final answer.**

---

## 4. Tool System: From 27 Modules to 18 Standards

### The ToolFile format

Every tool module exports a list of `ToolDef` objects:

```python
# tools/browser.py

from core.tool_base import ToolDef, tool


@tool(
    name="browser_navigate",
    description="Navigate to a URL in the current browser window",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to navigate to (with https:// prefix)",
            },
        },
        "required": ["url"],
    },
)
def browser_navigate(url: str) -> str:
    """Navigate the browser to the given URL."""
    from tools._browser_engine import driver
    driver.get(url)
    return f"Navigated to {url}, page title: {driver.title}"
```

### Tool auto-discovery

```python
# tools/__init__.py — ~30 lines

import importlib
import pkgutil
from core.tool_base import ToolRegistry

registry = ToolRegistry()

for module_info in pkgutil.iter_modules(__path__):
    if module_info.name.startswith("_"):
        continue  # Skip private modules (engine helpers)
    module = importlib.import_module(f"tools.{module_info.name}")
    if hasattr(module, "register"):
        module.register(registry)
```

### The module consolidation plan

| Current Module | Target | Change |
|---------------|--------|--------|
| browser_automation (6 files) | tools/browser.py | Merge controllers |
| security (nmap, scan, network) | tools/security.py | Merge 3 files |
| code_execution, shell | tools/code_exec.py | Merge |
| file_ops, document_reader | tools/file_ops.py | Merge |
| smart_home (hue, lights) | tools/smart_home.py | Keep |
| web_search, web_scrape, news | tools/web.py | Merge |
| mcp_client | DELETE | Not core |
| comms | DELETE | Not core |
| awareness | DELETE | Not core |
| triggers | DELETE | Not core |
| dictation | voice/ | Move to voice pipeline |
| focus, tasks, goals | DELETE | Model handles this |
| research_agent | DELETE | Replaced by delegate_task |
| image_gen | tools/image.py | Keep (cloud API) |
| STT (12 files) | voice/ (3 files) | Cloud API replacement |
| TTS | voice/tts.py | Cloud API replacement |
| app_launcher | tools/apps.py | Keep |
| system_control | tools/system.py | Keep |

**Deliverable: 18 standard tool modules instead of 27.**

### Tool module categorization

```
┌──────────────────────────────────────┐
│  FILE & CODE TOOLS (5)               │
│  ├─ file_ops      — read, write, ls  │
│  ├─ code_exec     — Python, shell    │
│  ├─ document      — PDF, DOCX, CSV   │
│  ├─ apps          — launch, find     │
│  └─ system        — info, monitor    │
├──────────────────────────────────────┤
│  NETWORK TOOLS (4)                    │
│  ├─ web           — search, scrape   │
│  ├─ browser       — Selenium auto    │
│  ├─ security      — nmap, scan, DNS  │
│  └─ network       — curl, ping, etc  │
├──────────────────────────────────────┤
│  MEDIA & VOICE (3)                    │
│  ├─ voice/stt     — cloud STT        │
│  ├─ voice/tts     — cloud TTS        │
│  └─ image         — vision, gen      │
├──────────────────────────────────────┤
│  CONTROL TOOLS (6)                    │
│  ├─ smart_home    — Hue, scenes      │
│  ├─ scheduler     — cron, reminders  │
│  ├─ delegate_task — sub-agent spawn  │
│  ├─ memory        — save/recall      │
│  ├─ database      — query facts      │
│  └─ personify     — switch persona   │
└──────────────────────────────────────┘
```

---

## 5. Memory: One Database, Three Tables

### Database schema

```python
# core/database.py — ~200 lines

import sqlite3
import json
from datetime import datetime


class Database:
    """Single SQLite store for all FRIDAY data.

    Tables:
    - sessions: Session metadata (id, created_at, persona, summary)
    - turns: Individual user ↔ assistant turns
    - facts: Key-value user facts (with FTS5 for search)
    - audit: Tool execution log

    No ChromaDB. No Mem0. No separate stores.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                persona TEXT DEFAULT 'default',
                summary TEXT
            );

            CREATE TABLE IF NOT EXISTS turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                role TEXT NOT NULL,  -- 'user' or 'assistant'
                content TEXT NOT NULL,
                tools_used TEXT,  -- JSON array
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                confidence REAL DEFAULT 1.0,
                updated_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                key, value, content='facts', content_rowid='id'
            );

            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                tool_name TEXT NOT NULL,
                args TEXT,  -- JSON
                result_summary TEXT,
                success INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session
                ON turns(session_id, id);
            CREATE INDEX IF NOT EXISTS idx_audit_tool
                ON audit(tool_name);
        """)

    def save_turn(self, session_id: str, user_input: str,
                  response: dict):
        tools_used = json.dumps([
            tc.get("name", "") for tc in response.get("tool_calls", [])
        ])
        now = datetime.utcnow().isoformat()

        self.conn.execute(
            "INSERT INTO turns (session_id, role, content, tools_used, created_at) "
            "VALUES (?, 'user', ?, ?, ?)",
            (session_id, user_input, "[]", now),
        )
        self.conn.execute(
            "INSERT INTO turns (session_id, role, content, tools_used, created_at) "
            "VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, response.get("content", ""), tools_used, now),
        )
        self.conn.commit()

    def get_recent_turns(self, session_id: str, limit: int = 10) -> list:
        cursor = self.conn.execute(
            "SELECT role, content FROM turns "
            "WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, limit * 2),  # *2 because each turn has 2 rows
        )
        rows = cursor.fetchall()
        rows.reverse()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def save_fact(self, key: str, value: str, category: str = "general"):
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO facts (key, value, category, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (key.lower(), value, category, now),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO facts_fts (rowid, key, value) "
            "VALUES ((SELECT id FROM facts WHERE key = ?), ?, ?)",
            (key.lower(), key.lower(), value),
        )
        self.conn.commit()

    def get_fact(self, key: str) -> str:
        cursor = self.conn.execute(
            "SELECT value FROM facts WHERE key = ?", (key.lower(),)
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def search_facts(self, query: str) -> list:
        cursor = self.conn.execute(
            "SELECT f.key, f.value, f.category FROM facts f "
            "JOIN facts_fts fts ON f.id = fts.rowid "
            "WHERE facts_fts MATCH ? "
            "ORDER BY rank LIMIT 10",
            (query,),
        )
        return [dict(r) for r in cursor.fetchall()]
```

### What gets deleted (all memory-related)

| File | Lines | Reason |
|------|-------|--------|
| `core/memory_service.py` | 436 | Mem0 integration. Separate server process. Ignored by facade. |
| `core/memory/facade.py` | 359 | Write-path deduplicator. Not needed with one store. |
| `core/memory/semantic.py` | ~200 | Merged into database.py |
| `core/memory/episodic.py` | ~100 | Merged into turns table |
| `core/memory/procedural.py` | ~100 | Model doesn't need separate "how-to" store |
| `core/memory/graph.py` | ~100 | Knowledge graph overkill for <200 facts |
| `core/memory/embeddings.py` | ~100 | ChromaDB dependency |
| `core/session_rag.py` | ~150 | ChromaDB-dependent |
| `core/stores/` (9 files) | ~2,500 | 8 objects wrapping same SQLite |
| `core/context_store.py` | ~500 | Original 16-table store |
| `core/memory_broker.py` | 160 | Simplify to ~50 lines |

### How memory is used in practice

```python
# Inside system prompt (auto-injected):
"""
USER FACTS (from memory):
- name: Tricky
- os: Kali Linux
- preferred_editor: vim
- default_target: 192.168.1.0/24
"""

# Model can read/write facts via tools:
tools = [
    {
        "name": "remember_fact",
        "description": "Save a fact about the user for future reference",
        "parameters": {
            "key": "fact name",
            "value": "fact value",
        },
    },
    {
        "name": "recall_facts",
        "description": "Search for facts about the user",
        "parameters": {"query": "search terms"},
    },
]
```

---

## 6. CLI Interface: Prompt Toolkit, Streaming, Commands

### Main CLI

```python
# cli/interface.py — ~150 lines

import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText


class FridayCLI:
    """CLI interface for FRIDAY. Prompt_toolkit, streaming, colors."""

    def __init__(self, agent):
        self.agent = agent
        self.session = PromptSession(
            history=FileHistory("~/.friday_history"),
            style=Style.from_dict({
                "prompt": "ansibrightcyan bold",
                "user": "ansigreen",
                "assistant": "ansiwhite",
                "tool": "ansibrightyellow",
                "error": "ansired",
            }),
        )

    async def run(self):
        self._print_banner()
        while True:
            try:
                text = await self.session.prompt_async(
                    FormattedText([("class:prompt", "friday> ")]),
                )
                text = text.strip()

                if not text:
                    continue
                if text.startswith("/"):
                    await self._handle_command(text)
                    continue

                # Process with streaming callback
                async def stream(chunk):
                    print(chunk, end="", flush=True)

                print("")  # newline before response
                response = await self.agent.process_turn(text, stream)
                print("\n")

            except KeyboardInterrupt:
                print("\nUse /exit to quit, or /help for commands.")
            except EOFError:
                break

        print("\nGoodbye.")

    async def _handle_command(self, command: str):
        cmd = command[1:].lower()
        if cmd in ("exit", "quit"):
            raise EOFError
        elif cmd == "help":
            print("Commands: /exit, /help, /new, /persona <name>, /tools")
        elif cmd == "new":
            self.agent.new_session()
            print("New session started.")
        elif cmd.startswith("persona"):
            name = cmd.split(" ", 1)[1] if " " in cmd else "default"
            self.agent.set_persona(name)
            print(f"Switched to persona: {name}")
        elif cmd == "tools":
            for name in self.agent.list_tools():
                print(f"  {name}")
        else:
            print(f"Unknown command: {cmd}")

    def _print_banner(self):
        print("╔══════════════════════════════════════╗")
        print("║       FRIDAY v2.0 — Cloud Agent      ║")
        print("║    Type /help for commands            ║")
        print("╚══════════════════════════════════════╝")
        print("")
```

### Why prompt_toolkit over Textual/ncurses

1. **Lightest dependency** — prompt_toolkit is pure Python, 0 compiled deps
2. **History** — Built-in file-backed history with up/down arrow
3. **Streaming** — Works naturally with async generators
4. **Pipe-friendly** — `echo "nmap scan" | friday` works when stdin isn't a TTY
5. **Cross-platform** — Same exact code on Linux, macOS, Windows (WSL)

### Pipe support

```python
# main.py — entry point

import sys


def main():
    cli = FridayCLI(agent)

    # Pipe mode: read from stdin non-interactively
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            response = agent.process_turn(text)
            print(response)
        return

    # Interactive mode
    asyncio.run(cli.run())
```

---

## 7. Voice Pipeline: Cloud STT/TTS

### Full voice pipeline

```python
# voice/stt.py — ~50 lines

import requests


class CloudSTT:
    """Speech-to-text via cloud API.

    Supports OpenAI Whisper API and compatible endpoints.
    """

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def transcribe(self, audio_path: str) -> str:
        with open(audio_path, "rb") as f:
            resp = requests.post(
                f"{self.base_url}/audio/transcriptions",
                headers=self.headers,
                files={"file": f},
                data={"model": "whisper-1", "language": "en"},
                timeout=30,
            )
        resp.raise_for_status()
        return resp.json()["text"]
```

```python
# voice/tts.py — ~40 lines

import requests
import subprocess
import tempfile


class CloudTTS:
    """Text-to-speech via cloud API."""

    def __init__(self, api_key: str, voice: str = "alloy",
                 base_url: str = "https://api.openai.com/v1"):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.voice = voice

    def speak(self, text: str):
        resp = requests.post(
            f"{self.base_url}/audio/speech",
            headers=self.headers,
            json={
                "model": "tts-1",
                "voice": self.voice,
                "input": text,
                "response_format": "mp3",
            },
            timeout=30,
        )
        resp.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(resp.content)
            tmp_path = f.name

        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-volume", "80", tmp_path],
            capture_output=True,
            timeout=60,
        )
```

```python
# voice/listener.py — ~100 lines

import pyaudio
import wave
import tempfile


class MicListener:
    """Record audio from microphone."""

    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    CHUNK = 1024
    SILENCE_THRESHOLD = 500  # Adjust for environment

    def record_until_silence(self, max_seconds: int = 30) -> str:
        """Records audio until silence detected, returns path to WAV file."""
        p = pyaudio.PyAudio()
        stream = p.open(format=self.FORMAT, channels=self.CHANNELS,
                       rate=self.RATE, input=True, frames_per_buffer=self.CHUNK)

        frames = []
        silent_chunks = 0
        started = False

        for _ in range(0, int(self.RATE / self.CHUNK * max_seconds)):
            data = stream.read(self.CHUNK, exception_on_overflow=False)
            frames.append(data)

            # Simple VAD: amplitude threshold
            amplitude = max(abs(sample) for sample in
                          __import__("struct").unpack(f"<{len(data)//2}h", data))
            if amplitude > self.SILENCE_THRESHOLD:
                started = True
                silent_chunks = 0
            elif started:
                silent_chunks += 1
                if silent_chunks > self.RATE // self.CHUNK * 2:  # 2 seconds silence
                    break

        stream.stop_stream()
        stream.close()
        p.terminate()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wf = wave.open(f, "wb")
            wf.setnchannels(self.CHANNELS)
            wf.setsampwidth(p.get_sample_size(self.FORMAT))
            wf.setframerate(self.RATE)
            wf.writeframes(b"".join(frames))
            wf.close()
            return f.name
```

### Total voice pipeline: 3 files, ~190 lines (down from 12 files, 4,088 lines)

---

## 8. Security: What Stays, What Goes

### Security modules comparison

| Module | Current | Cloud-Only Target |
|--------|---------|-------------------|
| PathSecurity | ~200 lines | KEEP — filesystem isolation is code-enforceable |
| approval.py | ~150 lines | KEEP — user consent flow for destructive actions |
| ToolGuardrails | ~200 lines | DELETE — model follows tool descriptions |
| URLSafety | ~100 lines | DELETE — prompt rule + one-line sanity check |
| WebsitePolicy | ~100 lines | DELETE — model judgment replaces policy |
| ConsentService | ~100 lines | SIMPLIFY — merge into approval.py |
| PermissionService | ~100 lines | DELETE — prompt rule |

### The security architecture

```python
# core/safety/path_security.py (KEEP, SIMPLIFY)

class PathSecurity:
    """Filesystem isolation. Only code-enforceable policy."""

    ALLOWED_DIRS = [
        os.path.expanduser("~"),
        "/tmp",
        "/home",
    ]
    BLOCKED_PATTERNS = [
        "/etc/shadow",
        "/etc/sudoers",
        "/.ssh/",
    ]

    @classmethod
    def safe_path(cls, path: str) -> bool:
        resolved = os.path.realpath(os.path.expanduser(path))
        blocked = any(p in resolved for p in cls.BLOCKED_PATTERNS)
        allowed = any(resolved.startswith(d) for d in cls.ALLOWED_DIRS)
        return allowed and not blocked


# core/safety/approval.py (KEEP, SIMPLIFY)

class Approval:
    """User consent for destructive operations."""

    DESTRUCTIVE_TOOLS = {
        "delete_file", "modify_system", "execute_command",
        "install_package", "kill_process",
    }

    @classmethod
    def requires_approval(cls, tool_name: str) -> bool:
        return tool_name in cls.DESTRUCTIVE_TOOLS
```

### What gets deleted

```python
# core/safety/tool_guardrails.py — DELETE
# core/safety/url_safety.py — DELETE
# core/safety/website_policy.py — DELETE
# core/kernel/consent.py — DELETE
# core/kernel/permissions.py — DELETE
```

---

## 9. Delegation & Sub-agents: 4 Systems → 1 Tool Call

### Current delegation debt

FRIDAY has 4 delegation mechanisms:
1. `Delegate` class — background thread router
2. `DelegationManager` — formal sub-agent system (never actually spawns)
3. `MixtureOfAgents` — multi-model voting (irrelevant with one model)
4. `ResearchAgent` — 7 files, 3,510 lines, uses the same Router

### Target: one tool

```python
# tools/delegate.py — ~80 lines

import requests


@tool(
    name="delegate_task",
    description="Run a task in a sub-agent. Use for complex multi-step work "
                "that benefits from isolation.",
    parameters={
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "What the sub-agent should accomplish",
            },
            "context": {
                "type": "string",
                "description": "Relevant background information",
            },
        },
        "required": ["goal"],
    },
)
def delegate_task(goal: str, context: str = "") -> str:
    """Spawn a sub-agent to complete a task.

    Uses the same cloud API but with a fresh conversation context.
    The sub-agent has access to all tools and runs independently.
    """
    # Implementation: new API call with goal as system prompt
    messages = [
        {"role": "system", "content": f"You are a focused sub-agent.\n"
                                       f"Context: {context}\n"
                                       f"Goal: {goal}\n"
                                       f"Complete the goal and report back."},
    ]

    response = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={
            "model": MODEL,
            "messages": messages,
            "max_tokens": 2048,
        },
        timeout=60,
    )
    return response.json()["choices"][0]["message"]["content"]
```

**Files deleted:**
- `core/delegate.py` (83 lines)
- `core/research_agent/` (7 files, 3,510 lines)
- `core/mixture_of_agents.py` (~200 lines)
- `core/reasoning/agentic_services/` (~200 lines)

---

## 10. Event Bus & Extensions: The Parts Worth Keeping

### Event bus (KEEP)

```python
# core/event_bus.py — ~100 lines

from collections import defaultdict
from typing import Callable


class EventBus:
    """Simple pub/sub for internal events.

    Extensions subscribe, core publishes, no coupling.
    """

    def __init__(self):
        self._subscribers = defaultdict(list)

    def subscribe(self, event: str, callback: Callable):
        self._subscribers[event].append(callback)

    def publish(self, event: str, **data):
        for callback in self._subscribers[event]:
            try:
                callback(**data)
            except Exception as e:
                logger.error(f"Event handler {callback} failed: {e}")
```

### Extension system (SIMPLIFY)

The current 4-file split (protocol.py, adapter.py, decorators.py, loader.py)
is over-engineered. Simplify to 1-2 files.

```python
# core/extensions/__init__.py — ~100 lines

import importlib


class Extension:
    """Base class for FRIDAY extensions."""

    name: str = ""
    description: str = ""

    def on_register(self, bus: EventBus):
        """Called when extension is loaded. Subscribe to events here."""
        pass

    def on_startup(self):
        """Called when FRIDAY starts."""
        pass

    def on_shutdown(self):
        """Called when FRIDAY shuts down."""
        pass


def load_extensions(config: dict) -> list[Extension]:
    """Load all configured extensions from Python paths."""
    extensions = []
    for ext_config in config.get("extensions", []):
        module = importlib.import_module(ext_config["module"])
        ext_class = getattr(module, ext_config.get("class", "Extension"))
        extensions.append(ext_class())
    return extensions
```

---

## 11. Config File Reference

```yaml
# config.yaml — FRIDAY v2.0 Cloud-Only

# ── Cloud Provider ─────────────────────────────────
provider:
  type: openai_compat
  # Primary provider
  base_url: https://api.opencode-zen.com/v1
  model: deepseek/deepseek-v4-flash-free
  api_key_env: FRIDAY_API_KEY     # Reads from environment variable
  max_tokens: 8192
  temperature: 0.3
  timeout_s: 30

# ── Persona ────────────────────────────────────────
persona: default                   # Load from personas/default.yaml

# ── Voice ──────────────────────────────────────────
voice:
  enabled: true
  input_device: default             # Microphone device index
  wake_word: false                  # No local wake word (use push-to-talk)
  stt_provider: openai              # openai | deepgram
  tts_provider: openai              # openai | elevenlabs
  tts_voice: alloy                  # alloy, echo, fable, onyx, nova, shimmer

# ── Database ───────────────────────────────────────
database:
  path: ~/.friday/friday.db

# ── Logging ────────────────────────────────────────
logging:
  level: info                       # debug | info | warn | error
  file: ~/.friday/friday.log

# ── Extensions ─────────────────────────────────────
extensions:
  # - module: my_extensions.hello_world

# ── Browser ────────────────────────────────────────
browser:
  headless: false
  user_data_dir: ~/.friday/browser_profile

# ── Scheduler ──────────────────────────────────────
scheduler:
  enabled: true
```

---

## 12. Dependency Comparison: Before vs After

### Deleted dependencies

| Library | Reason | Size Saved |
|---------|--------|-----------|
| `llama-cpp-python` | Local GGUF inference | ~50MB (compiled) |
| `PyQt6` | Desktop GUI | ~50MB |
| `chromadb` | Vector store | ~30MB |
| `sentence-transformers` | Embeddings | ~250MB (models) |
| `faster-whisper` | Local STT | ~500MB (model) |
| `piper-tts` | Local TTS | ~200MB (model) |
| `vosk` | Local STT fallback | ~100MB (model) |
| `pocketsphinx` | Offline wake word | ~20MB |
| `pvporcupine` | Wake word | ~10MB |
| `langgraph` | Workflow orchestrator | ~5MB |
| `mem0` | Long-term memory server | ~10MB |
| `networkx` | Knowledge graph | ~5MB |

**Total saved: ~1.2GB of packages + models**

### Kept dependencies

| Library | Purpose |
|---------|---------|
| `requests` | HTTP for cloud API |
| `prompt-toolkit` | CLI interface |
| `pyaudio` | Microphone input |
| `selenium` | Browser automation |
| `sqlite3` (stdlib) | Database |
| `pyyaml` | Config + personas |
| `pytest` | Tests |

### Optional dependencies (per-tool)

| Library | Tool | Purpose |
|---------|------|---------|
| `openai` | STT/TTS | Alternative provider |
| `pillow` | Image tools | Image processing |
| `phue` | Smart home | Philips Hue control |

---

## Appendix: File Deletion Manifest

### Total files to delete: ~280 (from ~463 to ~183)

| Directory | Before | After | Deleted |
|-----------|--------|-------|---------|
| `core/` | ~80 files | ~20 files | ~60 |
| `voice/` | 12 files | 3 files | 9 |
| `HUD/` | ~15 files | 0 | ~15 |
| `modules/` | ~100 files | ~60 files | ~40 |
| `memory/` | ~20 files | 0 | ~20 |
| `stores/` | ~15 files | 0 | ~15 |
| `planning/` | ~15 files | 0 | ~15 |
| `reasoning/` | ~10 files | 0 | ~10 |
| `safety/` | ~8 files | 2 files | 6 |
| `tests/` | 155 files | ~100 files | ~55 |
| `models/` | ~30 files | 0 | ~30 |
| Other | ~15 files | ~10 files | ~5 |

### What FRIDAY v2.0 Cloud-Only looks like

```
friday/
├── main.py               # 50 lines
├── config.yaml            # 40 lines
├── .env.example           # 5 lines
├── cli/
│   └── interface.py       # 150 lines
├── core/
│   ├── __init__.py
│   ├── provider.py        # 80 lines
│   ├── router.py          # 200 lines
│   ├── model_manager.py   # 50 lines
│   ├── database.py        # 200 lines
│   ├── config.py          # 50 lines
│   ├── event_bus.py       # 100 lines
│   ├── logger.py          # 50 lines
│   ├── scheduler.py       # 200 lines
│   ├── tracing.py         # 100 lines
│   ├── persona_manager.py # 200 lines
│   ├── tool_base.py       # 80 lines
│   ├── tool_executor.py   # 100 lines
│   ├── extensions/        # 200 lines total
│   └── safety/
│       ├── path_security.py   # 80 lines
│       └── approval.py        # 80 lines
├── tools/                 # 18 modules, ~8,000 lines total
│   ├── __init__.py
│   ├── file_ops.py
│   ├── code_exec.py
│   ├── browser.py
│   ├── security.py
│   ├── web.py
│   ├── smart_home.py
│   ├── document.py
│   ├── image.py
│   ├── apps.py
│   ├── system.py
│   ├── network.py
│   ├── delegate.py
│   ├── memory.py
│   ├── scheduler.py
│   └── ... (3-4 more)
├── voice/
│   ├── stt.py             # 50 lines
│   ├── tts.py             # 40 lines
│   └── listener.py        # 100 lines
├── personas/
│   └── default.yaml       # 30 lines
└── tests/                 # ~100 files, ~12,000 lines
```

**Target: ~183 files, ~20,000 lines of project code**
**(from ~463 files, ~76,000 lines)**

A 57% file reduction and 74% code reduction for an agent that's
faster, smarter, and easier to maintain.
