# Contributing to FRIDAY

Thanks for your interest in FRIDAY! This guide covers the dev setup and the
conventions that keep the project coherent. Please also read the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report bugs** — open a [bug report](../../issues/new/choose) with repro steps
  and the relevant `logs/friday.log` excerpt.
- **Propose features** — open a [feature request](../../issues/new/choose) and
  describe the user-facing behavior (the phrasing you'd speak/type).
- **Send pull requests** — see the workflow below.

For anything large (new module, routing layer, storage change), please open an
issue first so we can agree on the approach before you build.

## Dev setup

```bash
# Linux
git clone https://github.com/SanthoshReddy352/Friday_Linux.git
cd Friday_Linux && ./setup.sh && source .venv/bin/activate

# Windows
git clone https://github.com/SanthoshReddy352/Friday_Linux.git
cd Friday_Linux; .\setup.ps1; .\.venv\Scripts\Activate.ps1
```

Run the test suite:

```bash
python -m pytest -q
```

## Project conventions

These are not optional — they're what keeps a multi-module voice assistant
maintainable. Reviewers will check for them.

### 1. Every new capability needs an intent pattern + tests

When you `app.register_capability(...)`, you **must** also add a deterministic
regex in [`core/intent_recognizer.py`](core/intent_recognizer.py) (unless the
capability is intentionally LLM-routed only — rare).

> Without an explicit pattern, a capability is at the mercy of the small chat
> model, which will happily fabricate plausible success for tools it didn't
> actually call.

Wiring checklist:

1. Pick or add a `_parse_<domain>` method; add the regex(es) there.
2. Register it in the `_parse_clause` chain — **narrow parsers before broad
   catch-alls** (ordering matters; see the comments in that method).
3. Return the canonical action dict: `{"tool", "args", "text", "domain"}`,
   where `args` matches the capability's declared parameters.
4. Gate on tool presence:
   `if "<name>" not in getattr(self.router, "_tools_by_name", {}): return None`.
5. Cover the axes that matter: verb variants, object variants (with/without
   "the/my/your"), word order, spoken cardinals, optional args, filler-word
   tolerance — **and at least one negative case that must NOT match.**
6. Add `tests/test_<domain>_intent.py` following the `_make_recognizer(tools=[…])`
   pattern (`tests/test_environment_intent.py` is the canonical example).

### 2. Keep it cross-platform

FRIDAY ships on Linux **and** Windows. Guard platform-specific code with
`platform.system()` / `os.name`. Known patterns already in use:

- Subprocess: `start_new_session=True` (POSIX) vs `creationflags=DETACHED_PROCESS` (Windows).
- Venv python: `.venv/bin/python3` vs `.venv/Scripts/python.exe`.
- `strftime("%-I")` is Linux-only — use a Windows-safe format and `.lstrip("0")`.
- Always pass `encoding="utf-8", errors="replace"` to `subprocess.run(..., text=True)`.

If you fix a bug on one OS, check and fix the other, and keep `setup.sh` /
`setup.ps1` in parity.

### 3. Storage goes through the domain stores

Persistence lives in [`core/stores/`](core/stores/) — six domain stores, each
owning ≤4 tables, methods ≤30 lines, **write-ownership strict** (a store writes
only its own tables; reads may cross). New table? Add it to the matching store's
`migrations/<name>.sql` and a focused test under `tests/stores/`. Do **not** add
state to the transitional `ContextStore` facade.

### 4. Update the docs in the same PR

After any change to user-visible behavior, update
[`docs/testing_guide.md`](docs/testing_guide.md) — add/amend the relevant `T-N.M`
entry (the **You say** field is the live spec of accepted phrasings) and append a
row to its Modification Log with today's date.

## Definition of done

A change isn't done until:

- [ ] New behavior is the only path (old path deleted, not left running alongside).
- [ ] A test exists that **fails without your change**.
- [ ] New capabilities have an intent pattern + intent test.
- [ ] Cross-platform branches are guarded and verified (or N/A noted).
- [ ] `docs/testing_guide.md` is updated for user-visible changes.
- [ ] `python -m pytest -q` is green.

## Pull request process

1. Fork and branch from `main` (e.g. `feat/brightness-presets`).
2. Make focused commits; keep unrelated changes out of the PR.
3. Fill in the PR template (what/why, tests, platforms verified).
4. Ensure CI is green. A maintainer will review.

## Commit messages

Short imperative subject (`system_control: add brightness presets`), with a body
explaining the *why* when it isn't obvious. Group by domain/module prefix to
match existing history.

## Code style

- Python, type hints where they clarify intent.
- Match the surrounding code's idiom, naming, and comment density.
- Prefer small, single-responsibility functions (the store layer caps at 30 lines
  per method — a good target elsewhere too).

## Questions?

Open a [discussion or issue](../../issues). We're happy to help you land your
first contribution.
