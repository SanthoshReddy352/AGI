# FRIDAY — Testing Guide

> Track 5.3 P2.4 full rewrite, 2026-05-23. Old guide archived at
> `docs/archive/testing_guide_v1_2026-05-22.md`. Test IDs renumbered
> from scratch within each section. The CLAUDE.md "update testing
> guide in the same response as code" rule is back in effect now that
> this rewrite has landed.

## 0. How to use this guide

This guide is **command-first**. Each test is a short scenario the user
can speak to FRIDAY or type into the GUI / Telegram bridge, with the
expected behaviour, the failure mode that means the feature regressed,
and a runnable command that verifies the system state after the turn.

**Test ID format:** `[T-<section>.<sequence>]`. IDs are stable per
section; new tests append to the end so existing numbers don't shift.

**Template every test follows — no variations:**

```markdown
### T-<id>  <short title>

**You say:** "<exact natural-language input>"
**Expected:** <one-line description of what FRIDAY does / says>
**What it tests:** <one-line trace of the components involved>
**Wrong behaviour:** <one-line description of the regression mode>
**Verify:** <one or two shell commands that confirm the post-state>
```

**Logs** live under `logs/friday.log`. **DB** is `data/friday.db`.
**Chroma** is `data/chroma/`. **Audit** trail is the `audit_events`
table.

For hermes-ported features, the **What it tests** line ends with
`[ported: hermes-agent/<source-path>]` so reviewers can cross-reference
upstream behaviour. See `docs/third_party_credits.md` for the full port
manifest.

---

## 0a. Command quick-reference — every combo to test

Everything here works **identically in the GUI input box and in Telegram**
(slash commands come from `core.slash_commands.REGISTRY`, which also drives
Telegram's `/`-autocomplete via `setMyCommands`). Slash + `!`/`>` prefixes
are **not** available over voice (STT can't reliably produce leading
punctuation) — use the spoken phrasings instead.

> **Input runs off the UI thread.** GUI input is dispatched on a worker
> thread (`_InputWorker`), so a slow network command (`/web`, `/quick`,
> `/fast`, `/deep`, `/fetch`, `/crawl`) never freezes the window or trips
> the desktop "Force Quit" dialog. Regression fixed 2026-05-25 (`/web …`
> → `zsh: killed`).

### Slash commands

| Command | Args | What it does | Equivalent spoken/typed phrasings |
|---|---|---|---|
| `/help` | — | List all slash commands | — |
| `/new` | — | Reset conversation + new session | "start over", "new conversation" |
| `/clear` | — | Alias for `/new` | — |
| `/web <query>` | query | **Result links** (SearchFlox→DDG→Wikipedia) | "search the web for X", "google X", "look up X online", "what's the latest on X" |
| `/quick <question>` | question | **Instant answer in chat, nothing saved** | "quick answer about X", "quick search on X", "just tell me about X", "quickly look up X" |
| `/fast <topic>` | topic | **~2-min latest-info summary** (research quick mode, saved) | "quick research on X", "fast research on X", "tldr X", "briefly on X", "one-pager on X", "overview of X" |
| `/deep <topic>` | topic | **Heavy executive summary** (research deep mode, saved) | "deep dive on X", "deep research on X", "thorough briefing on X", "comprehensive analysis of X", "literature review on X", "compare X vs Y" |
| `/research <topic>` | topic | Hand off to research agent (asks for depth if ambiguous) | "research X", "brief me on X", "put together a briefing on X" |
| `/fetch <url>` | url | Fetch a URL as clean text | "fetch <url>", "read this url <url>", "extract content from <url>" |
| `/crawl <url> [what]` | url + instructions | Crawl a site, LLM-guided | "crawl <url>", "scrape this site <url>" |
| `/screenshot` | — | Full-screen screenshot | "take a screenshot" |
| `/voice on\|off\|status` | mode | Enable/disable/report voice | "enable voice", "mute yourself", "voice status" |
| `/lock` | — | **Lock the real OS session** (laptop/desktop) | "lock the screen", "lock my laptop", "lock my computer" |
| `/unlock` | — | Explains OS unlock uses your system password | "unlock the screen" |

### Prefixes (GUI / Telegram only)

| Prefix | Example | What it does |
|---|---|---|
| `!<cmd>` | `!ls -la`, `!sudo apt install x` | Run a shell command (gated by screen lock) |
| `> <text>` | `> y`, `> mypassword` | Pipe input to a running `!` shell session's stdin |

### Email (spoken or typed — workspace_agent / gws)

| Phrasing | Routes to |
|---|---|
| "check my mail" / "check my mails" / "check email" / "any new mail" / "do I have any email" / "how many unread emails" | `check_unread_emails` (Primary inbox, unread) |
| "summarize my emails" / "summarize mails" / "summarize my inbox" / "email summary" / "inbox digest" / "what's in my inbox" | `summarize_inbox` |
| "read my latest email" / "read the latest message" / "read my most recent mail" | `read_latest_email` |
| "daily briefing" / "morning briefing" / "brief me" | `daily_briefing` |

### Voice-mode commands (spoken or `/voice`)

| Say | Effect |
|---|---|
| "switch to persistent mode" / "always listen" | persistent VAD (always on) |
| "use wake word mode" / "only listen for the wake word" | wake-word gated |
| "on-demand mode" / "only listen when I click" | push-to-talk |
| "manual mode" / "stop listening" | mic off until re-enabled |
| "enable voice" / "unmute yourself" / `/voice on` | TTS + mic on |
| "disable voice" / "mute yourself" / `/voice off` | TTS off |
| "voice status" / `/voice status` | report current mode |
| GUI: the **VOICE** panel combo (top-right) | pick mode from dropdown |
| GUI: **STOP SPEECH** button | interrupt current TTS playback |

### Voice commands for tools — extended toughness matrix

Each tool should route via `source=intent` (deterministic), **not** fall to
the chat model. Speak each row; the **Verify** column at the bottom of each
section's T-entry confirms it. Try the awkward phrasings too — they're the
ones that regress.

| Domain | Try saying (all must route to the tool, not chat) | Tool |
|---|---|---|
| Email | "check my mail", "check my mails", "any new email", "do I have mail", "how many unread emails" | `check_unread_emails` |
| Email | "summarize my emails", "summarize mails", "summarize my inbox", "what's in my inbox", "email digest" | `summarize_inbox` |
| Email | "read my latest email", "read the most recent message" | `read_latest_email` |
| Email | "daily briefing", "morning briefing", "brief me" | `daily_briefing` |
| Web | "search the web for X", "google X", "look X up online", "what's the latest on X" | `web_search` |
| Web | "quick answer about X", "quick search on X", "just tell me about X", "quickly look up X" | `quick_answer` |
| Research | "quick research on X", "fast research on X", "tldr X", "briefly on X", "one-pager on X" | `research_topic` (quick) |
| Research | "deep dive on X", "deep research on X", "thorough briefing on X", "literature review on X", "compare X vs Y" | `research_topic` (deep) |
| Screen | "lock the screen", "lock my laptop", "lock my computer" | `lock_screen` (OS lock) |
| Brightness | "set brightness to 60", "brightness fifty", "max brightness", "dim the screen", "brightness 80 percent" | `set_brightness` |
| Volume | "volume up", "set volume to 30", "mute", "turn it down" | volume control |
| Screenshot | "take a screenshot", "capture my screen", "screenshot please" | `take_screenshot` |
| Apps | "rescan my apps", "reindex applications", "rebuild the app index" | `refresh_app_index` |
| Files | "reindex my files", "find the file called notes.txt", "search for design.pdf" | file index tools |
| System | "what's the system usage", "cpu and ram", "battery level" | system info |
| Time | "what time is it", "what's today's date" | time/date |
| Weather | "what's the weather", "weather in Nellore", "will it rain tomorrow" | weather |
| News | "tech news", "give me the headlines", "world news" | news tools |
| Memory | "remember I love coding", "what do you remember about me", "forget my hometown" | memory tools |
| Reminders | "remind me to call mom at 6pm", "show my reminders" | reminders |
| Calendar | "what's on my calendar today", "this week's agenda" | calendar |
| Identity | "who are you", "what's your name", "introduce yourself" | `identify_self` |

### Disambiguation rules to test (these are the tricky ones)

- "summarize my emails" → **`summarize_inbox`**, NOT research on the topic
  "emails" (`_parse_email_action` runs before `_parse_research_topic`).
- "quick research on X" → **research** (mode=quick), NOT `quick_answer`.
- "quick answer about X" → **`quick_answer`** (chat, no file), NOT research.
- "the battery in my car died" → must NOT route to email.

**Verify the whole routing table:**
```
python3 -m pytest tests/test_email_intent.py tests/test_quick_answer_intent.py \
  tests/test_research_mode_detection.py tests/test_web_intent.py -q
```

---

## 1. Memory & Profile

What this section validates: free-form fact saves, namespaced reads,
profile/memory display, forget / wipe / export, and the cross-session
recall surface (FTS5 + session summary + nudger).

### T-1.1  Save a free-form fact ("remember X")

**You say:** "Friday, remember I love cars."
**Expected:** "Got it — I'll remember you love cars."
**What it tests:** `intent_recognizer._parse_free_remember` →
`record_personal_fact` capability → `MemoryFacade.set`.
**Wrong behaviour:** FRIDAY chats back without saving; nothing in
`facts`.
**Verify:**
```
sqlite3 data/friday.db "SELECT namespace,key,value FROM facts ORDER BY updated_at DESC LIMIT 1;"
# → a row with value containing "cars"
```

### T-1.2  Save a profile fact ("my name is X")

**You say:** "Friday, my name is Santhosh."
**Expected:** "Nice to meet you, Santhosh."
**What it tests:** Onboarding profile write to `user_profile`
namespace.
**Wrong behaviour:** Name saved into a session-scoped namespace and not
visible across restarts.
**Verify:**
```
sqlite3 data/friday.db "SELECT key,value FROM facts WHERE namespace='user_profile';"
# → name | Santhosh
```

### T-1.3  Show what FRIDAY remembers

**You say:** "Friday, what do you know about me?"
**Expected:** Two-section reply: "**About you:** name: Santhosh …"
then "**You told me:** loves: cars …".
**What it tests:** `MemoryManagerPlugin._handle_show_memories` merges
`user_profile` + per-session facts.
**Wrong behaviour:** "I don't have any stored memories yet." while
`facts` table is non-empty.
**Verify:**
```
tail -20 logs/friday.log | grep -E "show_memories|facts"
```

### T-1.4  Forget a single fact by key

**You say:** "Friday, forget my location."
**Expected:** "Done — I've forgotten your location."
**What it tests:** `forget_memory` capability → `MemoryFacade.forget`.
**Wrong behaviour:** Fact still present in `facts` table.
**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM facts WHERE namespace='user_profile' AND key='location';"
# → 0
```

### T-1.5  Memory-wipe two-step confirmation (init)

**You say:** "Friday, forget everything you know about me."
**Expected:** "This will erase everything I know about you — including
N profile facts, M memories and K goals. Say 'yes, wipe everything' to
confirm, or anything else to cancel." (Phase 3 preview: real counts of
what will be deleted; falls back to "your name, preferences, and all
stored memories" when counts can't be read.)
**What it tests:** `wipe_memory_init` sets
`session_state.pending_memory_wipe = True`; `_wipe_preview` counts the
`user_profile` facts, memories, and goals that will be lost.
**Wrong behaviour:** Wipe runs immediately without the second turn.
**Verify:**
```
sqlite3 data/friday.db "SELECT state_json FROM conversation_sessions ORDER BY updated_at DESC LIMIT 1;" | grep pending_memory_wipe
```

### T-1.6  Memory-wipe confirm

**You say:** "yes, wipe everything" (next turn after T-1.5)
**Expected:** "Done — everything is gone."
**What it tests:** `confirm_memory_wipe` clears `facts`, `memory_items`,
KG tables, goals; resets the Chroma collection.
**Wrong behaviour:** Some rows survive; `audit_events` missing the
`MEMORY_WIPE_EXECUTED` entry.
**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM facts; SELECT count(*) FROM memory_items;"
# → both 0
sqlite3 data/friday.db "SELECT event_type FROM audit_events ORDER BY id DESC LIMIT 1;"
# → MEMORY_WIPE_EXECUTED
```

### T-1.6b  Full user-data wipe via CLI script

**You run:**
```
python scripts/wipe_user_data.py --force
```
**Expected:** All user data cleared (sessions, turns, memories, goals, audit, KG, workflows, intent learning). App + file indexes preserved.

**What it tests:** `scripts/wipe_user_data.py` wipes `memory_items`, `facts`, `entities`, `entity_facts`, `entity_relationships`, `goals`, `goal_progress`, `sessions`, `turns`, `conversation_sessions`, `personas`, `audit_events`, `online_permission_events`, `agent_messages`, `commitments`, `workflows`, `routing_observations`, `learned_phrases`, `intent_profile` + FTS5 + Chroma `friday_memory`. Keeps `app_index`, `file_index`, `indexed_documents` + Chroma `friday_documents`.

**Wrong behaviour:** App or file index tables are truncated; Chroma `friday_documents` is deleted.

**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM sessions; SELECT count(*) FROM app_index; SELECT count(*) FROM file_index;"
# → 0, ≥1, ≥1
```

### T-1.7  Memory-wipe cancel

**You say:** "no" (next turn after T-1.5)
**Expected:** "Wipe cancelled — I'll keep everything I know about you."
**What it tests:** `cancel_memory_wipe` + `MEMORY_WIPE_CANCELLED` audit
row.
**Wrong behaviour:** Wipe runs anyway, or no audit row.
**Verify:**
```
sqlite3 data/friday.db "SELECT event_type FROM audit_events ORDER BY id DESC LIMIT 1;"
# → MEMORY_WIPE_CANCELLED
```

### T-1.8  Export memory to JSON

**You say:** "Friday, export my memory."
**Expected:** "Memory exported to ~/friday_memory_<TS>.json (NN KB)."
**What it tests:** `export_memory` capability → `scripts/memory_admin
export`.
**Wrong behaviour:** File not created or 0 bytes.
**Verify:**
```
ls -lh ~/friday_memory_*.json | tail -1
```

### T-1.9  Memory admin CLI — list

**You say:** *(shell, not FRIDAY)*
**Expected:** Rows printed grouped by table.
**What it tests:** `scripts/memory_admin.py list`.
**Wrong behaviour:** Empty output even when `facts` has rows.
**Verify:**
```
python scripts/memory_admin.py list | head -20
```

### T-1.10  Memory admin CLI — inspect

**You say:** *(shell)*
**Expected:** One-screen summary with row counts per table + Chroma
collection size.
**What it tests:** `scripts/memory_admin.py inspect`.
**Wrong behaviour:** Counts are zero across the board after a normal
session.
**Verify:**
```
python scripts/memory_admin.py inspect
```

### T-1.11  Cross-session keyword search (FTS5, P3.2)

**You say:** "Friday, search my conversations for cars."
**Expected:** "Found N mention(s) of 'cars':" + each hit on its own
line.
**What it tests:** `MemoryManagerPlugin._handle_search_conversations` →
`MemoryStore.fts_search` → `turns_fts`.
**Wrong behaviour:** "I didn't find anything…" while `turns` clearly
contains the word. [ported: hermes-agent/tools/session_search_tool.py]
**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM turns_fts;"
# matches: SELECT count(*) FROM turns;
```

### T-1.12  Session summary on exit (P3.3)

**You say:** Have a short conversation, then close FRIDAY (Ctrl-C / GUI
close).
**Expected:** A new `memory_items(memory_type='session_summary')` row
appears for the session that just ended.
**What it tests:** `FridayApp.shutdown` →
`SessionSummarizer.on_session_switch`. [ported:
hermes-agent/agent/memory_manager.py]
**Wrong behaviour:** No new summary row; nothing in `auto_extracted`
namespace either.
**Verify:**
```
sqlite3 data/friday.db "SELECT memory_type, substr(content,1,60) FROM memory_items WHERE memory_type='session_summary' ORDER BY created_at DESC LIMIT 1;"
```

### T-1.13  Memory nudger silent save (P3.5)

**You say:** "Friday, I work at Anthropic." (no "remember" verb)
**Expected:** A normal conversational reply. **No** spoken
acknowledgement that something was saved.
**What it tests:** `MemoryNudger.observe` end-of-turn regex →
`store_fact(namespace='user_profile', key='employer')`. [ported:
hermes-agent/agent/memory_manager.py]
**Wrong behaviour:** Fact not saved; or FRIDAY proudly announces "I'll
remember that" (the nudger should be silent).
**Verify:**
```
sqlite3 data/friday.db "SELECT key,value FROM facts WHERE namespace='user_profile' AND key='employer';"
# → employer | Anthropic
```

### T-1.14  Semantic recall on a paraphrase (RAG overhaul 2026-05-25)

**You say:** First "remember my sister's name is Asha", then later (new
question, no shared keywords) "what is my sibling called?"
**Expected:** FRIDAY recalls Asha — *sibling* matches *sister* by meaning,
not by shared words.
**What it tests:** `MemoryStore.semantic_recall` now embeds with the real
shared sentence-transformer (`all-MiniLM-L6-v2`, 384-dim) instead of the
old 64-dim SHA-256 hash, then RRF-fuses dense + FTS5 candidates and
MMR-selects. [ported: n/a — new]
**Wrong behaviour:** "I don't have anything about your sibling" while the
sister fact is stored (the old hash embedder failed all no-overlap
paraphrases); or the same memory returned 3× (no MMR diversity).
**Verify:**
```
.venv/bin/python3 tests/retrieval/test_recall_quality.py   # recall@3 and MRR ≈ 1.0
```

---

## 2. Files & Documents

What this section validates: file creation flows (dictate vs generate),
read, summarise, search by name.

### T-2.1  Create a file (dictate mode)

**You say:** "Friday, create kids.txt." → "yes" → "dictate" → "soccer,
chess, drawing"
**Expected:** File `~/Desktop/kids.txt` exists with the dictated body
verbatim.
**What it tests:** `file_create_with_content` workflow, dictate branch.
**Wrong behaviour:** File body is the slot prompt ("Activities that
kids love") instead of the dictation.
**Verify:**
```
cat ~/Desktop/kids.txt
```

### T-2.2  Create a file (generate mode, P1.2)

**You say:** "Friday, create kids.txt." → "yes" → "generate" →
"activities that kids love"
**Expected:** `~/Desktop/kids.txt` contains a real paragraph about the
topic, not the topic string itself.
**What it tests:** `file_workflow_helpers._llm_generate_about` →
`write_file`.
**Wrong behaviour:** File body is the verbatim topic.
**Verify:**
```
wc -w ~/Desktop/kids.txt
# → at least 30 words
```

### T-2.3  Read a file aloud

**You say:** "Friday, read kids.txt."
**Expected:** FRIDAY speaks the file body (sanitised for TTS).
**What it tests:** `read_file` capability + `sanitize_for_speech`.
**Wrong behaviour:** TTS reads literal markdown / URL tokens.
**Verify:**
```
grep -E "read_file|read kids.txt" logs/friday.log | tail -3
```

### T-2.4  Summarise a document

**You say:** "Friday, summarise ~/Documents/report.pdf."
**Expected:** A 2–4 sentence summary spoken / printed.
**What it tests:** `session_rag.load_file` + chat summary.
**Wrong behaviour:** "I can't read that file" when the file exists.
**Verify:**
```
grep "session_rag" logs/friday.log | tail -5
```

### T-2.4b  Ask about an attached document (session RAG) (2026-05-29 fix)

**You say:** *(after attaching a file in the GUI — "ATTACHED: Resume.pdf")*
"What is there in the document?" (also: "what does it say", "summarize
this", "what's in the file", "tell me about it")
**Expected:** FRIDAY answers from the loaded document — a grounded
summary / answer drawn from the file's contents.
**What it tests:** `IntentRecognizer._session_rag_doc_action` routes the
question to `llm_chat` (so `assistant_context` injects the relevant
SessionRAG excerpts) — checked at the top of `plan()` BEFORE the
`_is_knowledge_question` bail. `LLMChatPlugin.handle_chat` skips its
preflight tool-reroute while a doc is loaded. `SessionRAG.retrieve`
falls back to the leading chunks when keyword scoring finds nothing, so
broad questions still get document grounding. `SessionRAG.get_context_block`
(2026-05-29 second fix) frames the excerpts as a `[DOCUMENT Q&A]` block
that **explicitly grants the read capability** ("no tool needed, never say
you can't") and **pins the answer to the current document** ("if a
different document was discussed earlier, ignore it") — defeating the two
0.8B-model failure modes below.
**Wrong behaviour:** "What is there in the document?" routes to
`read_file` → "Which file would you like me to read?" (the 2026-05-29
log bug — the phrasing matched `_KNOWLEDGE_Q_RE`, `plan()` returned
`[]`, and the lexical router grabbed `read_file`). Also wrong: a generic
chat non-answer ("I don't have a story…") because the excerpt block came
back empty; FRIDAY refusing ("I don't have a separate tool for this
document, so I can't generate it"); or FRIDAY conflating the newly
attached file with an earlier one (answering a resume question with
content from a previously discussed doc).
**Verify:**
```
grep -E "session_rag|source=intent tool=llm_chat" logs/friday.log | tail -5
```

### T-2.4c  Switch documents mid-session / overview question (hybrid RAG) (2026-05-29 fix)

**You say:** *(attach `Advanced_System_Documents.md`, ask "what did you
understand about the document?", then attach `PRD.md` and ask the **same**
question again)*
**Expected:** The second answer is about **PRD.md** — its goals, scope,
requirements. It must NOT describe the first document. Overview questions
("what did you understand", "summarize this") return a grounded answer that
covers the document's leading section plus its most relevant sections, not
just the literal first 3 chunks.
**What it tests:** Two fixes for the 2026-05-29 cross-document bleed (PRD.md
returned a summary of the previously-loaded doc).
  1. `SessionRAG` is now **hybrid**: BM25 keyword scoring fused (Reciprocal
     Rank Fusion) with dense cosine over the resident `all-MiniLM-L6-v2`
     embedder — no new model load. Catches paraphrase/overview questions that
     share no literal terms with the document. Degrades to BM25-only when
     sentence-transformers is unavailable (`load_file` reports `(hybrid)` vs
     `(keyword)`). Overview queries lead with the document's opening section
     for grounding (`SessionRAG._ordered_chunks`).
  2. `AssistantContext.prune_document_turns()` drops the prior document's
     Q&A (the `[Re: …]` / `[Load file: …]` turns and the assistant reply that
     followed each) from history when a new file loads — called from
     `FridayApp.load_session_rag_file`. The excerpts are also folded into the
     **current user turn** (not the system prompt) where the 0.8B model
     actually attends to them.
**Wrong behaviour:** Second answer names or describes the first document
(e.g. "tenant_id, plan_type, quota_config" when PRD.md is loaded); overview
question returns only the head of the document and misses later sections.
**Verify:**
```
grep -E "session_rag.*indexed \((hybrid|keyword)\)" logs/friday.log | tail -5
```

### T-2.5  Find a file by name

**You say:** "Friday, find my budget spreadsheet."
**Expected:** A list of candidate paths or a single match.
**What it tests:** `file_search` / `DialogState.pending_file_request`.
**Wrong behaviour:** "I couldn't find it" while `find` clearly hits.
**Verify:**
```
tail -10 logs/friday.log | grep -E "file_search|pending_file_request"
```

### T-2.5b  "Bye" escapes a pending file prompt (2026-05-29 fix)

**You say:** *(after FRIDAY asks "Which file would you like me to open?"
or "I found multiple matching files. Which one should I use?")* "bye"
**Expected:** FRIDAY shuts down (`shutdown_assistant`) — it does NOT
treat "bye" as the filename.
**What it tests:** `_EXIT_ESCAPE_RE` short-circuit at the top of
`IntentRecognizer._parse_pending_selection` — a standalone
goodbye/exit phrase clears every pending slot (`reset_pending`) and
falls through to `_parse_exit`. A real filename like "exit_plan.txt"
still fills the slot.
**Wrong behaviour:** "bye" is searched as a filename and matches the
`*goodbye*` test files ("I found multiple matching files…") instead of
shutting down — the original 2026-05-29 log bug.
**Verify:**
```
tail -15 logs/friday.log | grep -E "shutdown_assistant|pending_file"
```

---

## 3. Browser & Media

What this section validates: URL opening, media playback, volume
control, and Restricted Media Control Mode entry/exit.

### T-3.1  Open a URL

**You say:** "Friday, open YouTube."
**Expected:** Chrome (or default browser) opens `youtube.com`.
**What it tests:** `browser_media_control` / `open_url`.
**Wrong behaviour:** FRIDAY chats back without launching anything.
**Verify:**
```
grep "open_url\|browser_media_control" logs/friday.log | tail -3
```

### T-3.2  Play a track

**You say:** "Friday, play sahiba."
**Expected:** YouTube Music (or active media player) starts the track.
**What it tests:** `play_youtube_music`; enters Restricted Media
Control Mode.
**Wrong behaviour:** Mode flag never flips; subsequent "pause" routes
to chat.
**Verify:**
```
grep "Restricted Media Control Mode" logs/friday.log | tail -2
```

### T-3.3  Pause / resume

**You say:** "Friday, pause." then "Friday, resume."
**Expected:** Media pauses, then resumes.
**What it tests:** Media control whitelist in Restricted Mode.
**Wrong behaviour:** "pause" treated as a generic word and routes to
chat fallback.
**Verify:**
```
grep -E "pause|resume" logs/friday.log | tail -4
```

### T-3.3a  Transparent recovery when the tab/context dies (2026-05-29 fix)

**You say:** "pause" → "play" repeatedly. On some machines (seen on
Windows) the Chrome tab/context dies on its own after a couple of
operations — `Page.evaluate: Target page, context or browser has been
closed`.
**Expected:** On the next "play"/"resume", FRIDAY **transparently
relaunches and replays the last track** (e.g. re-plays "sahiba") instead
of dead-ending on "The youtube tab was closed. Ask me to open it again."
A bare "play" recovers too — the service remembers the last media
(`_last_media`), so the caller doesn't need to re-supply the query. A
"pause" on a dead tab does NOT phantom-replay; it reports the tab closed.
**What it tests:** `BrowserMediaService._do_browser_media_control` now
(a) detects a dead context up front (`_context_is_usable()` — `page.is_closed()`
can falsely report alive when it's the whole context that died),
(b) makes `_set_media_state` re-raise closed-target errors instead of
swallowing them into a doomed keyboard fallback, and (c) routes every
closed-target path through `_closed_target_response` → `_relaunch_last_media`.
A `context.on("close")` / `browser.on("disconnected")` listener logs WHEN
the context dies so the root cause can be pinned down from the logs.
**Wrong behaviour:** "play" after a silent tab death dead-ends on "ask me
to open it again"; or "pause" on a dead tab restarts playback; or the
relaunch path reports phantom success without actually replaying.
**Verify:**
```
grep -E "relaunching last media|persistent context closed|chromium disconnected" logs/friday.log | tail -5
```

### T-3.3b  Re-open media after the tab was closed (2026-05-29 fix)

**You say:** *(after a video was playing and the tab got closed, so FRIDAY
said "The youtube tab was closed. Ask me to open it again.")* "open it"
(also: "open it again" / "reopen" / "play it again")
**Expected:** FRIDAY relaunches the browser and replays the last query
(e.g. re-plays "love selfie"). It does NOT route to `open_file` /
"Which file would you like me to open?".
**What it tests:** `_REOPEN_MEDIA_RE` in
`modules/browser_automation/media_helpers.py` — widens
`is_likely_media_command` so the bare re-open phrase keeps the active
`browser_media` workflow (`can_continue` → True, checked before intent
classification), and `parse_media_intent` maps it to `play` with the
remembered `query`/`platform` (or `open` when no query was captured).
**Also wired deterministically** into
`IntentRecognizer._parse_browser_media` (shares the matcher via
`is_reopen_media_command`) as the safety net for the v1 turn path,
which has no workflow hook — there the re-open phrase routes straight
to `play_youtube` / `play_youtube_music` / `open_browser_url`. Both
paths gate on an active `browser_media` workflow, so neither poaches a
plain "open my file".
**Wrong behaviour:** "open it" falls through to the `open_file`
capability and asks "Which file would you like me to open?" — the
original 2026-05-29 log bug. A *named* file ("open my budget
spreadsheet") must still go to `open_file`.
**Verify:**
```
grep -E "browser_media|source=workflow|open_file" logs/friday.log | tail -5
```

### T-3.4  Volume change

**You say:** "Friday, set volume to 50%."
**Expected:** System volume changes; FRIDAY confirms.
**What it tests:** `set_volume` capability.
**Wrong behaviour:** Volume unchanged.
**Verify:**
```
pactl get-sink-volume @DEFAULT_SINK@ | head -1
```

---

## 4. System Control

What this section validates: screenshot, brightness, window
management, system info.

### T-4.1  Screenshot (P0.1)

**You say:** "Friday, take a screenshot."
**Expected:** File saved under `~/Pictures/FRIDAY_Screenshots/`.
**What it tests:** `screenshot.py` backend chain — on GNOME Wayland the
Mutter ScreenCast + PipeWire backend should win in <1s; on KDE the
xdg-desktop-portal route wins; on wlroots (sway/Hyprland) grim wins.
**Wrong behaviour:** "Screenshot failed across every backend: …" with
the actual per-backend error list (the previous misleading "needs
python3-gi" message was removed 2026-05-23 — see T-4.1b). If you see
the "needs python3-gi" hint, then yes, `python3-gi` actually IS missing
(`sudo apt install python3-gi gir1.2-gst-plugins-base-1.0 gstreamer1.0-pipewire xdg-desktop-portal-gnome`).
**Verify:**
```
ls -t ~/Pictures/FRIDAY_Screenshots/ | head -1
```

### T-4.1b  Screenshot error reporting honesty (2026-05-23)

**You say:** "Friday, take a screenshot." on a system where every
backend fails (e.g. uninstall `xdg-desktop-portal-gnome` +
`gstreamer1.0-pipewire`).
**Expected:** The error message lists each backend that was tried with
its actual failure reason, joined by `|`. The "needs python3-gi" hint
appears only when one of the per-backend errors actually contains
`No module named 'gi'`.
**What it tests:** the `gi_import_failed` detector in
`modules/system_control/screenshot.py` no longer trips on substrings
like "GStreamer unavailable" / "PyGObject unavailable".
**Wrong behaviour:** "Screenshot requires python3-gi" appears even
though `python3 -c "import gi"` succeeds.
**Verify:**
```
grep "Screenshot failed across every backend" logs/friday.log | tail -1
```

### T-4.2  Brightness (2026-05-23 — real capability, no fabrication)

**You say:** "Friday, set brightness to 60%."
**Expected:** Backlight changes and FRIDAY confirms with `"Brightness set to 60%."`. On **Windows** the built-in laptop panel changes via WMI; if no internal display supports it (desktop / external-only), FRIDAY replies **honestly**: "I couldn't change the brightness (…). On Windows I can only adjust a built-in laptop display via WMI — external monitors need their own controls (or a DDC/CI tool)." On **Linux**, if neither `brightnessctl` nor `light` is installed and the user isn't in the `video` group, FRIDAY replies: "I couldn't change the brightness (/sys: permission denied — needs brightnessctl or video group). Install brightnessctl (sudo apt install brightnessctl) and add your user to the video group, then try again."
**What it tests:** real `set_brightness` capability (`modules/system_control/brightness.py`). On Windows (2026-05-29 fix) it calls `WmiMonitorBrightnessMethods.WmiSetBrightness` via PowerShell (`Invoke-CimMethod`) — gated on `which("powershell")` so the Linux backend tests are unaffected. On Linux it chains `brightnessctl set N%` → `light -S N` → `/sys/class/backlight/<panel>/brightness`. The persona prompt's clause ("never claim to have completed an action you don't actually have a tool for") plus the honest per-backend failure message prevent LLMChat from fabricating "Brightness set to 60." when no backend works.
**Wrong behaviour:** FRIDAY says "Brightness set to 60." but the screen doesn't change (LLMChat hallucinated success because no real tool was registered). This was the actual failure in the 2026-05-23 14:54 session log.
**Verify:**
```
cat /sys/class/backlight/*/brightness 2>/dev/null
# OR, when no backend is available, expect the failure message instead of a false success.
```

### T-4.2b  Brightness — desktop panel slider refreshes (2026-05-23)

**You say:** "Friday, set brightness to 100%." then "Friday, set brightness to 30%."
**Expected:** After each command the desktop's brightness widget (GNOME Quick Settings, KDE Plasma applet, XFCE power-manager indicator) shows the new value within ~1 second — without you having to click the slider.
**What it tests:** `_notify_desktop_environment` fans out a DBus / xfconf nudge to whichever desktop environment is running:
  - GNOME: `gdbus call --session --dest org.gnome.SettingsDaemon.Power --object-path /org/gnome/SettingsDaemon/Power --method org.freedesktop.DBus.Properties.Set "org.gnome.SettingsDaemon.Power.Screen" "Brightness" "<int32 N>"`
  - KDE: `qdbus org.kde.Solid.PowerManagement /org/kde/Solid/PowerManagement/Actions/BrightnessControl org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness N` (gdbus fallback)
  - XFCE: `xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/brightness-level -s N --create -t int`
**Wrong behaviour:** Hardware brightness changes (you can see the screen actually dim/brighten) but the panel slider stays at the old number until you wiggle it — means none of the DE notify branches matched, or they all silently failed.
**Verify:**
```
python3 -m pytest tests/test_brightness.py -v
# 5 new cases: test_notify_desktop_environment_is_called_on_success,
#              test_notify_desktop_environment_skipped_on_failure,
#              test_notify_helpers_swallow_missing_tools,
#              test_notify_gnome_invokes_gdbus
# Plus the existing 6 — total 10/10.
```

### T-4.3  System info

**You say:** "Friday, what's my system status?"
**Expected:** Short summary: CPU %, RAM, disk free.
**What it tests:** `system_info` capability.
**Wrong behaviour:** Hallucinated numbers; or "I can't tell".
**Verify:**
```
grep "system_info" logs/friday.log | tail -2
```

### T-4.3b  Intent recognition coverage for Track 6 / 6.3 tools (2026-05-23)

**You say (text or voice):** any of
- "rescan my apps", "refresh applications", "reindex apps", "Friday rescan my apps"
- "reindex files", "rescan filesystem", "rebuild index"
- "find the file called notes", "where is budget.xlsx", "locate file invoice.pdf"
- "set brightness to 60", "brightness 80%", "dim to 30", "max brightness"
- "lock screen", "lock friday", "lock yourself"
- "unlock screen 1234", "unlock with pin 9999"

**Expected:** Each phrase is routed deterministically by
`IntentRecognizer` (intent_conf=1.00, source=intent) — not by the LLM
planner / chat fallback. The respective capability runs and returns
its actual result.
**What it tests:** `_parse_environment`, `_parse_brightness`,
`_parse_screen_lock` in `core/intent_recognizer.py`. The 15:35 session
log showed "Friday rescan my apps" falling into chat mode because no
intent pattern existed — these parsers close that gap.
**Wrong behaviour:** Any of those phrases gets `source=chat` or
`source=planner` in the route log — that means the intent recognizer
missed it and the small chat LLM is about to fabricate a response.
**Verify:**
```
python3 -m pytest tests/test_environment_intent.py -v
```

### T-4.3c  Paraphrase routing via expanded catalog (Adaptive Intent, Phase 1, 2026-05-25)

**You say (text or voice):** colloquial paraphrases that share few literal
tokens with the canonical phrasing, e.g.
- "how much charge is left" → `get_battery`
- "pull up that document I was editing" → `open_file`
- "give me the gist of this report" → `summarize_file`
- "catch me up on today's headlines" → `get_news_briefing`
- "any recent papers on this" → `arxiv_search`
- "what did I just copy" → `get_clipboard`

**Expected:** When the regex `IntentRecognizer` doesn't match, the
`EmbeddingRouter` (MiniLM cosine over `data/tool_catalog.yaml`
`example_phrases`) still dispatches the correct tool — no LLM round-trip.
**What it tests:** the expanded catalog phrasings + the
`tests/routing/test_routing_quality.py` eval harness. Measured baseline
after the 2026-05-25 expansion: **96.4% top-1, 0% miss** on the labelled
paraphrase set in `data/routing_eval.yaml`.
**Wrong behaviour:** a listed phrase logs `source=chat`/`source=planner`,
or the eval harness top-1 drops below the 0.85 regression floor — that
means the catalog regressed or the embedder/threshold changed for the worse.
**Verify:**
```
PYTHONPATH=. .venv/bin/python3 tests/routing/test_routing_quality.py   # metrics dump
.venv/bin/python3 -m pytest tests/routing/test_routing_quality.py -q   # gated
```

### T-4.3d  Mid-band "did you mean …?" confirmation (Adaptive Intent, Phase 2, 2026-05-25)

**You say (text or voice):** a near-miss phrasing that the regex layer
doesn't catch and the embedding router scores in the low-confidence band
(cosine in `[0.50, 0.62)`) — e.g. a synonym pair like "summarize what's on
my screen" when both `analyze_screen` and `summarize_screen` exist, or a
vague request that's *almost* a tool ("make things on screen easier to
read").

**Expected:** instead of silently dropping to chat (where a small model may
fabricate a fake success), FRIDAY asks **"Did you want me to &lt;tool
summary&gt;? Say yes or no."**
- **"yes"** → the tool runs **and** the phrasing→tool pairing is recorded as
  a confirmed hit in `learned_phrases` (`hit_count += 1`) + the tool's
  `intent_profile` count bumps. This is the day-by-day learning signal — N=3
  confirmed hits later auto-promotes the phrasing (Phase 4).
- **"no"** → nothing runs; the pairing is recorded as a correction
  (`corrected_count += 1`, `status='blocked'`) so it's never re-suggested.
- An unrelated reply (neither yes nor no) leaves the pending prompt alone and
  routes the new text normally; a prompt older than 60s is dropped so a
  late "yes" can't fire a stale suggestion.

**What it tests:** `EmbeddingRouter.confirm_candidate` (band gate +
empty-args-safety filter via the catalog's `blocked_from_chat_preflight`),
`CapabilityBroker._maybe_confirm_intent` / `_propose_intent_confirmation` /
`_plan_pending_intent`, the `pending_intent` session-state channel
(SessionStore → ContextStore facade → MemoryService), and the wiring into
`PlannerEngine.plan` (step 5b, just before the chat fallback).
**Wrong behaviour:** a band-score utterance drops straight to `source=chat`
with no confirmation; a "yes" runs the tool but `learned_phrases` shows no
hit (learning signal lost); a tool needing structured args (e.g.
`set_volume`) is offered for confirmation then dead-ends on empty args; or a
stale prompt fires after the 60s TTL.
**Verify:**
```
.venv/bin/python3 -m pytest tests/test_confirmation_loop.py -q
tail -5 logs/friday.log   # mid-band turn logs [ROUTE] mode=clarify then a tool dispatch on "yes"
```

### T-4.3e  Fuzzy/lexical near-miss routing (Adaptive Intent, Phase 3, 2026-05-25)

**You say (text or voice):** a phrasing the regex layer doesn't catch because
of an STT mishear, a typo, or a shuffled word order — but that's still
*lexically* almost a known command, e.g.
- "lock the screem" / "lock teh scren" → `lock_screen`
- "capture my scren" → `take_screenshot`
- "how much batery is left" → `get_battery`
- "screen lock the" (word order) → `lock_screen`

**Expected:** the `LexicalRouter` (rapidfuzz `token_set_ratio` over catalog +
promoted learned phrasings, with a small synonym fold like
"screem"→"screen", "pic"→"screenshot") dispatches the correct tool — before
the embedding router or LLM run. It auto-dispatches only when the best tool
clears the `LEXICAL_THRESHOLD=88` bar **and** beats the runner-up tool by
`LEXICAL_MARGIN=6`, so loosely-related text falls through untouched.
**What it tests:** `core/lexical_router.py` (rapidfuzz fast path + stdlib
`difflib` fallback when rapidfuzz is absent), `CapabilityBroker._maybe_lexical_route`
(empty-args dispatch → excludes `blocked_from_chat_preflight` tools), and the
wiring into `PlannerEngine.plan` as **step 4b** (between the deterministic
best-route and the LLM planner). Disable with `FRIDAY_DISABLE_LEXICAL_ROUTER=1`
or `routing.lexical_enabled: false`.
**Wrong behaviour:** a clear typo of a known command drops to
`source=chat`/`source=planner` instead of dispatching; OR an unrelated
sentence that merely shares a word ("the lock on my car door is broken")
wrongly fires `lock_screen` — the margin/threshold guard regressed; OR a
structured-arg tool (`set_volume`) gets an empty-args fuzzy dispatch.
**Verify:**
```
.venv/bin/python3 -m pytest tests/test_lexical_router.py -q
tail -5 logs/friday.log   # a near-miss turn logs [lexical-router] then a tool dispatch
```

### T-4.3f  Learned-phrase auto-dispatch after repeats (Adaptive Intent, Phase 4, 2026-05-25)

**You say (text or voice):** the *same* off-canonical phrasing across several
sessions — one the regex layer never catches, e.g. "make the screen cozy" for
`set_brightness`. The first few times it routes via the confirmation loop
(T-4.3d), the lexical layer (T-4.3e), or the chat embedding preflight.

**Expected:** after `PROMOTE_AFTER=3` confirmed/uncorrected hits of that exact
phrasing, FRIDAY **auto-dispatches it deterministically** — no confirmation,
no LLM — and the `[ROUTE]` log shows **`source=learned`**. The learning
persists across restarts (boot replays learned phrasings into the embedding
router via `add_phrase`). A correction ("no") on a promoted phrasing **blocks**
it — it stops auto-dispatching.
**What it tests:** `IntentLearningStore.promoted_lookup` / `active_phrases`;
`EmbeddingRouter.add_phrase` (personal phrasings folded into the index,
surviving rebuilds); `CapabilityBroker._maybe_learned_dispatch` (wired into
`PlannerEngine.plan` as **step 4a**, before the lexical layer, with
`route_origin="learned"` → `TurnOrchestrator._plan_source` reports it);
capture-at-source (`note_hit` on the lexical path, the chat preflight reroute,
and confirmation-yes); per-tool frequency via
`TurnOrchestrator._bump_intent_profile`. Config gates:
`routing.learned_dispatch_enabled` (default true). Disable all learning by
not feeding hits (or clear with the Phase-5 `forget_learned_intents`).
**Wrong behaviour:** a phrasing used 3+ times still needs confirmation every
time (promotion not firing); a promoted phrasing keeps auto-dispatching after
the user corrected it (demotion broken); or learned phrasings vanish after a
restart (boot replay missing).
**Verify:**
```
.venv/bin/python3 -m pytest tests/test_learned_phrase_promotion.py -q
sqlite3 <db> "SELECT normalized,tool,hit_count,status FROM learned_phrases ORDER BY hit_count DESC;"
```

### T-4.3g  Profile biasing + forget controls (Adaptive Intent, Phase 5, 2026-05-25)

**You say (text or voice):**
- *Tie-break / favourite-arg:* after you've launched music a few times with one
  app, a vague "play some music" leans toward that app; when two tools score
  almost identically the one you use more (and at this time of day) wins.
- *Forget:* "forget how I talk" / "reset what you learned about my phrasing" /
  "stop learning how I talk".
- *Disable entirely:* set `routing.learning_enabled: false` in `config.yaml`.

**Expected:**
- The profile tie-breaker only fires when the top-2 embedding candidates are
  within `TIE_EPSILON=0.05` — it **never** overrides a confident match.
  Favourite-arg defaults fill only *missing* preference-style args (`app`,
  `browser`, `player`, …) — never content args (`query`, `topic`) and never an
  explicitly-supplied value.
- "forget how I talk" → `forget_learned_intents` clears learned phrasings +
  usage profile (NOT your facts/preferences), drops the in-memory personal
  phrases from the embedding index, logs a `LEARNED_INTENTS_FORGOTTEN` audit
  event, and replies with the count forgotten.
- With `routing.learning_enabled: false`, nothing is captured (`note_hit`,
  `bump_profile`, arg capture) and learned auto-dispatch + arg-fill are off.

**What it tests:** `IntentLearningStore.record_args` / `favorite_args` /
`profile_score`; `CapabilityBroker._apply_arg_defaults` (preference-key
safelist, missing-only, master-flag gated) + `_learning_enabled`;
`EmbeddingRouter.set_tie_breaker` / `best_match` epsilon gate (wired in
`FridayApp._load_learned_phrases` to `profile_score`); `_parse_forget_learned`
intent parser (anchored on talk/speak/phrasing so it never poaches
`wipe_memory_init`); the `forget_learned_intents` capability + catalog entry;
`TurnOrchestrator._bump_intent_profile` arg capture.
**Wrong behaviour:** "forget how I talk" wipes your *facts* (poached
wipe_memory_init); a favourite-arg fill overrides an explicit arg or injects a
content arg; the tie-breaker flips a clear cosine winner; learning still
captured with `routing.learning_enabled: false`.
**Verify:**
```
.venv/bin/python3 -m pytest tests/test_forget_learned_intent.py tests/test_profile_biasing.py -q
sqlite3 <db> "SELECT tool,count,fav_args_json FROM intent_profile ORDER BY count DESC;"
```

### T-4.3h  Routing threshold tuner (Adaptive Intent, Phase 6, 2026-05-25)

**You run (developer-facing, not a spoken command):**
```
.venv/bin/python3 -m core.routing_tuner
```
**Expected:** a per-threshold sweep table (accuracy / false-dispatch / defer /
precision) over the labelled set `data/routing_eval.yaml`, plus the
coverage-max recommendation (lowest threshold with false-dispatch ≤ 2%), the
accuracy-plateau top, and the confirmation-band precision. The shipped
`DISPATCH_THRESHOLD=0.62` must report **on accuracy plateau: True**.
**What it tests:** `core/routing_tuner.py` — `sweep_threshold` (generic over any
`score_fn(text) -> {tool,score}|None`, so it tunes the embedding band today and
the lexical ratio tomorrow), `recommend_threshold` / `recommend_max_accuracy` /
`on_accuracy_plateau`, `band_precision`, `recommend_promotion_n`, and the case
loaders `cases_from_eval` / `cases_from_learned` (replays the user's own
confirmed phrasings, weighted by hit_count — what makes tuning *adaptive*).
**Data finding (2026-05-25):** on the 28-case set, 0.40–0.64 form a flat
plateau (96.4% acc / 3.6% false / 0% defer); the lone false case is a true
synonym pair that only clears at 0.74, which would cost ~18% coverage — so it
belongs to catalog disambiguation / the confirmation loop, NOT a global
threshold hike. **Defaults kept** (`DISPATCH_THRESHOLD=0.62`, `CONFIRM_LOW=0.50`,
`LEXICAL_THRESHOLD=88`, `TIE_EPSILON=0.05`, `PROMOTE_AFTER=3`) — now data-validated
rather than guessed. The confirmation band catches 0 eval cases (clean
paraphrases all score high); tuning `CONFIRM_LOW` needs real
`routing_observations` accrued in production.
**Wrong behaviour:** the integration test fails (`DISPATCH_THRESHOLD` slipped
below peak accuracy) — re-tune and adjust the default with a recorded reason.
**Verify:**
```
.venv/bin/python3 -m pytest tests/routing/test_threshold_tuning.py -q
.venv/bin/python3 -m core.routing_tuner   # metrics dump + recommendation
```

### T-4.4  Reindex installed applications (Track 6.1)

**You say:** "Friday, rescan my apps."
**Expected:** "Reindexed N installed applications." where N matches the
number of `.desktop` (Linux) / Start Menu + Uninstall registry entries
(Windows) discovered.
**What it tests:** `refresh_app_index` capability → `SystemCapabilities.probe()`
→ `AppIndexStore.bulk_upsert`. Categories from `.desktop` `Categories=`
field land on `DesktopApp.categories`; Windows resolves `.lnk` targets
via pywin32 when available.
**Wrong behaviour:** Returns 0 with a populated `~/.local/share/applications`;
or "App discovery is unavailable" on a system that previously launched
apps fine.
**Verify:**
```
sqlite3 ~/.friday/friday.db "SELECT COUNT(*), MAX(updated_at) FROM app_index;"
```

### T-4.5  Reindex user files (Track 6.2)

**You say:** "Friday, reindex my files."
**Expected:** "Reindexed N files." Background scan walks `~/Documents`,
`~/Downloads`, `~/Desktop`, `~/Pictures`, `~/Videos`, `~/Music` plus
any external mounts under `/mnt` or `/media`. Hidden dirs and
`node_modules` / `.venv` / `.git` / `__pycache__` are skipped.
**What it tests:** `refresh_file_index` capability → `FileIndexer.scan_once()`
→ `FileIndexStore.bulk_upsert`. Should also work on first boot via the
daemon thread `FridayApp._start_file_indexer()` kicks off in
`initialize()`.
**Wrong behaviour:** Counts everything under `~`, including dot-dirs;
or hangs the turn (the scan must run in a background thread when
invoked at startup, but the explicit `refresh_file_index` capability
runs inline and may block briefly on a large index — that is expected).
**Performance (2026-05-29):** the startup scan is held back
`file_index.initial_delay_s` (default 20s) so it doesn't contend with
model loading / the first turns, walks + flushes in 2000-row batches,
and `FileIndexStore.bulk_upsert` commits each batch in its own short
transaction. The store shares `friday.db` with the turn/audit stores, so
the previous single 200k-row commit held the SQLite write lock for
seconds and stalled every turn's DB write behind it. Batched commits
release the lock between chunks. The index persists across runs, so the
delayed refresh has no functional downside on a warm DB.
**Verify:**
```
sqlite3 ~/.friday/friday.db "SELECT COUNT(*), MAX(indexed_at) FROM file_index;"
```

### T-4.6  Search the file index (Track 6.2)

**You say:** "Friday, where is the file called meeting?"
**Expected:** Top N matches with full `parent_dir` paths, ordered by
recency (mtime DESC).
**What it tests:** `search_indexed_files` capability → `FileIndexStore.search`
with `LIKE` over `name`. The regex fallback in `handle_search_indexed_files`
extracts the noun after "where is the file called" / "find the file" /
"locate file" when the router doesn't fill the `query` arg.
**Wrong behaviour:** Triggers a fresh filesystem walk (latency >2s);
or returns unrelated hits because the matcher dropped the filter.
**Verify:**
```
grep "search_indexed_files" logs/friday.log | tail -3
```

### T-4.7  Screen lock — locks the real OS session (revised 2026-05-25)

**You say (GUI, Telegram, or voice):** "/lock" · "lock the screen" ·
"lock my laptop" · "lock my computer"
**Expected:** The **actual desktop/laptop locks** (you must re-enter your
system password to get back in), and FRIDAY replies "Screen locked." On
Linux it tries `loginctl lock-session`, then `xdg-screensaver lock`,
`qdbus …ScreenSaver Lock`, `xflock4`, etc. (first available wins). On
Windows it calls `LockWorkStation`.
**You say:** "/unlock" / "unlock the screen"
**Expected:** FRIDAY explains it can't unlock for you — the OS lock screen
is cleared with your own system password (there is no programmatic
unlock, by design).
**While locked — capability gate:** screen-dependent tools are refused
with "The screen is locked, so I can't run '<tool>' …". Test that these
are BLOCKED: "open firefox" (`launch_app`), "google cats" /
"search the web" via browser, "play a song on youtube", "open <file>",
"take a screenshot", "what's on my screen" (vision). Test that these
still WORK: chat, "check my mail", "summarize my emails", "research X",
"/web X", "/quick X", "what's the weather", "remind me …", "read <file>".
**Telegram log on transitions:** when the screen locks you get a Telegram
message "🔒 Screen locked — …"; when you unlock it (with your system
password) the `LockStateMonitor` poll detects it within ~2s and sends
"🔓 Screen unlocked — all tools available again." This fires for locks
from FRIDAY **and** from the desktop directly (Super+L / Win+L).
**Windows unlock detection (2026-05-29 fix):** the monitor now polls the
input desktop via `OpenInputDesktop` on Windows (locked = secure desktop,
can't be opened / name ≠ "Default"), so after a FRIDAY `LockWorkStation`
lock a **manual unlock clears the gate within ~2s** instead of leaving it
stuck "locked" forever (the bug where "start a memo" after unlocking still
said "Unlock the screen first"). A `_LOCK_GRACE_SECONDS` (6s) window stops
the first poll from clearing a lock before the secure desktop engages.
**What it tests:** `modules/system_control/os_lock.py:lock_os_session`,
`core/lock_monitor.py:LockStateMonitor` (polls systemd-logind
`LockedHint` on Linux, `OpenInputDesktop` on Windows; notifies via
`app.comms.telegram.send`), the denylist
`core/screen_lock.py:BLOCKED_WHEN_LOCKED` + the gate in
`CapabilityExecutor.execute`, `SystemControlPlugin.handle_lock_screen`,
`core.slash_commands._lock`.
**Wrong behaviour:** "/lock" only prints a message but the screen doesn't
actually lock; or it asks for a PIN (the old gate — no
`FRIDAY_LOCK_PIN_HASH` needed now); or chat/email/research get refused
while locked; or no Telegram message on lock/unlock.
**Note:** the legacy FRIDAY tool-gating PIN feature still lives in
`core/screen_lock.py` (set `FRIDAY_LOCK_PIN_HASH` to a sha256 hex digest)
but the OS lock state is the primary driver now.
**Phase 3 confirmation (conversational only):** the spoken/typed
"lock the screen" now **asks first** — "I'll lock the screen. Shall I go
ahead? Say yes to confirm, or anything else to cancel." — and only locks
after you say "yes". The explicit **`/lock` slash command stays immediate**
(it calls `lock_os_session()` directly, bypassing the guard). See T-4.7b.
**Verify:**
```
python3 -m pytest tests/test_os_lock.py tests/test_lock_gating.py tests/test_slash_commands.py -v
```

### T-4.7b  Confirm-before-destructive guard (Phase 3, 2026-05-31)

**You say:** "lock the screen" → "yes"   ·   "delete my 5k goal" → "yes"
· "cancel my dentist reminder" → "no"   ·   "turn off the heater" → "yes"
· "forget my location" → "yes"   ·   "shut down" → "no"
**Expected:** The first turn previews the action and asks
"… Shall I go ahead? Say yes to confirm, or anything else to cancel." Saying
**yes** (yeah / sure / do it / confirm / go ahead / proceed) performs the
action; saying **anything else** replies "Okay, cancelled — I won't do
that." and nothing happens.
**What it tests:** `core/workflows/confirmation.py:ConfirmationGuard` — each
destructive handler (`lock_screen`, `delete_goal`,
`ha_turn_on`/`ha_turn_off`, `shutdown_assistant`, `forget_memory`) calls
`guard.arm(...)` once it has resolved its target, persisting
`session_state.pending_destructive_action`. The
`IntentRecognizer._parse_pending_destructive` interceptor (runs first in the
parser chain) routes the next turn to `confirm_pending_action` (affirmation)
or `cancel_pending_action` (anything else); `confirm` re-dispatches the
stored capability with `_confirmed=True` so the same handler runs for real.
Composes with `delete_goal`'s "which goal?" disambiguation (the guard arms
only after a single goal is resolved). Disable globally with
`routing.confirm_destructive: false` in `config.yaml`.
**Wrong behaviour:** The action runs immediately with no confirmation turn;
or "yes" doesn't execute it; or an unrelated next command silently leaves
the action armed (it must resolve — confirm or cancel — on the very next
turn).
**Verify:**
```
python3 -m pytest tests/test_confirmation_guard.py tests/test_pending_destructive_intent.py tests/test_destructive_guard_handlers.py -v
```

### T-4.8  `!` shell prefix (Track 6.3, 2026-05-23)

**You say (GUI or Telegram):** `!ls -la ~/Documents | head -5`
**Expected:** Reply is a fenced code block with `$ ls -la …` header
followed by the actual output. stdout + stderr are merged; exit code
is shown only when non-zero.
**What it tests:** `core.shell_prefix.run_shell` runs the command in a
POSIX PTY (so commands that probe `isatty()` behave like in a real
terminal). When the screen is locked, the command is refused with
"Shell access is locked. Run /unlock <pin> first."
**Wrong behaviour:** Asterisks, pipes, or quotes get mangled; or the
command runs while the screen is locked.
**Verify:**
```
python3 -m pytest tests/test_shell_prefix.py -v
```

### T-4.8c  `!cmd` runs under bash + auto-venv (2026-05-24)

**You say:**
1. `!source .venv/bin/activate && python -c "import sys; print(sys.prefix)"`
2. `!if [[ -d .venv ]]; then echo venv_exists; fi`
3. `!which python`

**Expected:**
1. Prints the venv path — proves `source` (bash builtin) works.
2. Prints `venv_exists` — proves `[[ ]]` (bash test) works.
3. Prints `<repo>/.venv/bin/python` — proves the venv is auto-activated
   without the user typing `source` anywhere.

**What it tests:** `core/shell_prefix.py` now passes
`executable=_preferred_shell()` (prefers `/bin/bash`, falls back to
`/bin/sh`) to every `subprocess` call, AND `_shell_env()` autodetects
a project-root `.venv/` and prepends `<venv>/bin` to PATH plus sets
`VIRTUAL_ENV`. Before the fix, `!source …` returned `/bin/sh: 1:
source: not found` because `shell=True` resolved to dash on Kali.
**Wrong behaviour:**
1. `/bin/sh: 1: source: not found` for `!source …` — bash isn't being
   used.
2. `!which python` returns `/usr/bin/python` — venv isn't on PATH.
3. `!python --version` and `!.venv/bin/python --version` print
   different versions — env wasn't applied.
**Verify:**
```
python3 -m pytest tests/test_shell_prefix.py -k "bash or venv or which_python or source" -v
```

### T-4.8b  Interactive shell input via `>` prefix (2026-05-23)

**You say:**
1. `!sudo apt install brightnessctl`
2. `> <your password>`
3. `> y`  (to confirm the apt prompt)

**Expected:**
1. FRIDAY replies with `$ sudo apt install brightnessctl` followed by
   any output so far, then an italic hint: *"Awaiting password — reply
   with `> <password>` (input will not be echoed)."*
2. The password is piped to sudo's stdin; the response shows the next
   chunk of apt's output (now past authentication).
3. `y` is piped to apt's "Do you want to continue?" prompt; the
   command runs to completion; FRIDAY emits the final `[exit 0]` block
   and the shell session ends.

**What it tests:** PTY-backed `_ShellSession` in `core/shell_prefix.py`
keeps the command alive across turns. `is_shell_followup` recognises
`> …`. `app._maybe_handle_input_prefix` pipes `>` to stdin and — this
is the key bit — intercepts **any non-`>` message** while a session is
alive, killing the command rather than letting "yes" / "1234" leak to
the LLM chat path. Prompt detection (`_looks_like_prompt`) tags
`Password:`, `[Y/n]`, etc., so the user gets a specific hint instead
of a generic "still running".
**Wrong behaviour:**
1. "Friday is typing…" forever (PTY never streams; whole apt run buffered).
2. The user types a password without `>` and it ends up in the chat
   log / LLM context (security bug — password leaked to the model).
3. Sudo prompt: `sudo: a terminal is required to read the password`
   (means PTY was bypassed and the command ran with `stdin=PIPE`).
4. After the command finishes, the next normal message is misrouted
   to `feed_followup` (session wasn't cleared).
**Verify:**
```
python3 -m pytest tests/test_shell_prefix.py::test_interactive_session_captures_stdin_via_followup \
                 tests/test_shell_prefix.py::test_cancel_active_session_kills_long_running \
                 tests/test_shell_prefix.py::test_new_run_supersedes_old_session -v
```

### T-4.9  Telegram typing indicator (Track 6.3, 2026-05-23)

**You say (from Telegram):** any prompt that triggers a slow tool, e.g.
"Friday, research the history of GPT" (research_agent path).
**Expected:** Telegram client shows "FRIDAY is typing…" continuously
from the moment your message is received until the response arrives.
The indicator is refreshed every 4 seconds via `sendChatAction` so it
never falls off Telegram's 5s window.
**What it tests:** `TelegramChannel.typing_loop` background thread
wrapped around `_process` in `modules/comms/telegram.py`.
**Wrong behaviour:** Indicator vanishes after 5s; or stays on after
the response sends.
**Verify:**
```
grep "sendChatAction\|chat_action" logs/friday.log | tail -10
```

### T-4.10  Weather intent (Step 4, 2026-05-23)

**You say:** "what's the weather", "how's the weather", "weather forecast",
"what's the temperature", "is it raining", "is it sunny outside",
"will it rain", "how hot is it outside", "how cold is it", "how's it outside",
"weather in Nellore", "weather forecast for New York", "is it raining in London".
**Expected:** Routes with `source=intent intent_conf=1.00` to `get_weather`;
when a location is named, it's captured as the `location` arg.
**What it tests:** `_parse_weather`. Anti-poach: "open the weather app"
goes to `launch_app`, never to `get_weather`.
**Wrong behaviour:** `source=chat` for "what's the weather"; or
`get_weather` invoked with location="today"/"outside"/etc.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k weather -v
```

### T-4.11  Clipboard get/set/analyze (Step 4)

**You say:**
- Get: "what's in my clipboard", "show my clipboard", "read the clipboard",
  "get clipboard contents", "paste my clipboard".
- Set: `copy "hello world" to clipboard`, "copy to clipboard: my secret token",
  "put this to the clipboard: 12345".
- Analyze image: "analyze my clipboard image", "describe my clipboard image".

**Expected:** Routes to `get_clipboard` / `set_clipboard` /
`analyze_clipboard_image` respectively; set extracts the quoted or
post-colon text.
**What it tests:** `_parse_clipboard`. The analyze branch is what catches
"analyze my clipboard image" — it used to short-circuit to the LLM
because `_KNOWLEDGE_Q_RE` matched the bare verb "analyze"; the regex
was tightened with a negative lookahead for tool-nouns.
**Wrong behaviour:** "analyze my clipboard image" → chat. Quoted text
in set is captured with the quotes still present.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k clipboard -v
```

### T-4.12  Awareness mode toggle (Step 4)

**You say:** "is awareness on", "are you watching my screen",
"enable awareness mode", "turn on screen awareness", "watch my screen",
"start observing my screen", "disable awareness mode", "stop watching my screen".
**Expected:** Routes to `awareness_status` / `enable_awareness_mode` /
`disable_awareness_mode`.
**What it tests:** `_parse_awareness`.
**Wrong behaviour:** "watch my screen" routes to vision/launch_app instead.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k awareness -v
```

### T-4.13  Send a desktop notification (Step 4)

**You say:** "send a notification: standup in 5 minutes",
"send me a desktop notification saying coffee break",
"show notification: build done", "notify me: tests passed",
"ping me: deploy finished".
**Expected:** Routes to `send_notification` with `text` arg = the
content after the colon / saying / with.
**What it tests:** `_parse_send_notification`.
**Wrong behaviour:** Falls through to chat and the LLM reads the
notification text back to you instead of firing it.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k notification -v
```

### T-4.14  Active-window query (Step 4)

**You say:** "what's my active window", "which window is focused",
"what app am I using", "currently focused window".
**Expected:** Routes to `get_active_window`.
**What it tests:** `_parse_window_query`. Anti-poach: doesn't fire on
"what am I looking at on screen" (that goes to `summarize_screen`).
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k window -v
```

### T-4.15  Code evaluation (Step 4)

**You say:** "evaluate: 2 + 2", "run this: print('hello')",
"execute python: x = 5; print(x)", "eval: sum(range(10))".
**Expected:** Routes to `evaluate_code` with `code` arg = everything
after the colon. Multi-statement Python (with semicolons) is preserved
intact — the clause-splitter has a guard for `eval(uate)|run|execute`
+ `python|py|code` that keeps the whole input as one clause.
**What it tests:** `_parse_code_eval` + the `_split_into_clauses`
code-eval guard + the `code_execution` plugin actually loading.
**Live gating (2026-05-25):** the plugin is config-gated — `setup(app)` in
`modules/code_execution/__init__.py` returns the plugin only when
`code_execution.enabled: true` (now set in config.yaml). Before this fix the
package `__init__.py` was empty, so the PluginManager found no `setup` and
`evaluate_code` never registered — "compute 6 * 7" fell through to chat. With
it enabled, "compute 6 * 7" → "42". **SECURITY:** this runs arbitrary
Python/Bash in a subprocess; flip `code_execution.enabled: false` to remove the
capability entirely.
**Wrong behaviour:** "execute python: x = 5; print(x)" gets split on
`;` and `evaluate_code` only sees the first statement; OR `evaluate_code` isn't
registered at boot even with `code_execution.enabled: true`.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k code_eval -v
python3 -m pytest tests/test_code_execution_sandbox.py -q
```

---

### T-4.16  Focus / Pomodoro session (proper implementation, 2026-05-26)

**You say (start):** "start a focus session", "begin a pomodoro",
"enter focus mode", "deep work mode", "turn on do not disturb",
"enable do not disturb", "focus for 50 minutes", "pomodoro for 45
minutes", "dnd for 25", "do not disturb for 30 minutes", "focus for
half an hour", "focus for fifty minutes", "silence my notifications
for an hour", "give me 25 minutes of focus".
**You say (status):** "focus status", "how much focus is left", "am I
still in focus mode".
**You say (end):** "end focus", "stop focus session", "turn off do not
disturb", "disable do not disturb".
**Expected:** Start → `start_focus_session`; when a duration is spoken
it arrives in `args["minutes"]` (capped 1–240), otherwise the handler
defaults to 25. The `FocusModeWorkflow` enables **Do Not Disturb**, stops
**all** playing media, blocks new browser media for the duration, and arms
a one-shot timer that restores notifications and announces completion.
Status reports the remaining time; end stops the timer early and restores
notifications. (Media is intentionally not auto-resumed — pausing is the
safe action; the user resumes manually.)
**Cross-platform (2026-05-29):** every side effect now works on both OSes.
  - **Do Not Disturb:** Linux → `gsettings show-banners false`; Windows →
    the `…\PushNotifications\ToastEnabled` registry switch (0 = off),
    restored on end. `_notifications_supported()` is now True on both, so the
    start reply honestly claims DND on each.
  - **Stop all media:** Linux → a `gdbus` `Pause` sweep over every MPRIS
    player on the session bus (Spotify, VLC, a normal browser tab); Windows →
    `TryPauseAsync` over every System Media Transport Controls session via
    WinRT/PowerShell (pauses, never toggles). Plus FRIDAY's own Playwright
    browser, on both.
  - **Block browser media during focus:** while a session is active,
    `play_youtube` / `play_youtube_music` and any play/resume in
    `browser_media_control` are refused ("the only sound should be me") in
    `BrowserMediaService` — the gate sits at the `_do_*` chokepoint so every
    routing path (intent → workflow, chat preflight, re-open) is covered.
    Pause/stop/next/seek stay allowed so focus's own pause still works.
**"stop the focus session" while media is playing (2026-05-29 fix):** the
**"stop the focus session" while media is playing (2026-05-29 fix):** the
end phrase must route to `end_focus_session`, NOT be swallowed by the
bare-cancel path that cancels the *active* `browser_media` workflow. The
2026-05-29 bug: "stop the focus session" while a YouTube session was active
logged `Cancelled active workflow 'browser_media'`, said "Okay, cancelled,"
left the focus timer running, AND "forgot" the media session so a later
"play" fell to chat. `WorkflowOrchestrator._targets_other_workflow` now
detects that the utterance would START a *different* workflow (focus_mode)
and lets it fall through to intent routing. Bare "stop"/"cancel" still
cancels whatever workflow is active.
**What it tests:** `_parse_focus_session` + `_focus_minutes`
(numeric + spoken-cardinal + "an hour"/"half an hour" extraction) →
`FocusSessionPlugin` handlers → the `focus_mode` agentic service in
`core/reasoning/agentic_services/focus_mode.py`;
`WorkflowOrchestrator._targets_other_workflow` /
`FocusModeWorkflow._notifications_supported`.
**Wrong behaviour:** "focus on my homework" / "let's focus on the bug"
wrongly start a session (the old bare-`on` trigger); OR a spoken
duration is dropped and every session runs the 25-minute default; OR
the start phrase falls through to the LLM and Qwen fabricates a
"Focus mode enabled." reply for a session that never armed; OR "stop the
focus session" cancels the active media workflow instead of ending focus;
OR media keeps playing during focus; OR YouTube/YouTube Music can still be
started mid-session; OR notifications keep popping up on either OS.
**Verify:**
```
python3 -m pytest tests/test_focus_session_intent.py tests/test_focus_session_media.py \
                 tests/test_browser_automation_service.py -q
# Linux — during a session, confirm media is actually paused:
gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
  --method org.freedesktop.DBus.ListNames | tr ',' '\n' | grep mpris
# Windows — confirm DND is on (0 = toasts suppressed):
#   reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\PushNotifications" /v ToastEnabled
```

---

## 5. Kali / Security tools (requires `lab_mode: true`)

What this section validates: routing of recon phrases, CIDR detection,
ping sweep, host scan, custom nmap.

### T-5.1  Ping sweep with explicit subnet

**You say:** "Friday, do a network recon on 192.168.1.0/24."
**Expected:** Live hosts on the subnet are reported.
**What it tests:** `_HOST_SCAN_PATTERNS` CIDR regex; `ping_sweep`
routing.
**Wrong behaviour:** Falls through to chat; no `[ROUTE]
tool=ping_sweep` log line.
**Verify:**
```
grep "ROUTE.*tool=ping_sweep" logs/friday.log | tail -2
```

### T-5.2  Network recon free-form (P1.1)

**You say:** "Friday, scan my network."
**Expected:** Either a target clarification or a sweep against the
default subnet.
**What it tests:** Free-form alias coverage on `ping_sweep`.
**Wrong behaviour:** "Sorry, I can't do that" or LLM chat reply.
**Verify:**
```
grep "ping_sweep\|ROUTE.*security" logs/friday.log | tail -3
```

### T-5.3  Host service scan

**You say:** "Friday, scan 192.168.1.50 for open ports."
**Expected:** Port / service table.
**What it tests:** `host_service_scan` capability.
**Wrong behaviour:** No output; or shell error not surfaced.
**Verify:**
```
grep "host_service_scan" logs/friday.log | tail -3
```

### T-5.4  Custom nmap

**You say:** "Friday, run nmap -sV -p 22,80,443 192.168.1.1."
**Expected:** Raw nmap output read back.
**What it tests:** `run_custom_nmap`.
**Wrong behaviour:** Refused (means `lab_mode` is off).
**Verify:**
```
grep "run_custom_nmap" logs/friday.log | tail -2
```

### T-5.5  Lab mode gate

**You say:** "Friday, scan 8.8.8.8." (with `lab_mode: false`)
**Expected:** Refusal pointing at the lab-mode setting.
**What it tests:** `lab_mode` enforcement.
**Wrong behaviour:** Scan runs anyway.
**Verify:**
```
grep -i "lab_mode" logs/friday.log | tail -3
```

### T-5.5  DNS enumeration (Step 4, 2026-05-23)

**You say:** "dns enum example.com", "dns enumeration for mybox.local.lab",
"subdomain scan of example.lab.local".
**Expected:** Routes with `source=intent` to `dns_enum_owned_domain` with
`domain` arg populated. Still gated by `security.authorized_scopes` at
the handler — public domains outside the allowlist are refused.
**What it tests:** Extended `_parse_security` branch.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k security_extras -v
```

### T-5.6  Web directory enumeration (Step 4)

**You say:** "fuzz https://target.lab", "gobuster on target.local.lab",
"directory scan on target.lab.local", "dirb https://target".
**Expected:** Routes to `web_directory_enum` with `target` arg.
**Wrong behaviour:** "fuzz" alone (no URL) does not route — anti-poach.

### T-5.7  Compare scan results (Step 4)

**You say:** "compare the last two scans", "compare scan results",
"diff between scans", "what changed since the last scan".
**Expected:** Routes to `compare_scan_results`.
**What it tests:** The `_KNOWLEDGE_Q_RE` was tightened with a
negative lookahead for `compare ... scans?/screenshots?/scan results?`
— previously "compare the last two scans" short-circuited to the LLM
because the bare verb `compare` triggered the knowledge-question gate.

### T-5.8  Generate security report (Step 4)

**You say:** "generate a security report", "create a pentest report",
"write up the recon findings", "export the scan results".
**Expected:** Routes to `security_report_generate`.

---

## 6. Tasks, Reminders, Notes

What this section validates: ad-hoc reminders, task list, scheduled
routines (see §22 for cron scheduler).

### T-6.1  One-shot reminder

**You say (any of):**
- "Friday, remind me to call Sam in 10 minutes."  (complete → schedules at once)
- "Friday, remind me to call Sam tomorrow at 5pm." (date + time in one turn)
- "Friday, remind me to call Sam."  → "What date should I remind you?" → "tomorrow"
  → "What time should I remind you?" → "5pm" (two-phase follow-up)
**Expected:** "Got it! I'll remind you to call Sam on <day> at <time>."; reminder
fires after the delay. When date and/or time are missing, FRIDAY asks for the
date, then the time (bare answers like "four" read as 4 o'clock; an ambiguous
already-passed morning hour today is taken as the afternoon).
**What it tests:** `set_reminder` capability + the `set_reminder` YAML template
slot-fill (launch-hardening §5.4 Step 3 — replaced the `ReminderWorkflow` shim;
`create_reminder` wraps the unchanged scheduling core).
**Wrong behaviour:** Reminder fires immediately or never; a missing time is
silently defaulted instead of asked for; "Created …" (calendar) wording instead
of "I'll remind you …".
**Verify:**
```
sqlite3 data/friday.db "SELECT title, remind_at, type FROM calendar_events WHERE title LIKE '%Sam%' ORDER BY id DESC LIMIT 1;"
```

### T-6.2  Add a quick note

**You say:** "Friday, make a note: investigate the FTS5 trigger."
**Expected:** "Noted."
**What it tests:** `save_note` → notes file or fact namespace
(depending on note-taking SKILL config).
**Wrong behaviour:** Verbose echo of the note back to the user.
**Verify:**
```
ls -t ~/Documents/FRIDAY/notes/inbox/*.md 2>/dev/null | head -1
```

### T-6.3  List today's tasks

**You say:** "Friday, what's on my list today?"
**Expected:** A short bulleted list.
**What it tests:** `list_tasks` + date filter.
**Wrong behaviour:** Returns tasks from other days.
**Verify:**
```
sqlite3 data/friday.db "SELECT description FROM goals WHERE created_at >= date('now') ORDER BY id DESC;"
```

### T-6.4  Goals — list / create / complete / pause / detail / update / delete (2026-05-25)

**You say (in order):**
1. "I have a new goal: ship the research agent"
2. "list my goals" / "show my goals" / "what am I working on"
3. "tell me about my goal"
4. "pause my goal" / "put my goal on hold"
5. "update the launch goal to 75%" / "set my research goal progress to 50%"
6. "remove the launch goal" / "delete my research goal"
7. "I finished the research agent"

**Expected:** Each phrasing routes with `source=intent intent_conf=1.00`
to the matching goals capability. The create-goal extractor captures
everything after the colon; the parser also accepts "my goal is to X",
"I want to achieve X", "new goal: X". `update_goal` extracts a title
and a percentage value. `delete_goal` extracts a title when specified
(e.g. "remove the launch goal" → `args={"title": "launch"}`), or sets
`args={}` for delete-all when no title is given (e.g. "remove all
goals"). When multiple goals match the same title, the system presents
a numbered list and enters disambiguation mode — user responds with
"first one" / "option 2" / "the second one" to pick.

**What it tests:** `_parse_goals` in `core/intent_recognizer.py` —
covers `list_goals`, `create_goal`, `complete_goal`, `pause_goal`,
`get_goal_detail`, `update_goal`, `delete_goal`, `select_goal_candidate`.
The `update_goal` regex matches "update/set/mark X goal to/at Y%",
"set progress of X to Y%", "advance X to Y%". The `delete_goal` regex
first tries title extraction via "remove/delete/clear/erase the X goal",
then falls back to the catch-all "delete/remove/clear goals". Prior to
this fix, every goals phrasing fell into chat and the 0.8B model
fabricated bullet lists; goals were per-session instead of global.

**Wrong behaviour:** `source=chat` for any of the above; OR the title
extractor capturing only the verb without the rest; OR `delete_goal`
with a bare "delete" showing a generic error instead of listing goals;
OR `update_goal` being poached by `launch_app` (the `_parse_goals`
parser was moved before email/research/web parsers in the clause chain
to prevent this).

**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k goals -v
```

### T-6.4a  Goal disambiguation — multiple goals with matching title

**You say:**
1. "I have a new goal: launch the app" → creates goal
2. "my goal is to launch the rocket" → creates another goal
3. "update the launch goal to 90%" → (two goals match "launch")
4. "first one" / "option 1" / "the first one"

**Expected:**
- After step 3, FRIDAY replies with a numbered list of matching goals
  and asks "Which one?"
- A `PendingGoalSelection` is set in `dialog_state` with the two
  candidates, the original tool (`update_goal`), and the original args
  (`{"title": "launch", "progress": 90}`).
- After step 4, the disambiguation resolves to the first goal and the
  `update_goal` executes against it — the progress changes for only
  that goal.

**What it tests:** `_find_goals_by_title` → `_disambiguate_or_return`
sets `dialog_state.pending_goal_selection`; `_parse_pending_selection`
(in `core/intent_recognizer.py`) routes "first one" / "option 2" /
"the second one" / "last" to `select_goal_candidate`; the handler in
`modules/goals/plugin.py` resolves the selection and dispatches to the
original tool (`update_goal`, `delete_goal`, or `complete_goal`).

**Wrong behaviour:** FRIDAY picks the first match arbitrarily and
updates the wrong goal; OR the user's selection reply (e.g. "first
one") falls through to chat; OR the disambiguation prompt is never
generated and `update_goal` silently picks one.

**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k goals -v
```

### T-6.4b  Delete goal with title extraction

**You say:** "remove the launch goal" / "delete my research goal" /
"clear the celebration goal"

**Expected:** Each routes with `source=intent` to `delete_goal` with
`args={"title": "launch"}` (or "research", "celebration"). The handler
looks up goals matching the title; if exactly one matches, it deletes
it and confirms.

**What it tests:** The `delete_goal` intent pattern first tries
`r"\b(?:remove|delete|clear|erase)\s+(?:my\s+|the\s+)?(.+?)\s+goal\b"`
to extract a title. Fallback: the bare "remove all goals" / "clear
goals" pattern returns `args={}` (delete-all, which lists active goals
for user selection).

**Wrong behaviour:** "remove the launch goal" routes with empty args
(the pattern doesn't extract the title); OR "delete my research goal"
matches but the captured title includes "my " or "the ".

**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k goals -v
```

### T-6.5  Triggers — list / clipboard / cron / file-watch / remove (Step 4)

**You say:**
- List: "list my triggers" / "show all triggers" / "active triggers"
- Clipboard: "watch my clipboard" / "tell me when I copy" / "add a clipboard trigger"
- Cron: "every monday remind me to commit" / "every 30 minutes run cleanup" / "add a scheduled job"
- File-watch: "watch ~/Downloads" / "notify me when a new file appears" / "add a file watcher"
- Remove: "remove trigger #3" / "delete trigger 5" / "cancel my trigger"

**Expected:** Routes deterministically; `remove_trigger` extracts the
trigger ID from `#N` or bare `N`.
**What it tests:** `_parse_triggers` in `core/intent_recognizer.py`.
**Wrong behaviour:** "watch ~/Downloads" routes to `search_indexed_files`;
"every monday remind me to X" routes to `set_reminder`.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k trigger -v
```

---

## 7. Persona & Greeter

What this section validates: identity replies, persona YAML (P2.5),
tone consistency.

### T-7.1  Who are you? — deterministic identity (2026-05-23)

**You say:** "Who are you?" / "What are you?" / "What's your name?" /
"Introduce yourself" / "Tell me about yourself" / "Are you an AI?" /
"Identify yourself" / "State your name".
**Expected:** A short canned identity line such as *"I'm FRIDAY — a
local-first AI assistant running entirely on your machine, Tricky."*
The reply comes from the `identify_self` capability in
`modules/greeter/extension.py`. Routing is `source=intent` at
`intent_conf=1.00` — the LLM is never invoked.
**What it tests:** `_parse_identity` in `core/intent_recognizer.py`
catches identity questions before they fall through to chat. This
defends against the 0.8B chat model echoing the system prompt
verbatim ("…never describe yourself using facts from the
USER_FACTS block…"), observed in session logs on 2026-05-23 17:00
and 17:41.
**Wrong behaviour:**
1. Reply quotes the system prompt verbatim (`"You are Friday, a
   personal AI assistant. I am intelligent, warm…never describe
   yourself using facts from the USER_FACTS block"`).
2. `[ROUTE] source=chat` for "Who are you?" — means the parser
   missed the phrase.
3. `identify_self` poaches "who am I" (must still go to
   `recall_personal_fact`).
**Verify:**
```
python3 -m pytest tests/test_identity_intent.py -v
tail -20 logs/friday.log | grep -B1 "Who are you"
# Expect: source=intent  tool= identify_self  (NOT source=chat)
```

### T-7.2  Persona YAML driven dos/donts

**You say:** "Friday, hello!"
**Expected:** Greeting that respects `donts` from the YAML — no emoji,
no "Sure!" preamble.
**What it tests:** YAML overrides are present in the system prompt.
**Wrong behaviour:** "Sure! 👋 Hi there!" (violates two donts).
**Verify:**
```
python -c "from core.persona_manager import PersonaManager; print('Don' in PersonaManager.identity_prompt())"
# → True
```

### T-7.3  Greeting after restart

**You say:** "Friday, hi." (immediately after a fresh boot)
**Expected:** Personalised greeting using the user's name from
`user_profile`.
**What it tests:** Onboarding + persona injection on startup.
**Wrong behaviour:** Generic "Hello!" with no name.
**Verify:**
```
sqlite3 data/friday.db "SELECT value FROM facts WHERE namespace='user_profile' AND key='name';"
```

### T-7.5  Bold/italic/code render in the GUI chat bubble (2026-05-23)

**You say:** "What do you know about me?" (with the GUI window open)
**Expected:** "**About you:**" renders as **About you:** (real bold)
inside the FRIDAY chat bubble. `*italic*` is italic; `` `code` `` is
monospace.
**What it tests:** `_markdown_inline_to_html` in `gui/main_window.py`
runs before `cursor.insertHtml`, so markdown bold survives the
HTML-escape step instead of being shown as literal asterisks.
**Wrong behaviour:** "**About you:**" appears with literal `**`s
around it, or HTML escaping kills the markdown entirely.
**Verify:** open the GUI, run the conversation, look at the chat bubble.

### T-7.4  Assistant does not speak AS the user (2026-05-23, v2)

**You say:** "What do you know about me?" or "What else do you know about me?"
(also reproducible via any chat turn while a document is attached — see #5)
**Expected:** A short, natural paragraph (1-3 sentences) that weaves
in USER_FACTS — e.g. *"From what I have on file, you're Tricky, a
student based in Nellore."* It must NEVER begin with `I'm <user_name>`,
NEVER bullet-list profile fields, and NEVER echo the user's prompt
back. FRIDAY must NEVER call **itself** by the user's name.
**What it tests:** the role-guard + paragraph-rule clauses in
`assistant_identity` (`core/assistant_context.py`) + the natural
paragraph rewrite of `_handle_show_memories`
(`modules/memory_manager/plugin.py`) + the `_parse_memory_query`
regex extension covering "what else / tell me more / anything else /
tell me everything". 2026-05-29: `assistant_identity` now **names the
user explicitly** ("The user's name is Luffy. You are NOT Luffy …") —
a far stronger signal to the 0.8B model than the abstract "your name is
not in USER_FACTS" rule — and a deterministic safety net,
`strip_user_impersonation` (`core/model_output.py`), rewrites any
leaked self-identification ("an assistant named Luffy" → "named FRIDAY")
on both the spoken sentences and the returned text in
`modules/llm_chat/plugin.py`. **Neither name is hardcoded:** the user's
name is read live from the `user_profile` and the assistant's from
`PersonaManager.assistant_name()` (the `name:` in
`config/personas/default.yaml`), so renaming either side propagates
without a code edit. The guard is skipped when the two names are equal
(user literally named after the assistant) to avoid a contradictory prompt.
**Wrong behaviour:**
1. "Hey! I'm Tricky. I know…" (impersonation — v1 fix).
2. Bullet list with `**About you:** \n - location: …` (v1 over-correction).
3. "What else do you know about me?" — model echoes the same list.
4. *"What else do you know about me?"* as a header followed by the
   same bullet list (LLM mirroring the prompt back).
5. "I'm Friday, an assistant named Luffy." — FRIDAY adopting the user's
   name as its own (the 2026-05-29 14:17 doc-Q&A session bug).
Cases 1-4 were observed in the 2026-05-23 14:54 + 15:35 session logs.
**Verify:**
```
python3 -m pytest tests/test_assistant_context.py::test_assistant_identity_forbids_speaking_as_user \
                 tests/test_assistant_context.py::test_identity_names_the_user_so_model_wont_impersonate \
                 tests/test_user_impersonation.py \
                 tests/test_show_memories_namespaces.py -v
```

### T-7.4b  show_memories prefers the facade over stale user_profile (2026-05-24)

**Repro:**
1. Say "What do you know about me?" — note the current name FRIDAY reports.
2. Say "My name is Santhosh".
3. Say "What do you know about me?" again.

**Expected:** Step 3 reports "Santhosh" (the just-saved name).
**Wrong behaviour (the 2026-05-24 07:25 bug):** Step 3 still reports
the old name (e.g. "Tricky") even though `recall_personal_fact`
("Who am I?") correctly says Santhosh. Caused by `_handle_show_memories`
reading the legacy `user_profile` namespace which had an outdated row.
**What it tests:** `_handle_show_memories` now overlays the
`MemoryFacade.recall` result on top of the `user_profile` dict — the
facade is the canonical writer post-Track-2.2, so it must also win on
read for every `_PROFILE_KEYS` field.
**Verify:**
```
python3 -m pytest tests/test_bugfix_2026_05_24.py::test_show_memories_prefers_facade_over_stale_user_profile -v
```

### T-7.6  Chat-side pre-flight reroute (Step 4b, 2026-05-24)

**Background:** When IntentRecognizer regex misses AND the Qwen-4B
planner picks chat (often a low-confidence default), the chat plugin
used to commit and the 0.8B model would refuse with "I can't access
external URLs" or similar — even though a real tool would have worked.

**You say:** a phrasing that **isn't in the regex coverage** but maps
to a catalog entry — e.g. "do you happen to know what the weather is
where I am right now" (semantic match for `get_weather`), or "could
you analyze the picture I just put in my clipboard for me" (semantic
match for `analyze_clipboard_image`).
**Expected:**
- Log line `[LLMChat] preflight reroute → <tool> (cosine=0.XX) for query=...`
- The tool's output is returned **without ever calling the chat model**.
- For tools tagged `blocked_from_chat_preflight: true` in the catalog
  (set_volume, set_reminder, set_brightness, …), preflight skips the
  match and chat proceeds normally (those need structured args the
  pre-flight can't extract).
**What it tests:** `EmbeddingRouter.preflight_route(query, threshold=0.72)`
honours the catalog's blocked flag; `LLMChatPlugin._preflight_reroute`
calls it and dispatches via `capability_executor` when there's a hit.
Threshold is intentionally tighter than the regular embed router's
0.62 because the cost of a wrong reroute here is higher.
**Wrong behaviour:**
1. Chat replies with a refusal/paraphrase when a clearly-matching tool
   exists in the catalog.
2. Pre-flight fires for a blocked tool with empty args (e.g.
   `set_volume` called without a percent).
3. Catalog entry exists but no `[LLMChat] preflight reroute` log line
   appears even though the query is close to its example_phrases.
**Verify:**
```
python3 -m pytest tests/test_tool_catalog.py -v
# 18 cases — loader, embedding-index rebuild, preflight block,
# chat-integration dispatch, planner-card injection.
```

---

## 8. Workflows (multi-turn)

What this section validates: file_create_with_content, onboarding,
recon, scheduler routines, clarify/approval gates.

### T-8.1  Onboarding cold-start

**You say:** Run `python main.py` on a wiped DB.
**Expected:** FRIDAY introduces itself and asks for name + role +
preferences.
**What it tests:** Onboarding YAML workflow.
**Wrong behaviour:** Skips straight to "How can I help" without
profile collection.
**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM facts WHERE namespace='user_profile';"
# → ≥1 after onboarding
```

### T-8.2  File-create slot fill

**You say:** "Friday, create newfile.txt." → answer the slot prompts in
turn.
**Expected:** File appears at the chosen path.
**What it tests:** Slot-fill primitive (template_compiler).
**Wrong behaviour:** FRIDAY forgets earlier slots between turns.
**Verify:**
```
ls -l ~/Desktop/newfile.txt
```

### T-8.3  Workflow resumes after interruption

**You say:** Begin file-create, say "stop", then "Friday, finish that
file."
**Expected:** FRIDAY resumes the same workflow with the previous slots
intact.
**What it tests:** Workflow checkpoint (P3.16) +
`workflow_orchestrator` resume.
**Wrong behaviour:** Asks slots from scratch.
**Verify:**
```
sqlite3 data/friday.db "SELECT state_json FROM conversation_sessions ORDER BY updated_at DESC LIMIT 1;" | grep workflow
```

---

## 9. Telegram bridge

What this section validates: text in/out, voice in (P1.4 / P3.20),
long-message chunking (P1.3), approval response routing.

### T-9.1  Inbound text

**You say:** *(from Telegram)* "what time is it"
**Expected:** A short text reply in the same chat.
**What it tests:** `TelegramInbound._dispatch` → `process_input(source=
'telegram')`.
**Wrong behaviour:** No reply; or reply spoken via TTS instead of sent
back over Telegram.
**Verify:**
```
grep "TelegramInbound" logs/friday.log | tail -3
```

### T-9.2  Inbound voice note (P3.20)

**You say:** *(from Telegram)* Send a voice memo saying "open YouTube".
**Expected:** Chrome opens; Telegram receives "Opening YouTube." reply.
**What it tests:** `TelegramInbound._handle_voice_note` →
`core.transcription.transcribe_file` → STT engine. [ported:
hermes-agent/tools/transcription_tools.py]
**Wrong behaviour:** Voice note silently ignored.
**Verify:**
```
grep "TelegramVoice" logs/friday.log | tail -5
```

### T-9.3  Outbound long message chunking (P1.3)

**You say:** *(from Telegram)* "Friday, give me a 1000-word essay on
the history of the steam engine."
**Expected:** Multi-message reply, each ≤ 3,800 chars; split on
sentence boundaries.
**What it tests:** `TelegramChannel._chunk_text`.
**Wrong behaviour:** Telegram returns HTTP 400 "message is too long";
nothing sent.
**Verify:**
```
grep -c "message is too long" logs/friday.log
# → 0 (must be 0)
```

### T-9.4  Approval-response interception

**You say:** *(from Telegram while an approval is pending)* "yes"
**Expected:** The pending approval resolves; the bare "yes" is not
routed as a new query.
**What it tests:** `TelegramChannel.try_resolve_approval`.
**Wrong behaviour:** "yes" goes through `process_input` as a new
utterance.
**Verify:**
```
grep "approval response consumed" logs/friday.log | tail -2
```

### T-9.7  Slash commands actually run in Telegram (2026-05-23 fix)

**You do:** in Telegram, type `/new` or `/research transformers` or `/lock`.
**Expected:** The command runs and FRIDAY replies (e.g. `/new` → "New conversation started.", `/lock` → "Screen locked. Tools require /unlock <pin> to run."). The slash command must NOT be silently dropped.
**What it tests:** `TelegramInbound._dispatch` now forwards every slash command except `/start` to `process_input`, where `core.slash_commands.dispatch` handles it. Group-chat suffixes like `@BotUsername` are stripped before forwarding.
**Wrong behaviour:** `/new` returns nothing in Telegram (Pre-Track-6.3-followup behavior — the `if text.startswith('/')` block silently swallowed everything but `/start`).
**Verify:**
```
python3 -m pytest tests/test_telegram_approval.py::test_inbound_dispatch_routes_slash_commands_to_friday \
                 tests/test_telegram_approval.py::test_inbound_dispatch_strips_bot_username_suffix \
                 tests/test_telegram_approval.py::test_inbound_dispatch_start_still_handled_locally -v
```

### T-9.8  In-chat "thinking…" bubble (Telegram editMessageText, 2026-05-23)

**You do:** in Telegram, send a slow prompt (e.g. "research transformers").
**Expected:** A bubble appears in the chat saying *"💭 thinking…"* (in italics). When FRIDAY's real response is ready, that same bubble morphs into the response — no second message is sent. The header-bar "FRIDAY is typing…" indicator continues to refresh in parallel.
**What it tests:** `TelegramChannel.send_capturing_id` drops the placeholder and captures its `message_id`; `_process` runs the turn synchronously; `TelegramChannel.edit_message` transforms the placeholder into the response via `editMessageText`. If the edit fails (e.g. response >4096 chars), `_process` falls back to sending a new message and leaves the placeholder. If the response is empty, the placeholder is `delete_message`'d so it doesn't hang around.
**Wrong behaviour:** Two bubbles appear ("thinking…" + the real response) — means the edit fell back to a new send and the placeholder wasn't cleaned. Or the placeholder hangs around forever.
**Verify:**
```
grep "editMessageText\|placeholder bubble" logs/friday.log | tail -5
```

### T-9.6  Slash command autocomplete (BotFather setMyCommands, 2026-05-23)

**You do:** open the FRIDAY bot in Telegram and type just `/` in the
message box.
**Expected:** Telegram's autocomplete menu pops up with every command
from `core.slash_commands.REGISTRY` (`/new`, `/clear`, `/research`,
`/web`, `/screenshot`, `/voice`, `/lock`, `/unlock`, `/help`) along
with a one-line description for each.
**What it tests:** `TelegramChannel.register_commands` POSTs to
`/bot<TOKEN>/setMyCommands` on `TelegramInbound.start()`. The push
pulls commands directly from `slash_commands.REGISTRY`, so any new
slash command added there automatically appears in Telegram.
**Wrong behaviour:** Typing `/` produces no suggestions, or shows an
out-of-date list (e.g. missing `/lock` after Track 6.3 landed).
**Verify:**
```
grep "setMyCommands registered" logs/friday.log
# Look for the count to match len(slash_commands.REGISTRY).
```

### T-9.5  Bold/italic/code render in Telegram (2026-05-23)

**You say:** "What do you know about me?" (from Telegram)
**Expected:** "**About you:**" arrives as **bold** in the Telegram
chat, not as literal `**About you:**` text. `*italic*` becomes italic,
`` `code` `` becomes monospace.
**What it tests:** `_markdown_to_telegram_html` in
`modules/comms/telegram.py` runs in `_send_sync` when the caller
didn't set `parse_mode`, escaping the body for Telegram's HTML
parse_mode and re-introducing `<b>`, `<i>`, `<code>`.
**Wrong behaviour:** Asterisks appear in the chat verbatim, or the
message comes back with an HTTP 400 from Telegram (entity parse
failure).
**Verify:**
```
python3 -c "from modules.comms.telegram import _markdown_to_telegram_html; print(_markdown_to_telegram_html('**bold** and *italic*'))"
# → <b>bold</b> and <i>italic</i>
```

---

## 10. Voice IO

What this section validates: wake word, barge-in, STT phonetic
substitutions (P2.3), voice mode toggle (P3.19).

### T-10.1  Wake word

**You say:** "Hey Friday."
**Expected:** Wake chime + listening UI.
**What it tests:** Porcupine wake detector.
**Wrong behaviour:** No reaction in wake_word mode; or false-trigger
on "Friday" inside a sentence in persistent mode.
**Verify:**
```
grep "wake" logs/friday.log | tail -3
```

### T-10.2  Barge-in during TTS

**You say:** While FRIDAY is speaking, say "stop".
**Expected:** TTS halts within ~500 ms.
**What it tests:** `BARGE_IN_WORDS` in `stt.py` + `tts.stop()`.
**Wrong behaviour:** FRIDAY finishes the sentence before reacting.
**Verify:**
```
grep "barge" logs/friday.log | tail -2
```

### T-10.3  Task cancel mid-tool

**You say:** Start a slow scan ("Friday, scan 10.0.0.0/16"), then say
"cancel" within 3 s.
**Expected:** Scan terminates; "Cancelled the scan."
**What it tests:** `TASK_CANCEL_WORDS` →
`interrupt_bus.signal('user_cancel')` → P3.16 process registry.
**Wrong behaviour:** Scan keeps running silently. [ported:
hermes-agent/tools/interrupt.py]
**Verify:**
```
grep "interrupt\|cancel_current" logs/friday.log | tail -3
```

### T-10.4  STT substitution (P2.3)

**You say:** "Friday, what's the weather in nolo-re?"
**Expected:** Normalised to "nellore" before routing; weather lookup
runs on the right city.
**What it tests:** `core/text_normalize.py` YAML substitution layer.
**Wrong behaviour:** Query routed with the raw misrecognition.
**Verify:**
```
grep "nolo-re\|nellore" logs/friday.log | tail -5
```

### T-10.5  Voice mode mute (P3.19)

**You say:** "Friday, mute yourself."
**Expected:** Reply is text-only; TTS silent on subsequent turns.
**What it tests:** `VoiceModeController.set('mute')` + `app.tts_muted`
flag in `VoiceIOPlugin.handle_speak`. [ported:
hermes-agent/tools/voice_mode.py]
**Wrong behaviour:** TTS still speaks.
**Verify:**
```
cat data/runtime_state.json | python -m json.tool | grep muted
# → "muted": true
```

### T-10.6  Voice mode timed mute (P3.19)

**You say:** "Friday, be quiet for 1 minute."
**Expected:** TTS silent; auto-unmutes after 60 s.
**What it tests:** `VoiceModeController` timed-mute clock.
**Wrong behaviour:** Mute persists past the timer.
**Verify:**
```
python -c "import time; from types import SimpleNamespace as N; from modules.voice_io.voice_mode import VoiceModeController; vm=VoiceModeController(N(tts_muted=False), state_path='/tmp/vm.json'); print(vm.is_muted())"
```

### T-10.7  Voice mode unmute

**You say:** "Friday, speak again."
**Expected:** TTS resumes on the next reply.
**What it tests:** `VoiceModeController.set('unmute')`.
**Wrong behaviour:** TTS stays silent.
**Verify:**
```
cat data/runtime_state.json | python -m json.tool | grep muted
# → "muted": false
```

### T-10.8  First-turn embedding warmup (2026-05-23)

**You say:** "Hi" — as the first turn after a fresh boot on a cold
HuggingFace cache.
**Expected:** Response within ~2s (the existing 0.8B chat-LLM
inference cost), not 8-9s. The
`sentence-transformers/all-MiniLM-L6-v2` (or whichever model
`EmbeddingRouter.model_name` resolves to) finishes loading in the
`embed-router-warmup` daemon thread before the user's prompt arrives.
**What it tests:** `core/app.py:initialize()` spawns the embed-router
warmup thread after `extension_loader.load_all()`. The "Loading
weights: 199/199" tqdm bar should appear in the logs DURING startup,
not interleaved with the first user turn.
**Wrong behaviour:** A 'Loading weights:' progress bar appears right
after the first `[USER]:` line and the route decision takes >5s.
**Verify:**
```
grep "embed-router-warmup\|Loaded sentence-transformers" logs/friday.log | head -2
# Must show the load timestamp is BEFORE the first user turn timestamp.
```

### T-10.9  Noisy-room transcription accuracy (signal-to-noise pipeline, 2026-05-26)

**You say:** A normal command (e.g. "Friday, open the calculator") in a
**noisy** room — fan, AC, TV in the background — where you are the only
speaker.
**Expected:** The command transcribes correctly. The same command in a
**silent** room must stay just as accurate and just as fast (no added
latency). Under the hood: quiet utterances use greedy decode; noisy ones
auto-switch to beam search (`stt_beam_size_noisy`, default 5), the bundled
Silero VAD (`stt_vad_filter`) drops non-speech frames, the decoder is biased
toward the command vocabulary (`stt_domain_prompt`), and the utterance is
RMS-normalized + DC-removed before inference (`stt_normalize_audio`).
**What it tests:** `STTEngine._estimate_snr_db` →
`_build_transcribe_kwargs` (adaptive beam + hallucination guards
`no_speech_threshold`/`log_prob_threshold`/`compression_ratio_threshold` +
temperature fallback) and `_prepare_audio_for_transcription` →
`_normalize_level` / optional `_denoise`. All tunable in `config.yaml`
under `voice.stt_*`. Optional spectral-subtraction denoise
(`stt_denoise`, off by default) needs `pip install noisereduce`.
**Wrong behaviour:** Wrong words in noise; OR the silent-room path gets
slower (it should still log `beam=1`); OR a noise-only buffer produces a
phantom transcript like "thank you for watching".
**Verify:**
```
grep "Whisper] Transcribing (SNR" logs/friday.log | tail -5
# Quiet utterance → 'beam=1'; noisy utterance → 'beam=5'. SNR is logged in dB.
```

### T-10.10  Chat-reply latency cap (2026-05-29)

**You say:** Any open-ended question that lands in chat (e.g. "what is in
the document?" with a doc attached, or "tell me about system design").
**Expected:** The spoken/typed reply completes promptly — a few
sentences — rather than the 0.8B chat model grinding out a multi-minute
monologue on CPU. Streaming still speaks the first sentence early.
**What it tests:** `routing.chat_max_tokens` (now **512**, was 2048) read
by `LLMChatPlugin._chat_max_tokens`. 512 covers normal conversational /
doc-summary replies (the 2026-05-29 resume answer was ~150 tokens) while
capping worst-case generation ~4x. Research synthesis is unaffected — it
uses its own larger budget.
**Wrong behaviour:** A single chat reply takes 20s+ and rambles well past
the answer; or research summaries get truncated (they must not — they
don't read `chat_max_tokens`).
**Verify:**
```
grep "chat_max_tokens\|\[LLMChat\] Response" logs/friday.log | tail -5
```

---

## 11. Cleanup & reset

What this section validates: memory wipe end-to-end, profile reset,
log rotation, DB / Chroma archive.

### T-11.0  `/new` and `/clear` true session isolation (2026-05-23)

**You say (in order):**
1. "Play sahiba on YouTube"  →  YouTube tab opens, plays.
2. "Friday, forget everything you know about me"  →  FRIDAY queues the wipe and asks for confirmation.
3. `!sleep 30`  →  shell session goes live (you see *_Still running…_*).
4. `/new`  (or `/clear`)
5. "Yes, wipe everything"
6. "Pause"

**Expected:**
- After step 4: reply is `New conversation started.`
- After step 5: a *normal* response (NOT a confirmed memory wipe) — the pending-wipe flag was carrying the prior session's state and must have been cleared.
- After step 6: `There's no active youtube tab.` (or equivalent) — NOT `Paused youtube.`, because the prior YouTube tab handle was dropped.
- The background `!sleep 30` is killed (verify via `pgrep -fa sleep` — no row).

**What it tests:** `core.slash_commands._new_session` now closes the
browser-media tab via `BrowserMediaService.reset_session()`, cancels
any live shell session via `core.shell_prefix.cancel_active_session`,
clears `pending_memory_wipe` on the OUTGOING session row, and resets
`routing_state`. Without this, `/new` was a label-only reset and the
new conversation could reach back into prior in-memory state.

**Wrong behaviour:**
- "Yes wipe everything" right after /new still triggers a memory wipe (means outgoing-session pending flag wasn't cleared).
- "Pause" right after /new still says "Paused youtube." (means browser handles weren't dropped).
- The `!sleep 30` keeps running after `/new` (means shell session wasn't cancelled).
- Identical pause/resume behaviour as before /new (means routing_state stayed dirty).

**Verify:**
```
python3 -m pytest tests/test_slash_commands.py -v
# 7 new cases: test_new_session_clears_browser_handles,
#              test_new_session_clears_pending_wipe_on_outgoing_session,
#              test_new_session_kills_active_shell,
#              test_new_session_rotates_session_id,
#              test_new_session_resets_routing_state,
#              test_clear_is_alias_for_new,
#              test_new_session_survives_missing_optional_attrs
```

### T-11.0b  `/new` expires the outgoing session's workflow rows (2026-05-24)

**Repro:**
1. Say "/research History of GPT", let it finish (writes to friday-research/…).
2. FRIDAY asks "Want me to read the summary aloud?"
3. Say "/new".
4. Say "Bye".

**Expected:**
- After /new: `New conversation started.`
- After "Bye": `See you next time, sir.` (the normal shutdown_assistant reply). NOT a 1-paragraph readout of the GPT briefing.

**What it tests:** `_new_session` now calls
`context_store.expire_all_workflows(outgoing_session_id)` which marks
EVERY active workflow row as `expired`. Combined with the new
`awaiting_readout` bail-out tokens, "Bye" can't be hijacked by the
dangling research-planner row.

**Wrong behaviour (the 2026-05-24 07:30 bug):** "Bye" after /new
triggered `source=workflow tool=research_planner` and FRIDAY read the
entire GPT briefing instead of shutting down.

**Verify:**
```
python3 -m pytest tests/test_bugfix_2026_05_24.py -v
```

### T-11.0c  `awaiting_readout` step bails on shutdown phrasings (2026-05-24)

**You say (after a research workflow asked "Want me to read the summary aloud?"):**
"bye" / "goodbye" / "exit" / "quit" / "/new" / "/clear" / "never mind" /
"see you" / "leave it".

**Expected:** The workflow ends quietly (`step="done"`, no readout)
and the outer router handles the message via its real intent —
shutdown_assistant for "bye", `_new_session` for "/new", etc.

**What it tests:** `_is_bailout` + the new branch in
`_handle.awaiting_readout` in
`core/reasoning/agentic_services/research_planner.py`. The branch
returns `WorkflowResult(handled=False, …)` so the router falls
through.

**Wrong behaviour:** A 1-paragraph summary is read aloud at the user
when they said "Bye".

### T-11.1  Full reset script (manual)

**You say:** *(shell)*
**What it tests:** `scripts/memory_admin.py wipe --confirm` removes
all rows + recreates an empty Chroma collection.
**Wrong behaviour:** Chroma collection survives or partially exists.
**Verify:**
```
python scripts/memory_admin.py wipe --confirm
python scripts/memory_admin.py inspect
# → row counts all zero, chroma size: 0
```

### T-11.2  Log rotation

**You say:** *(shell)*
**What it tests:** Log file rotates at the configured size cap.
**Wrong behaviour:** `logs/friday.log` grows unbounded past the cap.
**Verify:**
```
ls -lh logs/friday.log* | head
```

### T-11.3  DB / Chroma reconciliation (P2.2)

**You say:** *(shell, after the 2026-05-22 reconciliation)*
**What it tests:** Canonical path is `data/friday.db` + `data/chroma/`;
`core/data/` does not exist.
**Wrong behaviour:** `core/data/` reappears.
**Verify:**
```
test -e core/data && echo FAIL || echo OK
python -c "from core.stores import ContextStore; print(ContextStore().db_path)"
```

---

## 12. Web & Research

What this section validates: web search, extract, crawl (P3.10) +
arxiv / blogwatcher / research-paper / llm-wiki SKILL flows.

### T-12.1  Web search

**You say:** "Friday, search the web for 'Claude opus 4.7 release
notes'." or `/web claude opus 4.7 release notes`
**Expected:** ≥3 result titles + URLs.
**What it tests:** `modules/web.web_search`. Primary backend is now
SearchFlox (`modules/web/searchflox_client.py`); on 429/empty it falls
back to DuckDuckGo, then Wikipedia. [ported:
hermes-agent/tools/web_tools.py]
**Wrong behaviour:** "I don't have internet access" while
`config/web_search.yaml` is set up.
**Verify:**
```
grep "web_search\|searchflox" logs/friday.log | tail -3
```

### T-12.1f  Research ecosystem — four tiers (2026-05-25)

**You say (GUI or Telegram):**

| Command | Natural phrasing | Routes to | Behaviour |
|---|---|---|---|
| `/web <q>` | "search the web for X" | `web_search` | result links (SearchFlox→DDG→Wikipedia) |
| `/quick <q>` | "quick answer about X", "just tell me about X" | `quick_answer` | instant answer in chat, **nothing saved** |
| `/fast <q>` | "quick research on X", "fast research on X" | `research_topic` mode=quick | ~2-min latest-info summary, saved |
| `/deep <q>` | "deep dive on X", "deep research on X" | `research_topic` mode=deep | heavy executive summary, saved |

**Expected:** Each command works identically in the GUI and Telegram
(slash commands are sourced from `core.slash_commands.REGISTRY`, which
also feeds Telegram's `setMyCommands`). `/quick` returns a short answer
with 1-3 source links and writes nothing to `~/Documents/friday-research/`.
**What it tests:** `_quick`/`_fast`/`_deep` in `core/slash_commands.py`;
`quick_answer` capability + `_searchflox_links` in `modules/web/plugin.py`;
`_parse_quick_answer` in `core/intent_recognizer.py` (runs before
`_parse_research_topic` so "quick research" still means research).
**Wrong behaviour:** `/quick` saves a folder; "quick research on X"
routes to `quick_answer` instead of the research pipeline; commands work
in the GUI but not Telegram.
**Verify:**
```
python3 -m pytest tests/test_quick_answer_intent.py tests/test_searchflox_client.py -q
```

### T-12.7  Email — primary inbox unread + summary (2026-05-25)

**You say:** "check my mail" / "check my mails" / "any new email" →
unread **Primary** inbox list. "summarize my emails" / "summarize mails"
→ one-paragraph spoken summary of the unread primary mail.
**Expected:** A list of unread Primary-category senders+subjects, or a
synthesised summary paragraph. NOT "Checking your mail…" with no data
(that was the 0.8B chat model fabricating because the tool never reached
the router — see modification log 2026-05-25).
**What it tests:** `gws_client.gmail_list_unread` now passes
`--query "is:unread category:primary"` so Promotions/Social are excluded;
`_parse_email_action` in `core/intent_recognizer.py` (now matches the
plural "mails"); and the extension-protocol registration fix in
`core/extensions/protocol.py` that lets Extension capabilities carrying
metadata actually reach `router._tools_by_name`.
**Wrong behaviour:** "summarize mails" routes to `summarize_file`; email
commands fall through to chat and get a fabricated reply; inbox includes
Promotions/Social bulk.
**Verify:**
```
python3 -m pytest tests/test_email_intent.py tests/test_extension_metadata_registration.py -q
grep "check_unread_emails\|summarize_inbox" logs/friday.log | tail -3
```

### T-12.1e  Research mode auto-detection (Step 5d, 2026-05-24)

**You say:** Any phrasing in the table below.

| Phrasing | Routes to | Why |
|---|---|---|
| `tldr X` / `tl;dr X` / `briefly on X` / `quick research on X` / `quick brief on X` / `quick rundown on X` / `fast brief on X` / `rapid overview of X` / `summarize X` / `one-pager on X` / `overview of X` | **quick mode** | ~15-20s |
| `research X` / `deep dive on X` / `thorough briefing on X` / `comprehensive analysis of X` / `exhaustive research on X` / `in-depth research on X` / `literature review on X` / `detailed report on X` / `write a long-form report on X` / `investigate X` / `study X` | **deep mode** | ~60-120s |
| `compare X vs Y` / `contrast X with Y` / `differentiate X from Y` / `which is better X or Y` | **deep mode** | Comparative work needs multi-source synthesis |
| `brief me on X` / `put together a briefing on X` / `find research papers on X` | **(asks for focus)** | Generic — planner prompts for depth |

**Expected:**
- The explicit-mode phrasings skip the "Any specific angle?" prompt
  and go straight to kick-off ("Researching '<topic>' in quick mode…").
- The ambiguous phrasings still ask the user for focus + depth.
- When the user replies "general but quick" / "focus on RLHF, fast" /
  "focus on architecture, in detail", `_parse_mode` recognises the
  inline depth override and uses the right pipeline.

**What it tests:** `_parse_research_topic` in
`core/intent_recognizer.py` (`_RESEARCH_QUICK_PATTERNS`,
`_RESEARCH_DEEP_PATTERNS`, `_RESEARCH_COMPARE_PATTERNS`); the
`tl;dr` clause-splitter guard in `_split_into_clauses`; the comparative
guard in `_KNOWLEDGE_Q_RE` so "compare X vs Y" doesn't get poached to
the LLM fallback; `research_planner.begin(topic, sid, mode=…)`
explicit-mode fast path; `research_planner._parse_mode` returning
"quick"/"deep" for inline overrides.

**Wrong behaviour:**
1. "tldr GPT history" still prompts "Any specific angle?".
2. "deep dive on rotary position embedding" routes to legacy quality
   pipeline (means service dispatch didn't see `mode="deep"`).
3. "compare RAG vs fine-tuning" falls through to chat (means the
   knowledge-question regex still claims it).
4. "research X" stays in the legacy generic patterns (must now route
   to deep).

**Verify:**
```
python3 -m pytest tests/test_research_mode_detection.py -v
# 49 cases — 12 quick phrasings, 14 deep phrasings, 4 comparative
# phrasings, 3 legacy generic phrasings, 12 inline _parse_mode
# checks, 3 planner.begin behaviour checks, 1 plugin handler dispatch.
```

### T-12.1d  Deep-mode research pipeline (Step 5c, 2026-05-24)

**You say:** "Research transformer scaling laws" / "Deep dive on
rotary position embedding" / "Thorough briefing on long covid
treatment" / "Literature review on CRISPR Cas9" / "Detailed report on
price of MSFT" — anything that maps to `mode="deep"`.

**Expected:** ~4-5 min end-to-end (the 4B writer dominates). Produces
`~/Documents/friday-research/<ts>_<slug>/` with the same shape as
quick mode but YAML front-matter now includes `mode: deep` + a
`domains: <list>` line + (optional) `ticker:` line. `00-summary.md`
has 3 sections:
- **Executive Summary** (≈3-4 dense paragraphs, 14-18 sentences, every
  fact ends with [N], ≥5 sources, weaves sources together).
- **Key Findings** (6-10 specific concrete bullets).
- **Conflicting Claims** (only when sources disagree; OMITTED otherwise).

**Domain dispatch (regex-based, no LLM call):**

| Topic contains | Adds source |
|---|---|
| `arxiv|paper|transformer|scaling law|moe|attention head|…` | arxiv_search |
| `pubmed|clinical|disease|vaccine|crispr|…` | pubmed_search |
| `hn discussion|hacker news|trending on github|…` | hackernews_search |
| `stock|ticker|price of <TICKER>|$<TICKER>|market cap|…` | yfinance_quote + extracts the ticker |

Wiki anchor + web search are ALWAYS used.

**Wrong behaviour:**
1. Deep mode runs the legacy 25-iteration agentic loop and takes 600s
   (means service dispatch didn't see `mode='deep'`).
2. Synthesis cites `[15]` when only 6 sources exist (citation
   scrubber didn't run).
3. "history of long covid treatment" doesn't pull pubmed.
4. "price of MSFT" doesn't pull yfinance.
5. Conflicting Claims section is included with no content (writer
   should OMIT empty sections).

**What it tests:** `modules/research_agent/deep.py` —
`run_deep_research(app, topic, max_sources=12)`. `modules/research_agent/domain.py`
detects domains via regex. `_collect_arxiv` / `_collect_pubmed` /
`_collect_hackernews` / `_collect_yfinance` normalize per-domain
results into `ResearchSource`. `_synthesize_deep` shares quick mode's
`_writer_candidates` (4B tool model first → 0.8B chat → extractive
fallback), `_clamp_max_tokens` budget guard, and direct-body
`_source_bundle`; it builds the 3-section prompt with the domain hint
and the same `[N]`-only citation rule (cite 1-3 sources/sentence, no
spam). `_DEEP_SYNTH_MAX_TOKENS`=900. Same `_strip_dangling_citations`
+ truncation guard as quick mode.

**Verify:**
```
python3 -m pytest tests/test_research_deep_mode.py -v
# 30 cases — domain classifier × 11 phrasings, each per-domain
# collector, synth prompt domain hint, citation scrubber, no-LLM
# fallback, e2e pipeline writes deep-flavored YAML + per-source
# files, arxiv/pubmed/yfinance/hn pulled when domain matches,
# failure card on zero sources, empty topic error, service dispatch
# on mode='deep'.
```

### T-12.1c  Quick-mode research pipeline (Step 5b, 2026-05-24)

**You say:** "Quick research on history of GPT" / "tldr history of GPT" /
"give me a one-pager on rotary position embedding" — anything that
maps to `mode="quick"`.

**Expected:** ~3-4 min end-to-end (the 4B writer is the bottleneck —
see below). Produces `~/Documents/friday-research/<ts>_<slug>/` with:
- `00-summary.md` — YAML front-matter (topic, mode=quick,
  generated_at, sources_usable, sources_total) + a single
  **comprehensive Executive Summary** (≈3 dense paragraphs, 12-15
  sentences) that synthesises ALL sources, followed by References.
- `sources.md` — one URL per line.
- `01-…md` through `0N-…md` — one file per usable source with the
  trafilatura-extracted body.
**Wrong behaviour:**
1. `00-summary.md` says "_LLM unavailable — surfaced raw source
   summaries with citations._" followed by a raw dump of source
   bodies. This is the *extractive fallback* — it means NO writer model
   could be loaded (both the 4B tool and 0.8B chat models failed). The
   2026-05-24 live bug: a stale process running the old single-shot
   synthesis blew the 4096 context window (`Requested tokens (6380)
   exceed context window`) and fell back to this dump.
2. Every sentence ends with `[1][2][3]…[10]` (citation spam) — means
   the writer ran on the weak 0.8B model, not the 4B (check the
   `[quick] synthesis: writer=…` log line; it should say `writer=tool`).
3. Synthesis cites `[7]` when only 4 sources exist (dangling-citation
   scrubber didn't run).
4. The summary cuts mid-sentence with no `_(response truncated)_`
   marker (truncation guard didn't fire).
**What it tests:** `modules/research_agent/quick.py` —
`run_quick_research(app, topic, max_sources=5)`. Pipeline:
1. Wikipedia anchor via `modules.sources.wikipedia.summary_for_query`.
2. DDG search → top URLs (with the T-12.1b Wikipedia fallback baked in).
3. `modules.sources.newspaper.extract_many` parallel with 5 workers.
4. **Synthesis** (`_synthesize`): the cleaned source text is fed
   DIRECTLY to the writer (each body sliced to `_WRITER_BODY_CHARS`).
   `_writer_candidates` picks the best model first — the **4B tool
   model** (much better, less-hallucinated prose; routed via
   `model_manager.get_tool_model()` + the tool inference lock) — and
   falls back to the 0.8B chat model, then to the extractive dump.
   `_clamp_max_tokens` shrinks the generation budget so prompt+output
   never exceed the model's `n_ctx` (the structural fix for the old
   "exceed context window" failure). Generation budget is
   `_SYNTH_MAX_TOKENS` (=600), spent entirely on the Executive Summary.
5. `_strip_dangling_citations` removes `[N]` references where N >
   max_index.
6. Truncation guard appends `_(response truncated)_` when the last
   sentence doesn't end in terminal punctuation.
7. Writer emits the YAML-fronted summary + sources.md + per-source
   files.

**Why ~3-4 min:** the 4B tool model runs at ~2.7 tok/s on CPU, so a
600-token summary is ~3.5 min. This is the deliberate quality/latency
trade chosen 2026-05-24 (research runs in the background and announces
when ready). Tune `_SYNTH_MAX_TOKENS` down toward ~480 for a ~3-min
budget, or up for a longer summary. Requires `models.tool.n_ctx: 8192`
in config.yaml so the 4B can hold the multi-source bundle.

Failure path: when neither Wikipedia nor DDG returned anything, the
pipeline writes a clean failure card listing what was tried instead of
the silent empty file that was the pre-Step-5b symptom.

**Verify:**
```
python3 -m pytest tests/test_research_quick_mode.py -v
# slug/folder helpers, citation validator, truncation guard,
# synth-with-LLM, synth-fallback, writer-prompt size cap, end-to-end
# pipeline, no-wiki path, zero-sources failure card, mode='quick'.
```

### T-12.1b  /web falls back to Wikipedia when DDG returns empty (2026-05-24)

**Repro:** Run `/web Attack on Titan` repeatedly across a few minutes.
DDG HTML scraping is brittle and sometimes returns zero hits even for
common queries (2026-05-24 07:29 session: same query that returned 5
hits at 07:07 returned 0 hits at 07:29).
**Expected:** When DDG is empty, the response now starts with
*"(Web search returned nothing; pulled this from Wikipedia instead.)"*
followed by the Wikipedia summary for the query. Real content, not
"No results found for: X".
**What it tests:** `WebPlugin._try_wikipedia_fallback` calls
`modules.sources.wikipedia.summary_for_query` (free REST API, no rate
limit). Only fires when `_ddg_search` returns `[]`. The normal happy
path (DDG returns hits) is unchanged.
**Wrong behaviour:** `/web` returns "No results found" for a query
that has an obvious Wikipedia page.
**Verify:**
```
python3 -m pytest tests/test_bugfix_2026_05_24.py -k web_search -v
```

### T-12.2  Web extract

**You say:** "Friday, fetch https://docs.python.org/3/library/subprocess.html"
**Expected:** `[ROUTE] source=intent` (NOT chat) followed by a
plain-text body summarised if >5000 chars.
**What it tests:** `_parse_web_url_action` routes `fetch <URL>`,
`extract from <URL>`, `read this url`, and a bare URL to `web_extract`.
Before the 2026-05-23 fix this phrasing fell through to
`source=chat`, and the 0.8B model fabricated something like *"Friday,
fetching the Python documentation for `subprocess` module."* without
ever calling the tool.
**Wrong behaviour:** Garbage HTML / nav / footer; or `source=chat`
with the model paraphrasing the request instead of fetching.
**Verify:**
```
python3 -m pytest tests/test_web_intent.py::test_web_extract_routes_with_url -v
grep "web_extract" logs/friday.log | tail -2
```

### T-12.3  Web crawl

**You say:** "Friday, crawl https://news.ycombinator.com and find ML
stories."
**Expected:** `[ROUTE] source=intent tool= mode=tool intent_conf=1.00`
followed by a depth-limited follow + summary of pages whose content
matches the "ML stories" instruction.
**What it tests:** `_parse_web_url_action` in
`core/intent_recognizer.py` routes the URL-bearing clause to
`web_crawl`. The clause-splitter is taught NOT to split
"crawl <URL> and find …" — the "and find" portion is an *instructions
modifier*, not a second tool call. Before this fix (2026-05-23) the
splitter produced `["crawl <URL>", "find ML stories"]` and the planner
mis-routed the second half to `search_indexed_files` ("I couldn't find
any file named 'ml stories'.").
**Wrong behaviour:**
1. Reply is "I couldn't find any file named 'ml stories'." (means the
   split-guard isn't in place and the file-search index stole the verb).
2. `[ROUTE] source=planner` instead of `source=intent` (means the
   regex didn't fire and we fell through to the LLM planner).
3. Crawl runs unbounded.
**Verify:**
```
python3 -m pytest tests/test_web_intent.py -v
grep "web_crawl" logs/friday.log | tail -3
```

### T-12.4  arXiv SKILL — by ID

**You say:** "Friday, what does arxiv 2401.04088 say?"
**Expected:** Four-bullet structured summary + URL.
**What it tests:** `modules/web/SKILLS/arxiv.md` flow.
**Wrong behaviour:** Hallucinated abstract.
**Verify:**
```
grep "arxiv\|web_extract" logs/friday.log | tail -3
```

### T-12.5  Blogwatcher SKILL (recurring)

**You say:** "Friday, set up a morning briefing on the Anthropic blog."
**Expected:** A new entry in `config/routines.yaml` (or in-memory
schedule) for daily fire.
**What it tests:** Blogwatcher SKILL + P3.9 scheduler.
**Wrong behaviour:** Routine isn't registered.
**Verify:**
```
grep -A3 morning_brief config/routines.yaml
```

### T-12.6  Research-paper SKILL

**You say:** "Friday, write me a one-pager on prompt caching with
citations."
**Expected:** A 300–800 word markdown file saved under
`~/Documents/FRIDAY/research/` with numbered references.
**What it tests:** Research-paper SKILL + `delegate` (P3.12).
**Wrong behaviour:** Inline reply only, no file; or no References
section.
**Verify:**
```
ls -t ~/Documents/FRIDAY/research/ | head -1
```

### T-12.7  LLM-wiki SKILL

**You say:** "Friday, what is rotary position embedding?"
**Expected:** Structured Definition / How / Related / Confidence block.
**What it tests:** `modules/web/SKILLS/llm_wiki.md` flow.
**Wrong behaviour:** Free-form prose without the structure.
**Verify:**
```
grep "llm_wiki\|Confidence" logs/friday.log | tail -3
```

### T-12.8  Source tool: `wikipedia_summary` / `wikipedia_search` (2026-05-24)

**You say:** "wikipedia linux kernel" / "wiki summary of transformers"
/ "search wikipedia for neural networks".
**Expected:** `wikipedia_summary` returns a structured block with the
article title, a Wikipedia URL, and the REST API `extract` text. The
search variant lists the top N matching article titles.
**What it tests:** `modules/sources/wikipedia.py` — free REST API
(`/api/rest_v1/page/summary/<title>` + `/w/api.php?action=opensearch`),
no key required. Single source of truth for the research-quick anchor
+ the `/web` Wikipedia fallback (T-12.1b).
**Wrong behaviour:** "Wikipedia has no article matching X" when an
obvious article exists (means the open-search step failed or returned
junk); or extract text contains "[[wikitext markup]]" leaking from a
broken HTML→text step.
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k wikipedia -v
```

### T-12.9  Source tool: `arxiv_search` (2026-05-24)

**You say:** "arxiv search for mixture of experts" / "arxiv papers on
transformer scaling laws" / "academic papers on rotary position
embedding".
**Expected:** Up to 5 papers, each with title, top-4 authors,
published date, abstract URL, PDF URL.
**What it tests:** `modules/sources/arxiv.py` — Atom-XML response from
`http://export.arxiv.org/api/query`. Used by deep-mode research when
the topic is academic / technical (`domain.academic` flag in
`modules/research_agent/domain.py`).
**Wrong behaviour:** `arXiv rate-limited (429)` retry storm (the
legacy agentic loop had a 25-iteration loop that hammered the API).
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k arxiv -v
```

### T-12.10  Source tool: `hackernews_top` / `hackernews_search` (2026-05-24)

**You say:** "top stories on hacker news" / "hacker news search for
rust" / "hn discussions about rag".
**Expected:** Title, URL, score, comment count, HN permalink for each
of the top N stories.
**What it tests:** `modules/sources/hackernews.py` — Firebase API for
top stories + Algolia API for keyword search. No key. Used by
deep-mode research when the topic has tech-buzz vibes.
**Wrong behaviour:** Stories with score=0 (means we read the wrong
field) or missing HN permalinks (means the `objectID` → URL build
failed).
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k hackernews -v
```

### T-12.11  Source tool: `pubmed_search` (2026-05-24)

**You say:** "pubmed search for CRISPR" / "medical papers on long
covid" / "clinical papers on vaccine efficacy".
**Expected:** Up to 5 papers with title, top-4 authors, journal name,
publication date, PubMed URL.
**What it tests:** `modules/sources/pubmed.py` — NCBI Entrez
E-utilities (`esearch.fcgi` → PMIDs → `esummary.fcgi`). No key
required for low-volume usage.
**Wrong behaviour:** "PubMed returned no results" for a query with an
obvious hit (e.g. "CRISPR"). Used by deep-mode research when the
topic has medical/biomedical keywords.
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k pubmed -v
```

### T-12.12  Source tool: `newspaper_extract` (2026-05-24)

**You say:** "get just the article from https://example.com/post" /
"reader mode https://nytimes.com/2026/…" / "newspaper extract
https://…" / "strip nav from https://….com/page".
**Expected:** Clean article body only — nav menus, cookie banners,
footers, ads, comment sections all stripped. Title + URL + extracted
length displayed.
**What it tests:** `modules/sources/newspaper.py` — wraps `trafilatura`
(already in venv). Replaces the in-repo `_html_to_text` BeautifulSoup
hack. Powers per-URL fetches in `quick.py` and `deep.py` pipelines
(parallel 5-worker `ThreadPoolExecutor`).
**Wrong behaviour:** "Cookie Notice" / nav-bar text appearing in the
extracted body. Or `trafilatura` import failure printed to the chat
(silent skip is the expected behaviour).
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k newspaper -v
```

### T-12.13  Source tool: `yfinance_quote` (2026-05-24)

**You say:** "quote MSFT" / "price of AAPL" / "stock quote TSLA" /
"what's GOOG trading at" / "how's NVDA doing".
**Expected:** Company name + ticker + last price + day change (% and
absolute) + day range + market cap rendered as $X.XX T/B/M.
**What it tests:** `modules/sources/yfinance.py` — lazy-imports
`yfinance` (optional dep — run `pip install yfinance` to enable).
When missing, the handler returns a clear `pip install yfinance` hint
instead of crashing. Used by deep-mode research when `domain.finance`
fires (regex picks up the ticker from "$MSFT" / "price of MSFT" /
"quote MSFT" shapes).
**Wrong behaviour:** Hardcoded "USD" when the actual currency is
different (e.g. `7203.T` → JPY). Or stale price (means we hit
`.info` instead of `.fast_info`).
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k yfinance -v
```

### T-12.14  Source tool: `pdf_text_search` (2026-05-24)

**You say:** "search my PDFs for transformer scaling" / "look for
emergence in my pdfs" / "find in my pdfs the section on attention
heads".
**Expected:** Top N PDFs from `~/Documents` + `~/Downloads` (or the
`folder` arg) ranked by the count of query-token matches, with a
~280-char snippet around the first hit.
**What it tests:** `modules/sources/pdf_text.py` — lazy-imports
`pypdf` (run `pip install pypdf` to enable). When missing, the handler
returns the install hint and does NOT crash.
**Wrong behaviour:** Crash on scanned/image-only PDFs (means we didn't
catch the `extract_text` exception per-page); or filename-match results
leaking (means we accidentally fell through to `search_indexed_files`).
**Verify:**
```
python3 -m pytest tests/test_sources_tools.py -k pdf -v
```

---

## 13. Vision

What this section validates: image description, screen analysis.

### T-13.1  Describe an image

**You say:** "Friday, describe ~/Pictures/cat.jpg."
**Expected:** A 1–3 sentence description.
**What it tests:** `describe_image` capability (vision plugin).
[ported: hermes-agent/tools/vision_tools.py]
**Wrong behaviour:** "I can't see images" while the vision model is
configured.
**Verify:**
```
grep "describe_image" logs/friday.log | tail -2
```

### T-13.2  Analyse the screen

**You say:** "Friday, what's on my screen?"
**Expected:** Screenshot taken + described.
**What it tests:** `screenshot` (P0.1) piped into `describe_image`.
**Wrong behaviour:** "Failed to take screenshot" — see T-4.1 deps.
**Verify:**
```
ls -t ~/Pictures/FRIDAY_Screenshots/ | head -1
grep "analyze_screen\|describe_image" logs/friday.log | tail -3
```

### T-13.3  Vision long-tail capabilities (Step 4, 2026-05-23)

`_parse_vision_action` now covers the 8 remaining vision tools. Each
phrasing routes with `source=intent intent_conf=1.00`:

| Tool | Phrasings |
|------|-----------|
| `find_ui_element` | "where is the submit button", "find the close icon", "locate the menu", "point to the X button" |
| `compare_screenshots` | "compare these two screenshots", "diff my screenshots", "what's the difference between these screenshots", "spot the difference between the screenshots" |
| `debug_code_screenshot` | "debug my code", "debug this error", "what's wrong with this code", "why is this broken" |
| `recent_screen_activity` | "what have I been doing", "recent screen activity", "what did I just see", "my recent activity" |
| `roast_desktop` | "roast my desktop", "roast my wallpaper", "roast my setup" |
| `review_design` | "review my design", "critique my mockup", "feedback on my UI" |
| `explain_meme` | "explain this meme", "what's the meme", "I don't get the meme" |
| `describe_image` | "describe this picture", "what's in this image", "describe my screenshot" |

**What it tests:** Extended `_parse_vision_action` branches +
`_KNOWLEDGE_Q_RE` negative lookaheads so "describe this image",
"compare these screenshots", "analyze my screen" no longer
short-circuit to the LLM. Previously the bare verbs (`describe`,
`compare`, `analyze`) triggered the knowledge-question gate and the
tool was never reached.
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k vision_extras -v
```

---

## 14. Smart home

What this section validates: lights, climate, scenes, state queries
(P3.15).

### T-14.1  Turn on a light

**You say:** "Friday, turn on the bedroom lights."
**Expected:** Lights on.
**What it tests:** `turn_on` capability → Home Assistant REST.
[ported: hermes-agent/tools/homeassistant_tool.py]
**Wrong behaviour:** "Home Assistant isn't reachable" while the
service is up.
**Verify:**
```
grep "turn_on\|home_assistant" logs/friday.log | tail -3
```

### T-14.2  Set thermostat

**You say:** "Friday, set the AC to 22 degrees."
**Expected:** Thermostat changes; FRIDAY confirms.
**What it tests:** `set_temperature` capability.
**Wrong behaviour:** No change; or "I don't know which thermostat".
**Verify:**
```
grep "set_temperature" logs/friday.log | tail -2
```

### T-14.3  Query state

**You say:** "Friday, is the front door locked?"
**Expected:** "Yes" or "No" with the lock entity name.
**What it tests:** `get_state` capability.
**Wrong behaviour:** Hallucinated answer when entity is unknown.
**Verify:**
```
grep "get_state" logs/friday.log | tail -2
```

### T-14.4  Scene activation

**You say:** "Friday, movie mode."
**Expected:** All scene actions execute; result line lists what
changed.
**What it tests:** `modules/smart_home/SKILLS/scenes.md` flow.
**Wrong behaviour:** Only one device flips; rest silently dropped.
**Verify:**
```
grep "scene\|movie_mode" logs/friday.log | tail -5
```

### T-14.5  HA intent routing — deterministic + anti-poach (Step 4, 2026-05-23)

**You say:** "turn on the kitchen light", "switch off the tv",
"shut off the fan", "deactivate the alarm", "activate the porch light",
"set the AC to 22 degrees", "set the thermostat to 70",
"is the bedroom light on", "is the front door locked", "is the garage open".
**Expected:** Each phrase routes with `source=intent intent_conf=1.00`
to the matching `ha_*` capability. The entity name is captured into
`args["entity"]`; temperature into `args["temperature"]`.
**What it tests:** `_parse_homeassistant`. Anti-poach: HA does NOT
fire on "turn on voice", "turn on focus", "turn on do not disturb",
"lower the volume", "turn down the brightness" — those still go to
their own parsers (`_parse_voice_toggle`, `_parse_focus_session`,
`_parse_volume`, `_parse_brightness`) which all run earlier in the
chain. The HA parser checks for those domain words and returns None.
**Wrong behaviour:** "turn on the bedroom lights" routes to chat;
or "turn on focus" mis-routes to `ha_turn_on` with entity="focus".
**Verify:**
```
python3 -m pytest tests/test_step4_new_parsers.py -k "ha_" -v
```

---

## 15. Clarify / Delegate / MoA

What this section validates: P3.11 clarify, P3.12 delegate, P3.13
mixture-of-agents.

### T-15.1  Clarify on ambiguous "scan"

**You say:** "Friday, scan." (no target)
**Expected:** "Scan what — a host, a subnet, or open ports on this
machine?"
**What it tests:** `core.clarify.ask` triggered by ambiguity. [ported:
hermes-agent/tools/clarify_tool.py]
**Wrong behaviour:** Hallucinated default target; or "I don't
understand."
**Verify:**
```
grep "clarify\|pending_clarification" logs/friday.log | tail -3
```

### T-15.2  Delegate a long task

**You say:** "Friday, delegate: write me a one-line summary of REST vs
gRPC."
**Expected:** Child turn runs; final one-liner returned.
**What it tests:** `core.delegate.run_and_wait`. [ported:
hermes-agent/tools/delegate_tool.py]
**Wrong behaviour:** Parent turn blocks for the full delegated work
(should be quick because of child session).
**Verify:**
```
sqlite3 data/friday.db "SELECT session_id FROM turns ORDER BY id DESC LIMIT 5;"
# → multiple session_ids (parent + child)
```

### T-15.3  Mixture of agents

**You say:** "Friday, think hard about: how many 3.14s fit in 47?"
**Expected:** Single best answer (~14).
**What it tests:** `core.mixture_of_agents.run`. [ported:
hermes-agent/tools/mixture_of_agents_tool.py]
**Wrong behaviour:** Two raw answers printed instead of a synthesised
one.
**Verify:**
```
grep "mixture_of_agents\|MoA" logs/friday.log | tail -3
```

---

## 16. Code execution

What this section validates: `evaluate_code` sandbox (P3.7).

### T-16.1  Python arithmetic

**You say:** "Friday, compute 47 times 3.14."
**Expected:** `147.58`.
**What it tests:** `evaluate_code(language='python')` sandbox.
[ported: hermes-agent/tools/code_execution_tool.py]
**Wrong behaviour:** LLM does the math in its head (often wrong).
**Verify:**
```
grep "evaluate_code" logs/friday.log | tail -3
```

### T-16.2  Bash one-liner

**You say:** "Friday, run bash: ls /tmp | wc -l."
**Expected:** Number printed.
**What it tests:** `evaluate_code(language='bash')` sandbox.
**Wrong behaviour:** Sandbox escape; or 5 s timeout on a trivial cmd.
**Verify:**
```
grep "evaluate_code.*bash" logs/friday.log | tail -2
```

### T-16.3  Timeout enforcement

**You say:** "Friday, run python: while True: pass."
**Expected:** Timeout after ≤5 s; truncated error surfaced.
**What it tests:** Sandbox timeout.
**Wrong behaviour:** Hangs the turn / FRIDAY process.
**Verify:**
```
grep "timeout\|evaluate_code" logs/friday.log | tail -3
```

### T-16.4  Default-off flag

**You say:** *(with `code_execution.enabled: false`)* "Friday, compute
47*3.14."
**Expected:** Refusal pointing at the config flag.
**What it tests:** Default-off gate.
**Wrong behaviour:** Runs anyway.
**Verify:**
```
grep "code_execution.*disabled\|enable" logs/friday.log | tail -2
```

---

## 17. MCP client

What this section validates: P3.8 stdio MCP bridge + per-server tool
registration.

### T-17.1  List MCP servers

**You say:** "Friday, list my MCP servers."
**Expected:** Each server name + state from
`config/mcp_servers.yaml`.
**What it tests:** `mcp_list_servers` meta-capability. [ported:
hermes-agent/tools/mcp_tool.py]
**Wrong behaviour:** "None" while the YAML lists servers.
**Verify:**
```
grep "mcp_list_servers\|StdioMCPBridge" logs/friday.log | tail -3
```

### T-17.2  Invoke a server tool

**You say:** "Friday, list my open GitHub issues." *(requires gh MCP
server configured)*
**Expected:** A short bullet list of issues.
**What it tests:** Dynamic capability `mcp_gh_list_issues`.
**Wrong behaviour:** Routed to chat fallback.
**Verify:**
```
grep "mcp_gh_" logs/friday.log | tail -3
```

### T-17.3  Server crash recovery

**You say:** *(after killing the MCP child process)* re-run T-17.2.
**Expected:** Clear failure message; FRIDAY does not hang.
**What it tests:** Bridge timeout + reconnect.
**Wrong behaviour:** Turn hangs > 30 s.
**Verify:**
```
grep "MCP.*timeout\|MCP.*reconnect" logs/friday.log | tail -2
```

---

## 18. Skills (P3.1 / P3.18 / P4)

What this section validates: SKILL.md loading, hot-reload, provenance,
usage stats.

### T-18.1  List loaded skills

**You say:** *(shell)*
**What it tests:** SkillLoader walks both `SKILL.md` and `SKILLS/*.md`.
**Wrong behaviour:** Count < 22 (8 plugin + 14 P4 sub-skills).
**Verify:**
```
python -c "from core.skill_loader import SkillLoader; print(len(SkillLoader().scan()))"
# → 22
```

### T-18.2  Provenance — "which skill answered that?"

**You say:** "Friday, which skill answered that?"
**Expected:** Name + source-path of the skill used in the previous
turn.
**What it tests:** `core.skills.provenance`.
**Wrong behaviour:** "I don't track that" or wrong skill.
**Verify:**
```
sqlite3 data/friday.db "SELECT event_type, payload FROM audit_events WHERE event_type='SKILL_USED' ORDER BY id DESC LIMIT 1;"
```

### T-18.3  Usage stats

**You say:** *(shell)*
**What it tests:** `core.skills.usage` counters surfaced by
`memory_admin inspect`.
**Wrong behaviour:** Counters not updating.
**Verify:**
```
python scripts/memory_admin.py inspect | grep -i skill
```

---

## 19. Safety & guardrails (P3.17)

What this section validates: URL safety, path traversal, website
policy, tool guardrails.

### T-19.1  Block private-IP exfil

**You say:** "Friday, fetch http://10.0.0.5/admin."
**Expected:** Refused; URL flagged as private-network.
**What it tests:** `core.safety.url_safety`. [ported:
hermes-agent/tools/url_safety.py]
**Wrong behaviour:** Fetched anyway.
**Verify:**
```
grep "url_safety" logs/friday.log | tail -2
```

### T-19.2  Path traversal block

**You say:** "Friday, read /etc/shadow."
**Expected:** "I can't read files outside your home directory."
**What it tests:** `core.safety.path_security`. [ported:
hermes-agent/tools/path_security.py]
**Wrong behaviour:** File contents returned.
**Verify:**
```
grep "path_security" logs/friday.log | tail -2
```

### T-19.3  Website policy block

**You say:** "Friday, fetch a URL on a blocked domain."
**Expected:** Refusal citing the policy.
**What it tests:** `core.safety.website_policy` +
`config/website_policy.yaml`.
**Wrong behaviour:** Fetched anyway.
**Verify:**
```
grep "website_policy" logs/friday.log | tail -2
```

### T-19.4  Tool guardrail layer

**You say:** Any tool call that should require approval.
**Expected:** Approval prompt before execution.
**What it tests:** `core.safety.tool_guardrails`.
**Wrong behaviour:** Tool runs without approval prompt.
**Verify:**
```
grep "tool_guardrails\|approval" logs/friday.log | tail -3
```

---

## 20. Long-running tasks (P3.16)

What this section validates: process registry, checkpointing,
interrupt.

### T-20.1  Register a long-running task

**You say:** Start a long-running scan or web crawl.
**Expected:** Entry appears in process registry; pid tracked.
**What it tests:** `core.runtime.process_registry`.
**Wrong behaviour:** PID not tracked; "stop" can't find it.
**Verify:**
```
ls data/checkpoints/ 2>/dev/null
```

### T-20.2  Mid-task "stop"

**You say:** "Friday, stop." while task is running.
**Expected:** Task terminates (SIGINT, escalates to SIGKILL after 3 s).
**What it tests:** `core.runtime.interrupt.cancel_current`.
**Wrong behaviour:** Task keeps running.
**Verify:**
```
ps -ef | grep -i nmap   # should not include the killed scan
```

### T-20.3  Checkpoint resume

**You say:** Begin a multi-step task, interrupt, then say "resume".
**Expected:** Task continues from the last checkpoint, not from
scratch.
**What it tests:** `core.runtime.checkpoint_manager`.
**Wrong behaviour:** Re-runs already-completed steps.
**Verify:**
```
ls -t data/checkpoints/ | head -1
```

---

## 21. Conversation compression (P3.4)

What this section validates: long-session behaviour stays under the
context window.

### T-21.1  60-turn synthetic transcript

**You say:** *(synthetic via test)* 60 alternating user/assistant turns
of moderate length.
**Expected:** `build_chat_messages` output ≤ 8K tokens.
**What it tests:** `core.context_compressor.ContextCompressor`.
[ported: hermes-agent/agent/conversation_compression.py]
**Wrong behaviour:** Token count above the model's context window.
**Verify:**
```
pytest tests/test_context_compressor.py::test_synthetic_60_turn_transcript_stays_under_8k_tokens -q
```

### T-21.2  Compressor wired in main path

**You say:** *(programmatic)*
**Expected:** `AssistantContext.context_compressor` is non-None after
`FridayApp.__init__`.
**What it tests:** Wiring in `app.py`.
**Wrong behaviour:** `None` — compressor never built.
**Verify:**
```
python -c "from core.app import FridayApp; a=FridayApp(); print(a.context_compressor is not None)"
```

---

## 22. Cross-session recall (P3.2 / P3.3 / P3.5 / P3.9)

What this section validates: FTS search, session summary, nudger,
scheduler routines.

### T-22.1  FTS search after a restart

**You say:** (turn 1, session A) "I love jazz."  → (close FRIDAY) →
(reopen) → "Friday, search my conversations for jazz."
**Expected:** Hit returned from the previous session.
**What it tests:** P3.2 FTS5 backfill + `MemoryStore.fts_search`.
**Wrong behaviour:** "I didn't find anything…".
**Verify:**
```
sqlite3 data/friday.db "SELECT count(*) FROM turns_fts;"
```

### T-22.2  Session summary recall

**You say:** *(after the auto-summary lands on shutdown)* "Friday,
what did we talk about last time?"
**Expected:** A short recap drawn from the latest `session_summary`
memory item.
**What it tests:** P3.3 `on_session_switch`.
**Wrong behaviour:** "I don't remember our last conversation."
**Verify:**
```
sqlite3 data/friday.db "SELECT substr(content,1,80) FROM memory_items WHERE memory_type='session_summary' ORDER BY created_at DESC LIMIT 1;"
```

### T-22.3  Nudger picks up a casual mention

**You say:** "Friday, I live in Nellore." (no "remember" verb)
**Expected:** Silent save; surfaces on the next "what do you know
about me?".
**What it tests:** P3.5 `MemoryNudger`.
**Wrong behaviour:** Not saved.
**Verify:**
```
sqlite3 data/friday.db "SELECT value FROM facts WHERE namespace='user_profile' AND key='location';"
```

### T-22.4  Scheduler fires routine

**You say:** Add a routine with `interval_seconds: 60` to
`config/routines.yaml`, restart FRIDAY.
**Expected:** The configured command appears in the log every 60 s.
**What it tests:** P3.9 `Scheduler.tick`. [ported:
hermes-agent/tools/cronjob_tools.py]
**Wrong behaviour:** No fires; or fires faster than the interval.
**Verify:**
```
grep "scheduler.*fired" logs/friday.log | tail -3
```

---

## 23. Modification log

| Date | Change |
|------|--------|
| 2026-06-01 | **Phase 0 + Phase 4 (launch hardening) — docs, CI, and templates.** No behaviour change; open-source-launch finalize. **Phase 0:** added `CHANGELOG.md` (Keep a Changelog; `Unreleased` + `0.1.0`); `.github/workflows/ci.yml` — a fast `lint-and-intent` job (ruff + the intent eval gate `scripts/diagnostics/intent_eval.py` + `tests/test_intent_eval.py`/`test_intent_conflicts.py`) gating a full `pytest` matrix (ubuntu + windows × py 3.10–3.13, `QT_QPA_PLATFORM=offscreen`, PortAudio installed on Linux); `.github/ISSUE_TEMPLATE/` (phrasing-first bug report + feature request + `config.yml` contact links) and `.github/PULL_REQUEST_TEMPLATE.md` mirroring CONTRIBUTING's Definition of done. **Link fix:** README linked `docs/ARCHITECTURE.md` (uppercase) but only `docs/architecture.md` was tracked — broken on case-sensitive filesystems; renamed via `git mv` to the uppercase canonical name and updated the one lowercase reference in `SETUP_GUIDE_WINDOWS.md`. (`CODE_OF_CONDUCT.md` left as-is per user request.) **Phase 4:** prepended a "Launch architecture overview" to `docs/ARCHITECTURE.md` (turn lifecycle + the 5-layer routing pipeline with its confidence-band table + the workflow state-machine diagram for the confirmation/disambiguation/slot-fill guards); new `docs/intent_recognition.md` (the 5 layers, the confidence bands and thresholds, the eval/conflict gates, and the how-to-add-an-intent checklist); documented the Phase 2–3 `routing.*` confidence + layer/guard keys, the `code_execution` section, and `file_index.initial_delay_s` in `docs/config_reference.md` (and corrected `routing.chat_max_tokens` default 2048 → 512). Docs/CI only; no tests affected. **Verify:** `python scripts/diagnostics/intent_eval.py` (gate still green) and check the rendered links in README / `docs/ARCHITECTURE.md`. |
| 2026-05-31 | **Phase 3 checkpoint 4: reusable disambiguation / "which one did you mean?" pick guard.** Closes Phase 3. New `core/workflows/disambiguation.py:DisambiguationGuard` — the sibling of the checkpoint-2 `ConfirmationGuard`, same handler-arming shape. A handler that resolves a request to >1 candidate calls `guard.arm(action=…, arg_name=…, candidates=[…], base_args=…)` (unless `args["_picked"]`), persisting `session_state.pending_pick` and returning a numbered list. New `IntentRecognizer._parse_pending_pick` interceptor (2nd in the parser chain) routes a **selection-shaped** reply ("2", "the second one", "option 3", "last", or a unique candidate label) → `pick_pending_candidate` and a clear cancel/never-mind/none → `cancel_pending_pick`; anything that doesn't look like a selection **falls through** to normal routing (the user is never trapped). `pick()` fills the chosen value + `_picked=True` and re-dispatches the stored action via `CapabilityExecutor`. Shared `parse_selection`/`looks_like_selection` are the single source of truth for interceptor + guard. **Wired:** `search_indexed_files` (>1 match → pick → `open_file`), `launch_app` (ambiguous spoken name like "chrom" when Chrome+Chromium are both installed → pick via new `app_launcher.find_app_candidates`, detected on the raw token since `extract_app_names` collapses to one canonical), `query_document` (no path + a named doc matching several indexed files → file-picker via `_doc_name_hint`; single match auto-selects; generic "summarize the document" still gives the honest no-path error). `pick_pending_candidate`/`cancel_pending_pick` + `app.disambiguation_guard` registered in `core/app.py`; config gate `routing.disambiguate` (default true). **You say:** "find file report" → "I found 3 files matching 'report'. Which one should I open?" → "the second one" opens it; "open chrom" → "There's more than one app like 'chrom'. Which one? 1. chrome 2. chromium" → "1" launches Chrome. **Cross-platform:** pure-Python session-state + regex, no `platform.system()` branch. **Tests:** `tests/test_disambiguation_guard.py` + `tests/test_pending_pick_intent.py` = 57 new, all pass; intent conflict detector + `test_intent_eval` corpus green; full-suite failures unchanged from the pre-existing Windows-env set (3 routing snapshots launch_firefox/volume_up_steps/multi_open_then_time + audio/PIL/tts/workflow-timer/hud), zero in any touched area. **Verify:** `python -m pytest tests/test_disambiguation_guard.py tests/test_pending_pick_intent.py -q`. |
| 2026-05-31 | **Launch-hardening docs cleanup (`docs/tools.md` + `docs/architecture.md`).** No behaviour change — open-source-launch polish of two reference docs. **(1)** Removed all 181 hardcoded `/home/tricky/Friday_Linux` absolute paths (leaked a personal username + broke every `file:///` link for anyone cloning): tools.md markdown links → repo-relative (`../core/...`), architecture.md `**Path:**` lines → repo-relative, the "located at" prose → "repository root". **(2)** Fixed stale architecture.md storage section — §15, the repo-layout tree, the §27 module catalogue, and the bootstrap mermaid node all still described `core/context_store.py` as an 8-table god class; rewritten to reflect the Track 5.1 decomposition into the `core/stores/` domain stores (`session`/`memory`/`knowledge_graph`/`audit`/`goal`/`workflow`/`intent_learning`/`file_index`/`app_index`) with `ContextStore` as the transitional facade, and a note that `notes`/`calendar_events` (reminders, `type='reminder'`) live in TaskManager's own SQLite while calendar events are Google-owned. **(3)** Reconciled tools.md against the live registry + `data/tool_catalog.yaml`: all 109 listed tools verified to map to a real registered capability (0 phantoms); added a snapshot caveat + pointer to `tool_catalog.yaml` as the canonical user-facing list. **Known gap (not fixed here):** tools.md is missing ~34 newer catalog tools (brightness, lock/unlock, the web-search + research-source suite, Home Assistant, `evaluate_code`, …) — it is a point-in-time snapshot best regenerated from a live instance (needs the model runtime, not available on this Windows dev box). Docs-only; no tests affected. |
| 2026-05-31 | **Phase 3 checkpoint 3: shared NL-datetime extractor, expanded destructive guards, goals duplicate-method fix.** **(1) Shared datetime extractor** — `core/planning/slot_extractors.py:extract_datetime(text, now=)` returns ISO-8601 for the common NL shapes (relative "in 15 minutes"/"in an hour", today/tomorrow/weekday + clock, bare "at 3pm"/"15:30"/"noon"/"midnight"; date-only → 09:00; passed bare time → next day). Registered in the SlotFiller named registry as `datetime` for template/`SlotSpec` consumers; the production reminder path keeps its richer in-handler parser. 16 tests (`tests/test_datetime_extractor.py`). **(2) Expanded confirm-before-destructive guard** to `shutdown_assistant` and `forget_memory` (forget arms with the resolved key in the preview) — same `ConfirmationGuard` + `_parse_pending_destructive` mechanism as T-4.7b; 6 handler tests (`tests/test_destructive_guard_handlers.py`). T-4.7b guarded-set extended. **(3) Latent bug fix:** `modules/goals/plugin.py` defined `handle_update` **twice** — the first (no title disambiguation, silently picked `matches[0]`) was dead code shadowed by the second (with `_disambiguate_or_return`). Removed the dead duplicate so `update_goal` has a single source of truth that disambiguates ambiguous titles. An AST sweep for duplicate methods across `core/`+`modules/` found no others (the 4 router + 1 turn_context "dups" are intentional `@property`/setter pairs). **Cross-platform:** pure-Python, no platform branch. 117 pass across all affected suites. |
| 2026-05-31 | **Phase 3 (launch hardening) checkpoints 1–2: slot-filling foundation + confirm-before-destructive guard.** **(1) Track 2.4 — unified slot-filling.** New `core/planning/slot_filling.py` (`SlotSpec` + `SlotFiller`) gives Phase-3 workflows one front door over the three pre-existing slot mechanisms — deterministic `slot_extractors`, template `ask:`/`slot:` steps, and `QwenPlanner.fill_slots`. Cheapest-first precedence (caller-known → extractor → LLM only for still-missing *required* slots → optional default); pure + offline-safe (`planner=None` degrades to deterministic-only); named-extractor registry (`register_extractor`/`get_extractor`, seeded with `quoted_content`); alias normalization; and `specs_from_template()` to bridge a YAML template's ask-steps. 17 tests (`tests/test_slot_filling.py`). **(2) Reusable confirm-before-destructive guard.** New `core/workflows/confirmation.py:ConfirmationGuard` generalizes the proven memory-wipe two-step into one mechanism: a destructive handler calls `guard.arm(action, args, preview)` once its target is resolved (so the preview is specific) unless `args["_confirmed"]` is set; the new `IntentRecognizer._parse_pending_destructive` interceptor (first in the parser chain) routes the next turn to `confirm_pending_action` (affirmation) or `cancel_pending_action` (anything else); `confirm` re-dispatches the stored capability with `_confirmed=True`. Wired into `lock_screen`, `delete_goal` (composes with its "which goal?" disambiguation), `cancel_calendar_event`, `ha_turn_on`/`ha_turn_off`. The explicit `/lock` slash stays immediate. Config gate `routing.confirm_destructive` (default true). **(3) Memory-wipe preview** — `wipe_memory_init` now lists real counts (N profile facts, M memories, K goals) before confirming. New T-4.7b; T-1.5 + T-4.7 amended. Tests: `tests/test_slot_filling.py` (17), `tests/test_confirmation_guard.py` (13), `tests/test_pending_destructive_intent.py` (13); updated MagicMock-app assumptions in `tests/test_os_lock.py` + `tests/test_smart_home.py` (added arm-first tests). **Cross-platform:** pure-Python session-state + regex logic, no `platform.system()` branch — Linux identical. The 3 `test_workflow_orchestration.py` calendar/reminder failures on this Windows box are pre-existing (Windows timer `OverflowError`), confirmed via `git stash`. |
| 2026-05-29 | **Media control resilient to a dying browser tab/context (live session 13:11–13:21).** The YouTube tab/context kept dying on its own after a couple of pause/play cycles (`Page.evaluate: Target page, context or browser has been closed`), and the recovery was inconsistent: the keyboard-fallback closed-error branch dead-ended on "The youtube tab was closed. Ask me to open it again." even though the outer `except` *did* auto-replay when a query was present — so a bare "play"/"resume" got the dead-end. Investigation: the death is environmental (Chrome on the isolated `.cache/friday/browser-profile/chrome` profile on Windows); `page.is_closed()` also lied (returned False) when it was the whole context that died, so the code failed *inside* `page.evaluate` instead of recovering. Fixes in `modules/browser_automation/service.py`: (1) remember the last started media (`_last_media`) so recovery works for a bare "play" with no query; (2) detect a dead context up front via `_context_is_usable()` (not just `page.is_closed()`) and route to the `page is None` relaunch path; (3) `_set_media_state` re-raises closed-target errors instead of swallowing them into a doomed keyboard fallback; (4) unify all closed-target handling in `_closed_target_response` → `_relaunch_last_media` (transparent relaunch+replay for play/resume; honest "tab closed" for pause/seek — no phantom replay); (5) added `context.on("close")` / `browser.on("disconnected")` diagnostic logging to pin down WHEN/why the context dies on the next live run. New T-3.3a. 4 new tests in `tests/test_browser_automation_service.py` (dead-tab resume relaunch, bare-play from memory, pause-no-phantom-replay, empty-memory guard); 12/15 pass (the 3 failures are pre-existing profile-clone env tests, confirmed unchanged via `git stash`). |
| 2026-05-29 | **Focus-stop misroute, Windows focus honesty, and stuck Windows lock (live session 13:15–13:21).** Three bugs. **(1) "stop the focus session" cancelled the media session.** While a `browser_media` workflow was active, "stop the focus session" starts with "stop", so `_is_workflow_cancel` matched and `continue_active` cancelled browser_media (`Cancelled active workflow 'browser_media'`, "Okay, cancelled, sir.") — leaving the focus timer running AND "forgetting" the media session (a later "play" fell to chat: "Play / No_think 🎬"). Fix: `WorkflowOrchestrator._targets_other_workflow(user_text, active_name)` — if the cancel-shaped utterance would START a *different* registered workflow (here `focus_mode.should_start` matches its stop pattern), it's a targeted command, not a bare cancel, so we fall through to intent routing → `end_focus_session`. Bare "stop"/"cancel" still cancels the active workflow; "cancel the reminder" with a reminder active still cancels it (no other workflow starts on it). **(2) Focus mode dishonest on Windows.** `gsettings` is Linux-only, so on Windows focus claimed "Notifications are muted" (false) and logged a WARNING every turn. `FocusModeWorkflow._notifications_supported()` now gates the start message ("Media is paused." on Windows) and the missing-gsettings log is DEBUG off-Linux. Timer + media-pause unaffected. **(3) Windows lock state stuck after manual unlock.** `LockStateMonitor._query_os_locked` returned None on Windows, so after a FRIDAY `LockWorkStation` lock the gate never cleared — "start a memo" after unlocking still said "Unlock the screen first." Added `_windows_locked()` (polls `OpenInputDesktop`: locked = secure desktop, can't open / name ≠ "Default") + a `_LOCK_GRACE_SECONDS`=6s window so the first poll can't clear a just-issued lock before the secure desktop engages. Verified the probe returns False (unlocked) on the live Windows box. T-4.7 + T-4.16 updated. 15 new/again-green tests (`tests/test_focus_and_lock_fixes.py` 9 + `tests/test_focus_session_media.py` 6); `test_workflow_orchestration.py` failure set byte-identical to baseline (12 pre-existing env failures, confirmed via `git stash` — zero new regressions). |
| 2026-05-29 | **Latency + startup-contention fixes (live session 13:10–13:14).** Two user-reported issues: slow inter-message latency and slow startup. **(1) Chat reply latency:** `routing.chat_max_tokens` was **2048** — the 0.8B chat model could spend ~23s (observed) generating a long reply on CPU. Cut to **512** (code default), which covers conversational/doc-summary replies (~150 tokens in the log) and bounds worst-case generation ~4x. Research synthesis uses its own budget, unaffected. **(2) File-indexer DB-lock contention:** `FileIndexStore` shares `friday.db` with the turn/audit stores, but `bulk_upsert` committed all ~200k rows in ONE transaction, holding the SQLite write lock for seconds so every turn's DB write stalled behind it. Rewrote `bulk_upsert` to commit in 2000-row batches (`_flush_batch`, each its own short transaction → lock released between chunks); `FileIndexer.scan_once` now streams to the store in 2000-row batches during the walk (bounded memory + interleaved commits) and honours `_stop_event` mid-walk. **(3) Startup contention:** the initial filesystem walk (~2.5 min in the log) started immediately in `initialize()`, competing with model loading + first turns. `start_background_scan(initial_delay=…)` now holds it back (interruptible) and `FridayApp._start_file_indexer` passes `file_index.initial_delay_s` (default 20s). The index persists across runs, so delaying the refresh has no functional downside. New T-10.10; T-4.5 perf note added. New test `test_bulk_upsert_commits_across_batch_boundaries`; file_indexer + store suites green (21 pass, 1 pre-existing Windows-only `delete_under` test failure that hardcodes POSIX paths — unrelated, fails without this change too). |
| 2026-05-29 | **Attached-document questions ignored the session RAG (live session 11:11).** A PDF was loaded into the in-memory session RAG (`[session_rag] Loaded 'Resume.pdf' — 7 chunks indexed`), but "[Re: Resume.pdf] What is there in the document?" routed to `read_file` → "Which file would you like me to read?". Three compounding causes, all fixed: **(1)** the phrasing matches `_KNOWLEDGE_Q_RE` (the "what is X in Y" branch), so `IntentRecognizer.plan()` short-circuited to `[]` and the turn fell to the lexical router, which grabbed `read_file`. **(2)** Nothing routed SessionRAG docs anywhere — `_parse_query_document` only checks the `active_document` reference (the document_intel/ChromaDB path), which SessionRAG never sets. **(3)** `SessionRAG.retrieve` returned `[]` when BM25 matched no terms (a generic "what's in the document?" has no content words that appear in a resume), so even the chat path's excerpt injection was empty → generic non-answer. **Fixes:** new `IntentRecognizer._session_rag_doc_action` (+ `_is_session_doc_question` and the `_RE_PREFIX_RE`/`_DOC_NOUN_RE`/`_DOC_INTENT_RE`/`_DOC_VERB_PHRASE_RE` matchers) intercepts doc questions at the TOP of `plan()` (before the knowledge-question bail) and routes them to `llm_chat` when a session document is active — so `assistant_context.build_chat_messages` injects the excerpts. It's gated on an active SessionRAG + an explicit doc reference (the GUI's `[Re: <name>]` attach prefix, a doc noun + interrogative, or a doc-referential phrase like "what does it say"), so "what time is it" / "open calculator" are never poached. `LLMChatPlugin.handle_chat` now skips its preflight tool-reroute while a doc is loaded (otherwise it would bounce the question back to `read_file`). `SessionRAG.retrieve` falls back to the leading chunks when keyword scoring finds nothing. New T-2.4b. 23 new tests across `tests/test_session_rag.py` (retrieval/fallback) and `tests/test_session_rag_doc_intent.py` (routing + negatives + no-doc/no-chat-capability fall-through); intent/context-resolver suites green (170 pass across touched suites). |
| 2026-05-29 | **Re-open commands wired into IntentRecognizer (follow-up to the T-3.3b fix).** The earlier fix handled re-open phrases only via the browser_media workflow's `can_continue` (v2 turn path, checked before intent classification). Per CLAUDE.md's "every tool needs a robust deterministic pattern" rule, added the same coverage to `IntentRecognizer._parse_browser_media` as the safety net for the v1 turn path (which has NO workflow hook — see the comment at `_parse_pending_selection`). New public `is_reopen_media_command(text)` in `media_helpers.py` shares the single `_REOPEN_MEDIA_RE` matcher (no duplicated pattern). The new branch runs at the top of `_parse_browser_media`, gated on an active `browser_media` workflow, and routes "open it" / "open it again" / "reopen" / "play it again" / "resume that" / "open the video again" to `play_youtube` / `play_youtube_music` (with the remembered query) or `open_browser_url` (no query). Placed before the `play_video`/`bare_play` regexes so "play it again" isn't parsed with a literal query of "it again". T-3.3b updated. 11 new tests in `tests/test_browser_media_reopen_intent.py` (incl. negatives: no active workflow → not media; "open my budget spreadsheet" → not media); media-helper suite still 40/40. |
| 2026-05-29 | **"open it" after a closed media tab routed to open_file (live session 11:05–11:06).** A video was playing; the YouTube tab closed; FRIDAY correctly said "The youtube tab was closed. Ask me to open it again." The user's "open it" then routed to `open_file` ("Which file would you like me to open?") because `is_likely_media_command` requires a media KEYWORD and "open it" has none — so the active `browser_media` workflow's `can_continue` returned False and the turn fell through to intent classification. Fix in `modules/browser_automation/media_helpers.py`: new `_REOPEN_MEDIA_RE` matches re-open continuations ("open it", "open it again", "reopen", "play it again", "resume that", "open the video again") by pronoun/media-noun reference. `is_likely_media_command` returns True on a match (only ever consulted when a media workflow is active, so it can't hijack a plain "open my file"), and `parse_media_intent` maps it to `play` with the remembered `query`/`platform` (replays the same video) or `open` when no query was captured — placed before the bare-`^play` fresh-search guard so "play it again" isn't dropped. New T-3.3b. 11 new tests in `tests/test_batch2_routing.py` (40/40); no new failures in `test_workflow_orchestration.py` (12 pre-existing env failures unchanged). |
| 2026-05-29 | **"Bye" swallowed as a filename during a pending file prompt (live session 11:06 + 11:11).** After FRIDAY asked "Which file would you like me to open/read?" (`pending_file_name_request` set) or presented a candidate list, the next utterance "bye" was intercepted by `IntentRecognizer._parse_pending_selection` (which runs BEFORE `_parse_exit` in the clause chain) and treated as the *filename* — so it searched for "bye", timed out, and matched the `*goodbye*` test files. Fix: new `_EXIT_ESCAPE_RE` (mirrors `_parse_exit`'s vocabulary: bye/goodbye/exit/quit/stop assistant/shut down friday) checked at the top of `_parse_pending_selection`; on a whole-clause match it calls `dialog_state.reset_pending(...)` and returns None so the exit parser routes to `shutdown_assistant`. Narrow whole-clause match keeps real filenames like "exit_plan.txt" filling the slot. New T-2.5b. 26 new tests in `tests/test_exit_during_pending_intent.py`; environment/clarify/cancel intent suites green (93/93). |
| 2026-05-23 | **Full rewrite (Track 5.3 P2.4).** Replaced the 5,524-line v1 guide with a flat command-first structure (23 sections, ~100 test cases). Old guide archived at `docs/archive/testing_guide_v1_2026-05-22.md`. All P0–P4 surfaces covered. Hermes-ported tests tagged `[ported: hermes-agent/…]`. CLAUDE.md "update testing guide in the same response as code" rule is now back in effect. |
| 2026-05-23 | **Track 6 opened — environmental awareness.** Added T-4.4 (`refresh_app_index`), T-4.5 (`refresh_file_index`), T-4.6 (`search_indexed_files`) covering the new `AppIndexStore` + `FileIndexStore` + `FileIndexer` background service. `SystemCapabilities` extended with Windows Registry `Uninstall` scan, `.lnk` target resolution, and `.desktop` `Categories=` parsing. STATUS.md freeze closed; see `plan/2026-05-23_11-07-43_plan.md`. |
| 2026-05-23 | **Telegram followup: slash commands now run + in-chat thinking bubble.** Fixed the pre-Track-6.3 `if text.startswith('/')` block in `TelegramInbound._dispatch` that silently dropped every slash except `/start`. Every slash now forwards to `process_input`; `@BotUsername` suffixes (Telegram group-chat convention) are stripped first. Added `TelegramChannel.send_capturing_id`, `edit_message`, `delete_message`. `_process` now sends a `💭 _thinking…_` placeholder bubble into the chat, captures its message_id, and `editMessageText`'s it into the real response when ready — the user sees a single bubble morph instead of two messages. Empty response → placeholder deleted so nothing stale lingers. New T-9.7 (slash routing) + T-9.8 (in-chat thinking) + 3 new tests. Total suite: 1677 pass / 1 pre-existing fail / 0 regressions. |
| 2026-05-23 | **Intent recognition coverage audit + Telegram /-autocomplete.** Audited the 15:35 session log: "Friday rescan my apps" routed to chat-mode because no intent pattern existed for the Track 6 / 6.3 capabilities. Added `_parse_environment` (`refresh_app_index`, `refresh_file_index`, `search_indexed_files`), `_parse_brightness` (with cardinal-number handling: "set brightness to fifty" → 50), and `_parse_screen_lock` (`lock_screen`, `unlock_screen` with PIN extraction) to `core/intent_recognizer.py`. `search_indexed_files` regex deliberately tightened to require either "called X" or a `name.ext` filename so it doesn't poach from `search_file`. `TelegramChannel.register_commands` POSTs to `setMyCommands` on `TelegramInbound.start()`, driving Telegram's `/`-autocomplete from `core.slash_commands.REGISTRY`. New T-4.3b (intent coverage), T-9.6 (autocomplete) + 46 new tests in `tests/test_environment_intent.py`. |
| 2026-05-23 | **Bug-fix sweep #2 from 15:35 session log.** (1) Embedding-router warmup moved from `initialize()` to right after CommandRouter creation in `__init__` — earlier head-start kills the "Loading weights 199/199" tqdm bar from interleaving with the first user turn. (2) Real `set_brightness` capability (`modules/system_control/brightness.py`) — brightnessctl → light → /sys chain; honest failure mode replaces LLMChat's fabricated "Brightness set to 60." (3) `_handle_show_memories` rewritten to return a natural paragraph instead of a bullet list. (4) `_parse_memory_query` regex extended to catch "what else / tell me more / anything else / tell me everything" — these were falling into chat mode and getting echoed back. (5) Persona prompt softened: "list verbatim" replaced with "write a short, natural paragraph (1-3 sentences) that weaves USER_FACTS in" + "never claim to have completed an action you don't actually have a tool for". (6) Test updates: T-7.4 rewritten to pin v2 behaviour; `test_show_memories_namespaces.py` updated to assert paragraph form; `test_context_compressor.py` budget bumped to 2048 (system prompt grew). |
| 2026-05-23 | **Track 6.3 — input prefixes + screen lock.** New `core/screen_lock.py` (env-var PIN, default-unlocked, allowlist of capabilities for the locked state). New `core/slash_commands.py` with /new /clear /research /web /screenshot /voice /lock /unlock /help. New `core/shell_prefix.py` running `!cmd` lines via `subprocess.run(shell=True)` with 30s cap. Lock gate added to `CapabilityExecutor.execute`. Telegram now sends `sendChatAction=typing` every 4s while a turn runs. Added T-4.7 (lock/unlock), T-4.8 (! shell), T-4.9 (Telegram typing). 28 new tests across `tests/test_screen_lock.py`, `tests/test_slash_commands.py`, `tests/test_shell_prefix.py`. |
| 2026-05-23 | **Bug-fix sweep from live session 2026-05-23 14:54.** Added T-4.1b (honest screenshot errors — no more false "needs python3-gi"; cut worst-case timeout from 39s → ~10s by shrinking Mutter ScreenCast timeout 15→5s and portal 15→8s). Added T-7.4 (assistant does not speak AS the user — pins the role guard added to `assistant_identity`). Added T-7.5 + T-9.5 (markdown bold/italic/code render in GUI bubble + Telegram via inline `_markdown_inline_to_html` / `_markdown_to_telegram_html` helpers — previously `**bold**` leaked through as literal asterisks). Added T-10.8 (embed-router warmup daemon thread spawned from `initialize()` — eliminates the 8.5s first-turn HF model load that hit users on a cold cache). |
| 2026-05-23 | **Identity-prompt leak fix (session 17:00 + 17:41).** "Who are you?" was routing to chat and the Qwen 0.8B model was reciting the system prompt verbatim ("…never describe yourself using facts from the USER_FACTS block."). Added a new `identify_self` capability in `modules/greeter/extension.py` returning a canned identity line, and a `_parse_identity` parser in `core/intent_recognizer.py` covering "who/what are you", "what's your name", "introduce/describe yourself", "tell me about yourself", "are you an AI/bot/human/real", "state your name", "identify yourself". Inserted in the parser chain just before `_parse_greeting` so it never poaches "who am I" (that still routes to `recall_personal_fact`). Rewrote T-7.1 to pin the deterministic path. New `tests/test_identity_intent.py` (25 tests, all pass). |
| 2026-05-23 | **Interactive shell via `>` follow-up (session 16:20 sudo failure).** Old `!cmd` used `subprocess.run` with no stdin → `sudo apt install brightnessctl` hung at the password prompt and timed out at 30s, with no way to enter the password. Rewrote `core/shell_prefix.py` around `pty.openpty()` + a persistent `_ShellSession`. After 1.5s of stdout silence the command is left alive and FRIDAY replies with the partial output and an "awaiting input" hint (prompt-sniffing detects `Password:`, `[Y/n]`, `?` endings). The user's next `> <text>` is piped to the child's stdin; any **non-`>`** reply cancels the session BEFORE it can fall through to chat — so a password or "y" can't leak to the LLM. New T-4.8b. New tests: `test_is_shell_followup_recognises_gt_prefix`, `test_interactive_session_captures_stdin_via_followup`, `test_cancel_active_session_kills_long_running`, `test_feed_followup_without_active_session_is_safe`, `test_new_run_supersedes_old_session`. Existing `timeout=` kwarg preserved for sync one-shots so the legacy 7 tests still pass (12/12 green). |
| 2026-05-23 | **Browser multi-tab kill + phantom-resume fix.** Two related bugs from the 16:40+ session log: (1) "Google for capital of france" while YouTube was playing repurposed the YouTube tab — `_get_page` blindly returned `context.pages[0]` and `goto(google_url)` then killed playback. (2) After the user closed the YouTube tab externally, "play" reported "Resumed youtube." even though no tab existed. Fix in `modules/browser_automation/service.py`: new `_find_reusable_page` helper skips pages already claimed by another platform, opens a new tab instead. `_do_browser_media_control` now checks `page.is_closed()` up front and refuses on play/resume when there's no tab AND no query, rather than emitting a phantom-success line. New tests: `test_get_page_does_not_steal_other_platform_tab`, `test_get_page_reuses_blank_first_page_when_no_platform_claimed`, `test_browser_media_play_refuses_when_no_active_tab_and_no_query`, `test_browser_media_play_with_closed_tab_and_query_relaunches` (11/11 green in `test_browser_automation_service.py`). |
| 2026-05-23 | **Hermes web tools (web_extract / web_crawl) wired to intent recogniser.** Three live-session bugs: (a) "Friday, fetch https://docs.python.org/3/library/subprocess.htm" routed to chat and the 0.8B model paraphrased the request without ever fetching; (b) "crawl https://news.ycombinator.com and find ML stories" was clause-split into `["crawl URL", "find ML stories"]` and the second half was mis-routed by the planner to `search_indexed_files`; (c) routing collision between `search_google` (browser_automation) and `web_search` (DDG/Hermes) was implicit and depended on the LLM. Fix: new `_parse_web_url_action` in `core/intent_recognizer.py` (URL-required, never poaches no-URL phrasings); split-guard added in `_split_on_action_and` for `(?:crawl|scrape|fetch|extract|download).*https?://.*and`. Browser-driven `search_google` keeps "search the web for X" / "google for X" phrasing (explicit verb test in T-12.1). Updated T-12.2 + T-12.3 to pin `source=intent` routing. New `tests/test_web_intent.py` (18/18 green); existing `test_environment_intent.py`, `test_identity_intent.py`, `test_wipe_memory_intent.py`, `test_remember_intent.py` all still pass (112/112 across the intent suite). |
| 2026-05-23 | **Intent coverage audit — round 2 (live session log).** Three additional gaps from the 16:12–16:34 timeline: (a) "Forget my love for coding" routed to chat because `_parse_memory_query` referenced `delete_memory` (wrong tool name — the capability is `forget_memory`) and the regex didn't extract a key. New `_extract_forget_target` maps phrasings ("forget my love for X", "forget that I love X", "forget my hometown", "forget where I live", "forget my job") to canonical keys (`loves`/`likes`/`dislikes`/`preferences`/`location`/`role`/etc.) — with anti-poach guards for "forget it"/"forget everything". (b) "What's on my list today?" / "what do I have today" / "today's agenda" now route to `get_calendar_today`; "this week's agenda" → `get_calendar_week`; "show my reminders" → `list_reminders` (extension of `_parse_reminder`). (c) "scan 192.168.1.50 for open ports" / "nmap 192.168.1.1" / "ping sweep 10.0.0.0/24" now route to the lab-mode security capabilities via a new `_parse_security` parser (still gated by `authorized_scopes` inside the handler — intent routing never bypasses the safety check). New tests: `tests/test_forget_memory_intent.py` (18 cases) + `tests/test_audit_intent_2026_05_23.py` (25 cases). Full intent suite now 158/158 green. |
| 2026-05-23 | **`config.yaml` audit + new `docs/config_reference.md`.** Grepped every `config.get(...)` call in `core/` and `modules/`; surfaced three keys that the code read with hard-coded fallbacks but had no entry in `config.yaml` (so users couldn't tune them without editing source): `routing.qwen_planner_timeout_ms` (12000), `routing.qwen_planner_max_tokens` (512), `routing.qwen_planner_top_p` (0.2), and `llm.max_context_tokens` (4096). Added all four to `config.yaml`. New `docs/config_reference.md` documents every section (`app`, `conversation`, `capabilities`, `personas`, `models`, `routing`, `llm`, `gui`, `voice`, `modules`, `skills`, `browser_automation`, `document_intel`, `vision`, `memory`, `world_monitor`, `awareness`, `security`) with type / default / call-site / effect for each key, plus an "Adding a new key" checklist that includes "update this doc + testing guide" — keeps the doc from rotting. |
| 2026-05-24 | **DDG redirect-wrap + laggy Qt exit fixes (live session 17:58).** **(1)** `/web` and both research modes were emitting `https://duckduckgo.com/l/?uddg=…&rut=…` tracking-redirect wrappers. These (a) don't open in browsers without manual decoding and (b) 400 when trafilatura tries to fetch them — so even after the `_ddg_search` keyword fix in the previous row, every research mode still lost every web hit because the URLs were unfetchable. New `_unwrap_ddg_redirect(url)` in `modules/web/plugin.py` decodes the `uddg` querystring param into the real destination URL; called inside `_ddg_search` for both the `duckduckgo-search` library path and the HTML-scrape fallback. Now `/web quantum computing encryption` returns `https://thequantuminsider.com/...` instead of the `duckduckgo.com/l/?uddg=...` blob, and research's newspaper_extract step actually fetches. **(2)** Qt force-quit dialog on exit + laggy close — `closeEvent → app.shutdown()` was running `_snapshot_session_on_exit` (an LLM call, 5–30s) and `lifecycle.stop_all()` (serial per-plugin stop) inside the UI's blocking close path. Rewrote `FridayApp.shutdown(deadline_s=…)` to run snapshot + lifecycle stop in daemon threads, each with its own deadline (snapshot=1.5s, total=2.5s). `gui/hud.closeEvent` now: (a) calls bounded shutdown, (b) accepts the event, (c) schedules `os._exit(0)` via `QTimer.singleShot(800ms)` as a hard backstop so a stuck daemon thread or pending Playwright handshake can't keep Qt's force-quit dialog open. New `tests/test_shutdown_and_ddg_unwrap.py` (10 cases) — 4 verify shutdown returns within its deadline even when snapshot/lifecycle hangs 10s, 4 verify DDG unwrap on real wrapped URLs and skips non-wrapped ones, idempotency check, happy-path latency check (< 0.5s). 670/670 across all touched suites. |
| 2026-05-24 | **`_ddg_search` keyword regression — quick + deep both lost every web hit.** Live session 17:42: `quick research Tamil Nadu …` returned "hit a snag, sir: No usable sources"; deep mode for "quantum computing encryption" returned only 3 arxiv papers (Wikipedia and DDG both silent). Log line: `[quick] ddg search failed: _ddg_search() got an unexpected keyword argument 'limit'`. The real function signature is `_ddg_search(query, max_results)` — positional. My Step-5b call site was passing `limit=` which raised TypeError. The broad `except` swallowed it and returned `[]`, so the failure was invisible from the user's side except for "no sources". Fixed `_collect_web_urls` in `modules/research_agent/quick.py` to call `_ddg_search(topic, limit)` positionally. Test stubs that used `limit=` were masking the bug; rewrote them with `max_results=` to match the real signature. **New regression test `test_collect_web_urls_calls_ddg_with_correct_signature` calls a stub that mimics the REAL positional signature — if the call site regresses to `limit=` again, the stub raises TypeError and the test catches it (no broad-except masking). 114/114 across the four research test files; 658/658 across all touched suites.** |
| 2026-05-24 | **Research mode regex regression — connector word made optional.** Live session 17:35: "quick research Tamil Nadu 2026 Political Landscape" and "Deep Dive Quantum Computing advancments about encryption" both fell through to chat and the small model hallucinated answers (BJP/AAP nonsense for the first; refusal for the second). Root cause: the Step 5d regexes used the shape `verb\s+(?:on|about|for|of)?\s+(.+)`, which required a SECOND whitespace after the optional connector. When no connector was present, the second `\s+` couldn't match. Rewrote every quick/deep pattern as `verb(?:\s+(?:connectors))?\s+(.+)` so the trailing `\s+` consumes the verb-topic separator whether or not the connector word was used. 16 new tests in `tests/test_research_mode_detection.py` cover both live phrasings plus 13 other no-connector and connector variants. **Also fixed**: catalog cross-check in `core/app.py` was reading only `router._tools_by_name`, missing the 17 capabilities registered via `capability_registry` — now passes the UNION so the false "stale entries" warnings stop. Catalog duplicate `list_calendar_events` removed. 3 missing news capabilities added (`get_company_news`, `get_security_news`, `get_startup_news`). Catalog now has 132 entries, boot warnings clear. **657/657 across all touched suites.** |
| 2026-05-24 | **Step 5e — research-agent rebuild docs + integration tests.** Closes the Step-5 series with 7 new per-source-tool T-entries (T-12.8 wikipedia / T-12.9 arxiv / T-12.10 hackernews / T-12.11 pubmed / T-12.12 newspaper / T-12.13 yfinance / T-12.14 pdf_text_search). New `tests/test_research_e2e.py` (5 cases) stitches the islands: `IntentRecognizer.plan("tldr GPT history")` → `research_topic` capability handler → `research_planner.begin(mode="quick")` → `service.run_research(mode="quick")` → `quick.run_quick_research` → file on disk. Same E2E for deep mode. Plugin-handler short-circuit test proves the explicit-mode fast path doesn't go through the "Any specific angle?" prompt. Catalog cross-check verifies all 10 Step-5 capabilities (9 source tools + research_topic) have catalog entries with example_phrases. `research_status.md` finalised. **707 / 707 across the full research + intent + plumbing test surface.** Step 5 series total: ~1100 lines of new application code (`modules/sources/` plugin + 7 source modules + `quick.py` + `deep.py` + `domain.py`), 4 LLM round-trips replaced by 1 in quick mode and 2 in deep mode (down from 25+ in the legacy agentic loop), 7 free Python source tools added (no SaaS keys required), 49+13+30+5+58 = **155 new tests across the research surface**, T-12.1b through T-12.1e plus T-12.8 through T-12.14 added to the testing guide. |
| 2026-05-24 | **Step 5d — research mode auto-detection + intent wiring.** `_parse_research_topic` in `core/intent_recognizer.py` rewritten to detect three buckets: `_RESEARCH_QUICK_PATTERNS` (tldr / briefly / quick research / one-pager / summarize / overview → `mode="quick"`), `_RESEARCH_DEEP_PATTERNS` (deep dive / thorough / comprehensive / exhaustive / in-depth / literature review / detailed report / bare "research X" / "investigate X" / "study X" → `mode="deep"`), `_RESEARCH_COMPARE_PATTERNS` (compare X vs Y / contrast / differentiate / which is better → always deep, both sides stitched into the topic). Legacy generic patterns (brief me on / find papers on / put together a briefing on) still leave mode unset so the planner asks for focus. `tl;dr X` clause-splitter guard prevents the semicolon from being treated as a clause separator. `_KNOWLEDGE_Q_RE` negative lookahead extended so "compare X vs Y" routes to research instead of chat. `research_planner.begin(topic, sid, mode=…)` now takes an explicit-mode fast path that skips the "Any specific angle?" prompt and dispatches immediately. `_parse_mode` returns `"quick"`/`"deep"` (new pipelines) for inline focus-reply depth overrides; legacy `speed`/`balanced`/`quality` still recognised for backward-compat. `_DEFAULT_PLANNER_MODE` flipped to `"deep"`. Plugin handler `handle_research` reads `args["mode"]` and forwards to the planner. Catalog entry for `research_topic` rewritten with 17 curated example phrases across quick / deep / comparative buckets. New T-12.1e. 49 new tests in `tests/test_research_mode_detection.py`; **615 / 615 across all touched suites**. |
| 2026-05-24 | **Step 5c — deep-mode research rewrite.** New `modules/research_agent/domain.py` (regex classifier) + `modules/research_agent/deep.py` (~400 lines). Replaces the existing 1557-line agentic loop for `mode="deep"`. Pipeline: Wikipedia anchor + domain-specific source plugins (`arxiv_search` for tech/academic, `pubmed_search` for medical, `hackernews_search` for tech-buzz, `yfinance_quote` for finance — with ticker auto-extracted) + DDG web search → parallel `newspaper_extract` → one synthesis call with the 5-section template (Executive Summary / Key Findings / Cross-Source Analysis / Conflicting Claims (omitted when no conflicts) / Open Questions) + system prompt forcing every factual sentence to end with `[N]` and never to "pick one" when sources disagree → same `_strip_dangling_citations` + truncation guard as quick mode → writes YAML-fronted summary with `mode: deep`, `domains: <list>`, optional `ticker:`, plus per-source files. Reduces 25 sequential LLM action-picks to 2 calls total (planning is now regex). Legacy `_run_research_locked` stays for backward-compat (`mode="speed"|"balanced"|"quality"`). New T-12.1d. 30 new tests in `tests/test_research_deep_mode.py`; **543 / 543 across all touched suites**. |
| 2026-05-24 | **Step 5b — quick-mode research pipeline.** New `modules/research_agent/quick.py` (~400 lines, ~13 tests). `service.run_research(topic, mode='quick')` now dispatches to a composable single-LLM-call pipeline: Wikipedia anchor (always-non-empty for named entities; kills the "no search results → empty 00-summary.md" failure path) → DDG → trafilatura×5 in parallel (`ThreadPoolExecutor`, ~5s instead of 15s serial) → one-shot LLM synthesis with strict citation rules → `_strip_dangling_citations` scrubs hallucinated `[N]` references where N > max_index → truncation guard appends `_(response truncated)_` when the synth cuts mid-sentence. Writer emits YAML-fronted `00-summary.md` (`topic`, `mode`, `generated_at`, `sources_usable`, `sources_total`) + `sources.md` + one `0N-<slug>.md` per usable source. Extractive fallback when `router.get_llm()` returns None. Failure card lists what was tried (Wikipedia / DuckDuckGo) when zero sources came back. Deep mode (the existing agentic loop in `service._run_research_locked`) is unchanged — `mode='quick'` is dispatched in one line at the top of `run_research`. New T-12.1c. 13 new tests in `tests/test_research_quick_mode.py`; **513 / 513 across all touched suites**. |
| 2026-05-24 | **Four-bug sweep from live session 2026-05-24 07:05–07:30.** (1) `show_memories` returned a stale name from the legacy `user_profile` namespace even after the user said "My name is Santhosh" and the facade had been updated — `recall_personal_fact` correctly said Santhosh but `show_memories` still said Tricky. Fix: `_handle_show_memories` now overlays `MemoryFacade.recall(session_id, key=…)` on top of the user_profile dict for every key in `_PROFILE_KEYS`; the facade wins. (2) `/new` and `/clear` didn't expire the outgoing session's workflow rows; a pending `research_planner` row at `step=awaiting_readout` could intercept the next conversation's first message. Fix: new `WorkflowStore.expire_all_for_session(session_id)` → `ContextStore.expire_all_workflows(...)` → called from `_new_session` after the outgoing pending-wipe clear. (3) The `awaiting_readout` step in `core/reasoning/agentic_services/research_planner.py` treated only `_NEGATIVE_TOKENS` ("no", "skip", "cancel", …) as exit signals — "bye" / "goodbye" / "exit" / "quit" / "/new" / "/clear" / "never mind" went down the "read the briefing aloud" branch instead. The 2026-05-24 07:30 bug: user said "Bye" and FRIDAY read a 1-paragraph GPT briefing at them instead of shutting down. Fix: new `_BAILOUT_TOKENS` + `_is_bailout()` + `awaiting_readout` branch that returns `WorkflowResult(handled=False)` so the outer router can dispatch the real intent (`shutdown_assistant` for "bye"). (4) `/web` flakiness — DDG HTML scraping returns zero hits intermittently. Fix: `WebPlugin._try_wikipedia_fallback` uses `modules.sources.wikipedia.summary_for_query` as a fallback when `_ddg_search` returns empty — reply is prefixed with "(Web search returned nothing; pulled this from Wikipedia instead.)" so the user knows. Bonus: catalog audit added 9 missing entries (`get_calendar_agenda`, `list_calendar_events`, `update_calendar_event`, `open_url`, `read_email`, `search_drive`, `search_workspace`, `update_user_profile`, `voice_mode`, `set_voice_mode`). New T-7.4b, T-11.0b, T-11.0c, T-12.1b. 16 new tests in `tests/test_bugfix_2026_05_24.py`; 109 / 109 across all touched suites. |
| 2026-05-24 | **Step 5a — 7 free Python source tools ported.** New `modules/sources/` plugin registers 9 capabilities (wikipedia_summary / wikipedia_search / arxiv_search / hackernews_top / hackernews_search / pubmed_search / newspaper_extract / yfinance_quote / pdf_text_search), all backed by free public APIs or pure-Python libs. Each is a thin wrapper around the matching `core/modules/sources/<tool>.py` so the network shape is testable in isolation. `newspaper_extract` uses `trafilatura` (already installed) for boilerplate-stripped article text, replacing the existing `_html_to_text` that kept nav + footer garbage. `yfinance_quote` and `pdf_text_search` use lazy imports — graceful "pip install X" hint when the optional dep is missing. New `_parse_source_tools` intent parser handles "wikipedia <topic>", "search wiki for X", "arxiv on Y", "pubmed search Z", "hn top", "quote MSFT", "search my pdfs for X", etc. Dedicated `_parse_newspaper_extract` runs BEFORE `_parse_web_url_action` so "get just the article from <URL>" / "reader mode <URL>" beats the generic fetch. Catalog entries added for all 9 tools with curated `example_phrases`. **58 new tests in `tests/test_sources_tools.py` (22 unit/handler + 36 intent + smoke covering plugin registration); 612 / 612 across all touched suites.** Sourced from the GetStream ai-agent-tools-catalog after audit — most of its 84 entries were SaaS-paywalled or duplicates; these 7 were genuinely free, pure-Python, and filled gaps. |
| 2026-05-24 | **`!cmd` shell uses bash + auto-activates venv.** Live session bug at 06:37: `!source .venv/bin/activate` failed with `/bin/sh: 1: source: not found` because `subprocess(shell=True)` on Kali resolves to dash, which has no `source` builtin. Even with bash, `source` wouldn't have helped — each `!cmd` spawns a fresh shell that exits immediately, taking the activated env with it. Two fixes in `core/shell_prefix.py`: (1) explicit `executable=_preferred_shell()` (prefers `/bin/bash`, falls back to `/bin/sh`) wired into the PTY path, the sync-timeout path, and the no-PTY path — `source`, `[[ ]]`, arrays, process substitution all now work. (2) New `_shell_env()` autodetects `.venv/` (or `venv/`, `.env/`) in the project root and prepends `<venv>/bin` to PATH + sets `VIRTUAL_ENV`. Net effect: `!python script.py` uses the project interpreter without the user ever typing `source`. PYTHONHOME is scrubbed so it doesn't interfere with venv resolution. 6 new tests in `tests/test_shell_prefix.py` (18/18 green): `_preferred_shell()` picks bash, `source` builtin works, `[[ ]]` works, `.venv` detected, PATH prefix verified, `which python` end-to-end returns the venv binary. |
| 2026-05-24 | **Tool catalog + routing rewire (Step 4b of plan).** Single source of truth for ~110 user-facing capabilities in `data/tool_catalog.yaml` (`name`, `category`, `summary`, `example_phrases`, optional `parameters`, optional `blocked_from_chat_preflight`). Loaded once by `core/tool_catalog.py` as a singleton. Three downstream consumers: (1) `core/embedding_router.py` — `build_index()` now prefers the catalog's curated example_phrases over the auto-generated `aliases + context_terms` noun-cloud; tools missing from the catalog keep the legacy path so the rewrite isn't breaking. (2) `core/planning/qwen_planner.py` — `compact_capability_cards()` injects up to 6 example_phrases per tool as `examples` on the card; `plan_draft.j2` renders them as `Example phrasings → use <name>: "X", "Y", …` under each capability. Small models (Qwen 4B) gain large accuracy boosts from few-shot examples; this is the cheapest one to wire. (3) `modules/llm_chat/plugin.py` — new `_preflight_reroute` calls `embedding_router.preflight_route(query, threshold=0.72)`; on a hit it dispatches the matching tool via `capability_executor` and bypasses chat generation entirely. The chat pre-flight uses a tighter threshold than the regular embed router (0.72 vs 0.62) because the cost of a wrong reroute at this layer is higher; `blocked_from_chat_preflight: true` lets the catalog mark tools that require structured args (set_volume, set_reminder, …) so empty-args dispatches don't surprise the user. `core/app.py` calls `catalog.bind_registry()` at end of init to warn about stale catalog entries / missing entries. New `tests/test_tool_catalog.py` (18/18 green): catalog loader, schema edge cases, embedding-index uses catalog, preflight honours blocked flag, chat preflight integration, planner-card injection. **Suite: 553 / 553 across all touched files.** |
| 2026-05-23 | **Long-tail intent parsers — Step 4 of Plan 22:13.** Added 9 new parsers + extended 2 existing ones to close the 30-tool zero-coverage gap from the capability audit: `_parse_weather` (location-aware get_weather + anti-poach for "weather app"); `_parse_goals` (list/create/complete/pause/detail for the goals plugin, with title-extraction from "I have a new goal: X" / "my goal is to X" / "I want to achieve X"); `_parse_triggers` (list/remove plus the three add_*_trigger types — clipboard/cron/file-watch); `_parse_clipboard` (get/set with quoted or post-colon text + analyze_clipboard_image); `_parse_homeassistant` (ha_turn_on/off with entity capture, ha_set_temperature with degree parse, ha_get_state with "is the bedroom light on"-style room+device combos, anti-poach for voice/focus/dnd/lock/brightness/volume); `_parse_awareness` (status/enable/disable); `_parse_code_eval` with a `_split_into_clauses` guard so `execute python: x=5; print(x)` doesn't get split on `;`; `_parse_send_notification` (saying/with-text/colon/notify-me/ping-me); `_parse_window_query` (get_active_window). Extended `_parse_security` with dns_enum_owned_domain, web_directory_enum, compare_scan_results, security_report_generate. Extended `_parse_vision_action` with find_ui_element, compare_screenshots, debug_code_screenshot, recent_screen_activity, roast_desktop, review_design, explain_meme, describe_image. Extended `_parse_news_action` with world_monitor. Critical fix: `_KNOWLEDGE_Q_RE` had bare-verb matches for `analyze`, `compare`, `describe` that were short-circuiting tool invocations like "analyze my clipboard image", "compare these screenshots", "describe this picture" to the LLM fallback; added negative lookaheads for tool-noun tails (screen|clipboard|image|picture|screenshot|code|error|page|section|screenshots?|scans?|scan results?|files?). New `tests/test_step4_new_parsers.py` (147 parametrised cases incl. anti-poach + tool-absence inertness). Added T-4.10 through T-4.15 (weather/clipboard/awareness/notifications/active-window/code-eval), T-5.5–T-5.8 (security extras), T-6.4 (goals), T-6.5 (triggers), T-13.3 (vision long-tail), T-14.5 (HA intent routing). Suite: **522 / 522 across all touched files**. |
| 2026-05-23 | **Intent breadth — Step 3 of Plan 22:13.** Six existing parsers had narrow patterns that covered the canonical phrasing only. Broadened with the variants users actually speak (per CLAUDE.md "humans interact differently"): `_parse_brightness` now accepts "make my screen brighter/darker", "turn down the screen", "raise/lower screen brightness", "max/min brightness", "brightness to max", "full brightness", "lowest brightness", "dim the screen all the way", relative deltas (no number → ±20 from baseline), spoken cardinals including fives ("seventy five"), and `brighten` (was missing). `_parse_volume` adds "louder/quieter/softer", "crank it", "pump it up", "tone it down", "too loud/too quiet", "put the volume on full"; turn-it-up/down works when prior turn was volume; spoken cardinals via `_extract_volume_percent`. `_parse_screenshot` adds "capture my screen", "grab the screen", "snap a picture of my screen", "print screen", "snapshot", "do/shoot a screenshot", "get me a screenshot" (with anti-poach for "make my screen brighter" which used to be stolen). `_parse_time_date` adds "got the time", "time please", "time now", "what day is today", "what's today", "date please". `_parse_screen_lock` adds "lock the computer/laptop/pc/machine/workstation/desktop/session", "lock me out/down", "secure the computer", "step away mode", "going afk", "i'm afk", "engage/activate lock"; unlock adds "i'm back". `_parse_focus_session` adds "deep work mode", "dnd mode", "quiet mode", "silence/mute/block my notifications for an hour/30 min", "turn on focus/dnd/deep work", "am I still in focus mode", "leave dnd", "exit deep work mode". New `tests/test_intent_breadth_2026_05_23.py` with 149 parametrized cases (positive + anti-poach). Suite: **375 / 375 across all touched files**. |
| 2026-05-23 | **Brightness desktop-panel refresh (Step 2 of Plan 22:13).** Backlight was changing on the hardware via `brightnessctl` but the panel-slider indicator stayed stale until the user nudged it. `modules/system_control/brightness.py` now calls `_notify_desktop_environment(target)` after every successful set; that fans out three best-effort backends (GNOME via `gdbus` Properties.Set on `org.gnome.SettingsDaemon.Power.Screen.Brightness`, KDE via `qdbus`/`gdbus` to `org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness`, XFCE via `xfconf-query` on `/xfce4-power-manager/brightness-level`). Each backend returns False if its tool isn't installed or the DBus name isn't owned, so a system with only one DE running still works cleanly. New T-4.2b. 4 new tests in `tests/test_brightness.py` (10/10 green). |
| 2026-05-23 | **`/new` and `/clear` true session isolation (Step 1 of Plan 22:13).** Before this fix the slashes printed "New conversation started" but left four pieces of cross-turn state alive: the browser-media tab handle (`browser_media_service._pages`), any live `!cmd` shell session, the outgoing session's `pending_memory_wipe` flag, and `routing_state` mode flags. Net effect: "pause" after `/new` still controlled the prior YouTube tab; "yes wipe everything" after `/new` could confirm a wipe queued in the previous conversation. New `BrowserMediaService.reset_session()` closes tracked tabs without tearing down Playwright. `_new_session` now (in order) cancels the active shell, calls `reset_session()`, clears the outgoing pending-wipe, rotates the session id, resets dialog state, and resets `routing_state.reset_for_turn()`. New T-11.0. 7 new tests in `tests/test_slash_commands.py` (17/17 green). |
| 2026-05-23 | **Follow-up fixes from live re-test (session 21:35–21:51).** Five bugs surfaced after the morning sweep: **(1)** `!sudo apt install …` still failed with *"a terminal is required to read the password"* — the PTY had no controlling terminal. Fix: `preexec_fn` in `core/shell_prefix.py` issues `fcntl.ioctl(0, termios.TIOCSCTTY, 0)` so the child claims the slave as its controlling TTY. `sudo -n true` now reports "a password is required" (the *expected* non-interactive error) instead of "no TTY". **(2)** `Fetch <URL>` / `Crawl <URL>` still routed to chat because `modules/web/__init__.py` was empty — the loader's `module.setup(app)` probe found nothing, so `web_extract` / `web_crawl` / `web_search` never registered. Added the `setup()` shim. **(3)** `/research <topic>` returned "Capability 'research_agent' is not registered" — the slash handler probed the wrong name (the capability is `research_topic`). Now probes `research_topic` first, falls back to `research_agent`/`research`. Added `/fetch <url>` and `/crawl <url> [instructions]` slashes too. **(4)** "Search my conversations for programming" went to the file index — wrong store. Added a `search_conversations` branch to `_parse_memory_query` matching "search my conversations/chats/history for/about X" and "what did/have we (talk|discuss)ed about X". **(5)** "What else do you know about me?" returned the EXACT same paragraph as "What do you know about me?" (identical replies 30s apart in the log). Parser now tags the intent with `args["more"] = True` when "else"/"more"/"everything" appears; `_handle_show_memories` then renders a full key/value breakdown instead of repeating the curated paragraph verbatim. New `tests/test_followup_2026_05_23.py` (18 cases). Suite: **230 / 230 across all touched files**. |
| 2026-05-24 | **Research synthesis → 4B writer + comprehensive Executive Summary.** Live session: `quick research Tamil Nadu 2026` and a second quick run both produced `00-summary.md` files with NO synthesis — just "_LLM unavailable — surfaced raw source summaries with citations._" followed by a raw dump of source bodies. Root cause chain: the original quick writer was single-shot and fed raw 3000-char bodies for 10 sources, blowing the 0.8B chat model's 4096 ctx (`Requested tokens (6380) exceed context window of 4096`); the broad `except` swallowed it into the extractive fallback. A prior session had bumped chat `n_ctx`→8192 and added a 0.8B map-reduce, but the 0.8B model still hallucinated (invented "BJP 126 seats", "CMJ party") and spammed `[1][2]…[10]` on every sentence. **Fix:** route the final writer to the smarter **4B tool model** (`_writer_candidates` tries `model_manager.get_tool_model()` first, falls back to the 0.8B chat model, then to the extractive dump), feed it the cleaned source text directly (`_source_bundle`, each body sliced to `_WRITER_BODY_CHARS`=800 — no lossy 0.8B pre-compression), and spend the whole generation budget on ONE comprehensive Executive Summary (3 dense paragraphs synthesising all sources). New `_clamp_max_tokens` shrinks the budget so prompt+output can never exceed the model's `n_ctx` again — the structural cure for the original overflow. Tightened the system + user prompts to forbid out-of-source facts and cap citations at 1-3 per sentence. `config.yaml`: `models.tool.n_ctx` 2048→8192 so the 4B can hold the bundle (routing prompts are far shorter, so only KV memory grows). Deep mode shares the same writer path (`_DEEP_SYNTH_MAX_TOKENS`=900, 3 sections: Exec Summary / Key Findings / Conflicting Claims). **Validated end-to-end on the real 10 Tamil Nadu sources: 224s, a 3-paragraph summary with accurate seat counts / turnout / dates / alliance shifts, disciplined citations, and it even flagged the 107-vs-108-seat conflict — zero hallucinated entities.** Trade-off: 4B at ~2.7 tok/s ≈ 3.5-4 min for quick, ~4-5 min for deep (research is async). `_SYNTH_MAX_TOKENS`/`_DEEP_SYNTH_MAX_TOKENS` are tunable. T-12.1c and T-12.1d updated. 52/52 in `tests/test_research_quick_mode.py` + `tests/test_research_deep_mode.py`. |
| 2026-05-25 | **RAG production-hardening (8 tracks).** The "semantic recall" path was not semantic: `MemoryStore` persisted to Chroma but embedded with `HashEmbeddingFunction` — a 64-dim SHA-256 bag-of-words — so paraphrases with no shared tokens never matched, and the SQL fallback was literal token-overlap. **Track 1:** new `get_shared_embedder()` singleton in `core/memory/embeddings.py` (`SentenceTransformerEmbedder`, default `all-MiniLM-L6-v2`, 384-dim) shared by MemoryStore, plan_archive, and the embedding_router (one model resident); `MemoryStore` installs a new `SemanticEmbeddingFunction` and keeps the hash function only as the offline fallback. **Track 2:** the permanent `_vector_available=False` kill-switch became a consecutive-failure + 60s cooldown with auto re-init (`_vector_ready`/`_note_vector_failure`) so one transient Chroma error no longer downgrades the whole process. **Track 3:** `_maybe_rebuild_collection` detects an embedder-signature change on `friday_memory` and drops+recreates it (lazy re-index; `reindex_memory()` backfills on demand). **Track 4:** `semantic_recall` now Reciprocal-Rank-Fuses dense (Chroma) + sparse (FTS5 over turns) candidates. **Track 5:** MMR diversity over fused candidates + optional lazy cross-encoder rerank behind `FRIDAY_RERANK_MODEL`. **Track 6:** recency half-life decay + persona-scope boost + memory-type weighting in scoring. **Track 7:** content-hash LRU embed cache. **Track 8:** new `tests/retrieval/test_recall_quality.py` eval harness (recall@k / MRR gate) — measured **recall@3 = 1.0, MRR = 1.0** on a 7-query paraphrase set. Tunables surfaced under `memory.embedding` in `config.yaml` (wired to env via `app._apply_embedding_config`). New T-1.14. 9 new tests in `tests/stores/test_memory_store_rag.py` + the eval harness; all existing memory/store/router suites green (the 3 pre-existing `test_router_tools.py` failures are unrelated and predate this change). |
| 2026-05-25 | **Cross-encoder rerank enabled + graph refreshed.** Follow-up to the RAG overhaul: `config.yaml` `memory.embedding.rerank_model` set to `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU, ~80MB, lazy-loaded on first recall) — `MemoryStore._maybe_cross_encode` now jointly re-scores fused candidates for sharper top-k ordering. Verified the cross-encoder loads and recall quality holds (recall@3 = 1.0, MRR = 1.0). Also ran `/graphify . --update` (AST-only on 43 changed code files): +532 nodes / +826 edges, graph now 7343 nodes / 12446 edges / 496 communities; `SentenceTransformerEmbedder` and the new RAG tests are in the graph. |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 1 (measurement).** First slice of the adaptive-routing plan (`plan/2026-05-25_10-43-54_plan.md`). New domain store `core/stores/intent_learning_store.py` (+ `migrations/intent_learning.sql`) owning three tables: `routing_observations` (append-only log of every routing decision), `learned_phrases` (per-user phrasing→tool ledger with hit/correction counters and a candidate→promoted→blocked status; auto-promotes at `PROMOTE_AFTER=3` confirmed hits with zero corrections — wired for Phase 4 auto-dispatch), and `intent_profile` (per-tool usage count + 24-bucket time-of-day histogram for Phase 5 tie-breaking). Exposed on `FridayApp` as `self.intent_learning_store` (standalone, write-isolated, NOT part of the ContextStore facade). `TurnOrchestrator._record_routing_observation` persists one observation per turn right after the `[ROUTE]` decision (best-effort, never raises into the turn path). New eval harness `tests/routing/test_routing_quality.py` over a labelled paraphrase set `data/routing_eval.yaml` (28 cases) — routes each through the real `EmbeddingRouter` and gates top-1 accuracy / miss rate (regression floors 0.85 / 0.10). Harness immediately surfaced a **42.9% top-1 / 46% miss** baseline on hard paraphrases; expanding `data/tool_catalog.yaml` `example_phrases` with ~30 colloquial variants across 15 missed tools lifted it to **96.4% top-1 / 0% miss** (lone remainder `summarize_screen` vs `analyze_screen` is a true synonym pair, deferred to the Phase 2 confirmation loop). New T-4.3c. 8 new tests in `tests/stores/test_intent_learning_store.py` + the eval harness; orchestrator + stores suites green (157/157 across touched suites). |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 2 (mid-band confirmation loop).** Second slice of `plan/2026-05-25_10-43-54_plan.md`. When the embedding router's top-1 cosine lands in `[CONFIRM_LOW=0.50, DISPATCH_THRESHOLD=0.62)` — too weak to auto-dispatch, too strong to drop — FRIDAY now asks **"Did you want me to &lt;tool summary&gt;? Say yes or no."** instead of falling through to chat (where a small model fabricates fake success). New `EmbeddingRouter.confirm_candidate` (refactored `route` to share a threshold-free `best_match`; the band gate also skips tools flagged `blocked_from_chat_preflight` so a confirm never dead-ends on empty args). New broker machinery: `_maybe_confirm_intent` (called from `PlannerEngine.plan` as step 5b, just before the chat fallback) → `_propose_intent_confirmation` stashes a `pending_intent` payload in session state and returns a `clarify` ToolPlan; `_plan_pending_intent` resolves the next-turn yes/no — **yes** dispatches the tool *and* calls `IntentLearningStore.note_hit` + `bump_profile` (the day-by-day learning signal Phase 4 promotes at N=3), **no** calls `note_correction` (blocks the pairing). `check_pending_confirmation` now tries online-consent first, then intent. New `pending_intent` session-state channel: `SessionStore.set/clear_pending_intent` (generic `state_json`, no schema change) + ContextStore-facade + MemoryService delegators; 60s TTL reuses `_is_pending_expired`. Also fixed a latent Phase-1 bug: `TurnOrchestrator._record_routing_observation` was logging an empty `chosen_tool` because `ToolPlan` has no `tool_name` field — new `_primary_tool(plan)` reads `steps[0].capability_name`, so observations now carry the real tool. New T-4.3d. 10 new tests in `tests/test_confirmation_loop.py` (band logic + cross-turn propose→yes/no→learning + TTL + check_pending routing); updated 2 MagicMock-broker stubs in `tests/test_planning_engines.py` (`_maybe_confirm_intent.return_value=None`). Touched suites green: planning_engines 13/13, confirmation_loop 10/10, stores/routing 113 pass (2 pre-existing chromadb-absent failures unrelated). |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 3 (fuzzy / lexical layer).** Third slice of `plan/2026-05-25_10-43-54_plan.md`. New `core/lexical_router.py` (`LexicalRouter`) slotted between the regex/keyword layer and the embedding router: rapidfuzz `token_set_ratio` over catalog `example_phrases` + promoted learned phrasings, with a small hand-curated synonym fold applied to the query ("luminosity"→"brightness", "screem"→"screen", "pic"→"screenshot"). Catches STT mishears / typos / word-order shuffles that the regex layer drops, before paying for the 384-dim cosine or the LLM. Deliberately conservative — auto-dispatches only when the best tool clears `LEXICAL_THRESHOLD=88` AND beats the runner-up by `LEXICAL_MARGIN=6`, and excludes structured-arg tools via the embedding router's `_DEFAULT_BLOCKLIST` + the catalog `is_safe_for_preflight` flag (a fuzzy match dispatches with empty args, same constraint as the chat preflight). rapidfuzz is the declared dep + fast path; a pure-stdlib `difflib` fallback keeps the router functional (and tests green) if rapidfuzz is absent, so the module never hard-imports. Owned by `CommandRouter` as `self.lexical_router` (disable via `FRIDAY_DISABLE_LEXICAL_ROUTER=1`), wired into `PlannerEngine.plan` as **step 4b** through new `CapabilityBroker._maybe_lexical_route` (+ `_promoted_phrase_pairs` Phase-4 hook that feeds promoted learned phrasings into the fuzzy index). Config gate `routing.lexical_enabled` (default true). New T-4.3e. 14 new tests in `tests/test_lexical_router.py` (helpers, near-miss positives, unrelated negatives, structured-arg exclusion, extra-phrase indexing, both backends); added `_maybe_lexical_route.return_value=None` to the 2 MagicMock-broker stubs in `tests/test_planning_engines.py`. Touched suites green: lexical 14/14, planning_engines 13/13, confirmation_loop 10/10, routing 1/1; 875 pass across change-adjacent suites (6 pre-existing failures — qwen_planner jinja UndefinedError, research_agent, 3× router_tools, workflow bare-hour — all reproduce on clean baseline, unrelated). |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 4 (adaptive phrase memory + auto-dispatch).** The learning core of `plan/2026-05-25_10-43-54_plan.md`. Implemented the missing `EmbeddingRouter.add_phrase(phrase, tool)` that `core/skill_loader.py:159` already called: personal learned phrasings live in `_personal` (separate from the curated catalog), get folded into the index on every rebuild AND appended incrementally to the live index (`_append_to_index`, one-row encode + `np.vstack`), and skip blocklisted structured-arg tools. `IntentLearningStore` gains `active_phrases()` (non-blocked, for boot replay), `promoted_lookup(text)` (exact normalized-key match against `status='promoted'`, highest hit_count). New planner step **4a** `CapabilityBroker._maybe_learned_dispatch` (before the lexical layer): a phrasing the user confirmed `PROMOTE_AFTER=3` times auto-dispatches deterministically with `route_origin="learned"` (new `ToolPlan` field) → `TurnOrchestrator._plan_source` now returns the origin so `[ROUTE]` logs `source=learned`. **Capture-at-source** (cleaner than reverse-engineering origin in the orchestrator): `note_hit` fires on the lexical near-miss path, the `llm_chat` embedding-preflight reroute (`_note_learned_hit` — the high-value paraphrase signal), and confirmation-yes (Phase 2). The orchestrator additionally `bump_profile`s every real-tool dispatch (frequency for Phase 5; skips clarify/reply/chat/llm_chat). Boot replay: `FridayApp._load_learned_phrases()` (end of `initialize()`) registers all non-blocked learned phrasings into the embedding router so day-by-day adaptation survives restarts; the lexical router picks up promoted phrasings lazily via `_promoted_phrase_pairs`. Demotion: a correction sets `status='blocked'` so `promoted_lookup` (and thus auto-dispatch) stops. Config gate `routing.learned_dispatch_enabled` (default true). New T-4.3f. 11 new tests in `tests/test_learned_phrase_promotion.py` (store promotion/lookup/demotion/active; add_phrase dedup+blocklist+rebuild-survival+live-append+route; learned dispatch + telemetry + lexical capture); added `_maybe_learned_dispatch.return_value=None` to the 2 MagicMock-broker stubs in `tests/test_planning_engines.py`. Touched suites green: learned 11/11, confirmation 10/10, lexical 14/14, planning_engines 13/13, intent_learning_store + routing; 936 pass across change-adjacent suites (same 6 pre-existing baseline failures — qwen_planner jinja UndefinedError, research_agent, 3× router_tools, workflow bare-hour — unrelated). |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 5 (profile biasing + user controls).** Penultimate slice of `plan/2026-05-25_10-43-54_plan.md`. **Tie-breaker:** `IntentLearningStore.profile_score(tool, hour)` (usage count + 2× current-hour histogram hits); `EmbeddingRouter.set_tie_breaker(fn)` + a `TIE_EPSILON=0.05` gate in `best_match` — among the top-2 near-tied cosine candidates an injected profile tie-breaker may pick the more-used tool, but a clear winner is never overridden. Wired in `FridayApp._load_learned_phrases` to a closure over `profile_score` (returns None when all candidates are unseen, keeping the cosine winner). **Favourite-arg defaults:** `record_args(tool, args)` folds dispatched scalar args into `intent_profile.fav_args_json` as `{arg:{value:count}}`; `favorite_args(tool)` returns the modal value per arg; `CapabilityBroker._apply_arg_defaults` fills only *missing* preference-style keys (`app/browser/player/service/provider/engine/device` — never content args like query/topic, never an explicit value), applied on the learned-dispatch path. `TurnOrchestrator._bump_intent_profile` now also `record_args` on every real-tool dispatch. **User controls:** new `forget_learned_intents` capability (memory_manager plugin) → `store.forget_all()` + clears the embedding router's in-memory `_personal` + `LEARNED_INTENTS_FORGOTTEN` audit event; new `_parse_forget_learned` intent parser anchored on talk/speak/phrasing/wording/"learned" so it never poaches `wipe_memory_init` (runs before `_parse_memory_query`); catalog entry added. **Master privacy switch** `routing.learning_enabled` (default true) gates all capture (`_note_intent_hit`, orchestrator profile bump, chat preflight `_note_learned_hit`), learned auto-dispatch, and arg-fill. New T-4.3g. 23 new tests across `tests/test_forget_learned_intent.py` (8 route + 4 anti-poach/inert) and `tests/test_profile_biasing.py` (favourite-args, profile_score, arg-default fill incl. disabled, tie-breaker epsilon gate). Touched suites green: forget+profile 23/23, tool_catalog + intent_learning_store + routing 50/50; 993 pass across change-adjacent suites (same 6 pre-existing baseline failures — qwen_planner jinja UndefinedError, research_agent, 3× router_tools, workflow bare-hour — unrelated). |
| 2026-05-25 | **Adaptive Intent Recognition — Phase 6 (threshold tuning), plan COMPLETE.** Final slice of `plan/2026-05-25_10-43-54_plan.md`. New `core/routing_tuner.py` replaces hand-picked thresholds with a data-driven instrument: `sweep_threshold(score_fn, cases, lo, hi, step)` is generic over any `score_fn(text) -> {tool,score}|None` (tunes the embedding dispatch band today, the lexical ratio tomorrow), classifying each labelled case as correct / false-dispatch / deferred and reporting weighted rates + precision per threshold; `recommend_threshold` (lowest threshold within a false-dispatch budget), `recommend_max_accuracy` / `on_accuracy_plateau` (top of the coverage plateau), `band_precision` (confirmation-band quality), `recommend_promotion_n` (smallest N that wouldn't have promoted a later-corrected phrasing). Case loaders: `cases_from_eval` (static `routing_eval.yaml`) + `cases_from_learned(store)` (the user's own confirmed phrasings, weighted by hit_count — makes tuning *adaptive*). CLI `python -m core.routing_tuner` dumps the sweep + recommendations. **Data finding:** on the 28-case set, thresholds 0.40–0.64 form a flat plateau (96.4% acc / 3.6% false / 0% defer); the single false case is a genuine synonym pair that only clears at 0.74, which would cost ~18% coverage — so it's a catalog/confirmation concern, not a global-threshold one. **Defaults kept and now data-validated** (`DISPATCH_THRESHOLD=0.62`, `CONFIRM_LOW=0.50`, `LEXICAL_THRESHOLD=88`, `TIE_EPSILON=0.05`, `PROMOTE_AFTER=3`); the confirmation band catches 0 eval cases (clean paraphrases score high), so `CONFIRM_LOW` tuning awaits real production `routing_observations`. Phase 6 is import-isolated to its test + CLI — no live-path code changed. New T-4.3h. 7 new tests in `tests/routing/test_threshold_tuning.py` (sweep math + recommendation logic with a deterministic fake scorer; integration test asserting the shipped `DISPATCH_THRESHOLD` sits on the accuracy plateau). All six phases' suites green: 87 pass (confirmation 10, lexical 14, learned 11, profile 11, forget 12, planning 13, tuning 7, store, routing). **The full 6-phase adaptive-intent plan is now complete.** |
| 2026-05-25 | **Config audit — activate all latest features + fix dead code_execution plugin.** Audited `config.yaml` against every config key the code reads. Findings: all adaptive-intent feature flags (`routing.learning_enabled` / `learned_dispatch_enabled` / `intent_confirmation_enabled` / `lexical_enabled`) were already present + true; all section toggles (vision/awareness/document_intel/browser_automation/memory/world_monitor/security/greeter) on; `routing.use_qwen_planner` true; no extensions hidden (`enabled_by_default` defaults True, unset by all). **Two gaps fixed:** (1) **`code_execution` was dead** — `modules/code_execution/__init__.py` was empty (0 bytes), so the PluginManager (which calls `module.setup(app)`) never loaded `CodeExecutionPlugin` regardless of config; `evaluate_code` was never registered and "compute 6 * 7" fell through to chat. Added `setup(app)` that gates on `code_execution.enabled` and returns the plugin only when true. Added the `code_execution:` section (`enabled: true`, `timeout_sec: 15`) with a security note (runs arbitrary Python/Bash). Verified live: boot registers `evaluate_code`, "compute 6 * 7" → "42". (2) **Phase 6 thresholds made config-tunable** — the adaptive-intent thresholds were hardcoded module constants, so the tuner's recommendations couldn't be applied without editing source. Added `routing.dispatch_threshold/confirm_low/tie_epsilon/lexical_threshold/lexical_margin/promote_after` to config; `IntentLearningStore(promote_after=…)` now reads `routing.promote_after`; new `FridayApp._apply_routing_thresholds()` (called in `initialize()`) pushes the embedding/lexical thresholds onto the live routers (read at route time, so post-construction set is safe). Verified live: booted app reports all six values sourced from config. T-4.15 updated (live gating + security note). No new test failures (the 2 in the broad run — `test_research_agent`, `test_routing_snapshots[volume_up_steps]` — reproduce on the clean baseline); `tests/test_code_execution_sandbox.py` green; 248 pass across the change-adjacent + adaptive-intent suites. |
| 2026-05-25 | **Email-workflow root cause + research ecosystem + caching/FTS/GUI fixes (live session 16:22).** **(1) Headline bug:** "Check my mail" fell through to the 0.8B chat model which fabricated "Checking your mail…". Root cause was NOT the email code (it was complete) but `core/extensions/protocol.py`: it called `router.register_tool(spec, handler, metadata=…)` while the router's kwarg is `capability_meta`, so a TypeError was swallowed by a bare `except` and EVERY Extension capability carrying metadata (all of workspace_agent's email/calendar/drive tools) silently never reached `router._tools_by_name`. IntentRecognizer couldn't see them → chat fallback. Fixed the kwarg + replaced the silent swallow with `logger.exception`. New `tests/test_extension_metadata_registration.py`. **(2) Email:** `gmail_list_unread` now queries `is:unread category:primary` (Primary inbox only, no Promotions/Social); `_parse_email_action` regex extended to match the plural "mails" (was routing "summarize mails" → `summarize_file`). New `tests/test_email_intent.py`. **(3) Research ecosystem:** new `modules/web/searchflox_client.py` (free no-auth SearchFlox API, primary backend with DDG/Wikipedia fallback); new `quick_answer` capability (instant chat answer, no storage); four slash tiers `/web`(links) `/quick`(answer) `/fast`(quick research) `/deep`(deep research) — all auto-exposed in Telegram via `slash_commands.REGISTRY`; new `_parse_quick_answer` intent parser (ordered before `_parse_research_topic` so "quick research" still routes to research). New T-12.1f, T-12.7. New `tests/test_quick_answer_intent.py`, `tests/test_searchflox_client.py`. **(4) Caching:** revised `core/result_cache.py` TTL policy — recompute everything except heavy `latency_class=="background"` reads (900s); weather/news/email/web now always fresh. New `tests/test_result_cache_policy.py`. **(5) FTS crash:** `memory_store.fts_search` raw text hit `fts5: syntax error near ","`; new `_to_fts_match` tokenizes + quotes + OR-joins terms, returns "" for punctuation-only. New `tests/stores/test_fts_sanitize.py`. **(6) GUI:** voice-mode combo + Stop Speech button given `setMinimumHeight(34)` so their text is no longer clipped. **All 62 new tests pass; full touched-area suite 622 pass + 3 pre-existing failures (unchanged baseline).** |
| 2026-05-25 | **Follow-up fixes from live run 20:23.** (1) **"Summarize my emails" routed to research** (`research_topic` quick-mode on the topic "emails") — `_parse_research_topic` runs before `_parse_email_action` and its greedy `summari[sz]e (.+)` catch-all poached it. Moved `_parse_email_action` ahead of `_parse_quick_answer`/`_parse_research_topic` in the `_parse_clause` chain (it's narrow — requires email/mail/inbox nouns — so promotion can't poach anything). New regression tests in `tests/test_email_intent.py` (`test_summarize_email_beats_research`, `test_explicit_research_still_routes_to_research`); "quick research on X" still routes to research. (2) Added the missing `quick_answer` entry to `data/tool_catalog.yaml` (cleared the boot warning "1 registered tool(s) lack a catalog entry"). (3) **GUI voice panel** — voice-mode combo + Stop Speech button were squeezed/stretched out of place with clipped text; switched from `setMinimumHeight(34)` to `setFixedHeight(38)` + Fixed vertical `QSizePolicy`, and added a trailing `addStretch(1)` to the panel body so the controls stay top-aligned at a readable size. 28/28 in `tests/test_email_intent.py`; 127/127 across touched intent+web suites. |
| 2026-05-25 | **GUI force-quit on slash commands fixed + full command reference.** Live run: `/web mahesh babu` → `zsh: killed`. Root cause: `MainWindow.handle_return_pressed` (gui/hud.py + gui/main_window.py) called `app.process_input(...)` on the Qt main thread; normal turns hand off to `task_runner`, but the `/`-slash and `!`-shell prefix short-circuit (`_maybe_handle_input_prefix`) runs the capability INLINE — so a slash that hits a network capability (`/web` → SearchFlox's blocking urllib) froze the event loop and the desktop offered "Force Quit" (SIGKILL). Fix: GUI input now dispatches on a worker thread (`_dispatch_input` → existing `_InputWorker` QThread in hud.py; a daemon `threading.Thread` in main_window.py); responses still arrive via the event bus. Also tightened `_searchflox_links` to a 10s timeout so `/web` fails over to DDG quickly. Added a new **§0a Command quick-reference** to this guide: every slash command + args + spoken equivalent, the `!`/`>` prefixes, the email phrasings, and the four disambiguation rules (summarize-email vs research, quick-answer vs quick-research). No new test regressions; intent+web suites green. |
| 2026-05-25 | **"Lock the screen" now locks the real OS + GUI voice-panel overlap fixed + voice-command matrix.** (1) **OS lock:** "/lock" and "lock the screen"/"lock my laptop" only toggled FRIDAY's internal PIN gate (`core/screen_lock.py`) — the actual computer never locked, and it demanded `FRIDAY_LOCK_PIN_HASH`. New `modules/system_control/os_lock.py:lock_os_session()` performs a real cross-platform session lock (Linux: `loginctl lock-session` → `xdg-screensaver lock` → `qdbus …ScreenSaver Lock` → `xflock4` → … first available wins; Windows: `LockWorkStation`; macOS: `pmset displaysleepnow`). Repointed `SystemControlPlugin.handle_lock_screen` and `core.slash_commands._lock` to it; `unlock` now honestly explains the OS unlocks with the user's system password (no programmatic unlock). The PIN-gate module is untouched for its tool-gating role. T-4.7 rewritten. New `tests/test_os_lock.py` (5); `tests/test_slash_commands.py` lock tests updated to the OS-lock path. (2) **GUI overlap:** the VOICE panel held the most content (combo + Stop Speech + 5 labels) but had less stretch than the MODELS panel, so the rigid `setFixedHeight(38)` controls overflowed a too-short panel and rendered on top of each other. Fix: VOICE panel stretch 2→3 (MODELS 3→2) and `setMinimumHeight(284)` so the controls always have room; combo/button keep fixed 38px height + Fixed vertical policy. (3) **Testing guide:** expanded §0a with a voice-mode command table, an extended-toughness voice-command matrix covering ~20 tool domains with awkward phrasings, and corrected the `/lock` `/unlock` rows. All touched suites green (os_lock 5, slash 9, screen_lock 8, intent 259, system_control 44). |
| 2026-05-25 | **GUI input-device (mic) selector text clipped.** Same root cause as the voice-panel overlap: `MicSelector`'s `QComboBox` had no fixed height and the panel's minimum was only 40px, so the panel's stretch squeezed the dropdown until its device label was invisible. Fix: `combo.setFixedHeight(38)` + Fixed vertical `QSizePolicy` + a trailing `addStretch(1)`, and raised `mic_selector.setMinimumHeight(40)` → `96` so the "INPUT DEVICE" label + 38px combo + margins always fit. GUI-only change; `gui/hud.py` compiles. |
| 2026-05-25 | **GUI: Gemma card removed from Models panel, right-column reorganized, system pulse height fixed, mic selector inlined into VOICE panel.** Gemma card (LoRA intent router) removed from ModelsPanel — `_build_gemma_row()`, `_gemma_detail()`, `_on_gemma_prediction`, signal, bus subscription all removed. Right column reordered: VOICE (top, stretch 3) → SYSTEM PULSE (middle, stretch 3, minH 60→160) → MODELS (bottom, stretch 2). MicSelector standalone widget removed; input device label + combo inlined into VOICE panel with own discovery timer (10s refresh). PulseBars parent minHeight 60→160 for readable 6-bar animation. All voice controls (mode, stop, device, state labels) now in one panel. `scripts/wipe_user_data.py` added — wipes all user data (sessions, turns, memories, goals, audit, knowledge graph, workflows, intent learning) while preserving app_index, file_index, indexed_documents + friday_documents Chroma collection. GUI-only; `gui/hud.py` compiles clean. |
| 2026-05-25 | **Lock-aware capability gating + Telegram lock/unlock notifications + startup-speed wins.** (1) **Gating:** while the OS screen is locked, screen-dependent tools are now refused and everything else keeps working. Replaced `ScreenLock.ALLOWED_WHEN_LOCKED` (small allowlist) with `BLOCKED_WHEN_LOCKED` (denylist: browser automation, `launch_app`, `open_file`/`open_folder`, `open_url`, screenshots, on-screen vision, dictation, `get_active_window`, `web_crawl`) + a substring fallback (`screenshot`/`browser`/`youtube`/`launch_app`); `is_allowed` now returns allowed-unless-blocked. Added `ScreenLock.set_locked()`. Gate refusal message reworded (no PIN mention). (2) **OS lock state + notifications:** new `core/lock_monitor.py:LockStateMonitor` polls systemd-logind `LockedHint` every 2s, mirrors it into `screen_lock`, and sends a Telegram message on every lock↔unlock transition (works for FRIDAY-initiated `/lock` via `note_locked()` AND external Super+L); started at the end of `FridayApp.initialize()`. `handle_lock_screen` + `/lock` call `note_locked()` for an instant gate+notice. (3) **Startup speed:** `main.py` switches the HF stack to offline mode (`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`) when a HF cache exists — skips the slow unauthenticated Hub revision checks on cold start (opt out with `FRIDAY_HF_ONLINE=1`); `TOKENIZERS_PARALLELISM=false`. Telegram `setMyCommands` (a ~1-2s blocking network call) moved off the init path to a daemon thread. T-4.7 rewritten with the gating + Telegram checks. New `tests/test_lock_gating.py` (16); `tests/test_screen_lock.py` updated to the denylist. 810 pass + 2 pre-existing failures (qwen_planner template, research literature-review regex). |
| 2026-05-25 | **Goal persistence + intent routing + disambiguation updates.** Goals made global (not session-scoped) — `session_id` removed from all `create_goal`/`list_goals` calls in `modules/goals/plugin.py`. Added `delete_goal` capability with title extraction (e.g. "remove the launch goal" → `args={"title": "launch"}`; bare "remove all goals" → `args={}`, lists active goals for selection). Added `update_goal` intent pattern matching "update/set/mark X goal to Y%". Added goal disambiguation system: `PendingGoalSelection` dataclass in `core/dialog_state.py`; `_find_goals_by_title` + `_disambiguate_or_return` in plugin; `_parse_pending_selection` routes "first one" / "option 2" to `select_goal_candidate`. `_parse_goals` moved before `_parse_email_action`/`_parse_research_topic` in the clause chain so goal phrases don't get poached by `launch_app`. `isinstance(PendingGoalSelection)` check in `_parse_pending_selection` prevents MagicMock false-positives in tests. T-6.4 rewritten; T-6.4a (disambiguation), T-6.4b (delete with title) added. 398/398 tests pass. |
| 2026-05-26 | **Focus session — proper implementation.** The `FocusModeWorkflow` agentic service + `FocusSessionPlugin` were already wired, but `_parse_focus_session` in `core/intent_recognizer.py` had two defects. (1) **False positive:** the start trigger matched `(?:focus\|...)\s+(?:for\s+\d+\|mode\|on)` — the bare `on` hijacked ordinary speech ("focus on my homework", "let's focus on the bug") into a session start. Dropped the `on` alternative (kept `mode`, so "focus mode"/"deep work mode" still route; "focus mode on" still matches via `mode`). (2) **Dropped argument:** `start_focus_session` declares a `minutes` parameter but the parser always returned `args={}` — the duration only survived because the plugin re-passed raw text to the workflow. Added `_focus_minutes()` (numeric `for 50 minutes`/`2 hours`, bare `for 25`→minutes, `an hour`, `half an hour`, and spoken cardinals `for fifty minutes` — all capped 1–240) so the duration now lands in `args["minutes"]`; absent duration omits the key and the handler defaults to 25. Also broadened verbs (`enable`/`activate`/`put me in`, `turn off` for symmetry with `turn on`) and added "N minutes of focus". New T-4.16. New `tests/test_focus_session_intent.py` (54 cases: start/end/status breadth, minutes extraction incl. cap, the "focus on …" negatives, inert-without-capability). 54/54 pass; the lone `test_routing_snapshots.py::volume_up_steps` failure is pre-existing and unrelated (reproduces with the change stashed). |
| 2026-05-26 | **Focus session — actually block media + notifications.** Bug: during a focus session media kept playing because `FocusModeWorkflow._pause_media` only called `browser_media_service.fast_media_command("pause")`, which reaches **only FRIDAY's own Playwright browser** — Spotify, VLC, a normal browser tab, and every other MPRIS player on the session bus were untouched. Fix in `core/reasoning/agentic_services/focus_mode.py`: `_pause_media` now does two passes — (1) the in-process browser fast-pause (best effort), then (2) `_pause_system_media()`, which enumerates all `org.mpris.MediaPlayer2.*` bus names via `gdbus` `ListNames` and calls `org.mpris.MediaPlayer2.Player.Pause` on each (deduped; DE-agnostic, no `playerctl` dependency; no-op on Windows or when `gdbus` is absent). Media is **not** auto-resumed on focus end (re-blasting audio on a timer while the user is away is worse than a manual resume). Also made the previously-silent notification path diagnosable: `_set_notifications` now captures the `gsettings set show-banners` return code and logs a WARNING on failure or when `gsettings` is missing — the usual cause of "notifications still showing" is the app process lacking a session D-Bus (`DBUS_SESSION_BUS_ADDRESS` unset), which was failing invisibly. T-4.16 updated. New `tests/test_focus_session_media.py` (6 cases: MPRIS parse+dedupe, pause-every-player, browser+sweep both fire, no-op without gdbus, no-op on Windows, survives browser failure). 60/60 focus tests pass; verified live — the real chromium MPRIS player on the bus is now paused on focus start. |
| 2026-05-26 | **STT signal-to-noise pipeline — noisy-room accuracy.** Single speaker in a noisy room was getting mis-transcribed while a silent room stayed accurate. Root cause: the live path used the cheapest possible decode (`beam_size=1, best_of=1`) with `vad_filter=False`, and a crude energy-gate VAD that lets noise into the buffer. Reworked `STTEngine._transcribe_buffer` (`modules/voice_io/stt.py`) around two new helpers: `_estimate_snr_db` (numpy-only per-utterance SNR from 30 ms-window RMS percentiles) and `_build_transcribe_kwargs` (adaptive — greedy when SNR ≥ `stt_snr_noisy_db`/15 dB, beam search + temperature fallback when below; enables faster-whisper's **bundled Silero VAD** via `stt_vad_filter`; biases the decoder with `stt_domain_prompt`; adds hallucination guards `no_speech_threshold`/`log_prob_threshold`/`compression_ratio_threshold`). `_prepare_audio_for_transcription` now DC-removes + RMS-normalizes (`_normalize_level`, gain-clamped, `stt_normalize_audio`) and has an optional spectral-subtraction `_denoise` hook (`stt_denoise`, **off by default**, lazy `noisereduce` import, non-fatal if absent). The quiet-room path is unchanged in cost (still `beam=1`), so no added latency in the common case. Corrected two myths from the source advice: faster-whisper runs on CTranslate2 (not ONNX), and the project already ships Silero VAD (no extra dep). New `config.yaml` keys under `voice.stt_*` (beam_size, beam_size_noisy, snr_noisy_db, vad_filter, domain_prompt, normalize_audio, denoise). New T-10.9. New `tests/test_stt_noise_robustness.py` (10 cases: SNR high/low/short, adaptive greedy/beam/guards, normalize lift/DC/empty, denoise passthrough); existing voice suites green (60/60 across test_whisper, test_stt_barge_in, test_stt_substitutions, test_transcription_entrypoint, test_voice_mode_toggle). |
| 2026-05-29 | **RAG doc-Q&A refusal/conflation + assistant adopting the user's name (live session 14:17–14:19).** Two issues from the same session. **(1) RAG:** with a document loaded into the session RAG, "what do you understand about the document" produced *"I don't have a separate tool for this document, so I can't generate it directly"* — the global `assistant_identity` guard ("never claim an action you don't have a tool for") backfired on doc Q&A — and a second attached file got **conflated** with the first (a resume question answered partly with the earlier Dubai doc, which still lived in conversation history). Fix in `SessionRAG.get_context_block` (`core/session_rag.py`): excerpts are now framed as a `[DOCUMENT Q&A]` block that **explicitly grants the read capability** ("no tool needed … never say you can't") and **pins the answer to the current document** ("if a different document was discussed earlier, ignore it — it is no longer loaded"). **(2) Impersonation:** FRIDAY answered *"I'm Friday, an assistant named Luffy"* — adopting the user's profile name (Luffy) as its own. The abstract "your name is NOT in USER_FACTS" guard wasn't enough for the 0.8B model. Two-layer fix: (a) `assistant_context.build_chat_messages` now **names the user explicitly** in `assistant_identity` ("The user's name is Luffy. You are NOT Luffy …"); (b) new deterministic `strip_user_impersonation(text, user_name)` in `core/model_output.py` rewrites leaked self-identification ("an assistant named Luffy" → "named FRIDAY", "I am Luffy" → "I am FRIDAY") — applied in `modules/llm_chat/plugin.py` to each **spoken** sentence (so TTS never voices it) AND the returned text, with a new `_user_name()` helper reading the `user_profile` name. Legitimate uses (addressing the user by name) are left untouched. T-2.4b + T-7.4 updated. New `tests/test_user_impersonation.py` (8 cases: self-intro rewrite, legitimate-use passthrough, case-insensitive, empty-name/non-string no-op) + new assertions in `tests/test_session_rag.py` (capability-grant + current-doc pin) and `tests/test_assistant_context.py` (identity names the user). Touched suites green (33 pass; the 1 `test_session_rag_doc_intent.py::open calculator` failure + 3 `test_assistant_context_profile_injection.py` failures are pre-existing on HEAD, unrelated — confirmed via `git stash`). |
| 2026-05-29 | **Impersonation guard: de-hardcode the assistant name (follow-up).** The 2026-05-29 impersonation fix interpolated the user's name dynamically but hardcoded the assistant's name as the literal "FRIDAY" in both the prompt guard (`core/assistant_context.py`) and the scrubber's replacement (`modules/llm_chat/plugin.py`) — so renaming the persona would have left the assistant re-adopting/mismatching names. Added `PersonaManager.assistant_name()` (classmethod, reads `name:` from `config/personas/default.yaml`, falls back to "FRIDAY") as the single source of truth. `assistant_context._assistant_name()` and `llm_chat._assistant_name()` both resolve through it via lazy import (no hard persona dependency for lightweight test apps), and the resolved name is passed to `strip_user_impersonation(text, user_name, assistant_name)` (param already existed, default kept as a safe fallback). The prompt guard is now skipped when `profile_name == assistant_name` (case-insensitive) so a user literally named after the assistant can't produce a contradictory "You are NOT X. Your name is X" prompt. Both names are now resolved live — user from profile, assistant from persona. T-7.4 updated. New `test_assistant_name_is_not_hardcoded` in `tests/test_user_impersonation.py` (9 cases total); 22 pass across the three touched suites. |
| 2026-05-29 | **Brightness now works on Windows (was Linux-only).** `modules/system_control/brightness.py` had only Linux backends (`brightnessctl` → `light` → `/sys/class/backlight`), so on Windows every "set brightness" returned the "install brightnessctl" failure. Added a Windows backend `_via_windows_wmi(target)` that drives the built-in panel via `WmiMonitorBrightnessMethods.WmiSetBrightness` through PowerShell `Invoke-CimMethod` (works on Windows PowerShell 5.1 + PS7). It runs first **only** when `platform.system()=="Windows" and shutil.which("powershell")` — the `which("powershell")` gate means the existing Linux backend tests (which monkeypatch `which`→None) are untouched on both OSes, so **Linux behaviour is byte-for-byte unchanged**. Desktops / external-only setups (no `WmiMonitorBrightnessMethods` instance) surface an honest failure with a Windows-appropriate hint ("…external monitors need their own controls (or a DDC/CI tool)") rather than a fabricated success. No DE-refresh nudge on Windows (the OS repaints its own slider). T-4.2 updated. 2 new tests (`test_windows_uses_wmi_backend`, `test_windows_failure_is_honest`); 12/12 brightness tests pass; Linux path re-verified in isolation. |
| 2026-05-29 | **Focus session: cross-platform DND + stop-all-media + block browser media.** Three gaps closed in `core/reasoning/agentic_services/focus_mode.py` + `modules/browser_automation/service.py`. **(1) Do Not Disturb on Windows:** `_set_notifications`/`_restore_notifications` now dispatch by platform — Linux keeps `gsettings show-banners`; Windows flips `HKCU\…\PushNotifications\ToastEnabled` (0=off) via `winreg`, restoring the prior value on end. `_notifications_supported()` returns True on Windows now, so the start reply honestly claims DND on both OSes. **(2) Stop all media on Windows:** `_pause_system_media` dispatches — Linux keeps the `gdbus` MPRIS `Pause` sweep; Windows adds `_pause_windows_media()`, which pauses every System Media Transport Controls session via WinRT (`GlobalSystemMediaTransportControlsSessionManager` → `TryPauseAsync`) driven from PowerShell. `TryPauseAsync` *pauses* (doesn't toggle), so it won't resume FRIDAY's own browser that was just paused. **(3) Block browser media during focus:** new `BrowserMediaService._focus_blocks_media()` (lazy-imports `FocusModeWorkflow.is_active()`); `_do_play_youtube`, `_do_play_youtube_music`, and play/resume in `_do_browser_media_control` refuse with "the only sound should be me" while focus is active. The gate sits at the `_do_*` chokepoint so every routing path (intent→workflow, chat preflight, re-open) is covered; pause/stop/seek/next stay allowed so focus's own pause keeps working. Start message reworded to state DND + media stop + YouTube block. **Linux unchanged** — all platform branches key off `platform.system()`, Linux paths are identical to before. T-4.16 + T-4.2 updated. Tests: rewrote `test_pause_system_media_noop_on_windows` → `test_pause_system_media_uses_smtc_on_windows` + `_without_powershell`; added `test_notifications_supported_per_platform`, `test_set_notifications_dispatches_to_windows`, 4 browser-gate tests (`test_play_youtube_refused_during_focus`, `_music_`, `test_resume_refused_but_pause_allowed_during_focus`, `test_focus_blocks_media_reads_focus_state`); updated the two `test_focus_and_lock_fixes.py` start-message tests to assert DND on both OSes. 88 pass across focus + browser suites (the 3 pre-existing `_prepare_launch_profile_settings` cloned/isolated failures are unrelated — confirmed via `git stash`). |
| 2026-05-29 | **Session RAG → production-grade hybrid retrieval + cross-document bleed fix (live session 19:25–19:30).** Loading `PRD.md` and asking "what did you understand about the document" returned a summary of the *previously* loaded `Advanced_System_Documents.md` (tenant_id/plan_type/quota_config). Two root causes, both fixed. **(1) Retrieval was keyword-only and collapsed on overview questions.** `SessionRAG` (`core/session_rag.py`) is now **hybrid**: BM25 (now with proper length-normalization, `b=0.75`) fused with dense cosine over the already-resident `all-MiniLM-L6-v2` embedder via **Reciprocal Rank Fusion** — no new model is loaded, and it degrades cleanly to BM25-only when sentence-transformers is absent or only the `HashEmbedder` is available (`load_file` reports `(hybrid)`/`(keyword)`). Chunks are embedded once at load (heading + body). Overview-style queries (`_OVERVIEW_RE`) lead with the document's opening section for grounding then append the strongest relevant chunks (`_ordered_chunks`); `get_context_block` widens `top_k` to 6 for overview vs 4 otherwise. **(2) Stale conversation history dominated the fresh document for the 0.8B chat model.** New `AssistantContext.prune_document_turns()` drops prior `[Re: …]`/`[Load file: …]` turns and the assistant reply that followed each when a new file loads (called from `FridayApp.load_session_rag_file`). The excerpts are also folded into the **current user turn** ("Using only the document excerpts above, answer this question:") instead of being buried in the system prompt, where the small model ignored them. MarkItDown conversion verified correct (not the bug). **Linux unchanged** — no platform branches touched; embedder reuse is the same singleton memory recall already uses. New T-2.4c. New `tests/test_session_rag_history_bleed.py` (3 cases) + 3 new `tests/test_session_rag.py` cases (hybrid-mode report, dense paraphrase ranking, fake-embedder fusion); 24 pass across the three RAG suites. End-to-end two-document switch re-verified live: PRD.md answer contains PRD content, zero leak of the prior doc. |
| 2026-05-29 | **Identity prompt v3: stop the assistant parroting its own guard + role-impersonating the user (live session 19:56).** After loading `PRD.md`, "what did you understand about the document" opened with *"Understood. I am Friday, the assistant, not the user. I am an Software Engineer based in Nellore, and I care deeply about System Design."* — the model parroted its system-prompt guard verbatim **and** then spoke the user's `USER_FACTS` (role/location/cares-about) in first person. Root cause: the v2 `assistant_identity` in `core/assistant_context.py` had grown into a wall of repetitive ALL-CAPS negatives ("YOU ARE NOT THE USER", "Your name is NOT in USER_FACTS", "never call yourself <name>/never say I am <name>"), which on the 0.8B chat model both leaked as output and **negatively primed** the very tokens it forbade (pink-elephant effect). Fix: rewrote `assistant_identity` to state the identity **once, positively, and calmly**, keeping only the load-bearing rules; trimmed the per-name guard to a single "The user's name is X. You are NOT X — that's the person you're assisting. Your name is <bot>." (dropped the repeated "never say I am X" tail); simplified the `USER'S PROFILE` header to drop the adjacent "NOT you" repetition. Added a deterministic net `_strip_guard_leak()` in `core/model_output.py`, run first inside `strip_user_impersonation` (name-independent), that scrubs a parroted *"(Understood.) I am <bot>, the assistant, not the user."* sentence before display/TTS. **Cross-platform**: pure prompt/text logic, no `platform.system()` branch — Linux identical. Pinned test invariants ("never speak as the user", "do not bullet-list profile fields", "never claim to have completed an action you don't actually have a tool for", "The user's name is Luffy", "You are NOT Luffy") all preserved. 4 new cases in `tests/test_user_impersonation.py` (parroted-guard strip, name-independent, guard+name combo, normal "the user" sentence untouched); 22 pass across `test_user_impersonation.py` + `test_assistant_context.py`. |
| 2026-05-29 | **HUD layout: weather error stretched the left column off-screen.** When the weather fetch failed (no network), `WeatherFetchThread` emitted the raw exception string into the panel's word-wrapped detail label. A requests network error is a single very long unbreakable token (`HTTPSConnectionPool(host='api.open-meteo.com'…url:/v1/forecast?latitude=…)`); a word-wrapped `QLabel` can't break inside a word, so its minimum width ballooned and the left column ate space the 3:6:3 `setColumnStretch` should have given the center/right columns — visible as the growing `minimum size` in the `QWindowsWindow::setGeometry` warnings (1594→1664→1882). Fixed in `gui/hud.py`: new `_weather_error_message(exc)` maps the exception to a short, space-containing phrase ("Network unavailable", "Weather service timed out", …) instead of dumping the raw string; new `_clamp_detail()` defensively hard-breaks any overlong token and caps length so no future content from any source can stretch the column. **Cross-platform**: pure formatting logic, no `platform.system()` branch — Linux runs the identical path, weather panel behaviour is otherwise unchanged. New tests in `tests/test_hud.py` (`_weather_error_message` short/spaced + fallback, `_clamp_detail` token-break/cap/passthrough); 11/11 HUD tests pass. |
| 2026-05-30 | **Cross-platform hardening pass (open-source launch, Phase 1).** Repo-wide audit + fixes ahead of the public launch. **(1) Subprocess encoding parity:** added `encoding="utf-8", errors="replace"` to the remaining `subprocess.run(..., text=True)` calls that lacked it — the genuine cross-platform bugs were `run_python` (`modules/code_execution/plugin.py`, runs via `sys.executable` on every OS) and the MCP stdio bridge (`modules/mcp_client/plugin.py`); also swept the Linux-only `brightness.py` notify/backend calls and `vision/smart_error_detector.py` for consistency (Windows' cp1252 default raises `UnicodeDecodeError` on UTF-8 output). Most call sites already had it — the audit's grep over-counted by matching only the `text=True` line. **(2) `core/shell_prefix._preferred_shell()`** now returns `COMSPEC` on `os.name == "nt"` instead of a non-existent `/bin/sh` (defensive — the PTY/sync paths are already POSIX-gated). **(3) `scratch/`** (dev throwaway scripts, already in `.gitignore` but committed before the rule) **untracked** via `git rm --cached` — `scratch/test_llm.py` instantiated a model at import and was the lone `pytest --collect-only` error that would otherwise ship in a fresh clone and break CI. **(4) Real Windows test bug fixed:** `tests/test_clap_detector.py::test_launch_friday_uses_project_venv_and_main_entrypoint` unconditionally asserted `start_new_session is True` (POSIX-only) — now platform-branched to assert `DETACHED_PROCESS` creationflags on Windows, matching the already-correct `launch_friday`; also genericized two sample command strings off the hardcoded `/home/tricky/...` path. **(5)** New **[docs/platform_support.md](platform_support.md)** — honest feature-parity matrix (Linux/Windows/macOS) with Windows-specific notes and a contributor checklist. Linux behaviour byte-for-byte unchanged throughout. `git`-verified the 10 remaining failures on this Windows dev box (`/bin/bash`, `.venv/bin`, PIL) are pre-existing on HEAD, unrelated. |
| 2026-05-30 | **Production-grade intent recognition: measurement harness + 8 routing fixes (launch, Phase 2).** Made the deterministic intent layer measurable and regression-proof, then fixed the bugs the measurement surfaced. **Tooling (model-free, CI-gated):** (1) **intent eval harness** — `scripts/diagnostics/intent_eval.py` runs a golden corpus (`tests/intent_corpus/*.yaml`, ~100 cases / 13 domains) through `IntentRecognizer.plan()` and reports per-domain recall + negative-accuracy; gate is `tests/test_intent_eval.py`. (2) **conflict/overlap detector** (`--conflicts`) runs every parser independently via the new shared `IntentRecognizer._clause_parsers()` (refactored the inline `_parse_clause` tuple into one source of truth) and flags multi-matcher utterances + latent poaching; gate is `tests/test_intent_conflicts.py` (asserts zero latent poaching, and that the only overlap is the documented `search_indexed_files`⇄`search_file` filename split). (3) **routing observability** — `scripts/diagnostics/routing_stats.py` summarizes the live `[ROUTE]` log (source distribution, fallback rate, latency p50/p95, tool mix); tests in `tests/test_routing_stats.py`. (4) **calibrated confidence** — `core/planning/intent_engine.py` now reads an optional per-action `confidence` (default 1.0 → zero behaviour change) so a parser can route an ambiguous match into the existing confirmation band instead of dispatching silently. **Routing fixes (each fails on pristine HEAD via the corpus):** "end the focus session" / "focus session status" no longer mis-route to `start_focus_session` (end regex now accepts `the/this`, status regex accepts the `session/mode` noun); "take a note" → `save_note` not `start_dictation` (dictation now requires `note taking`, not a bare `note`); "what are my notes" / "show me my notes" → `read_notes`; "export my memories" (plural) → `export_memory`; "how much ram am I using" → `get_cpu_ram`; "is it going to rain today" → `get_weather`; "give me a literature review of X" → `research_topic`. Touched T-4.16 (focus) behaviour; affected suites green (the 3 pre-existing `test_routing_snapshots.py` failures — launch_firefox/volume_up_steps/multi_open_then_time — fail identically on pristine `intent_recognizer.py`, confirmed via `git stash`, unrelated). **Cross-platform:** pure-Python regex/log logic, no `platform.system()` branch — Linux identical. Audit refreshed: [docs/intent_routing_audit.md](intent_routing_audit.md) §Addendum 2026-05-30. |
| 2026-05-31 | **Reminder/calendar datetime machinery → shared `slot_extractors`; + slot-fill templates (launch-hardening Phase 3 / §5.4 Steps 1-2).** **Step 1 (behaviour-preserving refactor):** the full production datetime parser that lived inline in `modules/task_manager/plugin.py` (`_parse_datetime_parts` / `_parse_date` / `_parse_time` / `_parse_word_time` / `_apply_meridian` / `_combine_date_time` + the 8 regexes & `NUMBER_WORDS`/`MINUTE_WORDS`/`MONTHS`/`WEEKDAYS` tables) moved to `core/planning/slot_extractors.py` as pure functions; the plugin methods are now thin delegators that pass a patchable `now=` so the monkeypatched-clock tests stay deterministic. `extract_datetime` was upgraded to build on the rich parser (gaining spoken numbers, MM/DD + ISO dates, 'January 5th', compact '1530', o'clock) while keeping its word-number/'week' relatives + noon/midnight. **Zero behaviour change** — the live reminder/calendar dispatch is byte-for-byte unchanged (the 13 `test_workflow_orchestration.py` failures on this Windows box fail identically on baseline — Windows timer `OverflowError` + pre-existing file/browser/routing cases — confirmed via `git stash`). **Step 2 (additive, NOT yet live):** new `core/workflows/templates/set_reminder.yaml` + `create_calendar_event.yaml` slot-fill templates using `extract_with: extract_datetime`, backed by three template-internal capabilities (`extract_datetime`, `create_reminder`, `schedule_calendar_event`) that wrap the unchanged scheduling core (`create_calendar_event`) with no slot-fill state. These are registered + compiler-tested only; **the ReminderWorkflow/CalendarEventWorkflow delegation shims remain the live path** — the Step 3 dispatch cutover (which reverses the Track 5.2b decision and rewrites the reminder tests) is deferred pending explicit go-ahead. The three wrap capabilities are intentionally NOT given IntentRecognizer patterns (the user-facing `set_reminder`/`create_calendar_event` intents already route; the wrappers only run as resolved template steps). **Cross-platform:** pure-Python regex/datetime logic, no `platform.system()` branch — Linux identical. Tests: 15 `test_datetime_extractor` + 10 new `tests/test_reminder_calendar_templates.py` + 90 across template/slot suites, all green. |
| 2026-05-31 | **Reminder slot-fill cut over to the `set_reminder` YAML template; `ReminderWorkflow` retired (launch-hardening §5.4 Step 3 — reminders).** The live reminder follow-up state machine is now the declarative `set_reminder` template instead of the `ReminderWorkflow` delegation shim. `TaskManagerPlugin.handle_set_reminder` parses the first turn richly (unchanged `_parse_reminder_request`); a complete date+time / relative offset schedules immediately via the shared `_schedule_reminder` (which uses the unchanged `_create_calendar_event` core), otherwise it seeds whichever half it has and calls `WorkflowOrchestrator.start_template_slot_fill('set_reminder', …)`. `set_reminder.yaml` (v0.2.0) uses **two** ask-steps — `date` then `time` — backed by new `extract_reminder_date` / `extract_reminder_time` capabilities, deliberately preserving the pre-cutover two-phase behaviour (ask date → ask time; bare-hour answers like 'four' → 4 o'clock via `allow_bare`; ambiguous past-morning-hour-today → afternoon bump via `combine_date_time`); the schedule step runs the `create_reminder` capability. Removed `handle_reminder_followup`, `_handle_reminder_parts`, `_save_reminder_workflow`, `_clear_reminder_workflow`, the `REMINDER_WORKFLOW` const, and the `ReminderWorkflow` class + its registration. **UX deltas (accepted):** the both-missing first prompt is now 'What date should I remind you?' (was the combined 'When should I remind you? …'); a date+time given as one *follow-up* fills only the date then asks for time (first-sentence-complete still one turn). **Calendar half deferred:** `CalendarEventWorkflow` (Google-Calendar backend) is intentionally left untouched — the local `create_calendar_event` template would silently change the backend (dual-backend + capability-name collision); needs its own decision. **Cross-platform:** pure-Python regex/datetime + template logic, no `platform.system()` branch — Linux identical. T-6.1 updated. Tests: rewrote the 5 reminder flow tests in `test_workflow_orchestration.py` to the template path + added `_RouterCapabilityExecutor`/`_RouterOrderedExecutor` to its `build_test_app` so templates can run; updated `test_reminder_calendar_templates.py` (11) for the two-phase template. Full `test_workflow_orchestration.py` 13→12 pre-existing failures (the only delta: `test_reminder_accepts_bare_hour` now passes); 13 reminder + 118 across template/calendar/slot/datetime suites green; baseline-confirmed zero new failures via `git stash`. |
| 2026-05-31 | **Local calendar-event capabilities removed — Google Calendar owns calendar events now.** Per user decision, ripped out TaskManager's LOCAL calendar-event path so calendar events live only in Google Calendar (WorkspaceAgent). Removed the `create_calendar_event`, `move_calendar_event`, `cancel_calendar_event`, `list_calendar_events`, and `schedule_calendar_event` capabilities + handlers + the never-live `create_calendar_event.yaml` template + the `extract_datetime` capability, and the orphaned helpers (`handle_*`, `_parse_move_target_time`, `_reschedule_calendar_event`, `_extract_move_target`/`_clock_target`/`_cancel_target`, `_format_event_confirmation`). The name collisions now resolve cleanly: `create_calendar_event` / `cancel_calendar_event` route to the WorkspaceAgent (Google) handlers, and the `move/reschedule` intent patterns were **retargeted** to Google's `update_calendar_event` (which was built for 'move my 3pm to 4pm'). **Reminders are kept** (a separate local feature with local notifications): `set_reminder` (the §5.4 Step 3 two-phase template), `list_reminders`, `create_reminder` and the reminder firing/notification core are unchanged. The listing/briefing helpers (`_render_upcoming`, `get_unfinished_task_briefing`) were simplified to reminders-only. **Trade-off (user-accepted):** reminders are no longer voice-cancellable/movable (those handlers were dual-purpose and went to Google) — a `cancel_reminder` could be re-added later if wanted. Shared text helpers `_extract_event_title` / `_strip_temporal_expressions` / `_strip_temporal_suffix` were **retained** in TaskManager because the Google path reuses them for event-summary extraction (`WorkspaceAgent._extract_summary_from_text`, alongside the existing `_parse_datetime_parts`/`_combine_date_time` reuse). **Cross-platform:** pure-Python, no `platform.system()` branch — Linux identical. Tests: removed the 6 local calendar-event feature tests in `test_workflow_orchestration.py`, rewrote `TestListDisambiguation`→`TestListReminders` in `test_batch2_routing.py`, and trimmed `test_reminder_calendar_templates.py` to the live reminder template. `test_workspace_calendar.py` (Google) stays green (regression-caught: restored `_extract_event_title` after an over-removal broke it). Full `test_workflow_orchestration.py` still 12 pre-existing env failures (zero new); intent eval/conflict gates + 103 across template/workspace/routing/datetime suites green. Also updated `data/tool_catalog.yaml` (dropped local-only calendar entries). |
