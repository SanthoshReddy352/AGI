# Demo video script — "Where's My Context?"

Two videos, **one recording flow**. Record the whole thing once on the **self-hosted**
backend (Track A), then re-shoot only the 30-second "Backend → Cloud" beat for the
**Cloud** submission (Track B). Target length: **2–3 minutes**.

**Before you hit record**
- `python scripts/seed_demo_memory.py --reset` → a clean, rich graph that tells one story.
- Settings → MCP → Cognee → confirm **Connected**. Toggle on **Auto-ingest chats** and
  **Recall in chat** (for the airtight fresh-chat beat).
- Have the Memory tab and a fresh Chat tab ready.

---

## Scene 1 — The hangover (0:00–0:20)
**On screen:** the Chat view, a brand-new session.
**Do:** type *"which database engine do I favour?"* — but first show Namma's **old**
self with keyword-only memory drawing a blank (or narrate it).
**Say:** "Namma Agent's memory used to be keyword search over SQLite. Ask it something
reworded and the context is just… gone. Classic hangover. Let's fix that with Cognee."

## Scene 2 — The money shot (0:20–0:50)
**On screen:** Memory tab → **Keyword vs Semantic** panel.
**Do:** type *"which database engine do I favour?"* → **Compare**.
**Point at:** the left card ("Keyword search — No matches"), then the right card
("Cognee — your preferred graph database is **Kuzu**").
**Say:** "Same question, two engines. Keyword search has nothing — I never typed
'engine'. Cognee answers by *meaning*. That's the whole point."

## Scene 3 — The living graph (0:50–1:25)
**On screen:** Memory tab → the **knowledge graph**.
**Do:** drag a node, scroll to zoom, hover to trace neighbours; point at the entities
(me → Namma Agent → Python → Cognee → the hackathon).
**Say:** "This is my memory as a graph — people, projects, tools, all linked. Now watch
it grow." → go to **Remember**, untick *Build into graph* (session), add two quick
facts; switch to **Improve memory** → **Consolidate N into graph** → back to the graph,
**Refresh**: new nodes appear.
**Say:** "Remember, recall, **improve**, forget — the full memory lifecycle, all from
here. Consolidate runs Cognee's cognify pipeline; the graph tightens live."

## Scene 4 — It remembers *you* (1:25–2:00)
**On screen:** a **brand-new** Chat session.
**Do:** type *"what do you know about me, and what am I building?"*
**Point at:** Namma calling **`mcp_cognee_recall`** (visible tool call), then answering
from the graph — "You're Santhosh, building Namma Agent in Python, integrating Cognee…"
**Say:** "This is the part that matters — Cognee isn't a settings page, it's wired into
the conversation. Fresh session, no history, and Namma still knows me — because it
recalled from the graph."

## Scene 5 — Forget + the close (2:00–2:20)
**Do (optional):** Memory → **Forget** one item / show the danger-zone, graph updates.
**Say:** "Remember. Recall. Improve. Forget. A complete memory lifecycle, powered by
Cognee — Namma Agent never wakes up with a hangover again."

---

## Track B re-shoot — Cognee Cloud (30s)
**Say:** "Same app, same code — now on managed Cognee Cloud."
**Do:** Settings → MCP → Cognee → **Backend → Cognee Cloud** → it's connected → open the
Memory tab → the graph renders (synced from the cloud REST API) → run one recall.
**Say:** "One config entry. Zero local infra. Every op — remember, recall, improve,
forget — running against Cognee Cloud, with the exact same Memory tab."

## Capture checklist
- [ ] Money shot (keyword empty / Cognee answers)
- [ ] Graph: drag/zoom + grow-on-consolidate
- [ ] Fresh-chat recall with the **visible** `mcp_cognee_recall` call
- [ ] All four ops named on screen
- [ ] Track B: the one-click Backend switch + cloud graph
