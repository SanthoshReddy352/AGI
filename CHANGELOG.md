# Changelog

All notable changes to FRIDAY are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until `1.0.0`, minor version bumps may include breaking changes.

## [Unreleased]

### Added

- **Open-source launch readiness** — `CHANGELOG.md`, GitHub CI workflow
  (`pytest` matrix on Linux + Windows × Python 3.10–3.13, `ruff`, and the
  intent eval/conflict gates), issue templates (bug report, feature request,
  config), and a pull-request template mirroring the CONTRIBUTING "Definition
  of done".
- **`docs/ARCHITECTURE.md`** — launch-facing architecture overview with the
  routing-pipeline + confidence-band diagram and the workflow state-machine
  section (promoted from the historical `docs/architecture.md`).
- **`docs/intent_recognition.md`** — the 5-layer hybrid router explained:
  layers, confidence bands and thresholds, the eval harness, and a how-to for
  adding an intent.
- **Production-grade intent recognition** (Phase 2) — intent eval harness +
  103-case golden corpus with a CI gate (`scripts/diagnostics/intent_eval.py`),
  conflict/overlap detector, calibrated confidence infrastructure, and routing
  observability (`scripts/diagnostics/routing_stats.py`).
- **Multi-step workflow guards** (Phase 3):
  - Unified slot-filling (`core/planning/slot_filling.py` — `SlotSpec` +
    `SlotFiller`).
  - Confirm-before-destructive guard (`core/workflows/confirmation.py`) over
    `lock_screen`, `delete_goal`, `shutdown_assistant`, `forget_memory`, and
    Home Assistant on/off, plus a memory-wipe preview. Toggle:
    `routing.confirm_destructive`.
  - Disambiguation / "which one did you mean?" guard
    (`core/workflows/disambiguation.py`) over `search_indexed_files`,
    `launch_app`, and `query_document`. Toggle: `routing.disambiguate`.
  - Reminder slot-fill migrated to the live `set_reminder` two-phase YAML
    template; the `ReminderWorkflow` shim was retired.

### Changed

- **Calendar events are now Google-owned.** The local SQLite calendar-event
  capabilities were removed; `create_calendar_event` / `cancel_calendar_event`
  resolve to the Google Calendar (WorkspaceAgent) path, and move/reschedule
  retargets to `update_calendar_event`. Reminders remain a local feature.
- **Cross-platform hardening** (Phase 1) — subprocess calls pass
  `encoding="utf-8", errors="replace"` consistently (fixes Windows cp1252
  `UnicodeDecodeError`); `core/shell_prefix.py` falls back to `COMSPEC` on
  Windows instead of a non-existent `/bin/sh`; `scratch/` is untracked so a
  fresh clone collects tests cleanly.
- `docs/config_reference.md` — documented the Phase 3 `routing.*` confidence,
  learning, and guard keys, plus the `code_execution` and `file_index`
  sections.

### Fixed

- Several deterministic-routing bugs surfaced by the eval harness — e.g. "end
  the focus session" routing to `start_focus_session`, "take a note" routing to
  `start_dictation`, and missing routes for "export my memories" / "how much
  RAM am I using" / "is it going to rain today".
- Removed a dead duplicate `handle_update` in `modules/goals/plugin.py` that
  shadowed the disambiguation-aware definition.

## [0.1.0] — 2026-05-29

Initial public-preview snapshot of FRIDAY: a local-first, voice-driven AI
desktop assistant for Linux and Windows.

### Added

- **Voice I/O** — "Hey Friday" wake word (Porcupine), `faster-whisper` STT,
  Piper neural TTS with barge-in; text-chat fallback.
- **Conversation** — local chat model with session-aware turns, custom
  personas, and a three-tier memory (episodic / semantic / procedural) backed
  by SQLite domain stores (`core/stores/`) and a Chroma vector index.
- **v2 turn orchestration** — `TurnOrchestrator` with a 5-layer hybrid router
  (deterministic intent → route scorer → embedding → lexical → LLM planner),
  selective executor, and optional LangGraph execution engine.
- **System control** — brightness, volume, screen lock/unlock, screenshots,
  app launch, window queries, clipboard.
- **Document intelligence** — local RAG over PDFs/Office/Markdown
  (`markitdown` + Chroma).
- **Vision (VLM)** — screenshot explainer, OCR, screen summarizer, UI-element
  finder, and code debugger via a local SmolVLM2 model.
- **Online skills (opt-in)** — browser automation (Playwright/Selenium),
  web/quick-answer search, news & world monitoring, weather; gated behind
  per-turn online consent.
- **Productivity** — reminders, notes, tasks, goals, focus sessions,
  dictation, and Google Calendar events.
- **Extensibility** — capability registry across 28 plugin modules, optional
  external MCP client.
- **Privacy & safety** — ask-before-online consent, scoped security tooling
  (lab mode), and a local audit log.
- **Cross-platform** — one codebase for Linux and Windows with `setup.sh` /
  `setup.ps1` parity.

[Unreleased]: https://github.com/SanthoshReddy352/Friday_Linux/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/SanthoshReddy352/Friday_Linux/releases/tag/v0.1.0
