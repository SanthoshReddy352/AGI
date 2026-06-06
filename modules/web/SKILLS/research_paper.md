---
name: research-paper-writing
description: "Compose a short research write-up from a topic + sources — outline, draft, citations."
source: "hermes-agent skills/research/research-paper-writing (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - web_search
  - web_extract
  - arxiv-research
  - llm_chat
---

# research paper writing

## When to use

The user wants a structured short write-up on a topic — typically 300–800 words, with cited sources. Triggers: "write me a brief on X", "draft a literature note on Y", "give me a one-pager on Z with citations". Distinct from `web_search` (raw results) and `arxiv` (single-paper summary).

Delegate (P3.12) is a good fit when the user is also speaking other commands — runs the long write in the background.

## How to use

1. **Clarify scope** with `clarify` (P3.11) if the topic is broad: "Should I focus on the technique, the applications, or both?"
2. **Gather sources** (5–10):
   - `web_search` with the cleaned topic.
   - For each promising hit, `web_extract` → cap each to ≤2000 chars.
   - For academic topics, also call `arxiv-research` for 2–3 papers.
3. **Outline** with `llm_chat`:
   ```
   Produce an outline with sections: Background, Key approaches,
   Recent results, Open questions, References. Use only the
   provided source snippets — no external knowledge.
   ```
4. **Draft** section by section, passing the outline + relevant source chunks per section.
5. **Citations**: append a numbered references block. Each reference = `[N] Title — URL (accessed YYYY-MM-DD)`.
6. **Save** the result with `save_file` to `~/Documents/FRIDAY/research/<slug>.md` and read the path back to the user.

## Examples

- "Friday, write me a one-pager on mixture-of-experts routing strategies with citations."
- "Friday, draft a literature note on prompt caching — about 500 words."
- "Friday, brief on retrieval-augmented generation, focus on the eval methods."

## Common failures and recovery

- **Sources contradict each other** → quote both and note the disagreement explicitly; don't average.
- **`web_extract` returns mostly nav/footer** → drop that source, log "skipped <url> — extraction yielded no body".
- **LLM tries to add facts not in the sources** → re-prompt with "Use only the snippets above. If a claim is not supported, drop it."
