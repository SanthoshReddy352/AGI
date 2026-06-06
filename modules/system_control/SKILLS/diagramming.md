---
name: diagramming
description: "Generate Mermaid / PlantUML diagrams from a natural-language description; save to file."
source: "hermes-agent skills/diagramming (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - llm_chat
  - save_file
---

# diagramming

## When to use

The user wants a diagram — flowchart, sequence, class, state, or architecture — described in words. Triggers: "draw a flowchart for X", "give me a sequence diagram for the login flow", "diagram the architecture of the FRIDAY app".

## Picking a notation

- **Mermaid** — default; easy to embed in Markdown, renders on GitHub. Use for flowcharts, sequence, state, class, gantt.
- **PlantUML** — for richer C4 / component / deployment diagrams that Mermaid can't express. Requires the user to have a PlantUML renderer (`plantuml.jar` or the web service) to actually view.

## How to use

1. **Decide the diagram kind** from the user's verb:
   - "flow" / "decision tree" → `flowchart`
   - "sequence" / "interaction" → `sequenceDiagram`
   - "state machine" / "states" → `stateDiagram-v2`
   - "class" / "object model" → `classDiagram`
   - "architecture" / "C4" → PlantUML `@startuml`
2. **Generate** with `llm_chat`, system prompt:
   ```
   Output only the Mermaid (or PlantUML) source code in a fenced block.
   No prose, no explanation. Keep node labels short (≤4 words).
   ```
3. **Save** to `~/Documents/FRIDAY/diagrams/<slug>.md` (Mermaid) or `.puml` (PlantUML).
4. **Reply** with the file path + the first 5 lines of the source so the user can sanity-check without opening the file.

## Examples

- "Friday, draw a flowchart for the voice turn pipeline."
- "Friday, give me a sequence diagram of the Telegram inbound flow."
- "Friday, C4 component diagram for the storage layer."

## Common failures and recovery

- **Mermaid syntax error** → re-prompt the LLM with the error from the renderer; cap at 2 retries.
- **The diagram is too dense to read** → ask the user "drop sub-components or keep them?" via `clarify`; on "drop" re-generate with `Show only top-level nodes.`
- **User wants an image, not source** → mention they need a renderer; offer to open the Mermaid live editor URL if `web_extract` is available.
