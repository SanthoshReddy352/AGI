"""strip_user_impersonation — the deterministic safety net for the 2026-05-29
bug where the 0.8B chat model answered "I'm FRIDAY, an assistant named Luffy"
(Luffy being the user's profile name). See core/model_output.py.
"""
from __future__ import annotations

import pytest

from core.model_output import strip_user_impersonation


@pytest.mark.parametrize("text,expected", [
    ("I'm Friday, an assistant named Luffy.",
     "I'm Friday, an assistant named FRIDAY."),
    ("I am Luffy, your assistant.", "I am FRIDAY, your assistant."),
    ("My name is Luffy and I can help.", "My name is FRIDAY and I can help."),
    ("This is Luffy speaking.", "This is FRIDAY speaking."),
    ("I'm an assistant called Luffy.", "I'm an assistant called FRIDAY."),
])
def test_self_identification_is_rewritten(text, expected):
    assert strip_user_impersonation(text, "Luffy") == expected


@pytest.mark.parametrize("text", [
    "Luffy, here's what I found in the document.",   # addressing the user — fine
    "You asked me earlier, Luffy.",                  # addressing the user — fine
    "I'm FRIDAY, your assistant.",                   # already correct
])
def test_legitimate_uses_are_untouched(text):
    assert strip_user_impersonation(text, "Luffy") == text


def test_case_insensitive():
    assert strip_user_impersonation("i am LUFFY here", "luffy") == "i am FRIDAY here"


def test_assistant_name_is_not_hardcoded():
    # The replacement target follows the persona name, not a literal "FRIDAY".
    out = strip_user_impersonation("I am Luffy, an assistant named Luffy.",
                                   "Luffy", assistant_name="Jarvis")
    assert out == "I am Jarvis, an assistant named Jarvis."


def test_empty_name_is_noop():
    msg = "I am Luffy."
    assert strip_user_impersonation(msg, "") == msg
    assert strip_user_impersonation(msg, None) == msg


def test_non_string_returns_empty_string():
    assert strip_user_impersonation(None, "Luffy") == ""
    assert strip_user_impersonation(123, "Luffy") == ""


# ── Parroted-guard scrub (2026-05-29 v3) ──────────────────────────────────
# The 0.8B model sometimes opens a reply with the identity-guard sentence it
# was instructed with. That meta-disclaimer must be stripped before display.
@pytest.mark.parametrize("text,expected", [
    ("Understood. I am Friday, the assistant, not the user.\n\nHere's the summary.",
     "Here's the summary."),
    ("I am Friday, the assistant, not the user. The document covers X.",
     "The document covers X."),
    ("I'm Friday, the assistant, not the user.", ""),
    ("I am the assistant, not the user. Done.", "Done."),
])
def test_parroted_guard_is_stripped(text, expected):
    # Works even with no user name (the scrub is name-independent).
    assert strip_user_impersonation(text, "", assistant_name="Friday") == expected


def test_guard_scrub_runs_even_with_user_name():
    out = strip_user_impersonation(
        "Understood. I am Friday, the assistant, not the user. I'm Luffy here.",
        "Luffy", assistant_name="Friday",
    )
    assert out == "I'm Friday here."


def test_normal_reply_with_word_user_is_untouched():
    # "not the user" must appear as the guard phrasing to trigger a strip;
    # ordinary sentences mentioning the user are left alone.
    msg = "You are the user I'm assisting today."
    assert strip_user_impersonation(msg, "Luffy", assistant_name="Friday") == msg
