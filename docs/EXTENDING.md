# FRIDAY — Create Your Own Tools & Skills

This is the hands-on guide for **developers** extending FRIDAY by hand. (If you want
the *assistant* to extend itself at runtime, see
[SELF_MODIFICATION.md](SELF_MODIFICATION.md).)

**Decide which you need:**

| You want to… | Build a… | Where |
|---|---|---|
| Add a capability that doesn't exist (call an API, run a computation, drive a device) | **Tool** (Python) | `friday/tools/<name>.py` |
| Capture a repeatable *procedure* over existing tools | **Skill** (Markdown) | `friday/skills/<name>/SKILL.md` |

Rule of thumb: **a skill if existing tools can already do it; a tool only when new code
is required.**

---

## 1. Write a tool

A tool is a Python module in `friday/tools/` that exposes a `register(registry)`
function. It's auto-discovered at startup — no list to edit, no intent regex. The
model routes to it purely from the **name + description + JSON-Schema parameters**.

### Minimal example

`friday/tools/coin.py`:

```python
"""Coin flip tool."""
from __future__ import annotations

import secrets

from friday.core.tools import ToolRegistry, ToolResult


def _flip(_args: dict) -> ToolResult:
    side = secrets.choice(["heads", "tails"])
    return ToolResult(ok=True, content=f"It's {side}.", data={"side": side})


def register(registry: ToolRegistry) -> None:
    registry.register(
        "flip_coin",
        "Flip a fair coin and report heads or tails.",
        {"type": "object", "properties": {}},
        _flip,
    )
```

That's it. Restart the app (or it's loaded on next boot) and the model can call
`flip_coin`.

### A tool with arguments

```python
def _convert(args: dict) -> ToolResult:
    amount = args.get("amount")
    if amount is None:
        return ToolResult(ok=False, content="", error="'amount' is required")
    return ToolResult(ok=True, content=f"{amount} USD ≈ {amount * 83:.2f} INR")


def register(registry: ToolRegistry) -> None:
    registry.register(
        "usd_to_inr",
        "Convert an amount of US dollars to Indian rupees.",
        {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "description": "amount in USD"},
            },
            "required": ["amount"],
        },
        _convert,
    )
```

### The contract

| Piece | Rule |
|------|------|
| `register(registry)` | The one required entry point. Call `registry.register(...)` (one or many tools). |
| **name** | short `snake_case`; unique. |
| **description** | This is what the model reads to decide *when* to call the tool. Be specific and trigger-phrase aware. |
| **parameters** | JSON Schema, `type: "object"`. Use `properties` + `required`. Empty = `{"type":"object","properties":{}}`. |
| **handler** | `def handler(args: dict) -> ToolResult`. Return, never raise, on expected errors. |
| **ToolResult** | `ok`, `content` (what the model sees), `data` (structured, optional), `error` (when `ok=False`). |

### Destructive tools (approval-gated)

If a tool changes the system (writes/deletes files, runs shell, mutates a device), mark
it destructive so it goes through the user-approval round-trip:

```python
registry.register("wipe_thing", "Delete the thing.", schema, _wipe, destructive=True)
```

### Degrade gracefully

If a tool needs an external binary or service, **check and return a clear message** —
don't crash. This is a project-wide convention:

```python
import shutil

def _scan(args: dict) -> ToolResult:
    if not shutil.which("nmap"):
        return ToolResult(ok=False, content="", error="nmap not installed — `sudo apt install nmap`")
    ...
```

### Cross-platform

Guard OS-specific behavior with `platform.system()` / `os.name`, and pass
`encoding="utf-8", errors="replace"` to any `subprocess.run(..., text=True)`.

### Test it

Add `friday/tests/test_<area>.py`. Tools are easy to unit-test because they're plain
functions returning `ToolResult`:

```python
from friday.core.tools import ToolRegistry
from friday.tools.coin import register


def test_flip_coin():
    reg = ToolRegistry()
    register(reg)
    result = reg.execute("flip_coin", {})
    assert result.ok and result.data["side"] in ("heads", "tails")
```

Run: `python -m pytest friday/tests/ -q`.

---

## 2. Write a skill

A skill is a folder with a `SKILL.md` — YAML frontmatter + a markdown procedure that
orchestrates **existing** tools. No code. Drop it in `friday/skills/` (bundled) or
`~/.friday/skills/` (your own).

`friday/skills/morning-brief/SKILL.md`:

```markdown
---
name: morning-brief
description: >
  Give a morning briefing. Use when the user says "morning brief", "what's my day
  look like", or asks for a daily summary.
platforms: [linux, macos, windows]
version: 1.0.0
category: productivity
metadata:
  hermes:
    tags: [daily, summary]
---

# Morning Brief

## When to Use
The user wants a quick start-of-day summary.

## Procedure
1. get_weather for the user's city.
2. get_news for "technology" and "world" (top 3 each).
3. calendar_agenda for today.
4. list_tasks and list_reminders.
5. Summarize as a short, friendly briefing — headers-free, tight bullets.

## Verification
- Weather, news, agenda, and tasks are all present.
- No raw tool output dumped; it's synthesized.
```

The `description` is the key field — the model reads it (in the catalog) to decide
whether to load the skill with `use_skill`. See [SKILLS.md](SKILLS.md) for the full
format, template variables (`${SKILL_DIR}`, `${SESSION_ID}`), and the inline-shell
option.

---

## 3. Letting the assistant build them for you

Everything above can also happen at runtime, driven by the model:

- "Make a skill for my morning briefing" → `create_skill` writes it to `~/.friday/skills/`.
- "Make a tool that converts currencies" → `create_tool` writes + hot-loads Python to
  `~/.friday/tools/` (approval-gated).

See [SELF_MODIFICATION.md](SELF_MODIFICATION.md) for how that works and the safety model.

---

## 4. Checklist

- [ ] Tool file in `friday/tools/` with a `register(registry)` function.
- [ ] Clear `description` + JSON-Schema `parameters`.
- [ ] `destructive=True` if it changes the system.
- [ ] Graceful "install X" message if it needs a missing binary.
- [ ] Cross-platform guards where relevant.
- [ ] A test in `friday/tests/`; `python -m pytest friday/tests/ -q` green.
- [ ] (Skill instead?) `SKILL.md` with a trigger-rich `description`.

## 5. See also

- [SKILLS.md](SKILLS.md) · [SELF_MODIFICATION.md](SELF_MODIFICATION.md) ·
  [ARCHITECTURE.md](ARCHITECTURE.md) · [../CLAUDE.md](../CLAUDE.md)
