"""FTS query sanitiser — punctuation in user text must not crash FTS5.

Regression for the 2026-05-25 log: "Computer Science, AI & ML, Neural
Networks, Agentic Workflows, Coding." raised
`fts5: syntax error near ","` because the raw text went straight into MATCH.
"""
from __future__ import annotations

from core.stores.memory_store import _to_fts_match


def test_commas_and_punctuation_become_quoted_or_terms():
    expr = _to_fts_match("Computer Science, AI & ML, Neural Networks, Coding.")
    # every term quoted, OR-joined, no raw punctuation left
    assert "," not in expr and "&" not in expr and "." not in expr
    assert '"computer"' in expr and '"science"' in expr
    assert " OR " in expr


def test_punctuation_only_returns_empty():
    assert _to_fts_match(",.@& ") == ""
    assert _to_fts_match("") == ""


def test_single_term():
    assert _to_fts_match("python") == '"python"'


def test_at_sign_handled():
    # "/unlock tricky@1108"-style noise should not blow up.
    expr = _to_fts_match("tricky@1108")
    assert "@" not in expr
