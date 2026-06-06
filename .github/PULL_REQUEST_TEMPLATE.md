<!--
Thanks for contributing to FRIDAY! Keep PRs focused — one logical change per PR.
For anything large (new module, routing layer, storage change), please open an
issue first so we can agree on the approach.
-->

## What & why

<!-- What does this change do, and why? Link any related issue: "Fixes #123". -->

## How it behaves

<!--
For user-visible changes, describe it phrasing-first:
**You say:** "set brightness to night mode"
**FRIDAY does:** sets brightness to ~20% and confirms.
-->

## Definition of done

<!-- See CONTRIBUTING.md. Tick what applies; explain any N/A. -->

- [ ] New behavior is the only path (old path deleted, not left running alongside).
- [ ] A test exists that **fails without this change**.
- [ ] New capabilities have a deterministic intent pattern **and** an intent test
      (`core/intent_recognizer.py` + `tests/test_<domain>_intent.py`).
- [ ] Cross-platform branches are guarded and verified (or N/A noted below).
- [ ] `docs/testing_guide.md` updated for user-visible changes (T-entry + Modification Log row).
- [ ] `python -m pytest -q` is green locally.

## Platforms verified

- [ ] Linux
- [ ] Windows
- [ ] N/A (no platform-specific code)

## Notes for reviewers

<!-- Pre-existing failures, follow-ups deferred, anything you want a closer look at. -->
