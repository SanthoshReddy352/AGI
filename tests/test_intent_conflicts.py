"""Parser ordering safety net for the deterministic intent layer.

The intent chain (`IntentRecognizer._clause_parsers`) is hand-ordered and the
first matching parser wins — so ordering is load-bearing. These tests run every
parser independently against the golden corpus to guarantee two invariants that
the ordinary (first-match) eval can't see:

  1. **No latent poaching** — no `not:` negative is produced by *any* parser, so
     routing can't silently break if the chain is reordered.
  2. **Overlaps stay documented** — when two parsers both match an utterance, the
     pair is on a known allowlist. A new, undocumented overlap fails the build so
     it gets a conscious decision (and an ordering comment) rather than sneaking in.

Run `python scripts/diagnostics/intent_eval.py --conflicts` for the full report.
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


# Overlaps that are intentional and documented in core/intent_recognizer.py.
# Each entry is a frozenset of the tools two+ parsers may both emit for one
# utterance. The canonical case: an explicit filename ("find the file X.pdf")
# is matched by both _parse_environment (search_indexed_files, the fast index
# lookup that wins) and _parse_file_action (search_file, fuzzy disk match).
KNOWN_OVERLAP_TOOLSETS = {
    frozenset({"search_indexed_files", "search_file"}),
}


def test_no_latent_poaching():
    _overlaps, poaches = intent_eval.analyze_conflicts()
    assert poaches == [], (
        "A forbidden ('not:') tool is produced by some parser — routing would "
        "break if the chain were reordered:\n"
        + "\n".join(f"  {s!r} -> {t} (via {p})" for s, t, p in poaches)
    )


def test_overlaps_are_documented():
    overlaps, _poaches = intent_eval.analyze_conflicts()
    undocumented = []
    for say, hits in overlaps:
        toolset = frozenset(tool for _parser, tool in hits)
        if toolset not in KNOWN_OVERLAP_TOOLSETS:
            undocumented.append((say, hits))
    if undocumented:
        pytest.fail(
            "New undocumented parser overlap(s) — add an ordering comment and, if "
            "intentional, list the toolset in KNOWN_OVERLAP_TOOLSETS:\n"
            + "\n".join(
                f"  {s!r}: " + " > ".join(f"{p}->{t}" for p, t in hits)
                for s, hits in undocumented
            )
        )
