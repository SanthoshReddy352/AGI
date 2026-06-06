---
name: llm-wiki
description: "Answer ML/LLM trivia questions from the model's own knowledge in a wiki-style format."
source: "hermes-agent skills/research/llm-wiki (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - llm_chat
---

# llm wiki

## When to use

The user asks a factual ML / LLM / NLP question that the local chat model can answer from training — terms, technique definitions, model lineage, common benchmarks. Triggers: "what is FlashAttention", "explain RoPE", "how does grouped-query attention differ from multi-head".

**Don't** use this for current-event questions ("what did OpenAI release last week") — those need `web_search`.

## How to use

Single LLM call with a wiki-style system prompt:

```
You are a concise ML/LLM technical wiki. Answer in this exact shape:

  Definition: <one sentence>
  How it works: <2–3 sentences, no math jargon unless asked>
  Related: <comma-separated list of 3–5 related terms>
  Confidence: <high|medium|low — flag low when uncertain>

If you don't know the answer, output:
  Definition: Unknown
  Confidence: low
```

Speak only the Definition + Confidence aloud; write the full block to the assistant text.

If Confidence comes back as `low`, automatically follow up with a `web_search` so the answer doesn't leave the user with stale or wrong info.

## Examples

- "Friday, what is mixture of experts?"
- "Friday, explain rotary position embeddings."
- "Friday, how does QLoRA differ from regular LoRA?"

## Common failures and recovery

- **Model confidently hallucinates** → catch via the `Confidence` field; when low, always cross-check with web.
- **The user wants a longer explanation** → re-prompt with the same format but lift the sentence cap; never drop the structured fields.
- **The term is ambiguous** (e.g. "alignment") → call `clarify` to ask which sense.
