# Namma Agent

### Intelligence for Everyone.

> **Your Trusted AI Companion. Your Agent, Your Advantage.**

Namma Agent is a **cloud-only personal AI assistant** you run yourself. The brain is
a single API call — native Anthropic, OpenAI, or Google, or any OpenAI-compatible
endpoint (Ollama, LM Studio, opencode, or a custom base URL). Around that one call
sits everything that makes it an *agent*: one tool-calling loop, a registry of ~85
tools, cross-session memory, a learning-loop skill system, project knowledge bases
with document RAG, a built-in Learning Room, browser-native voice, a streaming web
UI, and messaging bridges.

Everything lives in the [`namma_agent/`](namma_agent/) Python package. There is no local-model
or PyQt stack — Namma Agent is provider-agnostic and runs anywhere Python does, from
a laptop to a tiny server.

> **Name your assistant whatever you like.** The *project* is Namma Agent; the
> *assistant you chat with* has a configurable display name. Set `assistant.name`
> in [`namma_agent/config.yaml`](namma_agent/config.yaml) (or the `ASSISTANT_NAME` env var)
> and it changes everywhere — the system prompt, the web UI, the voice, and the
> messaging bridges. See [Name your assistant](#name-your-assistant).

---

## Quick start

**Want the desktop app?** The one-click installers do everything below for you —
create the environment, install dependencies, configure your first AI provider,
add a shortcut, and launch. See **[docs/INSTALL.md](docs/INSTALL.md)**:

- **Windows:** double-click `installers\install.bat`
- **macOS:** double-click `installers/Install Namma Agent.command`
- **Linux:** `bash installers/install.sh`

To set it up manually instead, from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r namma_agent/requirements.txt
```

Don't need voice or the desktop window? Install just the core + your provider:

```bash
pip install fastapi "uvicorn[standard]" pydantic PyYAML anthropic
```

### Add your API key

```bash
cp namma_agent/.env.example .env          # .env is read from the project root
```

Edit `.env` and set the key for the provider you'll use, e.g.:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Pick the provider in [`namma_agent/config.yaml`](namma_agent/config.yaml) → `provider.type`
(`anthropic` · `openai` · `google` · `ollama` · `lmstudio` · `openai_compat`).
**Local Ollama / LM Studio need no key** — point `provider.type: ollama` at a
running server for a fully offline setup.

### Build the web UI

Both the desktop window and `--server` mode serve a **pre-built** React bundle from
`namma_agent/webui/dist`. Build it once before the first run (and again after any UI
change). Node 18+ is required:

```bash
cd namma_agent/webui
npm install        # install JS dependencies
npm run build      # emit namma_agent/webui/dist
cd ../..
```

For UI development with hot-reload, run `npm run dev` in `namma_agent/webui` (Vite dev
server) alongside `python -m namma_agent --server`.

### Run it

```bash
python -m namma_agent              # native desktop window (pywebview)
python -m namma_agent --server     # backend only — open http://127.0.0.1:8000
```

`--server` is the most reliable first run (no GUI dependency). The chat UI is at
**http://127.0.0.1:8000**.

---

## What it can do

Namma Agent acts through tools the model calls natively — no intent regexes, no
routing graph. Adding a capability is dropping one file in `namma_agent/tools/`.

| Area            | Tools                                                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| Files           | `read_file` `write_file` `list_dir` `move_path` `copy_path` `delete_path` `make_dir` `find_files` `organize_dir`                  |
| Shell / System  | `run_shell` `system_info` `open_app` `list_open_apps`                                                                            |
| Web             | `web_search` `web_extract` `web_crawl`                                                                                           |
| Browser / Media | `open_browser_url` `search_google` `play_youtube` `play_youtube_music` `media_control`                                           |
| Network         | `ping_host` `dns_lookup` `check_port` `public_ip`                                                                                |
| Security\*      | `port_scan` `ping_sweep` `dir_enum` `dns_enum`                                                                                   |
| Weather / News  | `get_weather` `get_news`                                                                                                         |
| Smart home†     | `ha_turn_on` `ha_turn_off` `ha_get_state` `ha_set_temperature`                                                                   |
| Vision          | `take_screenshot` `read_text_from_image`                                                                                         |
| Documents       | `read_document` (pdf/docx/pptx/xlsx/html via MarkItDown) · `convert_document` (Markdown → docx/pdf/pptx/html/txt/odt/… via pandoc) |
| Scheduler       | `add_reminder` `list_reminders` `remove_reminder` (fire in background)                                                           |
| Memory          | `remember_fact` `recall_facts` `forget_fact` `remember_note` `read_memory` `search_conversations` `recall_sessions` `summarize_session` `clear_memory` |
| Projects‖       | `search_project_documents` `search_project_history`                                                                              |
| Learning Room¶  | `set_learning_plan` `mark_module_complete` `record_understanding` `remember_learning_note` `set_teaching_preference` `render_diagram` `fetch_image` `render_simulation` |
| Agent           | `delegate_task` `switch_persona` `list_personas` `about_namma`                                                                  |
| Tasks / Goals   | `add_task` `list_tasks` `complete_task` `remove_task` · `add_goal` `list_goals` `update_goal_progress` `remove_goal`             |
| Focus           | `start_focus` `focus_status` `end_focus`                                                                                         |
| Skills          | `list_skills` `use_skill` `create_skill` `update_skill`                                                                          |
| Self-authoring  | `create_tool` (writes + hot-loads new Python tools, approval-gated)                                                             |
| Comms‡          | `send_notification` (+ inbound Telegram chat bridge)                                                                            |
| Workspace       | `gmail_list` `gmail_read` `gmail_send` `calendar_agenda` `calendar_create_event`                                               |
| MCP§            | `mcp_list_servers` + `mcp_<server>_<tool>` per connected server                                                                 |

\* off until `security.lab_mode: true` + `authorized_scopes` in config.
† off until `smart_home.url` + `HASS_TOKEN` are set.
‡ off until Telegram/Discord credentials are in `.env`.
§ only when `mcp.servers` are configured.
‖ active inside a project chat with indexed documents.
¶ active inside the Learning Room.

Sensitive/destructive tools are approval-gated by default; set
`conversation.auto_approve: true` to run them without prompting.

---

## Highlights

### 🧠 One agent, any brain

A turn is `generate → run tools → loop → answer`. The model calls tools natively,
chains them, and streams tokens straight to the UI. Swap Anthropic for a local
Ollama model by editing one config key, and a `ProviderChain` falls back across
providers automatically when one is down. Missing a system binary (e.g. `nmap`)?
The tool returns a clear "install X" message instead of crashing.

### 📚 Projects with document intelligence

Group chats into **projects** and give each one its own document shelf (up to 25
files, 10 MB each). Every upload is text-extracted, **screened for prompt
injection**, chunked structure-aware, and indexed into SQLite FTS5. In a project
chat the assistant grounds its answers with `search_project_documents` (BM25
ranking, per-document diversity, neighbour stitching, file/section citations) —
wrapped in a *data-not-instructions* guard. Flagged files are quarantined out of
retrieval until you trust them. A project chat also carries summaries of the
project's earlier conversations, so sessions days apart pick up where they left off.

### 🎓 Learning Room

Turn any goal — or an uploaded **syllabus** — into a structured learning path.
Namma Agent infers your level, builds a module path (browse it as a list or on a
pannable React Flow canvas), and teaches one module at a time — each in its own
chat — with research-backed pedagogy: recall warm-ups, a running example carried
across modules, Socratic hints, and inline server-rendered diagrams, images, and
interactive simulations. It **assesses through conversation** (not multiple-choice
cards), keeping a persistent **learner model** of how you think, and a module only
advances through an explicit **confidence gate**. Standing **teaching preferences**
("research every answer") apply across every module, and opt-in Telegram nudges
remind you about idle topics.

### 🧩 Skills & self-extension

Skills are Markdown playbooks (`SKILL.md`) the assistant loads on demand and can
**author itself** after solving a novel task. When no tool covers a need at all,
`create_tool` writes a brand-new Python tool and hot-loads it in the same turn
(approval-gated). See [docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md).

### 🗣️ Browser-native voice & messaging

Voice is 100% browser-native (Web Speech API): the UI reads answers aloud and the
mic dictates input — no server audio, no models to install. Chat with your
assistant from your phone over Telegram (and Discord), with voice-message
transcription when an STT key is configured.

---

## Name your assistant

The project is **Namma Agent**, but the assistant you talk to can be called
anything. One switch, applied everywhere:

```yaml
# namma_agent/config.yaml
assistant:
  name: Jarvis
```

or, without editing any file:

```bash
ASSISTANT_NAME=Jarvis python -m namma_agent --server
```

The name flows into the model's system prompt (its self-identity), the web UI
(title, greeting, sidebar, composer), the `about_namma` self-knowledge tool, and
the Telegram `/help`. `NAMMA_*` environment-variable names (API keys, Telegram
tokens) are intentionally left unchanged — they're stable identifiers, not display
text.

---

## Configuration

- **Base config** (documented, commented): [`namma_agent/config.yaml`](namma_agent/config.yaml)
- **UI / runtime overrides**: `namma_agent/config.local.yaml` (written by the Settings
  panel; the base file is never rewritten)
- **Secrets**: `.env` at the project root (never commit it)
- **Provider override**: `NAMMA_CONFIG=/path/to/config.yaml` to use a different file

Configure several providers (each with its own API key) and a curated list of
switchable models from **Settings → Providers / Models** — then switch brains from
the picker at the top of any chat.

---

## Optional system tools

Each degrades gracefully — if the binary is missing, the tool returns a clear
"install X" message instead of crashing.

- **Vision:** `grim` / `scrot` / `gnome-screenshot` (capture), `tesseract` (OCR).
- **Security:** `nmap`, `gobuster`, `dig`.
- **Real browser control:** Playwright (`pip install playwright && playwright install chromium`).
- **Document conversion:** `convert_document` turns the Markdown the agent writes
  into the format a user actually asks for (Word, PDF, PowerPoint, etc.). With
  [`pandoc`](https://pandoc.org/installing.html) on PATH (a system binary, not a pip
  package) it handles every format at high fidelity. Without it, the built-in
  fallbacks still cover `md`, `txt`, `html`, and `docx` (the last via `python-docx`);
  any other target returns an "install pandoc" message.
- **Diagrams (Learning Room):** `render_diagram` produces PNGs **entirely
  server-side** — the browser never renders mermaid. It uses the hosted
  `mermaid.ink` API first (needs `requests`), then falls back to a fully local
  renderer for offline use (`pip install mermaid-cli && playwright install
  chromium`). If both are unavailable it degrades to a text outline.
- **Google Workspace:** the [`gws` CLI](https://github.com/googleworkspace/cli) for
  the Gmail/Calendar tools (`gws auth login` once).

---

## Documentation

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — how the system works, UML diagrams,
  and the reasoning behind every major technical decision. Start here.
- **[docs/SKILLS.md](docs/SKILLS.md)** — how skills (procedural memory) work and are created.
- **[docs/EXTENDING.md](docs/EXTENDING.md)** — create your own tools and skills.
- **[docs/SELF_MODIFICATION.md](docs/SELF_MODIFICATION.md)** — how the assistant extends
  and reconfigures itself at runtime.

---

## Testing

```bash
python -m pytest namma_agent/tests/ -q       # full suite, offline/mocked, no API key
```

---

## Troubleshooting

- **`ModuleNotFoundError: anthropic`** → install your provider SDK
  (`pip install anthropic` / `openai` / `google-genai`).
- **Native window doesn't open** → pywebview missing or no display; use
  `python -m namma_agent --server` and open the browser.
- **Provider/auth errors on first chat** → key missing/typo in `.env`, or
  `provider.type` doesn't match the key you set.

---

## License

[MIT](LICENSE). © 2026 Santhosh Reddy and the Namma Agent contributors.
