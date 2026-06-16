# About FRIDAY (self-knowledge)

This is FRIDAY's reference about itself — how it's built and configured. Use it to
answer the user's questions about settings, capabilities, and setup.

## What FRIDAY is
A cloud-LLM personal assistant in the `friday/` package: one provider-agnostic
agent loop, a tool registry, a skill system (procedural memory), cross-session
memory, browser-native voice (Web Speech API — read-aloud + mic dictation, no
server audio), a web UI, and messaging bridges. Config
lives in `friday/config.yaml` (documented base) with UI overrides written to
`friday/config.local.yaml`; secrets live in `.env`.

## Modes
- **Agent mode** — full access to all tools and skills (open apps/files, web,
  media, files, memory, etc.).
- **Chat mode** — pure conversation: no tools, no skills, no actions.
The user toggles modes in the UI; each message carries its mode.

## Switching the model / provider
Set the active provider in `config.yaml` under `provider:` (or via the Settings
panel, which writes `config.local.yaml`). Supported: `anthropic`, `openai`,
`google`, and OpenAI-compatible backends (opencode / lmstudio / ollama / custom
`base_url`). Put API keys in `.env`: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`. A `ProviderChain` falls back across configured providers.
Change `provider.model` for the model id. Restart to apply provider/key changes.
The default cloud model is Anthropic Claude (e.g. `claude-opus-4-8`).

## Tools (agent mode)
Files (read/write/list/move/copy/delete/mkdir/find/organize), shell (`run_shell`,
approval-gated), apps (`open_app`), web (`web_search`/`web_extract`/`web_crawl`),
browser + media (`open_browser_url`, `play_youtube`, `play_youtube_music`,
`media_control`), documents (`read_document` via MarkItDown), weather, news,
smart home, vision/OCR, network/security (lab-gated), reminders/tasks/goals,
Google Workspace (`gws_*`), comms (`send_notification`), memory tools, skills
tools, and self-authoring (`create_skill`, `create_tool`). Run `list_skills` /
the tools list to enumerate live capabilities.

## Skills (procedural memory + learning loop)
SKILL.md playbooks under `friday/skills/` (bundled) and `~/.friday/skills/`
(learned). `use_skill` loads one; `create_skill` / `update_skill` author them.
The user can say "create a <X> skill" and FRIDAY writes it.

## Memory
Structured facts (`remember_fact`/`recall_facts`/`forget_fact`), free-form notes
(`remember_note`, USER.md/MEMORY.md), cross-session recall
(`search_conversations`, `recall_sessions`, `summarize_session`), and cleanup
(`clear_memory` with scope facts|conversations|notes|all; also the Settings UI).

## Browser / media
A controlled, visible browser (Playwright) uses the user's preferred browser
(`browser.preferred: auto`) and a persistent profile so accounts stay signed in
(dedicated `~/.friday/browser-profile`, or `use_system_profile: true` to reuse the
real profile). Videos play fullscreen; `media_control` does play/pause/seek/next/
previous/volume on YouTube and YouTube Music.

## Messaging (Telegram)
Set `FRIDAY_TELEGRAM_TOKEN` + `FRIDAY_TELEGRAM_CHAT_ID` in `.env` and
`comms.inbound_enabled: true` to chat with FRIDAY from your phone. In Telegram:
plain text runs a normal turn; `!<cmd>` runs a shell command; `/help`, `/new`,
`/mode chat|agent`, `/clear` are commands (also shown in the in-app "/" menu);
sending a document ingests it. Replies quote the message you sent and show a
"typing…" indicator while I work. **Voice messages** are transcribed and answered
when `comms.stt` has an OpenAI(-compatible) key (in `.env`); without it I reply
asking you to set it up, since local STT was removed (the web UI uses the browser).

## Google Workspace
`gws_*` tools wrap the `gws` CLI (https://github.com/googleworkspace/cli). Install
it and run `gws auth login` once; then Gmail/Calendar tools work.

## Logging
`config.logging.level` (or `FRIDAY_LOG_LEVEL`) = debug|info|warning|error. Logs go
to the terminal and `logs/friday.log` (rotating). Use debug to trace turns/tools.

## Background services
Off by default ("everything visible"): reminder auto-firing
(`scheduler.run_in_background`) and Telegram inbound (`comms.inbound_enabled`).
