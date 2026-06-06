"""Tests for core/planning/slot_extractors.py — Track 1.4b shared infra."""
from __future__ import annotations

import pytest

from core.planning.slot_extractors import (
    content_is_quoted_in,
    extract_quoted_content,
)


@pytest.mark.parametrize("text, expected", [
    ("write 'Hello Friday' to hello.txt", "Hello Friday"),
    ('write "Hello Friday" to hello.txt', "Hello Friday"),
    ("write `Hello Friday` to hello.txt", "Hello Friday"),
    ("write 'Hello Friday' into hello.txt", "Hello Friday"),
    ("append 'log line' to notes.md", "log line"),
    ("add 'extra' to the file", "extra"),
    ("with content: some long block of text", "some long block of text"),
    ("that says: ready to go", "ready to go"),
    ("write hello world to file my.txt", "hello world"),
    ("append second line to file notes.md", "second line"),
    ("add a new section to the document", "a new section"),
    ("add hello", "hello"),
    ("append more notes", "more notes"),
])
def test_extract_quoted_content_matches_known_shapes(text, expected):
    assert extract_quoted_content(text) == expected


@pytest.mark.parametrize("text", [
    "",
    "hello there",
    "open hello.txt",
    "what's the weather",
    "create file my.txt",
])
def test_extract_quoted_content_returns_empty_when_no_match(text):
    assert extract_quoted_content(text) == ""


def test_extract_quoted_content_non_string_input():
    assert extract_quoted_content(None) == ""  # type: ignore[arg-type]
    assert extract_quoted_content(123) == ""   # type: ignore[arg-type]


def test_extract_quoted_content_strips_outer_quotes():
    """The strip step removes whitespace and a single layer of quote chars
    so a pattern that captured the quotes (older shape) still returns the
    bare content."""
    # The trailing strip handles patterns like `with content: "X"` where
    # the regex captures everything after the colon, quotes included.
    assert extract_quoted_content('with content: "wrapped"') == "wrapped"


@pytest.mark.parametrize("text, content, expected", [
    ("write 'Hello Friday' to hello.txt", "Hello Friday", True),
    ('write "Hello Friday" to hello.txt', "Hello Friday", True),
    ("write `Hello Friday` to hello.txt", "Hello Friday", True),
    # Bare unquoted text is not "quoted"
    ("write Hello Friday to hello.txt", "Hello Friday", False),
    # Wrong quote style
    ("write Hello Friday to hello.txt", "Hello", False),
    # Empty inputs
    ("", "Hello", False),
    ("write 'X' to Y", "", False),
])
def test_content_is_quoted_in(text, content, expected):
    assert content_is_quoted_in(text, content) is expected
