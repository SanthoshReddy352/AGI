---
name: deep-research
description: >
  Research a topic in depth and produce a sourced, synthesized answer. Use when
  the user asks to "research", "look into", "find out about", "compare", or wants
  a thorough, citation-backed overview rather than a quick fact.
platforms: [linux, macos, windows]
version: 1.0.0
category: research
metadata:
  hermes:
    tags: [research, web, synthesis]
---

# Deep Research

A repeatable procedure for thorough, sourced research.

## When to Use

- The user asks you to research / investigate / look into a topic.
- The question needs multiple sources or comparison, not one quick fact.
- The user wants citations or a written overview they can keep.

Do NOT use for a single quick lookup (just `web_search` once) or for a question
you can already answer confidently.

## Procedure

1. Break the topic into 2–4 concrete sub-questions.
2. For each sub-question, call `web_search` (limit 5). Pick the most relevant,
   authoritative results.
3. Call `web_extract` on the 2–3 best URLs to read the actual content — never
   summarize from titles/snippets alone.
4. If the topic is broad or independent, hand a sub-question to `delegate_task`
   so it researches in parallel and reports back.
5. Cross-check claims across at least two sources. Note disagreements.
6. Synthesize into a clear answer: lead with the bottom line, then supporting
   detail, then a short "Sources" list with the URLs you actually read.

## Verification

- Every non-obvious claim traces to a source you opened with `web_extract`.
- The answer leads with the conclusion, not a wall of links.
- A "Sources" list with real URLs is included.
- Conflicting evidence is acknowledged rather than hidden.
