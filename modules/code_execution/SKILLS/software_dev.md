---
name: software-development
description: "Patterns for code review, refactor, test writing, and quick computation via the sandbox."
source: "hermes-agent skills/software-development (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - evaluate_code
  - read_file
  - save_file
  - llm_chat
---

# software development

## When to use

The user wants engineering help against a code base they're working in: review a diff, refactor a function, write a test for behaviour X, run a quick calculation, or trace a bug. Triggers: "review this change", "write a test for this function", "compute X", "why is this slow".

For broad codebase questions ("how does the router work") prefer `/graphify query` first per `CLAUDE.md`; come back here once a specific file is in scope.

## Patterns

### Quick computation
Always prefer `evaluate_code` over the LLM doing arithmetic in its head.
```python
evaluate_code(language='python', code='print(47 * 3.14)')   # → 147.58
evaluate_code(language='python', code='import statistics; print(statistics.mean([12, 17, 23, 31]))')
```

### Test writing
1. `read_file` the function-under-test.
2. Ask `llm_chat`:
   ```
   Write pytest cases for the function below. Cover: happy path,
   edge cases (empty / None / boundary), and one error path.
   Use plain pytest — no fixtures unless the function needs IO.
   ```
3. Save the test to `tests/test_<module>.py` (don't overwrite an existing file without approval).
4. Run with `evaluate_code(language='bash', code='pytest tests/test_<module>.py -v')`. Surface the result.

### Diff review
1. Get the diff: `evaluate_code(language='bash', code='git diff <ref>')`.
2. Ask `llm_chat` with `Review for: correctness bugs, edge cases missed, hidden complexity. List 3–5 high-confidence findings. No nits.`
3. Reply with the findings; do not propose a commit — the user drives that.

### Refactor
1. `read_file` the target.
2. Spell out the constraints: file-length budget (≤30-line methods per FRIDAY's CLAUDE.md), backwards-compat callers, public surface that can't change.
3. Draft the refactor with `llm_chat`, but **never write it back** without showing the diff and gating with `core.approval.request_approval()`.

## Examples

- "Friday, compute the standard deviation of 12, 17, 23, 31."
- "Friday, write pytest cases for the `_chunk_text` function in `modules/comms/telegram.py`."
- "Friday, review the diff on this branch — what looks broken?"

## Common failures and recovery

- **`evaluate_code` times out** → the sandbox cap is 5 s. For longer compute, delegate (P3.12) and report when done.
- **Tests fail** → surface the failure verbatim; do not "fix" the function unsupervised — ask the user which side is wrong.
- **Refactor diff is large** → break it into commits in the response, each ≤30 lines per Direction §5.1.
