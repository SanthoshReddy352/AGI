# FRIDAY v2 Migration — Status Tracker

> **This is the live progress ledger for the cloud-only rebuild.** It is the single
> authority on what is done, in progress, and pending. Every task of every phase is
> listed here. The canonical plan ("god document") is
> [`FRIDAY_V2_GOD_DOC.md`](./FRIDAY_V2_GOD_DOC.md).

**Last updated:** 2026-06-06 (Phase 7 Waves 1–5 complete — 53 tools; awareness + multimodal-vision deferred)

## Legend

- `[ ]` TODO — not started
- `[~]` IN-PROGRESS — actively being worked
- `[x]` DONE — completed and verified

## Progress summary

| Phase | Title | Status |
|------|-------|--------|
| 0 | Safety net & docs | `[x]` DONE |
| 1 | Provider layer | `[x]` DONE |
| 2 | Agent core | `[x]` DONE |
| 3 | Model-narrated progress | `[x]` DONE |
| 4 | Backend server | `[x]` DONE |
| 5 | Modern GUI | `[x]` DONE |
| 6 | Voice (Piper TTS + STT) | `[x]` DONE |
| 7 | Module porting waves | `[x]` waves 1–4 + Wave 5 (comms/tasks/goals/mcp/onboarding/focus/runner) DONE; only `awareness` + multimodal-vision deferred |
| 8 | Purge legacy | `[ ]` TODO |
| 9 | Finalize | `[ ]` TODO |

---

## Phase 0 — Safety net & docs
- [x] Create god doc (`FRIDAY_V2_GOD_DOC.md`)
- [x] Create this status tracker (`STATUS_V2.md`)
- [x] Add "ACTIVE MIGRATION (v2)" pointer to `CLAUDE.md`
- [x] `git init`, `.gitignore` sanity (added piper tarball), initial commit
- [x] Baseline tag `v1-pre-rebuild`
- [x] Record baseline metrics (see below)

**Baseline metrics (v1, 2026-06-06):**
| Metric | Value |
|--------|-------|
| Python files | 478 |
| Python lines | 101,937 |
| `core/` files | 146 |
| Modules | 27 |
| Test files | 168 |
| `intent_recognizer.py` | 3,564 lines |
| `router.py` | 1,113 lines |
| `app.py` | 1,187 lines |
| Python runtime | 3.13.12 |
| Git tracked files | 687 |
| Rollback point | tag `v1-pre-rebuild` |

## Phase 1 — Provider layer
- [x] `friday/core/providers/base.py` (Provider ABC + `LLMResponse` + `ToolCall`; neutral message/tool schema)
- [x] `openai_provider.py` (native OpenAI, thin subclass of compat)
- [x] `anthropic_provider.py` (native `tool_use` + prompt caching + streaming)
- [x] `google_provider.py` (Gemini function-calling, google-genai SDK)
- [x] `openai_compat.py` (reference OpenAI-style impl: tools + streaming + retries; opencode / lmstudio / ollama / custom base_url)
- [x] `registry.py` (config-driven selection + `ProviderChain` fallback + `--test` CLI)
- [x] `friday/config.yaml` provider section + `friday/config.py` loader + `.env.example` keys (ANTHROPIC/OPENAI/GOOGLE/FRIDAY_API_KEY)
- [x] `friday/core/logger.py` (package-local, no dep on legacy `core/`)
- [x] `friday/tests/test_providers.py` — **21 tests passing**

## Phase 2 — Agent core
- [x] `friday/core/tools.py` ToolRegistry (`Tool`/`ToolResult`/`@tool`; neutral defs + approval gate)
- [x] `friday/core/memory.py` single SQLite (sessions/turns/facts standalone-FTS5/audit, thread-safe)
- [x] `friday/core/persona.py` (port persona YAML→prompt + agent/narration preamble + USER_FACTS) + `friday/personas/friday_core.yaml`
- [x] `friday/core/agent.py` the one loop (generate→tools→loop→final, streaming, bounded, event emit)
- [x] `remember_fact` / `recall_facts` tools (`friday/core/builtins.py`)
- [x] `friday/tests/test_agent_loop.py` (7 tests)
- [x] `friday/tests/test_memory.py` (6 tests)
- [x] **All 33 friday tests passing**

## Phase 3 — Model-narrated progress
- [x] `friday/core/events.py` (EventBus pub/sub + `fanout` multi-sink emit)
- [x] `friday/core/narration.py`: spoken model preamble alongside tool calls
- [x] Context-aware long-task progress lines (timer pattern, tool/args-aware, pluggable `phrase_generator`)
- [x] Tool-step narration on `tool_finished` (opt-in) + suppression after turn finalized
- [x] `friday/tests/test_narration.py` (10 tests); 43 friday tests passing

## Phase 4 — Backend server
- [x] `friday/service.py` FridayService (wires provider+tools+memory+agent+narration; injectable for tests)
- [x] `friday/server/api.py` FastAPI app + REST (health/config/tools/persona/session) + static GUI mount
- [x] WebSocket `/ws` event protocol (token/preamble/tool_started/tool_finished/turn_completed/turn_result)
- [x] Approval round-trip over socket (id'd approval_request ↔ approval_response; per-turn approval gating in agent)
- [x] `friday/tests/test_server.py` (6 tests: REST + WS plain/tool/approval-approved/declined); 49 friday tests passing

## Phase 5 — Modern GUI
- [x] `friday/webui/` Vite + React + Tailwind scaffold (built to `webui/dist`)
- [x] Streaming chat transcript (token-by-token via `useFriday` WS hook)
- [x] Tool/progress timeline component (live preamble + tool states)
- [x] Voice orb / push-to-talk control (+ approval modal)
- [x] Settings (provider/model/persona/tools view)
- [x] Dark modern glassy theme (Tailwind, animated)
- [x] `friday/app.py` + `friday/__main__.py`: uvicorn thread + pywebview window (browser fallback); serves `webui/dist`
- [x] End-to-end smoke verified (GUI served at `/`, REST, WS turn stream); 49 tests passing

## Phase 6 — Voice
- [x] `friday/voice/tts.py` Piper (queue worker, sentence chunking, playback backend select, graceful no-op); speaks final answers + narration
- [x] `friday/voice/stt.py` local push-to-talk (faster-whisper + sounddevice; start/stop + record_until_silence; low-signal filter)
- [x] Barge-in (`stop_speech` WS msg → `tts.stop()`); STT endpoints (`/api/voice`, `/api/stt/record`)
- [x] Wired into FridayService (Piper as narration + final-answer speech sink); `friday/tests/test_voice.py` (7); 56 tests passing

## Phase 7 — Module porting waves
*(each module: convert params to JSON Schema, drop intent regex, add focused test)*
- [x] Wave 1: file_ops (read/write/list), shell (run_shell), system (system_info), apps (open_app) — clean v2 tools + auto-discovery (`friday/tools/`) + `friday/core/safety.py` (PathSecurity, destructive classification); `test_tools_wave1.py` (9). 65 tests passing.
- [x] Wave 2: web (`web_search`/`web_extract`/`web_crawl`, stdlib DDG + HTML-to-text), browser (`open_browser_url`/`search_google`/`play_youtube`/`play_youtube_music` via stdlib `webbrowser`), network (`ping_host`/`dns_lookup`/`check_port`/`public_ip`), security (`port_scan`/`ping_sweep`/`dir_enum`/`dns_enum` — nmap/gobuster/dig, `lab_mode`+`authorized_scopes` gated, approval-gated). `config.yaml` security section + safety destructive set. `test_tools_wave2.py` (21). 86 tests passing.
- [x] Wave 3: weather (`get_weather` — keyless Open-Meteo+Nominatim, 24h cache), smart_home (`ha_turn_on`/`ha_turn_off`/`ha_get_state`/`ha_set_temperature` — Home Assistant REST, config+env gated, mutators approval-gated), news (`get_news` — keyless RSS, stdlib XML), vision (`take_screenshot` CLI capture + `read_text_from_image` tesseract OCR — text-channel only; visual *description* deferred until multimodal agent input), document_intel (`read_document` — txt/md/csv/pdf/docx text extraction, path-secured), scheduler (`add_reminder`/`list_reminders`/`remove_reminder` — persisted `data/reminders.json`; firing is a future runner). `config.yaml` smart_home+scheduler sections; safety destructive set extended. `test_tools_wave3.py` (19). 105 tests passing.
- [x] Wave 4: memory (`forget_fact` + `search_conversations` added to existing `remember_fact`/`recall_facts`; `delete_fact`/`search_turns` on the DB), delegate_task (one sub-agent tool over a read-only research toolset — collapses v1 Delegate/MoA/ResearchAgent; excludes itself so it can't recurse), persona (`switch_persona`/`list_personas` + `friday_concise`/`friday_playful` personas). Wired via `register_agent_tools` in `service.py` (needs live agent/provider/db). `test_tools_wave4.py` (11). **116 tests passing. 40 tools total.**

### Phase 7 — not yet ported (beyond the original wave plan)
The waves above cover the god-doc's value-priority list. These v1 modules were **not** in that plan and remain unported — tracked here for the "port everything" goal (candidate **Wave 5+**):
- [x] **comms** — `friday/comms/` (Telegram + Discord, stdlib, env-gated) + `send_notification` tool + Telegram inbound bridge wired into the service (chat with FRIDAY from your phone). `test_comms.py` (12).
- [x] **task_manager** — `add_task`/`list_tasks`/`complete_task`/`remove_task` (persisted `data/tasks.json`). `test_tools_tasks_goals.py`.
- [x] **goals** — `add_goal`/`list_goals`/`update_goal_progress`/`remove_goal` (persisted `data/goals.json`).
- [x] **mcp_client** — `friday/mcp/` persistent stdio JSON-RPC client (correct initialize→tools/list→tools/call handshake; no `mcp` SDK dep) + `MCPManager` registers each server's tools as `mcp_<server>_<tool>` + `mcp_list_servers`. Wired into the service from `config.mcp.servers`. `test_mcp.py` (6, against a real fake stdio server).
- [x] **greeter / onboarding** — re-imagined for the web: `GET`/`POST /api/onboarding` (needs onboarding when no `name` fact), backed by memory. `test_onboarding_focus.py`.
- [x] **focus_session** — `start_focus`/`focus_status`/`end_focus` (data/focus.json); start queues a due reminder so the ReminderRunner announces the end.
- [x] **world_monitor** — covered by `get_news` (world/technology/security/business/science categories).
- [x] **workspace_agent** — covered by the file tools (`read_file`/`write_file`/`list_dir`) + `run_shell` + `delegate_task`.
- [ ] **awareness** — proactive ambient suggestions from live activity monitoring. **Deferred**: needs a persistent activity-watching daemon that doesn't fit the stateless cloud-only design; the proactive-timer slice is delivered via focus_session + the reminder runner.
- [ ] **vision visual description** — describe/review/roast screenshots; **deferred** (user's call) on multimodal image input in the agent message schema (text-only today)
- [x] **scheduler firing** — `friday/core/reminder_runner.py`: `add_reminder` parses `when` ("in 10 minutes" / "at 09:30" / ISO) → `due_ts`; a background `ReminderRunner` fires due reminders (speak + notify) and marks them. `test_reminder_runner.py` (8).

## Phase 8 — Purge legacy
- [ ] Delete intent_recognizer, planning/, routing layers, MoA, task_graph_executor, workflow_orchestrator
- [ ] Delete stores/, memory/, memory_service, session_rag, reasoning/, delegate/delegation
- [ ] Delete old llm_providers, gui/ (PyQt), cli/, main.py, local GGUF + kokoro*
- [ ] Prune/rewrite tests/

## Phase 9 — Finalize
- [ ] Rewrite README, SETUP_GUIDE*, requirements.txt, setup.sh/ps1, config.yaml, .env.example
- [ ] Rewrite CLAUDE.md (remove intent-recognizer rules; remove migration pointer)
- [ ] Rewrite docs/testing_guide.md for v2
- [ ] Full green test suite + end-to-end launch verification

---

## Change log
- 2026-06-06 — Migration kicked off. God doc + status tracker created.
- 2026-06-06 — Phase 0 complete: git initialized, baseline tag `v1-pre-rebuild`, CLAUDE.md migration pointer added, baseline metrics recorded.
- 2026-06-06 — Phase 1 complete: full provider layer (native Anthropic/OpenAI/Google + generic OpenAI-compat for opencode/lmstudio/ollama/custom), normalized `LLMResponse`/`ToolCall`, native tool-calling + streaming, config-driven `ProviderChain` fallback, v2 config loader. 21 tests passing.
- 2026-06-06 — Phase 2 complete: agent core — ToolRegistry, single-SQLite memory (turns/facts FTS5/audit), persona→prompt, the one agent loop (tool calling + streaming + events + bounded loop), memory built-in tools. 33 tests passing total. Starting Phase 3 (model-narrated progress).
- 2026-06-06 — Phase 3 complete: event bus + fanout, narration engine (model preamble spoken in-the-moment, context-aware long-task progress lines, opt-in tool-result narration, suppression on finalize). 43 tests passing. Starting Phase 4 (backend server).
- 2026-06-06 — Phase 4 complete: FridayService + FastAPI/WebSocket backend (streaming turn channel, tool events, approval round-trip). Fixed an approval-deadlock (duplicate approval_request). 49 tests passing. Starting Phase 5 (modern GUI).
- 2026-06-06 — Phase 5 complete: modern React+Tailwind GUI (streaming chat, live tool/progress timeline, voice orb, approval modal, settings), pywebview launcher serving the built bundle from FastAPI. Verified end-to-end. Starting Phase 6 (voice).
- 2026-06-06 — Phase 6 complete: local Piper TTS (final answers + narration spoken), local push-to-talk STT (faster-whisper), barge-in, voice endpoints; all degrade gracefully without audio hardware. 56 tests passing. Starting Phase 7 (module porting).
- 2026-06-06 — Phase 7 Wave 1 complete: v2 tools package with auto-discovery (file/shell/system/apps), path-security gating, destructive→approval classification. Full vertical verified (model→preamble→tool→narration→final). 65 tests passing. Waves 2–4 (web/browser/security/smart_home/etc.) pending.
- 2026-06-06 — Phase 7 Wave 2 complete: web (search/extract/crawl, stdlib-only DDG + HTML→text), browser (open URL / Google / YouTube / YT-Music via stdlib `webbrowser`, no Selenium), network (ping/dns_lookup/check_port/public_ip), security (nmap/gobuster/dig wrappers — off by default, double-gated by `lab_mode` + `authorized_scopes`, loopback-always, dangerous-flag blocking, approval-gated). Self-contained (no legacy `core/`/`modules/` deps); added `security` config section + extended destructive set. 21 new tests; 86 friday tests passing. Wave 3 (smart_home/document_intel/vision/scheduler/weather/news) pending.
- 2026-06-06 — Phase 7 Wave 5 complete (port-everything): **comms** (Telegram+Discord channels + send_notification + inbound Telegram bridge — chat with FRIDAY from your phone), **task_manager** + **goals** (persisted CRUD), **mcp_client** (persistent stdio JSON-RPC client + MCPManager registering mcp_<server>_<tool>), **scheduler firing** (due-time parsing + background ReminderRunner), **onboarding** (re-imagined as web `/api/onboarding`), **focus_session** (pomodoro tools). world_monitor/workspace_agent folded into news/file+shell+delegate. Deferred: **awareness** (needs ambient daemon, not cloud-shaped) and **multimodal vision** (user's call). 53 tools, **154 tests passing** across 5 commits on `worktree-phase7-wave2`.
- 2026-06-06 — Phase 7 Wave 4 complete + v2 run scaffolding: memory (forget_fact/search_conversations + DB delete_fact/search_turns), delegate_task (bounded sub-agent over read-only research tools; collapses Delegate/MoA/ResearchAgent; non-recursive), persona switch/list + concise/playful personas — wired via register_agent_tools. **Created `friday/requirements.txt`, `friday/.env.example`, and `docs/cloud-migration/RUNNING_V2.md` (setup/run/test guide)** since the cloud app had no install manifest. Smoke-verified: service wires 40 tools, `/api/health`=200, `/api/tools`=40. 11 new tests; **116 passing**. Added an explicit "not yet ported" inventory (comms/Telegram, task_manager, goals, mcp_client, ambient flows) for the port-everything goal.
- 2026-06-06 — Phase 7 Wave 3 complete: weather (keyless Open-Meteo+Nominatim, 24h disk cache, urllib not requests), smart_home (Home Assistant REST — `url`+`token_env`/`.env` gated, friendly-alias resolution, mutators approval-gated), news (keyless RSS via stdlib `xml.etree`, RSS+Atom), vision (`take_screenshot` cross-platform CLI capture + `read_text_from_image` tesseract OCR — text-channel only; true visual description deferred since the neutral message schema is text-only), document_intel (`read_document` txt/md/csv/pdf/docx → text, path-secured, optional pypdf/python-docx), scheduler (persisted reminder store add/list/remove). Self-contained; `config.yaml` smart_home+scheduler sections; destructive set extended (ha mutators + remove_reminder). 19 new tests; 105 friday tests passing. Wave 4 (memory/delegate_task/persona switch) pending.
