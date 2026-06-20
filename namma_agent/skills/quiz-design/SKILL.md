---
name: quiz-design
description: >
  Write a short, fair multiple-choice check that reveals whether a learner truly
  understood an idea (not just memorised words), then act on the result. Use in the
  Learning Room after teaching a point or finishing a module.
platforms: [linux, macos, windows]
version: 1.0.0
category: teaching
metadata:
  hermes:
    tags: [teaching, learning-room, quiz, assessment]
---

# Quiz Design

A playbook for the `pose_quiz` tool and acting on the answer.

## When to Use

- After teaching a single idea, or at the end of a module before `mark_module_complete`.

## Procedure

1. **Test understanding, not recall.** Ask the learner to apply the idea to a NEW small
   situation, not to repeat a definition.
2. **Write 3–4 options.** One clearly correct; the wrong ones are *plausible
   misconceptions* a struggling learner would actually pick (so a wrong answer tells you
   the gap). Avoid trick wording and "all of the above".
3. **Call `pose_quiz`** with the question, options, the 0-based `answer_index`, and a
   short `explanation` of why the answer is right.
4. **Read the result.** If correct, affirm briefly and move on. If wrong, identify which
   misconception the chosen option reveals and re-teach THAT (see `teaching-with-examples`).
5. **Update your model of the learner** with `record_understanding` (a 0–100 score and a
   one-line note on how they think / where they slip) so later modules adapt.

## Verification

- The question requires applying the idea, not reciting it.
- Each wrong option maps to a real misconception.
- You acted on the answer: affirmed + advanced, or diagnosed + re-taught, and recorded
  understanding.
