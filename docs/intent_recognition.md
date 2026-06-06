# Intent Recognition & Routing

How FRIDAY decides what you meant and which capability to run.

This is the reference for the routing layer. For the broader turn lifecycle see
[ARCHITECTURE.md](ARCHITECTURE.md); for the tunable knobs see
[config_reference.md](config_reference.md); for the contributor checklist see
[CONTRIBUTING.md](../CONTRIBUTING.md).

---

## 1. Why routing matters

FRIDAY runs small local models. The chat model (Qwen 0.8B) is happy to
**fabricate** a plausible success — *"Brightness set to 60."* — for a tool it
never actually called. The router exists to make sure a real capability runs
before the model gets a chance to invent one.

The design principle: **resolve the common phrasings deterministically, and only
fall to a model when nothing cheaper matched.** Every capability that ships
should have a deterministic pattern so it never depends on the chat model's
goodwill.

## 2. The five layers

`PlannerEngine.plan()` (`core/planning/planner_engine.py`) walks an ordered chain
and returns at the **first layer that produces a plan**. Two pre-checks run
before the layers proper:

0. **Pending online confirmation** — a prior turn asked "this needs the
   internet, OK?"; this turn's yes/no resolves it.
1. **Active workflow continuation** — a workflow (reminder slot-fill,
   confirmation, disambiguation, …) is mid-flow; the turn is handed to it.

Then, cheapest first:

| # | Layer | Source | What it does |
|---|---|---|---|
| L1 | **IntentRecognizer** | `regex` | ~50 deterministic `_parse_<domain>` parsers, first-match wins. Confidence 1.0/0.9. (`core/intent_recognizer.py`) |
| L2 | **RouteScorer** | `score` | Alias / pattern / context-term scoring over the capability registry; dispatches the best route scoring ≥ 80. (`core/reasoning/route_scorer.py`) |
| L2a | **Learned dispatch** | `learned` | A phrasing the user confirmed `routing.promote_after` times routes deterministically. Exact match. (`core/stores/intent_learning_store.py`) |
| L2b | **LexicalRouter** | fuzzy | `rapidfuzz` token-set ratio over the catalog + promoted phrasings; catches STT/typo near-misses. (`core/lexical_router.py`) |
| L3 | **EmbeddingRouter** | cosine | Cosine similarity over capability embeddings, with a dispatch / confirm / tie band (§4). (`core/embedding_router.py`) |
| L4 | **QwenPlanner** | `planner` | The local 4B tool/plan model synthesises a (possibly multi-step) `ToolPlan`. (`core/planning/`) |
| L5 | **llm_chat** | `chat` | Conversational fallback when nothing routed to a tool. |

> The 5 layers are L1–L5; L2a/L2b/L3 are the progressively-fuzzier middle that
> sits between the deterministic best-route and the LLM. When
> `routing.use_qwen_planner` is false, L4 is skipped and a mid-confidence
> embedding match instead triggers a **confirmation** ("did you mean …?") before
> dropping to chat.

## 3. Layer 1 — the deterministic parser chain

`IntentRecognizer._parse_clause()` dispatches a clause through an **ordered list**
of `_parse_<domain>` methods. **First match wins**, so order is load-bearing:
narrow/explicit parsers must run before broad catch-alls.

Two structural rules:

- **Interceptors run first.** The workflow guards register their parsers at the
  very top of the chain: `_parse_pending_destructive` (confirm), then
  `_parse_pending_pick` (disambiguate), then `_parse_pending_wipe`,
  `_parse_pending_selection`. They only intercept turns that look like an answer
  to the pending question — anything else falls through, so the user is never
  trapped mid-flow.
- **Narrow before broad.** e.g. `_parse_screen_lock` runs before `_parse_help`
  so "lock screen" never reads as a help query; `_parse_environment` runs before
  `_parse_file_action` so "find file foo.txt" wins on the index path.

A parser returns the canonical action dict and `plan()` may return several for a
multi-action utterance ("open chrome and tell me the time"):

```python
{"tool": "set_brightness", "args": {"level": 50}, "text": clause, "domain": "system"}
```

A regex hit produces an `IntentResult` with confidence ≥
`IntentEngine.HIGH_THRESHOLD` (0.9), which **short-circuits the rest of the
pipeline** — no scorer, no embedding, no LLM.

### Anti-patterns the chain guards against

- **Cross-domain poaching** — a parser stealing a phrase that belongs to another
  domain because it ran earlier. The conflict detector (§5) is the regression
  test for this.
- **Bare-keyword matches** — never route on a single common word
  (`battery`, `volume`, `screenshot`, `memory`) without a verb anchor; those
  words appear in unrelated sentences ("the battery in my car died").

## 4. Confidence bands

The fuzzy layers defend a band rather than dispatching on a raw best-match.
Defaults (tunable under `routing.*`):

| Layer | Knob | Default | Meaning |
|---|---|---|---|
| Intent fast-path | `HIGH_THRESHOLD` | `0.90` | ≥ → bypass planner, build plan from regex result. |
| Intent fast-path | `MEDIUM_THRESHOLD` | `0.50` | candidate kept, planner still consulted. |
| Embedding | `routing.dispatch_threshold` | `0.62` | cosine ≥ → auto-dispatch. |
| Embedding | `routing.confirm_low` | `0.50` | cosine in `[confirm_low, dispatch_threshold)` → ask "did you mean …?". |
| Embedding | `routing.tie_epsilon` | `0.05` | candidates within this of the top → disambiguate. |
| Lexical | `routing.lexical_threshold` | `88` | score must clear this to fire. |
| Lexical | `routing.lexical_margin` | `6` | …and beat the runner-up tool by this margin. |
| Learned | `routing.promote_after` | `3` | confirmations before a phrasing is promoted. |

The **confirm band** is the safety net: a mid-confidence match asks a yes/no
question instead of letting the chat model fabricate a success. That answer is
the learning signal — confirm a phrasing `promote_after` times and it graduates
to deterministic (L2a) dispatch.

## 5. Quality gates

Two CI gates keep routing honest. Both run as plain pytest and as standalone
scripts.

### Intent eval harness — recall on a golden corpus

`scripts/diagnostics/intent_eval.py` runs every case in
[`tests/intent_corpus/`](../tests/intent_corpus/) (103 cases / 13 domains) and
reports recall + negative accuracy. The corpus *is* the regression test — a
phrasing that should route is added here.

```bash
python scripts/diagnostics/intent_eval.py                 # full corpus
python scripts/diagnostics/intent_eval.py --domain system_control --verbose
python scripts/diagnostics/intent_eval.py --conflicts     # overlap/poaching report
```

As a test gate: `tests/test_intent_eval.py`.

### Conflict / overlap detector

`--conflicts` (and `tests/test_intent_conflicts.py`) flags two parsers that both
claim the same phrasing — the latent poaching bug. The only "overlap" allowed is
the documented intentional `search_indexed_files` ⇄ `search_file` split.

### Routing observability

`scripts/diagnostics/routing_stats.py` analyzes the `[ROUTE]` log lines to show
which layer handled real traffic (how often L1 caught it vs. how often turns
fell to the planner) — useful for spotting a capability that's silently relying
on the LLM.

## 6. How to add an intent

Every capability registered via `app.register_capability(...)` **must** also have
a deterministic pattern (unless it is intentionally LLM-routed only — rare).
`context_terms` / `aliases` / `description` on the capability spec feed the L2/L3
scorers, **not** L1 — without an explicit regex a capability is at the mercy of
the small chat model.

1. **Pick a parser** — reuse an existing `_parse_<domain>` when the tool fits;
   add a new one when it doesn't.
2. **Add the regex(es)** inside that parser — one `re.search` per phrasing family
   is fine.
3. **Register the parser** in the `_parse_clause` chain, minding order: narrow
   parsers before broad catch-alls.
4. **Return the canonical action dict** — `{"tool", "args", "text", "domain"}`,
   with `args` matching the capability's declared parameters.
5. **Gate on tool presence** so the parser is inert when the capability isn't
   loaded:
   ```python
   if "<name>" not in getattr(self.router, "_tools_by_name", {}):
       return None
   ```

### Cover these axes

- **Verb variants:** set / change / make / put / turn …
- **Object variants** (with and without "the/my/your").
- **Word order:** "brightness 80" and "set 80 brightness".
- **Spoken cardinals** where numbers are plausible: "fifty" → 50, "max" → 100.
- **Optional arg shapes:** "unlock screen" (re-asks) and "unlock with pin 1234".
- **Filler tolerance:** "Friday rescan my apps", "rescan apps please".
- **At least one negative** that must **not** match.

### Tests are mandatory

Add `tests/test_<domain>_intent.py` following the `_make_recognizer(tools=[…])`
pattern in [`tests/test_environment_intent.py`](../tests/test_environment_intent.py)
(the 46-test canonical example). Parametrize the positive phrasings and include a
negative. Then add a case to the golden corpus under
[`tests/intent_corpus/`](../tests/intent_corpus/) so the eval gate covers it.

### Don't forget the docs

Update the relevant `T-N.M` entry in
[`docs/testing_guide.md`](testing_guide.md) — its **You say** field is the live
spec of accepted phrasings — and append a Modification Log row.

## 7. See also

- [ARCHITECTURE.md](ARCHITECTURE.md) §B–D — pipeline + confidence-band diagram, workflow state machine.
- [intent_routing_audit.md](intent_routing_audit.md) — the tool-by-tool audit and the historical poaching fixes.
- [config_reference.md](config_reference.md) — every `routing.*` knob.
