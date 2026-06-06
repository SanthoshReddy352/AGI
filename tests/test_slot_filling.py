"""Phase 3 / Track 2.4 — unified slot-filling foundation tests.

Covers :class:`core.planning.slot_filling.SlotFiller`:
  * caller-supplied (known) values win and are carried through
  * deterministic extractors fill before any LLM call
  * the LLM is consulted ONLY for still-missing required slots
  * `planner=None` (offline) degrades to deterministic-only
  * optional slots fall back to defaults; missing required slots drive
    `next_question`
  * alias normalization (caller + LLM keys)
  * the template ask:/slot: bridge (`specs_from_template`)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.planning.slot_filling import (
    SlotFiller,
    SlotSpec,
    get_extractor,
    register_extractor,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeSlotFill:
    def __init__(self, filled, *, missing=None, confidence=0.9, next_question=""):
        self.filled_slots = filled
        self.missing_slots = missing or []
        self.confidence = confidence
        self.next_question = next_question


class _FakePlanner:
    """Records calls and returns a canned SlotFill."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def fill_slots(self, user_text, selected):
        self.calls.append((user_text, selected))
        return self._response


class _BoomPlanner:
    def __init__(self):
        self.calls = 0

    def fill_slots(self, user_text, selected):
        self.calls += 1
        raise RuntimeError("model offline")


# ---------------------------------------------------------------------------
# Deterministic-only behaviour
# ---------------------------------------------------------------------------

def test_known_values_win_and_skip_extractor():
    seen = []

    def extractor(text):
        seen.append(text)
        return "from-extractor"

    spec = SlotSpec(name="city", extractor=extractor)
    result = SlotFiller(planner=None).fill([spec], "anything", known={"city": "Paris"})

    assert result.filled["city"] == "Paris"
    assert result.sources["city"] == "known"
    assert seen == []  # extractor never ran — known value short-circuited it
    assert result.complete


def test_extractor_fills_when_no_known_value():
    spec = SlotSpec(name="content", extractor=lambda t: "hello" if "write" in t else "")
    result = SlotFiller(planner=None).fill([spec], "write hello")

    assert result.filled["content"] == "hello"
    assert result.sources["content"] == "extractor"
    assert result.missing == []


def test_missing_required_slot_drives_next_question():
    spec = SlotSpec(name="target", prompt="Which host?")
    result = SlotFiller(planner=None).fill([spec], "scan it")

    assert result.missing == ["target"]
    assert result.next_question == "Which host?"
    assert not result.complete


def test_default_question_when_no_prompt():
    spec = SlotSpec(name="target_subnet")
    result = SlotFiller(planner=None).fill([spec], "")
    assert result.next_question == "What is the target subnet?"


def test_optional_slot_uses_default():
    spec = SlotSpec(name="profile", required=False, default="quick")
    result = SlotFiller(planner=None).fill([spec], "go")

    assert result.filled["profile"] == "quick"
    assert result.sources["profile"] == "default"
    assert result.missing == []  # optional never blocks


def test_offline_filler_never_calls_llm_even_if_missing():
    # planner=None means use_llm is forced off; a required slot stays missing
    # without raising.
    spec = SlotSpec(name="target", required=True)
    result = SlotFiller(planner=None).fill([spec], "do the thing")
    assert result.missing == ["target"]


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

def test_llm_consulted_only_for_missing_required():
    planner = _FakePlanner(_FakeSlotFill({"target": "10.0.0.1"}, confidence=0.8))
    specs = [
        SlotSpec(name="content", extractor=lambda t: "body"),  # filled by extractor
        SlotSpec(name="target"),                               # only this is missing
    ]
    result = SlotFiller(planner).fill(specs, "write body and scan")

    assert planner.calls, "LLM should be consulted for the missing required slot"
    _, selected = planner.calls[0]
    assert "target" in selected["required_slots"]
    assert result.filled["target"] == "10.0.0.1"
    assert result.sources["target"] == "llm"
    assert result.confidence == 0.8
    assert result.complete


def test_llm_not_called_when_extractors_satisfy_all_required():
    planner = _FakePlanner(_FakeSlotFill({}))
    spec = SlotSpec(name="content", extractor=lambda t: "x")
    SlotFiller(planner).fill([spec], "write x")
    assert planner.calls == []


def test_llm_failure_is_swallowed():
    planner = _BoomPlanner()
    spec = SlotSpec(name="target", required=True)
    result = SlotFiller(planner).fill([spec], "scan something")

    assert planner.calls == 1
    assert result.missing == ["target"]  # degrades cleanly
    assert result.confidence == 1.0


def test_use_llm_false_disables_model():
    planner = _FakePlanner(_FakeSlotFill({"target": "x"}))
    spec = SlotSpec(name="target")
    result = SlotFiller(planner, use_llm=False).fill([spec], "scan")
    assert planner.calls == []
    assert result.missing == ["target"]


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------

def test_known_alias_is_normalized_to_canonical_name():
    spec = SlotSpec(name="target", aliases=("host", "ip"))
    result = SlotFiller(planner=None).fill([spec], "x", known={"host": "1.2.3.4"})
    assert result.filled["target"] == "1.2.3.4"
    assert "host" not in result.filled


def test_llm_alias_key_is_normalized():
    planner = _FakePlanner(_FakeSlotFill({"host": "1.2.3.4"}))
    spec = SlotSpec(name="target", aliases=("host",))
    result = SlotFiller(planner).fill([spec], "scan it")
    assert result.filled["target"] == "1.2.3.4"


# ---------------------------------------------------------------------------
# Named extractor registry
# ---------------------------------------------------------------------------

def test_builtin_quoted_content_extractor_registered():
    fn = get_extractor("quoted_content")
    assert fn is not None
    assert fn("write 'hello' to x.txt") == "hello"


def test_spec_can_reference_named_extractor():
    register_extractor("shouty", lambda t: t.upper() if t else "")
    spec = SlotSpec(name="msg", extractor="shouty")
    result = SlotFiller(planner=None).fill([spec], "hi")
    assert result.filled["msg"] == "HI"


def test_unknown_named_extractor_resolves_to_none():
    spec = SlotSpec(name="x", extractor="does-not-exist")
    # No crash; slot simply stays missing.
    result = SlotFiller(planner=None).fill([spec], "text")
    assert result.missing == ["x"]


# ---------------------------------------------------------------------------
# Template bridge
# ---------------------------------------------------------------------------

class _FakeStep:
    def __init__(self, *, slot="", ask="", extract_with="", capability=""):
        self.slot = slot
        self.ask = ask
        self.extract_with = extract_with
        self.capability = capability

    @property
    def is_ask_step(self):
        return bool(self.ask and self.slot) and not self.capability


class _FakeTemplate:
    def __init__(self, steps, optional_inputs=None):
        self.steps = steps
        self.optional_inputs = optional_inputs or []


class _FakeExecutor:
    def __init__(self, value):
        self._value = value
        self.calls = []

    def execute(self, name, text, ctx):
        self.calls.append((name, text))
        return {"value": self._value}


def test_specs_from_template_maps_ask_steps():
    template = _FakeTemplate(
        steps=[
            _FakeStep(slot="user_name", ask="What's your name?", extract_with="extract_name"),
            _FakeStep(slot="user_role", ask="What do you do?"),
            _FakeStep(capability="complete_onboarding"),  # not an ask step
        ],
        optional_inputs=["user_role"],
    )
    specs = SlotFiller.specs_from_template(template)
    assert [s.name for s in specs] == ["user_name", "user_role"]
    assert specs[0].prompt == "What's your name?"
    assert specs[0].required is True
    assert specs[1].required is False  # in optional_inputs


def test_specs_from_template_wraps_extract_with_capability():
    executor = _FakeExecutor("Tony")
    template = _FakeTemplate(steps=[
        _FakeStep(slot="user_name", ask="Name?", extract_with="extract_user_name"),
    ])
    specs = SlotFiller.specs_from_template(template, capability_executor=executor)
    result = SlotFiller(planner=None).fill(specs, "my name is Tony")
    assert result.filled["user_name"] == "Tony"
    assert executor.calls == [("extract_user_name", "my name is Tony")]
