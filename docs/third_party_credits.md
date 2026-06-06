# Third-Party Credits

FRIDAY incorporates work from open-source projects. This file lists every
externally-sourced module/script/skill with its upstream provenance and
licence.

## hermes-agent (NousResearch) — MIT

Upstream: <https://github.com/nousresearch/hermes-agent>

Port performed in Track 5.3 (`plan/2026-05-22_10-45-00_plan.md`). The
**pattern** of each upstream file informed the FRIDAY implementation;
no source was copied verbatim — every file was rewritten to fit FRIDAY's
architecture (domain stores, capability registry, voice-first I/O) and
to drop cloud-only / non-local-first paths.

### Core (P3.1, P3.4, P3.6, P3.11–P3.13, P3.16, P3.17, P3.18, P3.21–P3.22)

| FRIDAY path | Hermes source |
|---|---|
| `core/skill_loader.py`, `core/skills/*` | `tools/skills_hub.py`, `skills_sync.py`, `skills_guard.py`, `skill_provenance.py`, `skill_usage.py` |
| `core/approval.py` | `tools/approval.py` |
| `core/clarify.py` | `tools/clarify_tool.py` |
| `core/delegate.py` | `tools/delegate_tool.py` |
| `core/mixture_of_agents.py` | `tools/mixture_of_agents_tool.py` |
| `core/runtime/process_registry.py`, `checkpoint_manager.py`, `interrupt.py` | `tools/process_registry.py`, `checkpoint_manager.py`, `interrupt.py` |
| `core/safety/url_safety.py`, `path_security.py`, `website_policy.py`, `tool_guardrails.py` | `tools/url_safety.py`, `path_security.py`, `website_policy.py`, `agent/tool_guardrails.py` |
| `core/prompt_builder.py`, `core/prompt_caching.py` | `agent/prompt_builder.py`, `agent/prompt_caching.py` |
| `core/tool_result.py` | `agent/tool_result_classification.py` |

### Core (P3.2–P3.5, P3.9, P3.20)

| FRIDAY path | Hermes source |
|---|---|
| `core/stores/migrations/session.sql` (turns_fts), `core/stores/memory_store.py:fts_search` | `tools/session_search_tool.py` |
| `core/session_summarizer.py` | `agent/memory_manager.py` (summary patterns), `agent/memory_provider.py` (interface shape) |
| `core/context_compressor.py` | `agent/conversation_compression.py` |
| `core/memory_nudger.py` | `agent/memory_manager.py` (nudge loop) |
| `core/scheduler.py` | `tools/cronjob_tools.py` |
| `core/transcription.py` | `tools/transcription_tools.py` |

### Plugins (P3.7, P3.8, P3.10, P3.14, P3.15, P3.19)

| FRIDAY path | Hermes source |
|---|---|
| `modules/code_execution/` | `tools/code_execution_tool.py` |
| `modules/mcp_client/` | `tools/mcp_tool.py` (subset, no OAuth manager) |
| `modules/web/` | `tools/web_tools.py` (DuckDuckGo + stdlib backends only) |
| `modules/vision/plugin.py:describe_image` | `tools/vision_tools.py` |
| `modules/smart_home/` | `tools/homeassistant_tool.py` |
| `modules/voice_io/voice_mode.py` | `tools/voice_mode.py` |

### Skill markdown (P4 — 14 files)

| FRIDAY path | Hermes source |
|---|---|
| `modules/web/SKILLS/arxiv.md` | `skills/research/arxiv/` |
| `modules/web/SKILLS/blogwatcher.md` | `skills/research/blogwatcher/` |
| `modules/web/SKILLS/research_paper.md` | `skills/research/research-paper-writing/` |
| `modules/web/SKILLS/llm_wiki.md` | `skills/research/llm-wiki/` |
| `modules/web/SKILLS/email.md` | `skills/email/` |
| `modules/web/SKILLS/github.md` | `skills/github/` |
| `modules/system_control/SKILLS/note_taking.md` | `skills/note-taking/` |
| `modules/system_control/SKILLS/diagramming.md` | `skills/diagramming/` |
| `modules/system_control/SKILLS/creative_writing.md` | `skills/creative/` |
| `modules/system_control/SKILLS/media.md` | `skills/media/` |
| `modules/code_execution/SKILLS/software_dev.md` | `skills/software-development/` |
| `modules/smart_home/SKILLS/scenes.md` | `skills/smart-home/` |
| `modules/mcp_client/SKILLS/mcp_usage.md` | `skills/mcp/` |
| `modules/security_tools/SKILLS/red_teaming.md` | `skills/red-teaming/godmode/` (defensive subset only — see file header) |

### What was deliberately not ported

| Upstream area | Why we skipped it |
|---|---|
| Honcho user modelling | Breaks local-first; we have `personas` + `user_profile`. |
| ACP adapter / registry | Multi-agent registry overkill at FRIDAY's scale. |
| `computer_use_tool.py` | We already have `modules/browser_automation/`. |
| `discord_tool.py` | Telegram bridge already covers this niche. |
| `image_generation_tool.py` / `video_generation_tool.py` | Requires a local image/video model FRIDAY doesn't ship. |
| `feishu_*`, `yuanbao_*`, Microsoft Graph | Cloud productivity stacks not in scope. |
| `mcp_oauth*` | OAuth manager deferred until needed. |
| Cloud provider adapters (Bedrock, Gemini, Anthropic) | FRIDAY is local-first with Qwen3.5 GGUFs. |
| Autonomous skill creation / self-evolution | Speculative; lacks the evaluation infra. |
| `gateway/`, `tui_gateway/` web UIs | FRIDAY already has voice + Telegram entrypoints. |
| `gaming`, `gifs`, `social-media`, `mlops`, `dogfood`, etc. | Irrelevant or duplicative. |

### MIT licence

The MIT licence is compatible with FRIDAY's own licence. Each ported
file retains a `source:` line in its frontmatter / header pointing at
the upstream path. The hermes-agent licence text is reproduced below
in full for completeness.

```
MIT License

Copyright (c) NousResearch

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```
