---
name: teaching-with-examples
description: >
  Explain any concept so a curious child could grasp it: define terms plainly,
  give one concrete real-life analogy per idea, then check understanding. Use in the
  Learning Room (or any time you're teaching) when introducing or re-teaching a point.
platforms: [linux, macos, windows]
version: 1.0.0
category: teaching
metadata:
  hermes:
    tags: [teaching, learning-room, examples, pedagogy]
---

# Teaching With Examples

A playbook for making one idea click before moving on.

## When to Use

- Introducing a new concept, term, or step in the Learning Room.
- A learner gave a wrong quiz answer and the point needs re-teaching differently.

## Procedure

1. **Name it plainly.** State the idea in one short sentence with no jargon. If a
   technical word is unavoidable, define it first in everyday language.
2. **One real-life analogy.** Tie the idea to something ordinary the learner already
   knows — a kitchen, pocket money, a queue at a shop, a playground game. Keep the
   analogy small and accurate; don't stretch it past where it holds.
3. **Walk the analogy back to the concept.** Map each part of the example to the real
   thing ("the queue is the buffer; the cashier is the CPU").
4. **Tiny concrete instance.** Give one specific worked example with real numbers or
   names, not an abstract description.
5. **Check.** Ask a one-line question or `pose_quiz`. If wrong, return to step 2 with a
   *different* analogy — never repeat the same explanation louder.
6. Only when it's understood, move on (and `mark_module_complete` if a module ends).

## Verification

- Every new term was defined before use.
- There is at least one everyday analogy AND one concrete instance.
- Understanding was checked before advancing.
