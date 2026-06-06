---
name: memory_manager
description: "Show, save, forget, wipe, and export FRIDAY's memory about you"
plugin_module: modules/memory_manager
capabilities:
  - name: show_memories
    description: "Show everything FRIDAY knows about you — profile and preferences"
    aliases:
      - "what do you know about me"
      - "show my memories"
      - "what do you remember"
      - "what have you learned about me"
      - "my preferences"
  - name: forget_memory
    description: "Forget a specific fact about you by key name"
    aliases:
      - "forget my location"
      - "delete that memory"
      - "stop remembering"
      - "remove that fact"
  - name: wipe_memory_init
    description: "Erase everything FRIDAY knows about you (requires confirmation)"
    aliases:
      - "forget everything you know about me"
      - "wipe your memory"
      - "start fresh"
      - "reset your memory"
  - name: export_memory
    description: "Export all stored memories to a JSON file"
    aliases:
      - "export my memory"
      - "backup my memory"
      - "save my memories to file"
---

# Memory Manager

Manages FRIDAY's persistent knowledge about you across sessions.

## Memory layers

1. **User profile** (`user_profile` namespace) — name, role, location, preferences. Written by onboarding. Shown in the "About you" section of `show_memories`.
2. **Session facts** (semantic memory via MemoryFacade) — things you've explicitly told FRIDAY. Shown in "You told me".
3. **Knowledge graph** (`entities` table) — structured entities and relationships.

## Capabilities

### show_memories
**You say:** "Friday, what do you know about me?"
**Expected:** Two-section response: "About you:" (profile) + "You told me:" (facts).

### wipe_memory_init (two-step)
**You say:** "Friday, forget everything you know about me"
**FRIDAY replies:** Confirmation prompt
**You say:** "yes, wipe everything"
**Expected:** All facts, memories, and entities cleared.

### export_memory
**You say:** "Friday, export my memory"
**Expected:** JSON file at `~/friday_memory_<timestamp>.json`

## CLI admin

```
python scripts/memory_admin.py inspect
python scripts/memory_admin.py list --namespace user_profile
python scripts/memory_admin.py export dump.json
python scripts/memory_admin.py wipe --confirm
```
