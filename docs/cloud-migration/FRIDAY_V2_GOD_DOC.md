# FRIDAY v2 — Cloud-Only Brain, Greenfield Rebuild

## Context

FRIDAY today is built around two weak local GGUF models (Qwen 0.8B + 4B). Because
those models can't route intent or call tools reliably, the repo grew ~22k lines of
**compensating infrastructure**: a 3,564-line regex `intent_recognizer.py`, a 5-layer
planning engine, embedding/lexical routers, a routing state machine, 8 stores, 6 memory
subsystems, Mem0, ChromaDB, mixture-of-agents, and 4 delegation mechanisms. The result
is slow, brittle, and the small chat model fabricates fake tool success.

The `docs/cloud-migration/` set lays out the case for going cloud-only. This plan
executes that direction **with the user's overrides**:

- **Greenfield v2 package** (`friday/`), porting the valuable modules across — not an
  in-place wave-deletion.
- **API-only brain**: no in-process `llama-cpp`. Local models are still reachable, but
  only as HTTP endpoints (LM Studio / Ollama via OpenAI-compat).
- **Native provider adapters** for Anthropic (Messages + `tool_use` + prompt caching),
  Google (Gemini function-calling), and OpenAI, plus **one generic OpenAI-compat adapter**
  covering opencode, LM Studio, Ollama, and any custom `base_url`.
- **GUI is primary** (CLI dropped): a new **modern web GUI** (React + Tailwind via Vite)
  driven by a FastAPI + WebSocket backend, shown in a native desktop window via
  **pywebview**. The old PyQt6 HUD is removed.
- **Voice**: local **Piper TTS** for speech output, plus local **STT push-to-talk** input.
- **New feature — model-narrated progress**: the model speaks naturally about what it's
  doing while long tasks run ("Sure, let me scan that subnet…", "Still going, almost there"),
  spoken aloud via Piper, instead of today's canned "One moment." phrases.

Intended outcome: a lean (~20–27k line), fast, genuinely conversational assistant that
keeps FRIDAY's real value (browser, security, smart-home, system, file, web tools) but
gets its intelligence from a capable cloud/endpoint model with native tool-calling.

---

## Target architecture (`friday/` package)

```
friday/
├── app.py                      # boots backend + opens native GUI window (pywebview)
├── config.py                   # load config.yaml + .env; resolve provider/persona
├── core/
│   ├── providers/
│   │   ├── base.py             # Provider ABC + normalized response dataclass
│   │   ├── openai_provider.py  # native OpenAI (chat.completions + tools + stream)
│   │   ├── anthropic_provider.py # native Messages API, tool_use, prompt caching
│   │   ├── google_provider.py  # native Gemini function-calling
│   │   ├── openai_compat.py    # generic: opencode / lmstudio / ollama / custom base_url
│   │   └── registry.py         # build provider from config["provider"]
│   ├── agent.py                # the ONE loop: build msgs → generate(tools) → exec → loop → final
│   ├── tools.py                # ToolRegistry: name → {json_schema, handler}; emits provider-native defs
│   ├── memory.py               # single SQLite: sessions, turns, facts(FTS5), audit
│   ├── persona.py              # YAML persona → system prompt (port persona_manager)
│   ├── narration.py            # model-narrated spoken progress (see below)
│   ├── events.py               # event bus (port core/event_bus.py) → streams to GUI + TTS
│   └── safety.py               # path_security + approval (ported, slim)
├── voice/
│   ├── tts.py                  # Piper TTS (ported from modules/voice_io/tts.py)
│   └── stt.py                  # local STT push-to-talk (ported, slimmed)
├── server/api.py               # FastAPI + WebSocket bridge
├── tools/                      # ported capability modules (v2 contract)
└── webui/                      # React + Tailwind (Vite) SPA → built to webui/dist
```

`config.yaml`, `.env.example`, `requirements.txt`, `setup.sh`/`setup.ps1` updated; the old
`core/`, `modules/`, `gui/`, `main.py`, `cli/`, local model files retired at the end.

---

## Provider layer (Phase 1)

`core/providers/base.py` defines:

```python
@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict]   # [{id, name, args:dict}]
    usage: dict
    raw: dict

class Provider(ABC):
    def generate(self, messages, tools=None, stream=False) -> LLMResponse | Iterator[Event]: ...
    def test_connection(self) -> bool: ...
```

All adapters normalize **into the same `LLMResponse`** so the agent loop is provider-agnostic:
- `openai_provider` / `openai_compat`: `tools=[{type:function,function:{name,description,parameters}}]`,
  parse `message.tool_calls`. Compat takes `base_url` + `api_key_env` (covers opencode, LM Studio
  `http://localhost:1234/v1`, Ollama `http://localhost:11434/v1`, any endpoint).
- `anthropic_provider`: convert tools to Anthropic `tool_use` schema, split `system`, map
  `stop_reason=="tool_use"` → `tool_calls`; enable prompt caching on the system block + tool defs.
- `google_provider`: Gemini `function_declarations`; map `functionCall`/`functionResponse`.

`registry.py` selects the adapter from `config["provider"]["type"]` and supports an ordered
**fallback list** (reuse the idea in existing `core/llm_providers/fallback_chain.py`). Reuse the
existing `core/llm_providers/anthropic_provider.py` / `openai_compat.py` as starting points but
extend them with **tool-calling + streaming** (current versions are text-only fallback chat).

---

## Agent loop (Phase 2)

`core/agent.py` replaces `router.py` + `intent_recognizer.py` + `planning/` + all routing layers:

```
build messages (system=persona+facts, history from SQLite, user turn)
loop (≤ N):
    resp = provider.generate(messages, tools=registry.defs(), stream=True)
    stream tokens → events → GUI/TTS
    if resp.tool_calls:
        speak resp.content if present   # natural preamble
        for tc: result = registry.execute(tc); append tool result
        continue
    else: final answer; persist turn; break
```

`core/tools.py` `ToolRegistry` builds native tool defs **directly from capability descriptors**
(`core/capability_registry.py` already stores `name`/`description`/`input_schema`). No YAML catalog,
no embedding router. `execute()` runs the handler with approval/path-security gating.

`core/memory.py`: single SQLite (schema from `FRIDAY_CLOUD_ONLY_ARCHITECTURE.md` §5 — `sessions`,
`turns`, `facts`+`facts_fts`, `audit`). `remember_fact` / `recall_facts` exposed as tools. No
ChromaDB / Mem0 / sentence-transformers / stores.

`core/persona.py`: port `persona_manager.py` YAML → system prompt (keep — it's good).

---

## Model-narrated progress (Phase 3) — the headline feature

Replaces canned phrases in `core/turn_feedback.py` with real, context-aware narration:

1. **Immediate preamble**: when the model returns `content` *alongside* `tool_calls`, that content
   ("Sure, let me scan that subnet for you") is spoken immediately via Piper before the tool runs.
2. **Long-task progress**: keep the existing `TurnFeedbackRuntime` timer pattern (delays from
   `conversation.progress_delays_s`), but instead of static strings, generate a short, context-aware
   line from the **current tool name + args + elapsed time** — produced cheaply (template + optional
   fast rephrase via the same/secondary provider, low max_tokens). Suppress once final tokens stream
   (existing `llm_first_token` guard already does this).
3. **Tool-step narration**: on each `tool_finished`, optionally speak a one-line human summary
   ("Found 3 open ports, checking services now").

Driven through `core/events.py` so both the GUI timeline and Piper TTS consume the same events.

---

## Backend + GUI (Phases 4–5)

`server/api.py` (FastAPI): REST for config/persona/tool-list + a **WebSocket** that streams a typed
event protocol (`token`, `tool_started`, `tool_finished`, `progress`, `approval_request`,
`turn_completed`). User input (typed or STT transcript) comes back over the socket.

`webui/` (Vite + React + Tailwind, lean SPA — not Next.js, which `web/` uses for the landing site):
- Streaming chat transcript with token-by-token rendering
- Live **tool/progress timeline** (shows the narrated steps)
- Voice orb / push-to-talk button (reuse the `web/components/VoiceOrb.js` concept)
- Settings: provider + model picker, persona switch, API-key status
- Modern dark theme, glassy/animated, responsive

`friday/app.py` builds the SPA (or serves `webui/dist`) and opens it in a native window via
**pywebview**. **CLI removed**; **PyQt `gui/` removed**.

---

## Voice (Phase 6)

- `voice/tts.py`: port `modules/voice_io/tts.py` Piper path (piper binary + `en_US-lessac-medium.onnx`,
  `aplay`/`pw-cat` playback, interrupt/barge-in via `interrupt_bus`). Strip cloud-TTS notions.
- `voice/stt.py`: port a slimmed local STT (push-to-talk) from `modules/voice_io/stt.py` — drop
  wake-word/clap/Vosk-management complexity; keep mic capture + transcription + barge-in.

---

## Port modules → v2 tool contract (Phase 7)

Contract stays close to today's `setup(app)` + `app.register_capability(spec, handler)`, but `spec.parameters`
becomes **real JSON Schema** (today it's loose strings like `{"entity": "string — …"}`), and **all intent
regex patterns are dropped** (the model routes). Port in value-priority waves:

1. file_ops, code_exec/shell, system_control, app_launcher
2. web (search/scrape), browser_automation, security_tools, network
3. smart_home, document_intel, vision/image, scheduler, weather, news
4. memory, delegate_task (single tool replacing Delegate/MoA/ResearchAgent), persona switch

Each ported module gets a focused test under `friday/tests/`.

---

## Purge + docs + tests (Phases 8–9)

After v2 is bootable and modules ported, delete: `core/intent_recognizer.py`, `core/planning/`,
`embedding_router`/`lexical_router`/`routing_tuner`/`routing_state`, `mixture_of_agents`,
`task_graph_executor`, `workflow_orchestrator`, `core/stores/`, `core/memory/`, `memory_service`,
`session_rag`, `reasoning/`, `delegate`/`delegation`, `core/llm_providers` (local-fallback variant),
`gui/`, `cli/`, local GGUF + `kokoro*`, dead `core/*`. Prune/rewrite `tests/`. Rewrite `README.md`,
`SETUP_GUIDE*`, `config.yaml`, `.env.example`, `requirements.txt`, `setup.sh/ps1`. Update `CLAUDE.md`
(intent-recognizer rules no longer apply) and `docs/testing_guide.md`. Keep cross-platform guards.

---

## Documentation & tracking artifacts (created first, before any code)

Per direction, the migration is governed by three living documents in the repo:

1. **God document** — `docs/cloud-migration/FRIDAY_V2_GOD_DOC.md`: this entire plan, saved
   as the canonical source of truth for the rebuild. All steps live here.
2. **Status tracker** — `docs/cloud-migration/STATUS_V2.md`: every task of every phase as a
   checkbox list (`- [ ]`), grouped by phase, with a status legend (TODO / IN-PROGRESS / DONE)
   and a "last updated" line. **Every step below is enumerated there.** I update it as each
   task completes — it is the live progress ledger for the whole migration.
3. **CLAUDE.md pointer** — add a top "🚧 ACTIVE MIGRATION (v2)" section to `CLAUDE.md` that
   points readers to `STATUS_V2.md` as the authority on current state, and instructs that all
   v2 work be tracked there. This pointer is **removed when migration completes**.

### Granular task list (mirrors STATUS_V2.md)

**Phase 0 — Safety net & docs**
- [ ] `git init`, `.gitignore` sanity, initial commit, baseline tag `v1-pre-rebuild`
- [ ] Record baseline metrics (startup time, file/line count, test pass list)
- [ ] Create god doc, STATUS_V2.md, CLAUDE.md migration pointer

**Phase 1 — Provider layer**
- [ ] `core/providers/base.py` (Provider ABC + `LLMResponse`)
- [ ] `openai_provider.py` (tools + streaming)
- [ ] `anthropic_provider.py` (native `tool_use` + prompt caching + streaming)
- [ ] `google_provider.py` (Gemini function-calling)
- [ ] `openai_compat.py` (opencode / lmstudio / ollama / custom base_url)
- [ ] `registry.py` (config-driven selection + fallback chain)
- [ ] `config.yaml` provider section + `.env.example` keys
- [ ] `tests/test_providers.py`

**Phase 2 — Agent core**
- [ ] `core/tools.py` ToolRegistry (native defs from capability descriptors)
- [ ] `core/memory.py` single SQLite (sessions/turns/facts FTS5/audit)
- [ ] `core/persona.py` (port persona_manager YAML→prompt)
- [ ] `core/agent.py` the one loop (generate→tools→loop→final, streaming)
- [ ] `remember_fact` / `recall_facts` tools
- [ ] `tests/test_agent_loop.py`, `tests/test_memory.py`

**Phase 3 — Model-narrated progress**
- [ ] `core/events.py` (port event bus)
- [ ] `core/narration.py`: spoken preamble alongside tool calls
- [ ] context-aware long-task progress lines (timer pattern, real context)
- [ ] tool-step narration on `tool_finished`
- [ ] `tests/test_narration.py`

**Phase 4 — Backend server**
- [ ] `server/api.py` FastAPI app + REST (config/persona/tools)
- [ ] WebSocket event protocol (token/tool/progress/approval/turn_completed)
- [ ] approval round-trip over socket
- [ ] `tests/test_server.py`

**Phase 5 — Modern GUI**
- [ ] `webui/` Vite + React + Tailwind scaffold
- [ ] streaming chat transcript
- [ ] tool/progress timeline component
- [ ] voice orb / push-to-talk control
- [ ] settings (provider+model picker, persona, key status)
- [ ] dark modern theme
- [ ] `friday/app.py` pywebview native window + serve `webui/dist`

**Phase 6 — Voice**
- [ ] `voice/tts.py` Piper (port, output + narration)
- [ ] `voice/stt.py` local push-to-talk (port, slimmed)
- [ ] barge-in via interrupt bus

**Phase 7 — Module porting waves** (each: JSON-schema params, drop intent regex, test)
- [ ] Wave 1: file_ops, code_exec/shell, system_control, app_launcher
- [ ] Wave 2: web, browser_automation, security_tools, network
- [ ] Wave 3: smart_home, document_intel, vision/image, scheduler, weather, news
- [ ] Wave 4: memory, delegate_task, persona switch

**Phase 8 — Purge legacy**
- [ ] delete intent_recognizer, planning/, routing layers, MoA, task_graph_executor, workflow_orchestrator
- [ ] delete stores/, memory/, memory_service, session_rag, reasoning/, delegate/delegation
- [ ] delete old llm_providers, gui/ (PyQt), cli/, main.py, local GGUF + kokoro*
- [ ] prune/rewrite tests/

**Phase 9 — Finalize**
- [ ] rewrite README, SETUP_GUIDE*, requirements.txt, setup.sh/ps1, config.yaml, .env.example
- [ ] rewrite CLAUDE.md (remove intent-recognizer rules; remove migration pointer)
- [ ] rewrite docs/testing_guide.md for v2
- [ ] full green test suite + end-to-end launch verification

## Phasing & execution order

| Phase | Deliverable | Bootable milestone |
|------|-------------|--------------------|
| 0 | `git init` + baseline tag (no rollback safety net exists today) | repo versioned |
| 1 | Provider layer (native + compat, tools + streaming) + registry + config | provider smoke test passes |
| 2 | Agent loop + ToolRegistry + SQLite memory + persona | text round-trip with a couple of tools |
| 3 | Model-narrated progress over event bus | progress events emitted |
| 4 | FastAPI + WebSocket backend | socket streams a turn |
| 5 | React+Tailwind GUI in pywebview window | usable desktop chat |
| 6 | Piper TTS + push-to-talk STT | speaks + listens |
| 7 | Module porting waves | tools work end-to-end |
| 8 | Purge legacy core/gui/cli/local-inference | lean tree |
| 9 | Tests, docs, setup scripts | green suite + docs |

I'll execute phase by phase, keeping v2 bootable at each milestone and reporting after each.

---

## Verification

- **Provider**: `python -m friday.core.providers.registry --test` (or a `tests/test_providers.py`) —
  each configured provider returns a normalized `LLMResponse` and a `tool_call` for a known tool prompt.
- **Agent**: `tests/test_agent_loop.py` — mock provider returns a `tool_call`; assert tool runs, result
  feeds back, final answer returned, turn persisted to SQLite.
- **Narration**: `tests/test_narration.py` — preamble spoken before tool; progress fires only while a
  long tool runs and is suppressed once final tokens stream.
- **Tools**: per-module tests assert JSON-schema validity + handler behavior.
- **End-to-end**: launch `python -m friday` → native window opens → type "scan localhost with nmap" →
  see streamed preamble, tool timeline, narrated progress, spoken via Piper, final answer.
- **Regression budget**: keep a baseline test list (Phase 0) green throughout.

---

## Open assumptions (proceeding unless told otherwise)

- API-only brain: in-process `llama-cpp` removed; Ollama/LM Studio used via OpenAI-compat HTTP.
- `web/` (Next.js landing/docs site) is left as-is; the **app** GUI is the new `webui/` SPA.
- Primary default provider configurable; I'll default to an Anthropic Claude model with an
  OpenAI-compat fallback, overridable in `config.yaml`.
- Secrets via `.env` (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, generic
  `FRIDAY_API_KEY` + `base_url` for compat endpoints).
