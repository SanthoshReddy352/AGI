"""Smoke tests for the cross-turn harness itself.

These assert that the harness can drive turns through a real FridayApp and
capture observable state. They do NOT assert on specific tool selection or
response content — those belong in track-specific test files. The smoke
tests prove the rig works.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.conversation


def test_harness_constructs_app_and_runs_one_turn(conversation_runner):
    rec = conversation_runner.turn("hello")
    assert rec.text == "hello"
    assert rec.source == "cli"
    assert rec.duration_ms >= 0.0
    # response may be empty (some greetings produce no spoken text); harness
    # must still capture the record without raising.
    assert isinstance(rec.response, str)


def test_harness_records_multiple_turns_in_order(conversation_runner):
    convo = conversation_runner.run(["hello", "what time is it"])
    assert len(convo.turns) == 2
    assert convo.turns[0].text == "hello"
    assert convo.turns[1].text == "what time is it"
    assert convo.last is convo.turns[-1]


def test_conversation_assertion_chain_returns_self(conversation_runner):
    convo = conversation_runner.run(["hello"])
    # All assertion methods must return the Conversation so chains work.
    chained = convo.assert_response_does_not_contain("__never_in_any_response__")
    assert chained is convo


def test_turn_index_navigation(conversation_runner):
    convo = conversation_runner.run(["hello", "thanks"])
    # Targeting a specific turn must work and chain back.
    convo.turn(0).assert_response_does_not_contain("__sentinel__").then()


def test_out_of_range_turn_index_raises(conversation_runner):
    convo = conversation_runner.run(["hello"])
    with pytest.raises(AssertionError, match="out of range"):
        convo.turn(5)


def test_empty_conversation_last_raises(conversation_runner):
    from tests.conversation._harness import Conversation

    empty = Conversation(app=conversation_runner.app)
    with pytest.raises(AssertionError, match="no turns yet"):
        _ = empty.last


def test_convo_fn_fixture_works(convo_fn):
    convo = convo_fn(["hello"])
    assert len(convo.turns) == 1
    assert convo.app is not None
