---
name: arxiv-research
description: "Find, fetch, and summarise arxiv.org papers — by ID, by query, or from a citation."
source: "hermes-agent skills/research/arxiv (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - web_search
  - web_extract
  - llm_chat
---

# arxiv research

## When to use

The user mentions an arxiv paper — by ID ("2305.12345"), title, author, or topic — and wants either a TL;DR, the abstract, the BibTeX entry, or a structured comparison with related work. Triggers include "find the arxiv paper on…", "summarise this arxiv link", "what does the paper at arxiv.org/abs/… say".

Prefer this skill over a generic web search when the user is clearly asking about scientific literature on arxiv. For non-arxiv preprints fall back to `web_search` + `web_extract`.

## How to use

1. **Resolve the paper**:
   - If the user gave an arxiv ID or URL, jump to step 2.
   - Otherwise call `web_search` with `site:arxiv.org <topic or author keywords>` and pick the top match. Confirm with the user before continuing if there's ambiguity.
2. **Fetch the abstract page** with `web_extract` on `https://arxiv.org/abs/<id>`. The page reliably contains: title, authors, abstract, submission date, primary category, comment / journal-ref fields.
3. **Optional full-text**: if the user wants more than the abstract, fetch `https://arxiv.org/pdf/<id>.pdf`. PDF extraction is best-effort — for long papers the page-1 abstract + introduction is usually enough.
4. **Summarise** with `llm_chat` using a structured prompt:
   ```
   You are summarising an arxiv paper. Output exactly four lines:
   • Problem: …
   • Method: …
   • Result: …
   • Why it matters: …
   ```
5. Return the structured summary + the canonical URL.

## Examples

- "Friday, find the latest arxiv paper on mixture of experts and summarise it."
- "Friday, what does arxiv 2401.04088 say?"
- "Friday, give me the four-bullet on the recent Anthropic interpretability paper."

## Common failures and recovery

- **PDF extraction returns garbage** → fall back to the abstract page; tell the user "I could only get the abstract".
- **`web_search` returns no arxiv result** → broaden the query (drop author quotes, try the topic alone) and retry once.
- **The arxiv ID resolves but the paper is withdrawn** → surface the withdrawal notice verbatim instead of pretending to summarise.
