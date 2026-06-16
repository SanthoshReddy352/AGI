---
name: creating-simulations
description: >
  Build a small self-contained interactive HTML/JS simulation to teach a concept
  that's clearer in motion (physics, algorithms, systems, math). Use in the Learning
  Room when an animation or a thing-the-learner-can-tweak beats a paragraph.
platforms: [linux, macos, windows]
version: 1.0.0
category: teaching
metadata:
  hermes:
    tags: [teaching, learning-room, simulation, interactive]
---

# Creating Simulations

A playbook for the `render_simulation` tool.

## When to Use

- The concept involves motion, feedback, or "what happens if I change X" (orbits,
  sorting, supply/demand, wave interference, recursion).
- A static diagram can't show the dynamic behaviour.

## Procedure

1. **Pick the one variable that teaches.** Decide the single thing the learner should
   change (a slider/button) and the single thing they should watch.
2. **Write ONE self-contained HTML document.** All CSS and JS inline; no external
   scripts, CDNs, or network calls (it runs in a sandboxed frame). Plain Canvas/SVG +
   vanilla JS. Keep it small and robust.
3. **Make it legible.** Large text, a clear control, a short on-screen label saying
   what to do. Neutral background so it reads in light and dark mode.
4. **Call `render_simulation`** with the full `html` and a short `title`.
5. **Frame it.** In your message, say in one line what to try and what they'll notice;
   then connect the observation back to the concept and check understanding.

## Verification

- The HTML is a complete `<!doctype html>` document, fully self-contained.
- Exactly one clear interaction; the teaching point is obvious without instructions.
- You explained what to observe and tied it back to the idea.
