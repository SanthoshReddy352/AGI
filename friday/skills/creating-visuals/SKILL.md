---
name: creating-visuals
description: >
  Add the right picture to a lesson: a Mermaid diagram for structure/flow, or a real
  online photo for intuition. Use in the Learning Room to make an idea visible rather
  than only described.
platforms: [linux, macos, windows]
version: 1.0.0
category: teaching
metadata:
  hermes:
    tags: [teaching, learning-room, diagram, image, visual]
---

# Creating Visuals

A playbook for the `render_diagram` and `fetch_image` tools.

## When to Use

- Structure, flow, hierarchy, sequence, or relationships → **`render_diagram`** (Mermaid).
- "What does it actually look like?" / real-world intuition → **`fetch_image`**.

## Procedure

1. **Choose the form.** Diagram for how-parts-relate; photo for what-it-looks-like.
   Don't add a visual that doesn't teach.
2. **Diagram:** write minimal Mermaid — the fewest nodes that carry the idea. Prefer
   `graph TD/LR`, `sequenceDiagram`, or `flowchart`. Label edges with the relationship.
   Call `render_diagram` with the code and a short `title`.
3. **Photo:** call `fetch_image` with a concrete query (e.g. "monarch butterfly life
   cycle"). It returns a license-clean image with attribution.
4. **Caption and connect.** In one line, point to what in the visual matters and why,
   then continue teaching. The image/diagram is a downloadable artifact for the learner.

## Verification

- The visual is the simplest one that conveys the point (no clutter).
- You told the learner what to look at in it.
- You used a diagram for relationships and a photo for appearance — not the reverse.
