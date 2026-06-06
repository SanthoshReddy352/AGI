# FRIDAY — Open-Source Launch Hardening: Status

**Branch:** `launch/hardening-2026-05-30` · **Started:** 2026-05-30 · **Last updated:** 2026-06-01

This tracks the multi-phase effort to prepare FRIDAY for its public open-source
launch. Full plan: [plan/2026-05-30_12-05-00_plan.md](../plan/2026-05-30_12-05-00_plan.md).

> **Framing note:** exploration showed FRIDAY is far more mature than "pre-launch
> from scratch." Intent recognition is already a 5-layer hybrid router, and
> workflows already have a YAML template engine. So this effort is **hardening,
> measuring, and filling gaps** — not rebuilding.

---

## 1. Phase status at a glance

| Phase | Title | Status | Notes |
|---|---|---|---|
| **0** | Launch readiness (docs, CI, templates) | ✅ **Done** | CHANGELOG, CI matrix + intent gate, issue/PR templates, doc-link fix (ARCHITECTURE.md case). `CODE_OF_CONDUCT.md` skipped at user request |
| **1** | Cross-platform hardening | ✅ **Done** | Subprocess encoding, shell fallback, scratch untrack, parity matrix |
| **2** | Production-grade intent recognition | ✅ **Done** | (2.4 slot-filling moved into Phase 3) |
| **3** | Multi-step workflows | ✅ **Done** | ✅ slot-filling foundation (2.4) · ✅ destructive confirmation (7 capabilities) · ✅ slot-fill (✅ §5.4 Step 1 datetime machinery → shared `slot_extractors`; ✅ Step 2 templates + wrap capabilities; ✅ Step 3 **reminder** cutover live — `set_reminder` template, `ReminderWorkflow` retired; ✅ **calendar** resolved — local calendar events removed, Google Calendar owns them (see §5.4)) · ✅ disambiguation (checkpoint 4 — `DisambiguationGuard`, see §5.5) |
| **4** | Docs polish & finalize | ✅ **Done** | ARCHITECTURE.md routing/confidence/workflow diagrams, new intent_recognition.md, config_reference routing keys, CHANGELOG |

Legend: ✅ done · 🔄 in progress · ⏸️ deferred · ⬜ not started

---

## 2. Phase 0 — Launch readiness (✅ done, 2026-06-01)

Low-risk, high-visibility files that make the repo safe to publish.

| Item | Status | Detail |
|---|---|---|
| `CODE_OF_CONDUCT.md` | ⏭️ Skipped | Skipped at user's request (2026-06-01). Stub file already present, so README/CONTRIBUTING links resolve. |
| `CHANGELOG.md` | ✅ | Keep a Changelog format; `Unreleased` + `0.1.0` (2026-05-29 snapshot). |
| `.github/workflows/ci.yml` | ✅ | Fast `lint-and-intent` job (ruff + `intent_eval.py` gate + eval/conflict tests) gating a `pytest` matrix (ubuntu + windows × py 3.10–3.13; `QT_QPA_PLATFORM=offscreen`; PortAudio on Linux). |
| `.github/ISSUE_TEMPLATE/*` | ✅ | `bug_report.yml`, phrasing-first `feature_request.yml`, `config.yml` (contact links → discussions / security advisory / setup guide). |
| `.github/PULL_REQUEST_TEMPLATE.md` | ✅ | Mirrors CONTRIBUTING "Definition of done". |
| README/doc link verification | ✅ | All README targets exist. Fixed the one broken link: README referenced `docs/ARCHITECTURE.md` (uppercase) but only lowercase `docs/architecture.md` was tracked → `git mv` to the uppercase canonical name; updated the lowercase ref in `SETUP_GUIDE_WINDOWS.md`. |

---

## 3. Phase 1 — Cross-platform hardening (✅ done)

| Item | Status | File(s) | Detail |
|---|---|---|---|
| Subprocess encoding (cross-platform bugs) | ✅ | [code_execution/plugin.py](../modules/code_execution/plugin.py), [mcp_client/plugin.py](../modules/mcp_client/plugin.py) | `run_python` (runs via `sys.executable` everywhere) + MCP stdio bridge were missing `encoding=` → Windows cp1252 `UnicodeDecodeError` |
| Subprocess encoding (consistency) | ✅ | [brightness.py](../modules/system_control/brightness.py) ×6, [smart_error_detector.py](../modules/vision/smart_error_detector.py) | Linux-only calls swept for the project rule |
| Windows shell fallback | ✅ | [shell_prefix.py](../core/shell_prefix.py) | `_preferred_shell()` returns `COMSPEC` on `nt`, not a non-existent `/bin/sh` |
| Untrack `scratch/` | ✅ | `git rm --cached scratch/` | Gitignored but committed; `scratch/test_llm.py` loaded a model at import = lone `--collect-only` error in a fresh clone |
| Windows test bug | ✅ | [test_clap_detector.py](../tests/test_clap_detector.py) | Asserted `start_new_session is True` (POSIX-only) → now platform-branched to `DETACHED_PROCESS`; production code was already correct |
| Removed hardcoded `/home/tricky` | ✅ | [test_clap_detector.py](../tests/test_clap_detector.py) | Genericized 2 sample command strings |
| Platform parity matrix | ✅ | [docs/platform_support.md](platform_support.md) | Honest Linux/Windows/macOS feature table + contributor checklist |
| Modification log | ✅ | [docs/testing_guide.md](testing_guide.md) | 2026-05-30 Phase 1 row |

**Sweeps that came back clean:** `strftime("%-")`, `os.uname`, `/dev/null`, hardcoded `/tmp/`, and all `start_new_session` sites (already platform-branched).

**Verification:** `test_clap_detector.py` 11/11. The 10 other failures on this Windows box (`/bin/bash`, `.venv/bin`, PIL) are **pre-existing** (confirmed via `git stash`). Linux behaviour byte-for-byte unchanged.

---

## 4. Phase 2 — Production-grade intent recognition (✅ done)

### 4.1 Sub-tasks

| # | Task | Status | Artifact(s) |
|---|---|---|---|
| 2.1 | Intent eval harness + golden corpus + CI gate | ✅ | [intent_eval.py](../scripts/diagnostics/intent_eval.py), [tests/intent_corpus/](../tests/intent_corpus/), [test_intent_eval.py](../tests/test_intent_eval.py) |
| 2.2 | Conflict / overlap detector | ✅ | `_clause_parsers()` refactor, `--conflicts` mode, [test_intent_conflicts.py](../tests/test_intent_conflicts.py) |
| 2.3 | Calibrated confidence (safe infra) | ✅ | [intent_engine.py](../core/planning/intent_engine.py), [test_planning_engines.py](../tests/test_planning_engines.py) |
| 2.4 | Unified slot-filling | ✅ **Done (in Phase 3)** | [slot_filling.py](../core/planning/slot_filling.py) `SlotSpec`+`SlotFiller` (extractor→LLM→default precedence; template bridge), [test_slot_filling.py](../tests/test_slot_filling.py) 17 tests |
| 2.5 | Routing observability | ✅ | [routing_stats.py](../scripts/diagnostics/routing_stats.py), [test_routing_stats.py](../tests/test_routing_stats.py) |
| 2.6 | Docs (audit refresh + testing guide) | ✅ | [intent_routing_audit.md](intent_routing_audit.md) §Addendum, [testing_guide.md](testing_guide.md) |

### 4.2 Routing bugs found by the harness & fixed

All in [core/intent_recognizer.py](../core/intent_recognizer.py); each fails on pristine HEAD (the corpus is the regression test).

| Utterance | Was | Now | Root cause |
|---|---|---|---|
| "end the focus session" | `start_focus_session` | `end_focus_session` | end regex allowed only `my`, not `the` |
| "focus session status" | `start_focus_session` | `focus_session_status` | status regex missed the `session` noun |
| "take a note" | `start_dictation` | `save_note` | dictation claimed a bare `note`; now needs `note taking` |
| "what are my notes" / "show me my notes" | (no route) | `read_notes` | added interrogative + filler-`me` phrasings |
| "export my memories" | (no route) | `export_memory` | required singular `memory`; now `memor(y\|ies)` |
| "how much ram am I using" | (no route) | `get_cpu_ram` | added the phrasing |
| "is it going to rain today" | (no route) | `get_weather` | added `going to rain/snow` |
| "give me a literature review of X" | (no route) | `research_topic` | accepts a `give me a …` prefix (fixes a pre-existing failing test) |

### 4.3 Health signals (current)

| Metric | Value |
|---|---|
| Eval corpus | **103 cases / 13 domains** |
| Recall | **100%** (93/93 positives) |
| Negative accuracy | **100%** (10/10) |
| Latent poaching | **0** |
| Undocumented overlaps | **0** (only the intentional `search_indexed_files`⇄`search_file` split) |
| New Phase 2 tests | **23 passing** |

**Verification:** broad regression run = 1155 passed. The 3 `test_routing_snapshots.py` failures (launch_firefox / volume_up_steps / multi_open_then_time) are **pre-existing** (verified via `git stash` of only `intent_recognizer.py`).

---

## 5. Phase 3 — Multi-step workflows (✅ done)

Build on the existing YAML template engine + `WorkflowOrchestrator`; LangGraph
`StateGraph` for branching flows. Two reusable nodes: **confirmation** and
**disambiguation/pick**. Each new workflow needs a regex intent + tests +
testing-guide entry.

Delivered in **checkpoints** (per user request — one reviewable unit at a time).

| Group | Targets | Status |
|---|---|---|
| **Slot-filling foundation** (was 2.4) | `SlotSpec`/`SlotFiller` wrapping `slot_extractors` + `QwenPlanner.fill_slots` + template `ask:`/`slot:` | ✅ **Done** — [slot_filling.py](../core/planning/slot_filling.py), 17 tests |
| **Destructive confirmation** (no guard today) | `lock_screen`, `delete_goal`, `cancel_calendar_event`, `ha_turn_on`/`ha_turn_off`; wipe-preview | ✅ **Done** — [confirmation.py](../core/workflows/confirmation.py) `ConfirmationGuard` + `_parse_pending_destructive` interceptor + `confirm_pending_action`/`cancel_pending_action`; all 5 handlers + wipe-preview wired; 26 tests; `routing.confirm_destructive` toggle |
| **Destructive confirmation (expanded)** | `shutdown_assistant`, `forget_memory` + goals `handle_update` duplicate-method fix | ✅ **Done** — same `ConfirmationGuard`; [test_destructive_guard_handlers.py](../tests/test_destructive_guard_handlers.py) (6) |
| **Slot-fill** | `set_reminder`, `create_calendar_event`, `move_calendar_event` (extract NL datetime into reusable capabilities) | ✅ **Reminders done (Steps 1-3); calendar Step 3 deferred** — ✅ Step 1: datetime parser → shared [`slot_extractors`](../core/planning/slot_extractors.py) (plugin delegates, unchanged). ✅ Step 2: templates + wrap capabilities. ✅ **Step 3 reminders live**: `set_reminder` two-phase template is the live reminder slot-fill ([set_reminder.yaml](../core/workflows/templates/set_reminder.yaml) v0.2.0 + `extract_reminder_date`/`extract_reminder_time`/`create_reminder`); `ReminderWorkflow` retired; behaviour (two-phase date→time, bare-hour, afternoon bump) preserved. ✅ **Calendar resolved (2026-05-31)**: local calendar-event capabilities removed — Google Calendar (WorkspaceAgent) owns calendar events; move/reschedule retargeted to `update_calendar_event`. See **§5.4** |
| **Disambiguation** | `search_indexed_files` (pick result), `launch_app` (ambiguous name), `query_document` (file picker) | ✅ **Done** — [disambiguation.py](../core/workflows/disambiguation.py) `DisambiguationGuard` + `_parse_pending_pick` interceptor + `pick_pending_candidate`/`cancel_pending_pick`; all three wired; 57 tests; `routing.disambiguate` toggle (see §5.5) |
| Per-workflow intent + tests + T-entry | All of the above | ✅ for shipped groups (confirm/cancel reuse the generic interceptor; datetime extractor is template/SlotFiller infra) |

> Agentic services (`research_planner`, `research_mode`, `focus_mode`) stay
> LLM/thread-driven — correctly *not* templatable.

### 5.1 Checkpoint 1 — Slot-filling foundation (Track 2.4) ✅

`core/planning/slot_filling.py` — `SlotSpec` + `SlotFiller` unify the three
pre-existing slot mechanisms (deterministic `slot_extractors`, template
`ask:`/`slot:`, `QwenPlanner.fill_slots`) behind one cheapest-first interface:
caller-known → deterministic extractor → LLM (only for still-missing
*required* slots) → optional default. Pure + offline-safe (`planner=None`
degrades to deterministic-only); named-extractor registry
(`register_extractor`/`get_extractor`); alias normalization; and
`specs_from_template()` bridging a `WorkflowTemplate`'s ask-steps. 17 tests.

### 5.2 Checkpoint 2 — Confirm-before-destructive guard ✅

`core/workflows/confirmation.py:ConfirmationGuard` generalizes the proven
memory-wipe two-step into one reusable mechanism:

- A destructive handler calls `guard.arm(action, args, preview)` **once it has
  resolved its target** (so the preview is specific) unless `args["_confirmed"]`
  is set — persisting `session_state.pending_destructive_action`.
- New `IntentRecognizer._parse_pending_destructive` interceptor (first in the
  parser chain) routes the next turn → `confirm_pending_action` (affirmation:
  yes/yeah/sure/do it/confirm/go ahead/proceed) or `cancel_pending_action`
  (anything else). It does **not** clear the flag; the guard's `confirm`/
  `cancel` own that (single source, can't go stale).
- `confirm()` re-dispatches the stored capability via `CapabilityExecutor` with
  `_confirmed=True` — the same handler then runs its real side effect.
- `confirm_pending_action`/`cancel_pending_action` registered in `core/app.py`
  alongside `app.confirmation_guard`. Config gate `routing.confirm_destructive`
  (default true). The explicit `/lock` slash stays immediate (bypasses guard).

**Wired (one guard line each):** `lock_screen`, `delete_goal` (composes with
its "which goal?" disambiguation — arms only after a single goal resolves),
`cancel_calendar_event`, `ha_turn_on`, `ha_turn_off`. Plus **memory-wipe
preview**: `wipe_memory_init` now lists real counts (N profile facts, M
memories, K goals) before confirming. 26 tests.

### 5.3 Checkpoint 3 — Shared datetime extractor + expanded guards + bug fix ✅

1. **Shared NL-datetime extractor** — `slot_extractors.extract_datetime(text,
   now=)` returns ISO-8601 for the common shapes (relative "in 15 minutes" /
   "in an hour"; today/tomorrow/weekday + clock; bare "at 3pm"/"15:30"/"noon"/
   "midnight"; date-only → 09:00; passed bare time → next day). Registered as
   the `datetime` named extractor. 16 tests. *(Note: this is the lighter shared
   extractor; the production reminder parser is still the richer in-handler one
   — see §5.4.)*
2. **Expanded confirmation guard** to `shutdown_assistant` and `forget_memory`
   (forget arms with the resolved key in its preview). 6 handler tests.
3. **Latent bug fixed:** `modules/goals/plugin.py` defined `handle_update`
   **twice** — the first (no disambiguation, silently picked `matches[0]`) was
   dead code shadowed by a later disambiguation-aware definition. Removed the
   dead duplicate. An AST sweep for duplicate methods across `core/`+`modules/`
   found **no others** (the 4 `router.py` + 1 `turn_context.py` apparent dups
   are intentional `@property`/setter pairs).

### 5.4 Reminder/calendar template migration (✅ reminders live · ✅ calendar resolved → Google-only)

> **Update 2026-05-31 (calendar landmine resolved — local calendar events
> removed):** the dual-backend question from the deferred calendar half has been
> settled by user decision — **rip out the LOCAL calendar-event path; Google
> Calendar (WorkspaceAgent) owns calendar events.** Removed TaskManager's
> `create_calendar_event` / `move_calendar_event` / `cancel_calendar_event` /
> `list_calendar_events` / `schedule_calendar_event` capabilities + handlers, the
> never-live `create_calendar_event.yaml` template, and the `extract_datetime`
> capability. The `create_calendar_event` / `cancel_calendar_event` name
> collisions now resolve to the Google handlers; the move/reschedule intent
> patterns were retargeted to Google's `update_calendar_event`. **Reminders are
> kept** (separate local feature): `set_reminder` (the two-phase template),
> `list_reminders`, `create_reminder`, and the firing/notification core are
> unchanged; listing/briefing simplified to reminders-only. **Trade-off
> (user-accepted):** reminders are no longer voice-cancellable/movable (those
> handlers were dual-purpose and went to Google) — a `cancel_reminder` can be
> re-added if wanted. The shared `_extract_event_title` / `_strip_temporal_*`
> helpers stay in TaskManager (the Google path reuses them for summary
> extraction, alongside `_parse_datetime_parts`/`_combine_date_time`). Verified
> zero new failures (`test_workspace_calendar` Google suite green; full
> orchestration still the same 12 pre-existing env failures; intent gates green).
> `data/tool_catalog.yaml` updated.


> **Update 2026-05-31 (Step 3 — reminder cutover landed):** the reminder slot-fill
> is now driven **live** by the `set_reminder` YAML template; the `ReminderWorkflow`
> delegation shim has been **retired**. The calendar half of Step 3 is **deliberately
> deferred** — a landmine surfaced during implementation (below).
>
> **Reminder cutover (done):**
> - `TaskManagerPlugin.handle_set_reminder` now parses the first turn richly
>   (unchanged `_parse_reminder_request`); a complete date+time (or relative
>   offset) schedules immediately via `_schedule_reminder`, otherwise it seeds
>   whichever of date/time it has and hands off to
>   `WorkflowOrchestrator.start_template_slot_fill("set_reminder", …)`.
> - `set_reminder.yaml` (v0.2.0) is a **two-phase** template — separate `date`
>   then `time` ask-steps backed by new `extract_reminder_date` /
>   `extract_reminder_time` capabilities — chosen to **preserve** the pre-cutover
>   follow-up behaviour: ask date → ask time, bare-hour answers ("four" → 4
>   o'clock via `allow_bare`), and the ambiguous-past-morning → afternoon bump
>   (via the shared `combine_date_time`). The schedule step runs the
>   `create_reminder` capability → `_schedule_reminder` → the unchanged
>   `_create_calendar_event` core (same notification/firing path).
> - **UX deltas (accepted):** the both-missing first prompt is now "What date
>   should I remind you?" (was the combined "When should I remind you? Please
>   mention the date and time"); a date+time given together as a *single
>   follow-up* fills only the date and then asks for the time (the first-sentence
>   complete case still resolves in one turn). The "today" standalone follow-up is
>   still poached by the `get_date` intent — a **pre-existing** router precedence
>   issue (date/time aren't `_SHORT_ANSWER_SLOTS`), not introduced here.
> - **Verification:** full `test_workflow_orchestration.py` goes from 13→12
>   pre-existing failures — the *only* delta is `test_reminder_accepts_bare_hour`,
>   which **now passes** (the rewrite seeds the date on the first turn, avoiding
>   the "today" poaching). All 12 remaining failures are the identical
>   environmental ones (Windows systemd/notify-send timer `OverflowError`, file
>   workflow, browser, confirm) — confirmed against baseline via `git stash`. 13
>   reminder tests + 118 across template/calendar/slot/datetime suites green.
>
> **Calendar half (deferred — landmine):** Step 3 originally also said "retire
> `CalendarEventWorkflow`". It is **left untouched**, because:
> - `create_calendar_event` is registered by **two** plugins — `TaskManagerPlugin`
>   (local SQLite + local notifications) and `WorkspaceAgent` (Google Calendar via
>   `gws.calendar_create_event`). `CalendarEventWorkflow` drives the **Google**
>   path (`WorkspaceAgent._handle_create_event`, state key `calendar_event_workflow`).
> - The `create_calendar_event.yaml` template + `schedule_calendar_event` wrapper
>   target the **local** scheduling core. So "retire `CalendarEventWorkflow` and
>   route through the template" would silently switch that flow Google → local
>   SQLite — a backend/feature change, not a faithful migration. The plan didn't
>   reckon with the dual-backend + capability-name collision.
> - Decision (user-confirmed 2026-05-31): **leave the calendar dispatch exactly
>   as-is.** `create_calendar_event.yaml` + `schedule_calendar_event` stay
>   registered + compiler-tested but **not live**. A calendar cutover needs its
>   own decision about which backend wins.
>
> ---
>
> _Original Steps 1-2 record (still accurate):_
>
> - **Step 1 (done):** the full production datetime machinery
>   (`_parse_datetime_parts` / `_parse_date` / `_parse_time` / `_parse_word_time`
>   / `_apply_meridian` / `_combine_date_time` + regexes & word tables) moved
>   into [`core/planning/slot_extractors.py`](../core/planning/slot_extractors.py)
>   as pure functions (`parse_datetime_parts`, `parse_date`, `parse_time`,
>   `parse_word_time`, `apply_meridian`, `combine_date_time`,
>   `date_from_month_match`). `TaskManagerPlugin`'s methods are now thin
>   delegators that pass a patchable `now=`. `extract_datetime` was upgraded to
>   build on the rich parser (spoken numbers, MM/DD + ISO dates, "January 5th",
>   compact "1530", o'clock) while keeping its word-number/"week" relatives +
>   noon/midnight. **Behaviour byte-for-byte unchanged** — verified the existing
>   reminder/calendar/datetime suites fail identically on baseline (`git stash`):
>   the 13 `test_workflow_orchestration.py` failures are the pre-existing Windows
>   timer `OverflowError` + file/browser/routing cases, none datetime-caused.
> - **Step 2 (done):** [`set_reminder.yaml`](../core/workflows/templates/set_reminder.yaml)
>   + [`create_calendar_event.yaml`](../core/workflows/templates/create_calendar_event.yaml)
>   slot-fill templates using `extract_with: extract_datetime`, backed by three
>   **template-internal** wrap capabilities (`extract_datetime`,
>   `create_reminder`, `schedule_calendar_event`) that wrap the **unchanged**
>   `create_calendar_event` scheduling core with no slot-fill state of their own.
>   Registered + compiler-tested in
>   [test_reminder_calendar_templates.py](../tests/test_reminder_calendar_templates.py)
>   (10 tests). The wrap capabilities are intentionally **not** given
>   IntentRecognizer patterns — the user-facing `set_reminder`/
>   `create_calendar_event` intents already route, and these run only as resolved
>   template steps. _(Superseded for reminders by the Step 3 cutover above; the
>   `CalendarEventWorkflow` shim remains the live calendar dispatch path.)_

Requested as the "full template migration" of `set_reminder` /
`create_calendar_event` / `move_calendar_event`. Investigation originally
**paused at user request** before any dispatch change. What the exploration
established:

**Key finding — the codebase already made a deliberate decision here.**
`ReminderWorkflow` and `CalendarEventWorkflow` (in
[core/workflow_orchestrator.py](../core/workflow_orchestrator.py)) were
**explicitly reclassified as *permanent* delegation shims in Track 5.2b**, with
the documented reasoning: the real slot-fill state machine lives in
`TaskManagerPlugin.handle_reminder_followup` / `WorkspaceAgent._handle_create_event`,
which **interleaves NL datetime parsing with slot transitions**; templating it
would require either moving the parsing into capabilities (a much bigger
refactor) *or* splitting slot-fill from parsing (a "weird boundary"). So a full
template cutover **reverses a prior intentional architecture call** — worth
doing consciously, not by default.

**Why a full gut-rewrite is high-risk (not just big):**

- The reminder/calendar path is **live and side-effecting** — `_create_calendar_event`
  persists rows AND schedules OS/desktop notifications that fire later. Breaking
  it silently breaks a core feature; it can't be fully verified in this dev
  environment (no live models/notifications).
- The production datetime parser
  (`TaskManagerPlugin._parse_datetime_parts` + `_parse_date` / `_parse_time` /
  `_parse_word_time`, backed by 8 module regexes + `NUMBER_WORDS` / `MINUTE_WORDS`
  / `MONTHS` / `WEEKDAYS`) is **substantially richer** than the new shared
  `extract_datetime`: it also handles spoken numbers ("fifteen"), `MM/DD[/YY]`
  and ISO dates, "January 5th", compact "1530", `o'clock`, bare-hour on the
  *followup* turn, and "ambiguous past hour → assume afternoon". A naïve
  template cutover on top of the lighter extractor would **regress** these.
- `move_calendar_event` is **not a slot-fill workflow** at all — it's a
  search-then-modify (find upcoming events, match by title/clock-target,
  shift-by-N / reschedule). It does not map cleanly onto declarative `ask:`/
  `slot:` steps.
- The existing reminder behaviour is pinned by a large suite in
  [tests/test_workflow_orchestration.py](../tests/test_workflow_orchestration.py)
  (~15 reminder/calendar tests asserting the current handler API + workflow
  state shape: `handle_reminder_followup`, `pending_slots`, spoken-time,
  bare-hour, past-hour-afternoon, confirmation wording, type tagging, firing
  announcements). A cutover **rewrites those tests** — they no longer describe
  the live path.

**Recommended migration shape (when resumed) — safe, phased:**

1. **Port the full datetime machinery into shared `slot_extractors` pure
   functions** (`parse_datetime_parts`, `parse_date`, `parse_time`,
   `combine_date_time` + the regexes/dicts) and have `TaskManagerPlugin`
   *delegate* to them. Upgrade `extract_datetime` to use the full logic
   (add the spoken-number / month / compact / noon-midnight coverage it
   currently lacks). **This is the plan's actual "migrate interleaved datetime
   logic out" deliverable, and it's low-risk** — the existing suite guards it,
   behaviour is unchanged.
2. **Add YAML templates** (`set_reminder.yaml`, `create_calendar_event.yaml`)
   using `extract_with: extract_datetime` + thin new capabilities
   (`create_reminder`, `schedule_calendar_event`) that wrap the **unchanged**
   `_create_calendar_event` scheduling core. Register + unit-test at the
   template/compiler level.
3. **Cutover (the risky step):** make `handle_set_reminder` /
   `handle_create_calendar_event` pre-extract slots and call
   `start_template_slot_fill(...)` (a contained handler-level bridge — no
   orchestrator surgery needed, since followups already route through
   `TemplateWorkflow.run_slot_fill_turn` via `continue_active`). Retire the
   Reminder/Calendar shims, **rewrite** the affected `test_workflow_orchestration`
   tests, and re-verify firing/notification behaviour.
4. **Leave `move_calendar_event` handler-side** (it's search-then-modify, not
   slot-fill) but switch its parsing to the shared extractors.

**Status (updated 2026-05-31):** Steps 1–2 landed, and **Step 3 for reminders is
now live** — the `set_reminder` two-phase template drives the reminder slot-fill
and `ReminderWorkflow` is retired (see the update box at the top of this section
for the behaviour-preservation details + verification). **Step 3 for the calendar
is deferred**: `CalendarEventWorkflow` drives the Google-Calendar backend while
the local template wraps the SQLite core, so a cutover would silently change the
backend — it needs its own decision, not a default retirement.

### 5.5 Checkpoint 4 — Disambiguation / pick guard ✅

`core/workflows/disambiguation.py:DisambiguationGuard` is the sibling of the
checkpoint-2 `ConfirmationGuard`: where confirmation asks *"shall I go ahead?"*
before a destructive action, this asks *"which one did you mean?"* when a
capability resolves a request to **more than one** candidate. Same
handler-arming shape, so it composes with everything already built.

- A handler, the moment it discovers >1 candidate, calls
  `guard.arm(action=<capability to run on pick>, arg_name=<arg the picked value
  fills>, candidates=[…], base_args=…)` — unless `args["_picked"]` is set —
  persisting `session_state.pending_pick` and returning a numbered list.
- New `IntentRecognizer._parse_pending_pick` interceptor (second in the parser
  chain, right after `_parse_pending_destructive`) routes a **selection-shaped**
  utterance ("2", "the second one", "option 3", "last", or a unique candidate
  label) → `pick_pending_candidate`, and a clear "cancel"/"never mind"/"none" →
  `cancel_pending_pick`. Crucially it **only** intercepts selection-shaped
  input — an unrelated command ("actually, what's the weather?") falls through
  to normal routing, so the user is never trapped. The shared selection parser
  (`parse_selection`/`looks_like_selection`) is the single source of truth for
  both the interceptor and the guard.
- `pick()` resolves the selection to one candidate, fills
  `base_args[arg_name]` with its value + `_picked=True`, and re-dispatches the
  stored `action` via `CapabilityExecutor` — so the chosen file is opened, app
  launched, document queried. An unresolved reply re-asks (keeps the pick
  armed); nothing dispatches.
- `pick_pending_candidate`/`cancel_pending_pick` registered in `core/app.py`
  alongside `app.disambiguation_guard`. Config gate `routing.disambiguate`
  (default true).

**Wired (one branch each):**
- **`search_indexed_files`** — >1 match → numbered pick whose `action` is
  `open_file` (picking "the second one" opens that file). A single match is
  reported as before.
- **`launch_app`** — an ambiguous spoken name (e.g. "chrom" when both Chrome and
  Chromium are installed) arms a pick over `find_app_candidates(...)`
  (new in [app_launcher.py](../modules/system_control/app_launcher.py); detects
  ambiguity on the *raw* token because `extract_app_names` already collapses to a
  single canonical via fuzzy match). Exact/unique names launch immediately.
- **`query_document`** — no explicit path and the question names a document that
  matches several indexed files → file-picker over the doc-type index hits
  (`_doc_name_hint` extracts the name; a single match auto-selects; a generic
  "summarize the document" with no name still gives the honest "no file path"
  error rather than guessing).

**Tests:** [tests/test_disambiguation_guard.py](../tests/test_disambiguation_guard.py)
(guard + `parse_selection` + `find_app_candidates` + `_doc_name_hint` + the three
handler branches) and
[tests/test_pending_pick_intent.py](../tests/test_pending_pick_intent.py)
(interceptor routing incl. the fall-through guarantee) — **57 tests**. The
intent **conflict detector** stays green (the new parser introduces no overlap),
`test_intent_eval` corpus green, and the only full-suite failures remain the
documented pre-existing Windows-env set (3 routing snapshots = launch_firefox /
volume_up_steps / multi_open_then_time; audio/PIL/tts/workflow-timer/hud) —
zero in any touched area.

> **Pure-Python + offline-safe:** like the confirmation guard, the
> disambiguation guard is session-state + regex only, no `platform.system()`
> branch — Linux behaviour identical.

---

## 6. Phase 4 — Docs polish & finalize (✅ done, 2026-06-01)

| Item | Status | Detail |
|---|---|---|
| `docs/ARCHITECTURE.md` | ✅ | "Launch architecture overview" prepended: turn lifecycle, the 5-layer routing pipeline + confidence-band table, and the workflow state-machine diagram (confirmation / disambiguation / slot-fill guards). Renamed from `architecture.md` (case fix). |
| `docs/intent_recognition.md` (new) | ✅ | The 5 layers, the confidence bands + thresholds, the eval/conflict gates + `routing_stats`, and the how-to-add-an-intent checklist. |
| `docs/config_reference.md` | ✅ | Added the Phase 2–3 `routing.*` confidence keys + layer/guard toggles (`confirm_destructive`, `disambiguate`, …), the `code_execution` section, and `file_index.initial_delay_s`; corrected `routing.chat_max_tokens` default. |
| `CHANGELOG.md` | ✅ | `Unreleased` populated with Phase 1–4 work; `0.1.0` baseline. |
| `docs/testing_guide.md` | 🔄 Ongoing | T-entries + Modification Log per user-visible change; 2026-06-01 Phase 0+4 row added. |

---

## 7. New files created so far

| File | Phase | Purpose |
|---|---|---|
| [docs/platform_support.md](platform_support.md) | 1 | Feature parity matrix |
| [scripts/diagnostics/intent_eval.py](../scripts/diagnostics/intent_eval.py) | 2 | Intent eval harness (corpus runner) |
| [scripts/diagnostics/routing_stats.py](../scripts/diagnostics/routing_stats.py) | 2 | `[ROUTE]` log analyzer |
| [tests/intent_corpus/](../tests/intent_corpus/) (13 files) | 2 | Golden corpus |
| [tests/test_intent_eval.py](../tests/test_intent_eval.py) | 2 | Eval CI gate |
| [tests/test_intent_conflicts.py](../tests/test_intent_conflicts.py) | 2 | Conflict/poaching CI gate |
| [tests/test_routing_stats.py](../tests/test_routing_stats.py) | 2 | routing_stats tests |
| [core/planning/slot_filling.py](../core/planning/slot_filling.py) | 3 / 2.4 | Unified `SlotSpec`+`SlotFiller` slot-filling foundation |
| [tests/test_slot_filling.py](../tests/test_slot_filling.py) | 3 / 2.4 | 17 tests for the slot-filling foundation |
| [core/workflows/confirmation.py](../core/workflows/confirmation.py) | 3 | Reusable `ConfirmationGuard` (confirm-before-destructive) |
| [tests/test_confirmation_guard.py](../tests/test_confirmation_guard.py) | 3 | 13 guard unit tests |
| [tests/test_pending_destructive_intent.py](../tests/test_pending_destructive_intent.py) | 3 | 13 interceptor routing tests |
| [tests/test_datetime_extractor.py](../tests/test_datetime_extractor.py) | 3 | 16 shared `extract_datetime` tests |
| [tests/test_destructive_guard_handlers.py](../tests/test_destructive_guard_handlers.py) | 3 | 6 shutdown/forget handler-guard tests |
| [core/workflows/templates/set_reminder.yaml](../core/workflows/templates/set_reminder.yaml) | 3 / §5.4 Step 3 | Reminder slot-fill template — **LIVE** (two-phase date→time; `extract_reminder_date`/`extract_reminder_time` → `create_reminder`); `ReminderWorkflow` retired |
| ~~core/workflows/templates/create_calendar_event.yaml~~ | 3 / §5.4 | **Deleted 2026-05-31** — local calendar events removed; Google Calendar owns them |
| [tests/test_reminder_calendar_templates.py](../tests/test_reminder_calendar_templates.py) | 3 / §5.4 | 8 compiler/loader + registration tests for the live `set_reminder` template (calendar-template tests removed) |
| [core/workflows/disambiguation.py](../core/workflows/disambiguation.py) | 3 / §5.5 | Reusable `DisambiguationGuard` (which-one-did-you-mean pick) + shared `parse_selection` |
| [tests/test_disambiguation_guard.py](../tests/test_disambiguation_guard.py) | 3 / §5.5 | Guard + selection parser + app-candidate finder + 3 handler-branch tests |
| [tests/test_pending_pick_intent.py](../tests/test_pending_pick_intent.py) | 3 / §5.5 | `_parse_pending_pick` interceptor routing (selection / cancel / fall-through) |
| [CHANGELOG.md](../CHANGELOG.md) | 0 / 4 | Keep a Changelog — `Unreleased` + `0.1.0` |
| [.github/workflows/ci.yml](../.github/workflows/ci.yml) | 0 | Lint + intent gate → pytest matrix (Linux/Windows × py 3.10–3.13) |
| [.github/ISSUE_TEMPLATE/](../.github/ISSUE_TEMPLATE/) (3 files) | 0 | Bug report, phrasing-first feature request, contact-links config |
| [.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md) | 0 | Mirrors CONTRIBUTING "Definition of done" |
| [docs/intent_recognition.md](intent_recognition.md) | 4 | The 5-layer router: layers, confidence bands, eval gates, how-to-add |
| [docs/launch_hardening_status.md](launch_hardening_status.md) | — | This document |

---

## 8. Open items / decisions

- **Reminder/calendar template cutover (§5.4) — fully resolved 2026-05-31.**
  Reminders: the `set_reminder` two-phase template is the live slot-fill,
  `ReminderWorkflow` retired, behaviour preserved. Calendar: the dual-backend
  landmine was resolved by **removing the local calendar-event path** — Google
  Calendar (WorkspaceAgent) owns calendar events; the `create`/`cancel` name
  collisions resolve to Google, and move/reschedule retargets to Google's
  `update_calendar_event`. **Open follow-up (minor):** reminders are no longer
  voice-cancellable/movable (the dual-purpose local handlers went to Google) — a
  reminder-scoped `cancel_reminder` can be added if that gap matters.
- **`shutdown_assistant` is now guarded** — "goodbye"/"bye"/"shut down" ask
  "shall I go ahead?" first (behind `routing.confirm_destructive`). Flag if you
  want shutdown to stay immediate like `/lock`.
- **`ha_turn_on`/`ha_turn_off` are guarded** per the plan, but confirming every
  "turn on the lights" may be undesirable for low-stakes devices. Toggle via
  `routing.confirm_destructive`; can be scoped down to lock/delete/cancel only
  if preferred.
- **Checkpoint 4 (disambiguation: `search_indexed_files`, `launch_app`,
  `query_document`) — done (2026-05-31).** `DisambiguationGuard` +
  `_parse_pending_pick` interceptor; all three wired; 57 tests; `routing.disambiguate`
  toggle. See §5.5. **This closes Phase 3** — all checkpoints landed.
- **Open follow-up (minor):** the disambiguation guard treats a non-selection,
  non-cancel reply as "fall through to normal routing" and leaves the pick armed
  (harmless; overwritten/cleared on the next arm/pick/cancel). A TTL/auto-expire
  could be added if a stale pick ever proves confusing — the confirmation guard
  has the same property.
- **Phase 0** — done (2026-06-01) on user signal. `CODE_OF_CONDUCT.md` was
  explicitly skipped; the existing stub keeps the README/CONTRIBUTING links from
  breaking, but it should be filled with the Contributor Covenant before launch.
- **Phase 4** — done (2026-06-01). All four phases now landed.
- **CI on real hardware** — `ci.yml` installs the full native stack
  (llama-cpp-python, Chroma, PyQt6, sounddevice) for the `test` matrix; the first
  live run may surface platform-specific install/timeout issues to tune. The
  `lint-and-intent` job is dependency-light and is the launch-critical gate.
- **No commits yet** — all work is uncommitted on `launch/hardening-2026-05-30`.
  The branch also carries pre-existing uncommitted work from earlier sessions
  (e.g. the brightness Windows-WMI backend).
- **Pre-existing test failures on the Windows dev box** (bash, `.venv/bin`, PIL,
  3 routing snapshots; + 3 `test_workflow_orchestration.py` calendar/reminder
  cases failing on a Windows timer `OverflowError`) are environmental/unrelated
  — confirmed via `git stash`; a clean run needs the Linux + Windows CI matrix
  from Phase 0.
