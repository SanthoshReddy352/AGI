"""CI gate for the deterministic intent layer.

Wraps the model-free intent eval harness (``scripts/diagnostics/intent_eval.py``)
so a regression in ``core.intent_recognizer`` — a parser that stops matching a
known phrasing, or starts poaching one it shouldn't — fails the build. The
golden corpus lives in ``tests/intent_corpus/*.yaml``; add a case there when you
add or fix an intent (see CONTRIBUTING.md / docs/intent_recognition.md).

Run the harness directly for a human-readable per-domain report:

    python scripts/diagnostics/intent_eval.py --verbose
"""
from __future__ import annotations

import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts", "diagnostics")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import intent_eval  # noqa: E402


def test_intent_corpus_exists():
    cases = intent_eval.load_corpus()
    assert cases, "intent corpus is empty — expected tests/intent_corpus/*.yaml"


def test_intent_eval_no_regressions():
    stats, failures, case_count = intent_eval.run_eval()
    assert case_count > 0
    if failures:
        lines = [
            f"  [{f.case.domain}] {f.case.say!r} -> got {f.got_tool!r} ({f.reason})"
            for f in failures
        ]
        pytest.fail(
            f"{len(failures)} intent routing regression(s) across {case_count} cases:\n"
            + "\n".join(lines)
        )
