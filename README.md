<div align="center">

# FRIDAY

**A local-first, voice-driven AI desktop assistant for Linux & Windows.**

FRIDAY keeps reasoning on your machine — chat, planning, and tool use run on
local models — and reaches online only when you ask it to.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20Windows-blue.svg)](#installation)
[![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue.svg)](#requirements)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

[Features](#features) · [Quick start](#quick-start) · [Architecture](#architecture) · [Configuration](#configuration) · [Contributing](CONTRIBUTING.md)

</div>

---

## What is FRIDAY?

FRIDAY is a desktop assistant you talk to. Say **"Hey Friday"**, ask it to set
your brightness, find a file, summarize a PDF, look something up, or run a
multi-step workflow — and it does the work locally, narrating progress out loud.

It is built around three ideas:

- **Local-first.** Speech-to-text, the conversational model, the planning model,
  vision, and embeddings all run on your hardware. No account, no cloud
  inference, no telemetry. Online skills (web search, browser automation) are
  opt-in and ask for consent before they reach the network.
- **Capability-driven.** Every skill is a self-contained capability registered
  in an MCP-compatible registry. A deterministic intent layer routes the common
  phrasings instantly; anything else falls through to a local planning model.
- **Cross-platform.** One codebase runs on Linux and Windows, with
  platform-specific paths guarded throughout and parity between `setup.sh` and
  `setup.ps1`.

> [!NOTE]
> FRIDAY is an early-stage project (v0.1). Expect rough edges, and please
> [open an issue](../../issues) when you hit one.

## Features

| Area | What it does |
|---|---|
| 🗣️ **Voice I/O** | "Hey Friday" wake word (Porcupine), `faster-whisper` STT, Piper neural TTS with barge-in. Falls back to text chat. |
| 💬 **Natural conversation** | Local chat model with session-aware turns, custom personas, and a three-tier memory (episodic / semantic / procedural). |
| 🖥️ **System control** | Brightness, volume, screen lock/unlock, screenshots, app launch, window queries, clipboard. |
| 📄 **Document intelligence** | Index and ask questions over your PDFs/Office/Markdown via local RAG (`markitdown` + Chroma). |
| 👁️ **Vision (VLM)** | Screenshot explainer, OCR, screen summarizer, UI-element finder, code debugger — powered by a local SmolVLM2 model. |
| 🌐 **Online skills (opt-in)** | Browser automation (Playwright/Selenium), web/quick-answer search, news & world monitoring, weather. |
| 🗂️ **Productivity** | Reminders, calendar events, notes, tasks, goals, focus sessions, dictation. |
| 🔌 **Extensible** | Add a capability + an intent pattern; optional external MCP and a plugin architecture across 28 modules. |
| 🔒 **Privacy & safety** | Ask-before-online consent, scoped security tooling (lab mode), local audit log. |

## Quick start

### Requirements

| | Minimum |
|---|---|
| **OS** | Ubuntu 22.04+/Debian 12+/Kali (Linux) · Windows 10 21H2+/Windows 11 |
| **Python** | 3.10 – 3.13 (3.11 recommended) |
| **RAM** | 8 GB (16 GB recommended) |
| **Disk** | ~10 GB for models + cache |
| **GPU** | Optional — llama.cpp & faster-whisper auto-use CUDA when present |

### Installation

<details open>
<summary><strong>Linux</strong></summary>

```bash
git clone https://github.com/SanthoshReddy352/Friday_Linux.git
cd Friday_Linux
chmod +x setup.sh
./setup.sh            # installs deps, Piper TTS, downloads default models, bootstraps .env
source .venv/bin/activate
python main.py
```

Full walkthrough (incl. fully-manual path): **[SETUP_GUIDE.md](SETUP_GUIDE.md)**
</details>

<details>
<summary><strong>Windows</strong></summary>

```powershell
git clone https://github.com/SanthoshReddy352/Friday_Linux.git
cd Friday_Linux
.\setup.ps1           # installs deps, Piper TTS, downloads default models, bootstraps .env
.\.venv\Scripts\Activate.ps1
python main.py
```

Full walkthrough: **[SETUP_GUIDE_WINDOWS.md](SETUP_GUIDE_WINDOWS.md)**
</details>

The setup scripts are idempotent — they skip any step whose output is already on
disk, and a failed/blank model download is reported, not fatal.

### Default models

| Role | Model | Size |
|---|---|---|
| Chat | `Qwen3.5-0.8B-Q4_K_M.gguf` | ~533 MB |
| Tool / planner | `Qwen3.5-4B-Q4_K_M.gguf` | ~2.7 GB |
| Speech-to-text | `faster-whisper base.en` | ~140 MB |
| Vision | `SmolVLM2-2.2B-Instruct-Q4_K_M.gguf` | ~1.7 GB |
| Embeddings | `all-MiniLM-L6-v2` + `ms-marco-MiniLM` reranker | ~120 MB |

Override the chat/tool downloads with `FRIDAY_CHAT_MODEL_URL` /
`FRIDAY_TOOL_MODEL_URL`, or drop your own `.gguf` files into `models/`.

### First words to try

> "Hey Friday — set brightness to 60."
> "What's on my calendar today?"
> "Find the file called design final report."
> "Summarize this PDF." · "Take a screenshot and explain it." · "What's the weather in Mumbai?"

## Architecture

```
voice / text in
      │
   STTEngine ──► TurnOrchestrator (v2)
                     │
        ┌────────────┴─────────────┐
   IntentRecognizer           RouteScorer (LLM)
   (deterministic regex)      (local planner, fallback)
        └────────────┬─────────────┘
                CapabilityBroker ──► ToolPlan
                     │
        OrderedToolExecutor  ⇄  GraphCompiler (LangGraph, opt-in)
                     │
            CapabilityExecutor ──► 28 capability modules
                     │
            ResponseFinalizer ──► persona ──► TTS / GUI
                     │
   Memory: SQLite domain stores (core/stores/) + Chroma vector index
```

- **`TurnOrchestrator`** owns the turn lifecycle (`core/planning/`).
- **`IntentRecognizer`** (`core/intent_recognizer.py`) is the fast deterministic
  routing layer — 50+ phrase parsers. Misses fall through to the local planner.
- **`WorkflowOrchestrator`** (`core/workflow_orchestrator.py`) runs multi-step
  templates with slot-filling, replanning, and step approval.
- **Persistence** is decomposed into six domain stores under `core/stores/`
  (session, memory, audit, workflow, goal, knowledge-graph).

A deeper map — communities, god-nodes, and a pre-built knowledge graph — lives
in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

## Configuration

Runtime behavior is driven by [`config.yaml`](config.yaml); secrets and machine
overrides go in `.env` (copied from [`.env.example`](.env.example) at setup).
Highlights:

```yaml
conversation:
  listening_mode: manual          # or wake-word driven
  online_permission_mode: ask_first
models:
  chat:  { path: models/Qwen3.5-0.8B-Q4_K_M.gguf }
  tool:  { path: models/Qwen3.5-4B-Q4_K_M.gguf }
routing:
  execution_engine: parallel      # ordered | parallel | graph (LangGraph)
  use_replanning: true
```

Full key-by-key reference: **[docs/config_reference.md](docs/config_reference.md)**.

## Project layout

```
core/        turn orchestration, intent recognition, routing, stores, reasoning
modules/     28 capability plugins (system_control, vision, document_intel, …)
gui/         PyQt6 HUD
docs/        architecture, setup, testing, and design docs
scripts/     setup helpers and hand-run diagnostics
tests/       pytest suite (unit + cross-turn conversation rig)
main.py      entry point
```

## Documentation

- **[SETUP_GUIDE.md](SETUP_GUIDE.md)** / **[SETUP_GUIDE_WINDOWS.md](SETUP_GUIDE_WINDOWS.md)** — install
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how it all fits together
- **[docs/testing_guide.md](docs/testing_guide.md)** — command-first behavior spec
- **[docs/config_reference.md](docs/config_reference.md)** — every config key
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — dev workflow & conventions

## Contributing

Contributions are welcome. Start with **[CONTRIBUTING.md](CONTRIBUTING.md)** for
the dev setup, the intent-pattern + test requirement for new capabilities, and
the PR checklist. Please also read the **[Code of Conduct](CODE_OF_CONDUCT.md)**.

## Security

FRIDAY runs local code, can control your system, and ships scoped security
tooling. To report a vulnerability, see **[SECURITY.md](SECURITY.md)** — please
do not open a public issue for security reports.

## License

[MIT](LICENSE) © 2026 Santhosh Reddy and the FRIDAY contributors.
Third-party components and their licenses are listed in
[docs/third_party_credits.md](docs/third_party_credits.md).
