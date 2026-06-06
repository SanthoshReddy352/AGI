# `config.yaml` — Reference

This document describes every top-level section of `config.yaml`, the keys
it exposes, the types/defaults the code expects, and which subsystem
reads each value. It is intended as a living spec — when you add a new
`config.get(...)` call site, also add a row here.

`config.yaml` is loaded by `core/config_loader.py` and exposed on
`FridayApp` as `self.config`. Code reads it via dotted keys, e.g.
`self.config.get("routing.tool_timeout_ms")`. **Default values in this
document are the value baked into the call site as a fallback — they
take effect only when the key is missing or empty.**

> Generated 2026-05-23 from `grep config.get(...)` over `core/` and
> `modules/`. Re-run the same grep before adding a key to confirm no
> other call site relies on the same name.

---

## `app` — Application identity

| Key            | Type   | Default        | Read by                              | Effect                                                                                |
|----------------|--------|----------------|--------------------------------------|---------------------------------------------------------------------------------------|
| `app.name`     | string | `"FRIDAY"`     | `gui/main_window.py`, `main.py`      | Window title, log prefix.                                                             |
| `app.version`  | string | `"0.1"`        | greeter banner, `/help`              | Shown in startup greeting and `/help`.                                                |
| `app.theme`    | string | `"dark"`       | `gui/main_window.py`                 | Qt stylesheet selector. Currently supports `dark` only — `light` is on the wishlist.  |

## `conversation` — Turn-orchestration runtime

| Key                                       | Type    | Default   | Read by                                          | Effect                                                                                                                                   |
|-------------------------------------------|---------|-----------|--------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `conversation.listening_mode`             | string  | `"manual"`| `core/app.py`, `modules/voice_io/`               | `manual` = push-to-talk button. `wake_word` = always-listening with `hey_friday.onnx`. `continuous` = no gating (debug only).            |
| `conversation.online_permission_mode`     | string  | `"ask_first"` | `core/online_permission.py`                 | Per-turn gate for online tools. `ask_first` prompts every time, `always_allow` skips the prompt, `block` refuses online tools entirely.  |
| `conversation.wake_session_timeout_s`     | int     | `12`      | `core/routing_state.py`                          | Seconds the wake-session stays open after the last user turn.                                                                            |
| `conversation.assistant_echo_window_s`    | float   | `1.8`     | `modules/voice_io/stt.py`                        | Time after TTS finishes during which STT discards transcripts (prevents the assistant hearing itself).                                   |
| `conversation.delegate_multi_action_threshold` | int | `2`       | `core/planning/turn_orchestrator.py`             | Number of parsed actions before the orchestrator delegates to the workflow engine.                                                       |
| `conversation.progress_delays_s`          | list[float] | `[4.0, 14.0]` | `core/planning/turn_orchestrator.py`         | Seconds at which to emit a progress message during a long-running turn.                                                                  |

## `capabilities` — Registry behaviour

| Key                                  | Type | Default                     | Read by                       | Effect                                                                                  |
|--------------------------------------|------|-----------------------------|-------------------------------|-----------------------------------------------------------------------------------------|
| `capabilities.registry_mode`         | string | `"internal_mcp_compatible"` | `core/capability_registry.py` | Reserved for future external-MCP federation. Only the default is wired today.           |
| `capabilities.allow_external_mcp`    | bool   | `false`                     | `core/capability_registry.py` | If `true`, the registry accepts capabilities from external MCP servers (not yet built). |
| `capabilities.online_skills_enabled` | bool   | `true`                      | `modules/skills/*`            | Master switch for skills that need internet.                                            |

## `personas` — Identity / tone

| Key                                | Type   | Default        | Read by                        | Effect                                                                                                                              |
|------------------------------------|--------|----------------|--------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| `personas.default_persona_id`      | string | `"friday_core"`| `core/persona_manager.py`      | Slug pointing to `config/personas/<id>.yaml`.                                                                                       |
| `personas.auto_memory_capture`     | string | `"aggressive"` | `core/memory_nudger.py`        | `aggressive` saves declared facts ("I love coding"). `conservative` only when user says "remember". `off` disables silent capture.  |

## `models` — Local LLM paths

| Key                       | Type   | Default                                         | Read by                | Effect                                                                                                  |
|---------------------------|--------|-------------------------------------------------|------------------------|---------------------------------------------------------------------------------------------------------|
| `models.chat.path`        | path   | `models/Qwen3.5-0.8B-Q4_K_M.gguf`               | `core/model_manager.py`| GGUF for the chat fallback model.                                                                       |
| `models.chat.preload`     | bool   | `true`                                          | `core/model_manager.py`| If true, the chat model is loaded at boot rather than on first turn.                                    |
| `models.chat.n_ctx`       | int    | `4096`                                          | `core/model_manager.py`| llama.cpp context window.                                                                               |
| `models.chat.n_batch`     | int    | `512`                                           | `core/model_manager.py`| llama.cpp prompt-batch size.                                                                            |
| `models.chat.temperature` | float  | `0.7`                                           | `modules/llm_chat/`    | Default chat sampling temperature.                                                                      |
| `models.tool.path`        | path   | `models/Qwen3.5-4B-Q4_K_M.gguf`                 | `core/model_manager.py`| GGUF for the tool-use / planner model.                                                                  |
| `models.tool.preload`     | bool   | `true`                                          | `core/model_manager.py`| Preload tool model.                                                                                     |
| `models.tool.n_ctx`       | int    | `2048`                                          | `core/model_manager.py`| Tool model context window.                                                                              |
| `models.tool.n_batch`     | int    | `256`                                           | `core/model_manager.py`| Tool model batch size.                                                                                  |
| `models.tool.temperature` | float  | `0.1`                                           | `modules/llm_chat/`    | Lower temperature on the tool model improves JSON faithfulness.                                         |

## `routing` — V2 orchestrator / planner

| Key                                 | Type | Default               | Read by                          | Effect                                                                                                                                                 |
|-------------------------------------|------|-----------------------|----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| `routing.orchestrator`              | string | `"v2"`              | `core/app.py`                    | Always `v2` since Track 0 retirement of v1.                                                                                                            |
| `routing.policy`                    | string | `"selective_executor"`| `core/planning/turn_orchestrator.py` | Selective executor short-circuits intent matches; alternative `"plan_first"` always runs the planner.                                                |
| `routing.execution_engine`          | string | `"parallel"`        | `core/planning/turn_orchestrator.py` | `parallel` allows independent actions to run concurrently; `serial` forces sequential.                                                               |
| `routing.tool_timeout_ms`           | int    | `6000`              | `core/router.py`                 | Per-tool LLM-call timeout (Qwen 4B route scorer).                                                                                                      |
| `routing.tool_max_tokens`           | int    | `256`               | `core/router.py`                 | Hard cap on planner output tokens.                                                                                                                     |
| `routing.tool_target_max_tokens`    | int    | `128`               | `core/router.py`                 | Soft cap; planner is asked to stay below this.                                                                                                         |
| `routing.tool_top_p`                | float  | `0.2`               | `core/router.py`                 | Planner nucleus sampling cutoff.                                                                                                                       |
| `routing.tool_json_response`        | bool   | `true`              | `core/router.py`                 | Force JSON mode on the planner model.                                                                                                                  |
| `routing.chat_max_tokens`           | int    | `512`               | `modules/llm_chat/plugin.py`     | Hard cap on chat-model output tokens. Cut from 2048 → 512 (2026-05-29) to bound worst-case generation latency on CPU.                                  |
| `routing.use_qwen_planner`          | bool   | `true`              | `core/app.py`                    | If `false`, falls back to the old rule-only planner (used for stress tests).                                                                           |
| `routing.use_replanning`            | bool   | `true`              | `core/planning/turn_orchestrator.py` | If a step fails, ask the planner to replan instead of returning the error.                                                                          |
| `routing.qwen_planner_timeout_ms`   | int    | `12000`             | `core/app.py`                    | **(2026-05-23 added.)** Qwen planner inference timeout. Was hard-coded before this entry.                                                              |
| `routing.qwen_planner_max_tokens`   | int    | `512`               | `core/app.py`                    | **(2026-05-23 added.)** Qwen planner max output tokens.                                                                                                |
| `routing.qwen_planner_top_p`        | float  | `0.2`               | `core/app.py`                    | **(2026-05-23 added.)** Qwen planner sampling top-p.                                                                                                   |
| `routing.max_workflow_steps`        | int    | `12`                | `core/planning/turn_orchestrator.py` | Hard cap on workflow steps to prevent runaway plans.                                                                                                 |
| `routing.max_step_retries`          | int    | `2`                 | `core/planning/turn_orchestrator.py` | Per-step retry budget on transient errors.                                                                                                           |
| `routing.workflow_total_timeout_sec`| int    | `300`               | `core/planning/turn_orchestrator.py` | Wall-clock cap on a single workflow.                                                                                                                 |

### `routing` — confidence bands (Phase 2)

These tune the fuzzy routing layers between the deterministic best-route and the
LLM planner. See [intent_recognition.md](intent_recognition.md) §4 for how the
bands compose. **All have a fallback baked into the call site**, so omitting them
keeps the documented default.

| Key                          | Type  | Default | Read by                                       | Effect                                                                                                  |
|------------------------------|-------|---------|-----------------------------------------------|---------------------------------------------------------------------------------------------------------|
| `routing.dispatch_threshold` | float | `0.62`  | `core/app.py` → `core/embedding_router.py`    | Embedding cosine **≥** this auto-dispatches the matched capability.                                     |
| `routing.confirm_low`        | float | `0.50`  | `core/app.py` → `core/embedding_router.py`    | Cosine in `[confirm_low, dispatch_threshold)` triggers a "did you mean …?" confirmation instead of chat. |
| `routing.tie_epsilon`        | float | `0.05`  | `core/app.py` → `core/embedding_router.py`    | Two candidates within this of the top score → treat as a tie and disambiguate.                          |
| `routing.lexical_threshold`  | float | `88`    | `core/app.py` → `core/lexical_router.py`      | rapidfuzz token-set score the best tool must clear to fire.                                              |
| `routing.lexical_margin`     | float | `6`     | `core/app.py` → `core/lexical_router.py`      | …and the margin by which it must beat the runner-up tool (prevents poaching).                           |
| `routing.promote_after`      | int   | `3`     | `core/app.py` → `core/stores/intent_learning_store.py` | Times a phrasing must be confirmed before it's promoted to deterministic dispatch.             |

### `routing` — layer & guard toggles (Phase 2–3)

Master switches for the optional routing layers and the multi-step guards. All
default `true` and read with a fallback.

| Key                                   | Type | Default | Read by                              | Effect                                                                                              |
|---------------------------------------|------|---------|--------------------------------------|------------------------------------------------------------------------------------------------------|
| `routing.lexical_enabled`             | bool | `true`  | `core/capability_broker.py`          | Enables the fuzzy lexical layer (L2b). Off → skip straight from best-route to planner.               |
| `routing.learning_enabled`            | bool | `true`  | `core/capability_broker.py`, `core/planning/turn_orchestrator.py`, `modules/llm_chat/plugin.py` | Master switch for day-by-day phrase learning (privacy toggle). Off → no confirmations are recorded.  |
| `routing.learned_dispatch_enabled`    | bool | `true`  | `core/capability_broker.py`          | Enables deterministic dispatch of phrasings already promoted (L2a).                                  |
| `routing.intent_confirmation_enabled` | bool | `true`  | `core/capability_broker.py`          | Enables the mid-confidence embedding "did you mean …?" confirmation loop.                            |
| `routing.confirm_destructive`         | bool | `true`  | `core/workflows/confirmation.py`     | **(Phase 3.)** Ask "shall I go ahead?" before destructive actions (`lock_screen`, `delete_goal`, `shutdown_assistant`, `forget_memory`, Home Assistant on/off, memory wipe). Off → act immediately. The explicit `/lock` slash always bypasses. |
| `routing.disambiguate`                | bool | `true`  | `core/workflows/disambiguation.py`   | **(Phase 3.)** When a request resolves to >1 candidate (`search_indexed_files`, `launch_app`, `query_document`), ask "which one?" with a numbered list. Off → the handler's prior single-result behaviour. |

## `llm` — Global LLM budgeting (Track 5.3)

| Key                       | Type | Default | Read by         | Effect                                                                                                                                                                  |
|---------------------------|------|---------|-----------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `llm.max_context_tokens`  | int  | `4096`  | `core/app.py`   | **(2026-05-23 added.)** Effective context-window budget used when fitting prompts. Distinct from `models.chat.n_ctx`/`models.tool.n_ctx` because the budgeter doesn't always know which model is active. |

## `gui` — Desktop window

| Key                  | Type | Default | Read by                  | Effect                                  |
|----------------------|------|---------|--------------------------|-----------------------------------------|
| `gui.window_width`   | int  | `500`   | `gui/main_window.py`     | Initial window width in pixels.         |
| `gui.window_height`  | int  | `700`   | `gui/main_window.py`     | Initial window height in pixels.        |

## `voice` — STT / wake / device

| Key                              | Type    | Default                        | Read by                       | Effect                                                                                                                                  |
|----------------------------------|---------|--------------------------------|-------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| `voice.stt_model`                | string  | `"base.en"`                    | `modules/voice_io/stt.py`     | faster-whisper model name. `base.en`, `small.en`, `medium.en` supported.                                                                |
| `voice.stt_compute_type`         | string  | `"int8"`                       | `modules/voice_io/stt.py`     | `int8` (CPU friendly), `int8_float16` (GPU friendly), `float32` (best accuracy, slowest).                                               |
| `voice.stt_language`             | string  | `"en"`                         | `modules/voice_io/stt.py`     | Whisper language hint.                                                                                                                  |
| `voice.stt_cpu_threads`          | int     | `8`                            | `modules/voice_io/stt.py`     | Worker threads for the CTranslate2 backend.                                                                                             |
| `voice.stt_max_utterance_s`      | float   | `20.0`                         | `modules/voice_io/stt.py`     | Max recording length per utterance.                                                                                                     |
| `voice.wake_model_path`          | path    | `models/hey_friday.onnx`       | `modules/voice_io/wake.py`    | openWakeWord model path.                                                                                                                |
| `voice.wake_transcript_fallback` | bool    | `true`                         | `modules/voice_io/wake.py`    | If wake model is missing, accept the literal phrase "hey friday" from STT as the wake trigger.                                          |
| `voice.media_max_uninvoked_words`| int     | `4`                            | `modules/voice_io/stt.py`     | While media is playing, only utterances ≤ this many words are treated as commands (prevents lyrics from being misheard as commands).    |
| `voice.input_device.id`          | int     | (PipeWire node id)             | `modules/voice_io/stt.py`     | Sound-device node id. `pw-cli ls Node` to find the ID.                                                                                  |
| `voice.input_device.kind`        | string  | `"pipewire"`                   | `modules/voice_io/stt.py`     | `pipewire` or `pulseaudio` or `alsa`.                                                                                                   |
| `voice.input_device.label`       | string  | (free-form)                    | `modules/voice_io/stt.py`     | Human-readable label for logging — re-resolved when the node id is stale.                                                               |

## `modules.<name>.enabled` — Plugin gates

Each loaded plugin under `modules/` honours `modules.<short_name>.enabled`. When the key is absent, the default is `true`. Set to `false` to disable the plugin without removing its code.

Currently observed in `config.yaml`: `modules.greeter.enabled`.

## `skills` — Skill mode and weather

| Key                        | Type   | Default        | Read by                | Effect                                                                                  |
|----------------------------|--------|----------------|------------------------|-----------------------------------------------------------------------------------------|
| `skills.mode`              | string | `"local_first"`| various skill modules  | `local_first` prefers cached / on-device data; `online_first` prefers fresh fetches.    |
| `skills.weather.api_key`   | string | `""`           | `modules/weather/`     | OpenWeatherMap key. Empty → public/no-key endpoint (lower fidelity).                    |
| `skills.weather.default_city` | string | `"Mumbai"`  | `modules/weather/`     | Used when the user asks "what's the weather" without naming a city.                     |

## `browser_automation` — Playwright / Chrome

| Key                                       | Type   | Default     | Read by                                | Effect                                                                                                                                              |
|-------------------------------------------|--------|-------------|----------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `browser_automation.enabled`              | bool   | `true`      | `modules/browser_automation/plugin.py` | Master switch.                                                                                                                                      |
| `browser_automation.allow_online`         | bool   | `true`      | `modules/browser_automation/service.py`| If `false`, the service refuses to navigate. Useful for offline-only smoke tests.                                                                   |
| `browser_automation.preferred_browser`    | string | `"chrome"`  | `modules/browser_automation/service.py`| `chrome`, `chromium`, or `firefox`.                                                                                                                 |
| `browser_automation.use_system_profile`   | bool   | `true`      | `modules/browser_automation/service.py`| Reuse the user's logged-in Chrome profile (cookies, sessions) instead of a fresh one.                                                               |
| `browser_automation.chrome_user_data_dir` | string | `""`        | `modules/browser_automation/service.py`| Override for the Chrome user-data root. Empty → autodetect from `~/.config/google-chrome` (Linux) or `%LOCALAPPDATA%\Google\Chrome` (Windows).      |
| `browser_automation.chrome_profile_directory` | string | `""`    | `modules/browser_automation/service.py`| Override for the profile sub-folder (default `"Default"`). Empty → resolve from `Local State.profile.last_used`.                                    |

## `document_intel` — MarkItDown + ChromaDB RAG

| Key                                  | Type        | Default              | Read by                            | Effect                                                                                                |
|--------------------------------------|-------------|----------------------|------------------------------------|-------------------------------------------------------------------------------------------------------|
| `document_intel.enabled`             | bool        | `true`               | `modules/document_intel/plugin.py` | Master switch.                                                                                        |
| `document_intel.chroma_path`         | path        | `data/chroma`        | `modules/document_intel/plugin.py` | Chroma persistence directory.                                                                         |
| `document_intel.db_path`             | path        | `data/friday.db`     | `modules/document_intel/plugin.py` | SQLite mirror for document metadata.                                                                  |
| `document_intel.collection_name`     | string      | `friday_documents`   | `modules/document_intel/plugin.py` | Chroma collection name.                                                                               |
| `document_intel.max_chunks`          | int         | `4`                  | `modules/document_intel/plugin.py` | Top-K chunks retrieved per query.                                                                     |
| `document_intel.max_context_tokens`  | int         | `1500`               | `modules/document_intel/plugin.py` | Token budget for RAG context.                                                                         |
| `document_intel.chunk_size_tokens`   | int         | `400`                | `modules/document_intel/plugin.py` | Chunk size at ingest time.                                                                            |
| `document_intel.chunk_overlap_tokens`| int         | `80`                 | `modules/document_intel/plugin.py` | Overlap between adjacent chunks.                                                                      |
| `document_intel.auto_index`          | bool        | `false`              | `modules/document_intel/plugin.py` | Watch `workspace_folders` for new files and ingest automatically.                                     |
| `document_intel.workspace_folders`   | list[path]  | `[~/Documents]`      | `modules/document_intel/plugin.py` | Roots scanned when `auto_index` is on.                                                                |
| `document_intel.index_extensions`    | list[string]| `.pdf .docx .pptx .xlsx .md .txt` | `modules/document_intel/plugin.py` | Allowlist of file extensions.                                                                |
| `document_intel.index_idle_only`     | bool        | `true`               | `modules/document_intel/plugin.py` | Only ingest while the user isn't typing.                                                              |
| `document_intel.index_batch_size`    | int         | `3`                  | `modules/document_intel/plugin.py` | How many files to ingest per idle cycle.                                                              |

## `vision` — SmolVLM2 multimodal stack

| Key                                | Type   | Default                                                  | Read by                       | Effect                                                                                              |
|------------------------------------|--------|----------------------------------------------------------|-------------------------------|-----------------------------------------------------------------------------------------------------|
| `vision.enabled`                   | bool   | `true`                                                   | `modules/vision/plugin.py`    | Master switch — when off, all 11 vision capabilities are unregistered.                              |
| `vision.model_path`                | path   | `models/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf`              | `modules/vision/plugin.py`    | SmolVLM2 model weights.                                                                             |
| `vision.mmproj_path`               | path   | `models/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf`         | `modules/vision/plugin.py`    | Multimodal projection weights.                                                                      |
| `vision.n_ctx`                     | int    | `2048`                                                   | `modules/vision/plugin.py`    | llama.cpp context.                                                                                  |
| `vision.n_batch`                   | int    | `256`                                                    | `modules/vision/plugin.py`    | Batch size.                                                                                         |
| `vision.max_image_width`           | int    | `1024`                                                   | `modules/vision/plugin.py`    | Images are resized to this max width before encoding.                                               |
| `vision.idle_timeout_s`            | int    | `300`                                                    | `modules/vision/plugin.py`    | Free VRAM/RAM if no vision call for this long.                                                      |
| `vision.features.<feature>`        | bool   | `true`                                                   | `modules/vision/plugin.py`    | Per-feature toggle. Recognised: `screenshot_explainer`, `ocr_reader`, `screen_summarizer`, `clipboard_analyzer`, `code_debugger`, `compare_screenshots`, `ui_element_finder`, `smart_error_detector`, `fun_features`. |

## `memory` — Memory subsystem

| Key            | Type | Default | Read by                | Effect                                                                            |
|----------------|------|---------|------------------------|-----------------------------------------------------------------------------------|
| `memory.enabled` | bool | `true` | `core/memory/facade.py`| Master switch. Disabling skips episodic/semantic/procedural writes (debug only).  |

## `world_monitor` — External news API

| Key                                   | Type        | Default                                  | Read by                      | Effect                                                                          |
|---------------------------------------|-------------|------------------------------------------|------------------------------|---------------------------------------------------------------------------------|
| `world_monitor.api_base_url`          | URL         | `https://api.worldmonitor.app`           | `modules/news_feed/`         | REST base.                                                                      |
| `world_monitor.web_base_url`          | URL         | `https://www.worldmonitor.app`           | `modules/news_feed/`         | Web-UI base for deep links shown in replies.                                    |
| `world_monitor.feed_api_base_url`     | URL         | `https://worldmonitor.app`               | `modules/news_feed/`         | RSS/feed base.                                                                  |
| `world_monitor.sources.<bucket>`      | URL         | (see config)                             | `modules/news_feed/`         | Per-category source endpoints.                                                  |
| `world_monitor.api_key`               | string      | `""`                                     | `modules/news_feed/`         | Optional — empty falls back to the public dashboard.                            |
| `world_monitor.public_dashboard_fallback` | bool    | `true`                                   | `modules/news_feed/`         | When no key, scrape the public dashboard rather than refuse.                    |
| `world_monitor.timeout_s`             | int         | `12`                                     | `modules/news_feed/`         | HTTP read timeout.                                                              |

## `awareness` — Always-on screen awareness

| Key                            | Type | Default | Read by                     | Effect                                                                                                                |
|--------------------------------|------|---------|-----------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `awareness.enabled`            | bool | `true`  | `modules/awareness/plugin.py`| Master switch.                                                                                                        |
| `awareness.capture_interval_s` | int  | `15`    | `modules/awareness/plugin.py`| Period of the awareness screenshot loop.                                                                              |
| `awareness.ocr_enabled`        | bool | `true`  | `modules/awareness/plugin.py`| OCR the captured screen with Tesseract. Off saves CPU at the cost of context.                                         |

## `code_execution` — Sandboxed code runner

**Default-off** — the capability is registered only when `enabled` is `true`.

| Key                          | Type | Default   | Read by                            | Effect                                                              |
|------------------------------|------|-----------|------------------------------------|---------------------------------------------------------------------|
| `code_execution.enabled`     | bool | `false`   | `modules/code_execution/plugin.py` | Master gate. When `false` the plugin registers zero capabilities.   |
| `code_execution.timeout_sec` | int  | `15`      | `modules/code_execution/plugin.py` | Wall-clock cap on a single `run_python` execution.                  |

## `file_index` — Background filesystem index

Drives the `FileIndexer` background service behind `search_indexed_files`.

| Key                          | Type  | Default | Read by         | Effect                                                                                                   |
|------------------------------|-------|---------|-----------------|----------------------------------------------------------------------------------------------------------|
| `file_index.initial_delay_s` | float | `20.0`  | `core/app.py`   | Seconds to hold back the initial filesystem walk after boot, so it doesn't contend with model loading and the first turns. The index persists across runs, so delaying the refresh has no functional downside. |

## `security` — Lab-mode security tooling (Phase 1)

| Key                            | Type        | Default                          | Read by                              | Effect                                                                                                                                              |
|--------------------------------|-------------|----------------------------------|--------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| `security.lab_mode`            | bool        | `true`                           | `modules/security_tools/plugin.py`   | Master gate — when `false` the plugin loads idle and registers zero capabilities.                                                                   |
| `security.authorized_scopes`   | list[CIDR/host] | (RFC1918 + loopback)         | `modules/security_tools/plugin.py`   | Allowlist of targets `host_service_scan` / `ping_sweep` will act on. **Any target outside this list is refused at the handler.** Edit before adding public IPs you own.       |
| `security.nmap_binary`         | string      | `"nmap"`                         | `modules/security_tools/plugin.py`   | Path or name of the nmap binary. Set to absolute path for non-PATH installs.                                                                        |
| `security.default_timeout_sec` | int         | `120`                            | `modules/security_tools/plugin.py`   | Wall-clock cap on a single scan.                                                                                                                    |
| `security.audit_log_path`      | path        | `logs/security_audit.log`        | `modules/security_tools/plugin.py`   | Where consent decisions and scan dispatches are logged.                                                                                             |

---

## Adding a new key

1. Pick the matching top-level section (or add a new one).
2. Add a sensible default to `config.yaml` so the key exists out of the box.
3. Read it in code via `self.app.config.get("section.key", fallback)` — always pass a fallback so older configs keep working.
4. Add a row to this document with the type, default, call site, and effect.
5. Update the testing guide if the key changes a user-visible behaviour.

## Settings vs. memory vs. plan

- **`config.yaml`** is for things that don't change per turn (model paths, feature gates, API keys). Re-read only on restart.
- **Memory** (`data/friday.db` + Chroma) is for things FRIDAY learns about you (name, location, preferences). Persists across sessions.
- **Plan / tasks** (in-conversation) is for ephemeral state that doesn't outlive the current conversation.

If you find yourself reaching for `config.yaml` for something the user said in a sentence, it probably belongs in memory instead.
