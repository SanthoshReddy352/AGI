# Recording guide — exact, click-by-click

Companion to [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md). This is the "press record and do
exactly this" version. Read Part 0 once, do the setup, then record Part 2 clip by clip.

**The one idea that makes this easy:** you do **not** need two builds of Namma. "Old
Namma" = keyword search over SQLite (still there). "New Namma" = Cognee. They live
side by side in the Memory tab's **Keyword vs Semantic** panel — so "old vs new" is a
single, labeled, deterministic screen. (Part 4 also gives a more dramatic toggle
method if you want it.)

---

## Part 0 — One-time setup (do this before recording)

### 0.1 Recording tools (Windows)
- **Screen recorder:** OBS Studio (free). Add a **Display Capture** or **Window
  Capture** of your browser. Output: **1920×1080, 30 fps, MP4**.
- **Cursor highlight (highly recommended):** Microsoft **PowerToys → Mouse
  utilities → Mouse Highlighter** (highlights clicks) + **Find My Mouse**. Turn them on.
- **Audio:** record narration **separately** as a voice-over after you have the
  picture — much cleaner than talking while clicking. (Or use OBS mic track and
  re-do takes.)
- **Browser:** Chrome/Edge, **fresh profile**, zoom **100%**, bookmarks bar hidden,
  press **F11** for fullscreen so there's no address bar in frame.

### 0.2 Start everything (self-hosted / Track A)
```powershell
# 1. Docker + Ollama + the cognee image (first time only; ~minutes)
scripts\setup_cognee.ps1

# 2. Start Namma (headless server; open the URL in your fullscreen browser)
python -m namma_agent --server
#    → http://127.0.0.1:8000
```
> If you changed code recently, **restart** this server so it loads the latest backend.

### 0.3 Connect + configure Cognee (in the browser)
1. Click **Settings** (gear) → top group **MCP** → **Cognee** tab.
2. **Cognee memory** card → click **Register Cognee server** → wait for the green dot +
   **Connected** (~20–30 s on first connect; it cold-starts the container).
3. **Behaviour** section — set the toggles for the demo:
   - **Auto-ingest chats** → **ON** (so the graph grows as you chat).
   - **Recall in chat** → **leave OFF** for now (so Namma's recall tool call is
     *visible* on camera). Only turn it ON if your dry run (Part 2, Clip 4) is flaky.
4. Close Settings.

### 0.4 Seed a rich, repeatable graph
In a terminal (keep the server running):
```powershell
python scripts\seed_demo_memory.py --reset
```
This **wipes** Cognee and loads one coherent story (you, Namma Agent, Python, Kuzu,
Cognee, the hackathon, your teammate Aria). Wait for "Seed complete."

5. Open the **Memory** tab (left sidebar, the little graph icon). Click **↻ Refresh**.
   You should see **~20+ entities** with labels like *santhosh, namma agent, python,
   kuzu, cognee, wemakedevs hackathon*. **If the graph is rich, you're ready.**

### 0.5 Pick & verify your money-shot query
The trick: ask about a **seeded** fact using **words you never stored**, so keyword
search finds nothing. Pick one (all verified against the seed), then **test it** in the
Compare panel (Part 2, Clip 2) — the left card must say **"No matches"**:

| Ask (reworded) | Cognee answers (verified) | Old fact it maps to |
|---|---|---|
| `what do I write all my code in?` | **python** | "My favourite programming language is Python" |
| `who helps me with the talking parts of the app?` | **Aria** | "Aria handles the demo narration / voice" |
| `which graph database do I prefer?` | **Kuzu** | "I prefer Kuzu as the graph database" |

> All three were verified live on the self-hosted backend: keyword side = **0 hits**,
> Cognee returns the clean answer shown. `what do I write all my code in?` is the
> best "reworded" example (no shared words with the stored fact).

> Don't *chat* these facts into Namma before recording — that would auto-capture them
> into SQLite and the keyword side would no longer be empty. Seeding only writes to
> Cognee, so keyword stays clean.

---

## Part 2 — Record, clip by clip

Record each clip as its **own file** (easier to retake). Keep clips a few seconds
longer than you need; trim in editing. Where it says **✂ cut**, you'll speed up or
jump-cut that wait in editing so the final video has no dead air.

### Clip 1 — The problem (≈15 s)
- **Screen:** Memory tab, the **Knowledge graph** filling the frame.
- **Do:** slowly **drag one node**, **scroll to zoom** in a touch, **hover** a node to
  light up its links.
- **Narration (VO):** "This is Namma Agent's memory — as a living knowledge graph.
  People, projects, the tools I use, all connected. It didn't always work like this.
  Namma used to remember with plain keyword search… so let's compare."
- **Expected:** smooth graph interaction.
- **Duration:** 12–15 s.

### Clip 2 — The money shot, old vs new (≈25 s) ⭐ the most important clip
- **Screen:** Memory tab → scroll to **Keyword vs Semantic**.
- **Do:**
  1. Click the input, type your chosen query, e.g. `which engine do I use to store relationships?`
  2. Click **Compare**. (Result is ~1–5 s.)
- **Expected:** **Left card "Keyword search — No matches."** **Right card "Cognee
  recall — …Kuzu."**
- **Narration:** "Same question, two engines. On the **left** is exactly how Namma
  remembered before Cognee — keyword search over SQLite. It has nothing, because I
  never typed the word 'engine'. On the **right**, Cognee answers by *meaning* — Kuzu.
  That's the whole point."
- **✂ cut:** none needed (it's fast). If recall is slow, trim the wait.
- **Retake tip:** if the left card shows a hit, your SQLite has that keyword — pick a
  different query from the table.
- **Duration:** 20–25 s.

### Clip 3 — All four ops + the graph grows (≈35 s)
- **Screen:** Memory tab → the **Remember something** and **Improve memory** cards.
- **Do (pre-stage, on camera):**
  1. In **Remember something**, **untick "Build into graph"** (so it's fast session
     memory). Type: `I just started learning Rust for a side project.` → **Remember**.
     (You'll see "Saved to session — consolidate to add it to the graph.")
  2. Type a second one: `My side project is a CLI tool called Tally.` → **Remember**.
  3. Look at **Improve memory** — it now shows a **"2 pending"** badge.
  4. Click **Consolidate 2 into graph**. **✂ cut here** — cognify runs ~10–30 s.
  5. After it finishes ("Consolidated 2 of 2…"), click the graph's **↻ Refresh** →
     **new nodes appear** (rust, tally, side project).
- **Narration:** "Remember, recall, **improve**, forget — the full lifecycle, right
  here. I drop in two quick notes as fast session memory, then **Consolidate** runs
  Cognee's cognify pipeline — entity extraction and linking — and the graph grows. New
  facts, now connected to everything else."
- **✂ cut:** speed the consolidate wait 4–8× or jump-cut to the refreshed graph.
- **Duration:** 30–35 s (after cuts).

### Clip 4 — It remembers *you* in a brand-new chat (≈30 s) ⭐ the "best use" clip
- **Screen:** click **New chat** (sidebar) → a fresh, empty conversation.
- **Do:** type: `what do you know about me, and what am I building?` → send.
- **Expected:** in the activity timeline Namma shows a tool step labeled
  **"Recalled from Cognee memory — what do you know about me…"** (the Cognee recall,
  visible on camera), then answers from the graph — *"You're Santhosh, you're building
  Namma Agent in Python, integrating Cognee for memory…"* Hover/expand the step to show
  the Cognee call to the judges.
- **Narration:** "This is the part that matters. Brand-new chat, zero history — and
  Namma still knows me, because it **recalled from the Cognee graph** mid-conversation.
  Memory isn't a settings page; it's woven into the assistant."
- **✂ cut:** trim the few seconds of think time if long.
- **DRY-RUN FIRST:** run this once before the real take. If Namma *doesn't* reach for
  recall, go to Settings → Cognee → Behaviour → turn **Recall in chat ON**, and retake
  (it will then pull from Cognee automatically).
- **Duration:** 25–30 s.

### Clip 5 — Forget + close (≈15 s)
- **Screen:** Memory tab → **Forget** card (bottom).
- **Do (optional):** click **Forget everything** → confirm. The graph empties (proves
  forget). *Only do this if you've finished all other clips* — or skip and just show
  the card while narrating.
- **Narration:** "Remember. Recall. Improve. Forget — a complete memory lifecycle,
  powered by Cognee. Namma Agent never wakes up with a hangover again."
- **Duration:** 10–15 s.
- **After this clip:** re-run `python scripts\seed_demo_memory.py --reset` to restore
  the graph for any retakes.

---

## Part 3 — Track B re-shoot (Cognee Cloud, ≈30 s)

You only re-shoot the **switch** + one recall + the cloud graph. Everything else is
shared.

1. **Settings → MCP → Cognee → Backend** section.
2. Click the **Cognee Cloud** card. Paste your **Instance URL**
   (`https://<id>.cognee.ai`) and **API key** (platform.cognee.ai, dev code
   `COGNEE-35`). Click **Connect to Cognee Cloud**. **✂ cut** the ~25 s reconnect.
3. Status shows **Connected · Cognee Cloud**.
4. Open **Memory** → the **graph renders** (synced from the cloud REST API).
5. Run one recall in **Ask my memory**, e.g. `what am I building?`
- **Narration:** "Same app, same code — now on **managed Cognee Cloud**. One config
  entry, zero local infrastructure. Same Memory tab, same graph, every op running
  against the cloud."
> Seed the cloud too if it's empty: `python scripts\seed_demo_memory.py --reset`
> (it auto-targets whichever backend is configured).

---

## Part 4 — Two ways to show "old vs new" (pick one)

**Method A — Compare panel (recommended, used above).** Deterministic, labeled,
one screen, no waiting. This is Clip 2.

**Method B — literal before/after by toggling Cognee (more dramatic, riskier).**
1. **Before:** Settings → MCP → **Cognee** → in **Cognee memory**, flip the server
   **toggle OFF** (or Servers tab → cognee off). New chat → ask
   `which engine do I use to store relationships?` → Namma can't recall it (keyword
   memory only). Record this.
2. **After:** flip cognee **ON** (**✂ cut** the ~25 s reconnect) → new chat → ask the
   same → it recalls **Kuzu**.
- **Caveats:** the "before" relies on the model not guessing; keep the question about a
  fact that's only in Cognee. Method A is safer for a judged submission.

---

## Part 5 — Editing & assembly

- **Order:** Clip 1 → 2 → 3 → 4 → 5, then the Track-B clip as a tag (or a separate
  second video for the Cloud submission).
- **Cuts:** speed-ramp or jump-cut every wait (consolidate, reconnect). No dead air.
- **Captions:** add on-screen labels — "Keyword (old)" / "Cognee (new)", and name each
  op as it appears ("remember", "recall", "improve", "forget").
- **Length:** aim **2–3 min**. Open on Clip 2 (the money shot) if you want the hook in
  the first 10 seconds.
- **Voice-over:** record narration over the finished cut for clean audio.
- **End card:** repo URL + "Built with Cognee · WeMakeDevs hackathon."

---

## Part 6 — Pre-flight checklist & troubleshooting

**Before each recording session**
- [ ] App running on latest code (restarted after any change).
- [ ] Settings → Cognee shows **Connected** (green).
- [ ] `seed_demo_memory.py --reset` run; Memory graph shows ~20+ entities.
- [ ] Compare query verified (left card = "No matches").
- [ ] Clip 4 dry-run passed (Namma recalls in a fresh chat).
- [ ] PowerToys Mouse Highlighter on; browser fullscreen (F11), 100% zoom.

**Troubleshooting**
- *Graph empty / "self-hosted-only" overlay on cloud:* you're connected but the graph
  fetch failed — click **↻ Refresh**; on cloud it pulls from the REST API and should
  fill. On local, ensure the container is up.
- *"Cognee offline" chip:* Settings → Cognee → **Reconnect** (or **Register** if the
  server isn't present).
- *Compare left card shows a hit:* that keyword is in SQLite — pick another query.
- *Consolidate/Remember slow:* expected (cognify makes several LLM calls) — that's why
  you **cut** the wait. Pre-seeding avoids it for the graph itself.
- *Switching backends seems stuck:* it now force-removes the old container first; give
  it the ~25 s reconnect, then **Reconnect** if needed.
- *Cloud (Track B) remember fails with a 409 / "ProgrammingError":* that's a
  **Cognee Cloud–side** database error (not a Namma bug) — it was intermittent during
  prep. Record **Track A (self-hosted) first** (it's the primary/MacBook track and is
  fully verified). For Track B, retry later: switch to Cloud, run
  `seed_demo_memory.py --reset`, confirm the graph fills, then re-shoot the 30 s cloud
  clip. The switch + cloud graph-sync code itself is proven working.

## Verified-ready status (self-hosted / Track A)

This whole flow was run end-to-end during prep and **works**:
- Graph: ~59 entities · 80 links (rich + connected).
- Money shot: keyword = 0 hits, Cognee answers python / Aria / Kuzu.
- Reworded recall: correct.
- Fresh-chat recall: the agent calls **Recalled from Cognee memory** (`mcp_cognee_recall`) and answers about you.
- Improve/Consolidate: graph grows with the new facts.
- Backend switch: one clean `namma_cognee` container, no orphans.
