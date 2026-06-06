---
name: creative-writing
description: "Long-form text generation — stories, essays, poems, dialogue, scripts."
source: "hermes-agent skills/creative (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - llm_chat
  - save_file
---

# creative writing

## When to use

The user wants generative text that's longer than a chat reply — story, essay, poem, song, monologue, scene, character sketch, dialogue. Triggers: "write me a short story about…", "draft a poem on…", "give me a 500-word essay on…".

For non-creative drafting (emails, reports, summaries) use the appropriate skill (`email`, `research-paper`) instead — those have format constraints this skill ignores.

## How to use

1. **Slot gathering**: form, length target, tone, constraints. Sensible defaults:
   - form: short story
   - length: 300–500 words
   - tone: warm and concrete, no purple prose

   Use `clarify` only when the request is genuinely ambiguous; otherwise pick defaults and proceed.

2. **System prompt** for `llm_chat`:
   ```
   You are a creative writer. Write a <form> of ~<length> words on
   the subject below. Tone: <tone>. Constraints: <constraints or "none">.

   Rules:
     - No meta-commentary, no "here is your story", no headers.
     - Start with the work itself.
     - End cleanly; no "to be continued".
   ```
3. **Generate** in a single call. For >1000-word targets, generate in 500-word chunks and let the LLM continue (pass the previous chunk as context).
4. **Save** to `~/Documents/FRIDAY/creative/<slug>-<YYYYMMDD>.md` and read the path back to the user.
5. If the user asked aloud and the piece is long, summarise in 2 sentences for TTS and write the full piece silently.

## Examples

- "Friday, write me a short story about a robot that learns to whistle."
- "Friday, draft a sonnet about late-night debugging."
- "Friday, give me a five-minute monologue from a character who lost their voice."

## Common failures and recovery

- **Output runs short** → re-prompt with "Continue from <last sentence>. Add ~<remaining> words. Stay in voice."
- **Tone drifts to corporate / generic** → re-prompt with "Cut all abstractions. Replace any sentence that could appear in a press release with a concrete image."
- **The piece offends a constraint the user mentioned** (e.g. profanity, violence) → regenerate; if it fails twice, surface the issue and ask the user to relax or restate the constraint.
