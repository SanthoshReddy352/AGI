<!--
Thanks for contributing to FRIDAY! Keep PRs focused — one logical change per PR.
For anything large (new provider, agent-loop change, new tool surface), please
open an issue first so we can agree on the approach.
-->

## What & why

<!-- What does this change do, and why? Link any related issue: "Fixes #123". -->

## How it behaves

<!-- For user-visible changes, describe what the user does and what the assistant does. -->

## Definition of done

<!-- See CONTRIBUTING.md. Tick what applies; explain any N/A. -->

- [ ] New behavior is the only path (old path deleted, not left running alongside).
- [ ] A test exists that **fails without this change** (`friday/tests/test_<area>.py`).
- [ ] New tools follow the v2 pattern (a `register(registry)` in `friday/tools/`,
      JSON-Schema params, approval-gated if destructive, graceful when a binary is missing).
- [ ] No hard-coded assistant name — resolved via `assistant_name()` / `config.assistant_name`.
- [ ] Cross-platform branches are guarded and verified (or N/A noted below).
- [ ] `python -m pytest friday/tests/ -q` is green locally.

## Platforms verified

- [ ] Linux
- [ ] Windows
- [ ] N/A (no platform-specific code)

## Notes for reviewers

<!-- Pre-existing failures, follow-ups deferred, anything you want a closer look at. -->
