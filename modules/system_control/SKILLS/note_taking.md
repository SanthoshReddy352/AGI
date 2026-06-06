---
name: note-taking
description: "Obsidian-style local Markdown notes — quick capture, daily log, link, search."
source: "hermes-agent skills/note-taking (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - save_file
  - read_file
  - llm_chat
---

# note taking

## When to use

The user wants to jot something down for later, append to a running log, or search across personal notes. Triggers: "make a note that…", "add to today's log…", "what did I write about X".

Distinct from `remember X` (which writes to the `facts` table for FRIDAY's memory). Note-taking writes Markdown files the user owns and can edit outside FRIDAY.

## Layout

Default vault: `~/Documents/FRIDAY/notes/` (override with `notes.vault_path` in `config/settings.yaml`).

```
notes/
├── inbox/                # quick captures, one file per day:
│   └── YYYY-MM-DD.md
├── topics/               # long-form per-topic notes:
│   └── <slug>.md
└── daily/                # explicit daily logs with date headers
    └── YYYY-MM-DD.md
```

## How to use

### Quick capture ("make a note")
1. Resolve target → `inbox/<today>.md`.
2. Append `- HH:MM  <captured text>` so each capture is one bullet.
3. Reply "Noted." Don't echo the full note unless asked.

### Daily log ("add to today's log")
1. Target → `daily/<today>.md`.
2. If the file doesn't exist, create it with `# YYYY-MM-DD` header.
3. Append the user's text under a `## HH:MM` subheading.

### Topic note ("note on X")
1. Slugify the topic → `topics/<slug>.md`.
2. If new, scaffold with `# <Topic>\n\n## Notes\n`.
3. Append a timestamped bullet under `## Notes`.

### Search ("what did I write about X")
1. Walk the vault, grep case-insensitive across all `.md` files.
2. For each hit, return: file path, line number, the matching line (truncate >100 chars).
3. Cap at 10 results; tell the user the total count.

## Examples

- "Friday, make a note: investigate the FTS5 trigger order."
- "Friday, add to today's log: pair-coded with Sam on the scheduler."
- "Friday, what did I write about Mumbai?"

## Common failures and recovery

- **Vault path doesn't exist** → create it on first use; no warning.
- **File locked by another editor** → retry once after 100 ms; on persistent lock, write to `inbox/<today>-conflict.md`.
- **Search returns 0 hits but user expected matches** → suggest checking spelling and offer to broaden to substring match.
