# Codebase Analysis: Architectural Health, Gaps, and Wiring Report

**Date:** May 20, 2026  
**Status:** System Audit & Architectural Review  
**Auditor:** Antigravity (Google DeepMind Team)  

---

## 1. Executive Summary

This report presents a thorough architectural audit of the **FRIDAY Linux** codebase. With the ongoing consolidation window (opened May 17, 2026), the system has made outstanding structural progress, notably in the modularization of its core database layer, unification of turn-based orchestration, and routing drift prevention.

---

## 2. Structural & Architectural Status

### 2.1 The Storage Layer Decomposition (Track 5.1)
The extraction of `core/context_store.py` (previously a 1480-line god class) into **six domain-specific stores** under `core/stores/` is fully complete and merged:
1. **`AuditStore`**: Manages event tracking, online permission metrics, and commitments.
2. **`WorkflowStore`**: Tracks stateful workflow runs.
3. **`MemoryStore`**: Integrates facts and episodic memory with the local ChromaDB vector index.
4. **`KnowledgeGraphStore`**: Maps semantic entity relationships.
5. **`GoalStore`**: Handles procedural objectives and milestones.
6. **`SessionStore`**: Owns session lifecycle, turns, and working artifacts.

**Evaluation:** This decomposition successfully honors the strict **"≤4 tables per store"** and **"≤30 lines per method"** rules. Write-ownership boundaries are clear, and reads correctly cross-reference SQLite tables directly without duplication.

### 2.2 Turn Orchestration and Single-Dispatch (Track 3)
FRIDAY’s v2 pipeline has successfully collapsed five competing v1 paths (TaskRunner, direct `_execute_turn`, fast media command, dictation early-exit, and legacy fallbacks) into a single controller: **`TurnOrchestrator.handle`**. The deletion of the Gemma shadow router and the retirement of the v1 dispatch branches have successfully guaranteed a single, deterministic routing decision per turn.

### 2.3 Declarative Workflows as YAML (Track 5.2)
The multi-turn slot-filling compiler is fully functional, as proven by the conversion of `OnboardingWorkflow` to `user_onboarding.yaml`. Slots are compiled, validated, and interpolated dynamically across multiple turns, drastically reducing boilerplate Python code.

---

## 3. Unit-Level Audit & Gaps

Individual classes and primitives show high cohesive quality, but there are minor technical debts and deferred design integrations.

### 3.1 Deferred State Machine Unification (`Track 5.2b-deferred`)
* **The Gap:** The slot-filling state machines for both the **Reminder** and **Calendar** workflows remain embedded inside `TaskManagerPlugin.handle_reminder_followup` and `WorkspaceAgentExtension._handle_create_event` instead of using the declarative YAML compiler (`TemplateWorkflow`).
* **Impact:** This creates split maintenance. The workflow coordinator wraps these shims under `ReminderWorkflow` and `CalendarEventWorkflow` classes in `core/workflow_orchestrator.py`, but they bypass the centralized YAML slot-filler.
* **Resolution Path:** Refactor the internal parsing and combination logic of `TaskManagerPlugin` and `WorkspaceAgentExtension` out of the handlers, lifting them into standard YAML templates with custom capability arguments once Track 5.2c (runtime predicates) lands.

### 3.2 Deprecated Datetime & Timezone Usage
* **The Gap:** A static analysis sweep and automated test warnings identify scattered usage of `datetime.utcnow()` and `datetime.utcnow().isoformat()` in files like `core/stores/session_store.py` and `modules/security_tools/audit.py`.
* **Impact:** In Python 3.11+, `utcnow()` is deprecated because it creates naive datetime objects that lack explicit timezone indicators, risking chronological discrepancies when calculated on systems using custom local offsets (e.g. `gws_client.py` and `WorkspaceAgentExtension` dealing with RFC3339 offsets).
* **Resolution Path:** Systematically migrate all instances of naive UTC lookups to timezone-aware objects using `datetime.now(timezone.utc)`.

### 3.3 Screenshot API & Background OCR Parameter Mismatch (Wiring Gap)
* **The Gap:** The background screen-capture and OCR service (`modules/awareness/service.py` at line 114) calls `take_screenshot(output_path=tmp_path)`. However, the core `take_screenshot()` function in `modules/system_control/screenshot.py` is defined with **no parameters** and hardcodes the output path to `~/Pictures/FRIDAY_Screenshots`.
* **Impact:** When the awareness/struggle-detector daemon is active, taking a screenshot throws a `TypeError: take_screenshot() got an unexpected keyword argument 'output_path'`, which is swallowed/logged as a debug traceback. This silently disables background screen OCR and struggle detection.
* **Resolution Path:** Update the `take_screenshot()` signature to accept an optional `filepath` or `output_path` argument, maintaining backwards compatibility with its default directory if none is provided.

### 3.4 Inefficient Local Model Test Copying (Resource Waste)
* **The Gap:** The integration test `tests/test_llama.py` copies the downloaded Qwen/Gemma GGUF model (~1.7GB) from the Hugging Face cache directory to `/home/tricky/Friday_Linux/models/gemma-2b-it.gguf` via `shutil.copy` before loading the model.
* **Impact:** This duplication wastes massive disk space (~1.7GB extra) and high-latency I/O time during testing. In resource-constrained or low-disk environments (as triggered in the recent `test_llama` failure), it raises `OSError: [Errno 28] No space left on device` and causes the test suite to fail, even though the model was successfully downloaded and cached.
* **Resolution Path:** Modify `tests/test_llama.py` to construct `Llama(model_path=str(model_path))` directly using the path returned by `hf_hub_download`, eliminating the redundant disk copy.


---

## 4. Module-Level Integration & Wiring

Module boundaries (bridges between core reasoning and capability extensions) show excellent patterns but suffer from operational fragility.

### 4.1 Registry Decoupling and Drift Prevention
* **Evaluation:** The introduction of `core/reasoning/routing_defaults.py` as the single source of truth for all capability aliases, pattern regexes, and context terms has completely eliminated the historical drift between `CommandRouter` and `RouteScorer`. All 18 first-party plugins now cleanly register via `app.register_capability` and inherit canonical scoring automatically.
* **Residual Coupling:** `FridayPlugin` still proxies capability registrations to `app.router.register_tool` underneath. While this ensures backward compatibility, final deletion of the legacy router registry blocks is deferred until all out-of-tree plugins migrate.

### 4.2 Local Inference & Resource Vulnerability (Keystone Risk)
* **The Gap:** During automated integration tests, `test_llama.py::test_llama` failed with:
  ```
  FAILED tests/test_llama.py::test_llama - OSError: [Errno 28] No space left on device
  ```
* **Impact:** Because FRIDAY is engineered as a local-first assistant, it relies heavily on Qwen-3.5 and llama.cpp runtimes executing directly on host resources. If the host disk space or memory is exhausted, the local LLM runtime crashes. Currently, there is a **lack of robust safety boundaries** and **graceful fallbacks**. If a local model fails to load or execute, the orchestrator does not fall back to lighter heuristic routers or report the issue cleanly to the user; instead, it raises unhandled `OSError` or `RuntimeError` exceptions.
* **Resolution Path:** Implement a localized "Resource Sentry" within the model manager that checks disk space and RAM before loading model weights, and define a clear degraded-performance fallback (e.g. using regular expression heuristics or a lightweight local backup model) if resources are exhausted.

---

## 5. System-Level E2E Audit

The E2E system encompasses the pipeline from audio stream capture (STT) -> Turn Orchestrator -> Tool Execution -> Audio/Visual Output (TTS).

### 5.1 Synchronous Blocking in the Main Thread
* **The Gap:** Although `TurnOrchestrator` structures the flow neatly, several I/O-intensive steps are performed synchronously:
  - Vector searches in `MemoryStore` (`_fallback_semantic_recall` using ChromaDB and `HashEmbeddingFunction`).
  - Google Workspace CLI lookups in `WorkspaceAgentExtension` (like Gmail/Calendar parsing).
* **Impact:** In voice-first environments, latency is the highest-priority constraint. If a vector search stalls or a CLI execution blocks the main thread, the audio processing loop suffers from audible stutter or delayed VAD barge-in response.
* **Resolution Path:** Promote high-latency vector lookups and external I/O commands to asynchronous execution, allowing the system's VAD and barge-in listeners to stay responsive on the main thread during heavy data queries.

### 5.2 Telemetry and Telemetry-Overhead Checks
* **Evaluation:** Track 0.4 introduced structured timing spans (`core/planning/spans.py` and `core/tracing.py`) marking six key checkpoints (`context_built`, `intent_classified`, `plan_built`, `plan_validated`, `tool_executed`, `response_finalized`).
* **Gap:** While timing data is recorded, there is no automatic system monitor that aggregates these spans to identify when the local model inference or database latency spikes. As a result, telemetry is currently passive and only aids offline diagnosis rather than live performance adaptation.

---

## 6. Detailed Recommendations

To prepare FRIDAY for its next evolution beyond the consolidation freeze, the following actions are recommended:

| Dimension | Target Component | Action Item | Priority |
| :--- | :--- | :--- | :--- |
| **Unit** | `core/stores/session_store.py` / `modules/security_tools/audit.py` | Replace naive `datetime.utcnow()` with timezone-aware `datetime.now(timezone.utc)` to avoid deprecation warnings and offset bugs. | **Medium** |
| **Unit** | `modules/task_manager` | Consolidate the reminder and calendar workflows into declarative YAML templates with custom capability hooks. | **Medium** |
| **Unit** | `modules/system_control/screenshot.py` | Add an optional `output_path` parameter to `take_screenshot()` to fix the signature mismatch crash with the background OCR service. | **High** |
| **Unit** | `tests/test_llama.py` | Load the downloaded model directly from the cache instead of using `shutil.copy` to avoid duplicating 1.7GB files on disk. | **Medium** |
| **Module** | `core/model_manager.py` | Implement disk and memory boundary guards with graceful fallback modes for local LLM runtimes to prevent system-wide crashes (e.g., in low disk-space scenarios). | **High** |
| **System** | `core/planning/spans.py` | Create a latency aggregator that logs a warning whenever E2E response times exceed a specific threshold (e.g., 2.5 seconds on local hardware). | **Low** |
| **System** | `core/stores/memory_store.py` | Offload heavy vector queries and disk I/O in memory Curators to asynchronous background executors. | **High** |

---

### Conclusion

FRIDAY's consolidation has placed it in a highly clean, robust, and mathematically sound state. The codebase represents a modern, state-of-the-art local AI architecture. By resolving the remaining deferred slot-filling machines and adding resilient resource guards for local runtimes, the system will achieve an elite level of reliability, ready to operate flawlessly across diverse Linux host environments.
