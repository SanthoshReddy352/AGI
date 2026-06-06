"""P3.5 — MemoryNudger tests."""
import pytest
from unittest.mock import MagicMock

from core.memory.facade import MemoryFacade
from core.memory_nudger import MemoryNudger, NudgeHit, _cheap_match, make_nudger
from core.stores import ContextStore


@pytest.fixture
def facade(tmp_path):
    db = str(tmp_path / "n.db")
    cs = ContextStore(db_path=db, vector_path=str(tmp_path / "vec"))
    return MemoryFacade(cs)


# ----------------------------------------------------------------------
# Regex layer
# ----------------------------------------------------------------------

def test_cheap_match_employer():
    hit = _cheap_match("I work at Anthropic.")
    assert hit is not None
    assert hit.namespace == "user_profile"
    assert hit.key == "employer"
    assert "Anthropic" in hit.value


def test_cheap_match_location():
    hit = _cheap_match("I live in Nellore.")
    assert hit is not None
    assert hit.key == "location"
    assert "Nellore" in hit.value


def test_cheap_match_name():
    assert _cheap_match("call me Santhosh").key == "name"
    assert _cheap_match("my name is Sandeep").key == "name"


def test_cheap_match_preferences():
    hit = _cheap_match("I love jazz music")
    assert hit is not None
    assert hit.namespace == "preferences"
    assert hit.key == "loves"


def test_cheap_match_returns_none_for_non_personal_text():
    assert _cheap_match("the weather is great today") is None
    assert _cheap_match("") is None
    assert _cheap_match("what time is it") is None


def test_cheap_match_truncates_value_at_punctuation():
    hit = _cheap_match("I live in Nellore, which is a town in India.")
    assert hit is not None
    assert hit.value == "Nellore"


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------

def test_observe_writes_to_facts(facade):
    nudger = MemoryNudger(facade)
    hit = nudger.observe("I work at Anthropic.", session_id="s1")
    assert hit is not None
    # MemoryFacade writes to facts table via the user_profile mirror
    rows = facade._store.get_facts_by_namespace("user_profile")
    assert any(r["key"] == "employer" and "Anthropic" in r["value"] for r in rows)


def test_observe_no_match_returns_none(facade):
    nudger = MemoryNudger(facade)
    assert nudger.observe("what is the weather", session_id="s1") is None


def test_observe_skip_when_already_saved(facade):
    nudger = MemoryNudger(facade)
    assert nudger.observe("I work at Anthropic.", "s1", already_saved_keys={"employer"}) is None
    rows = facade._store.get_facts_by_namespace("user_profile")
    assert rows == []


def test_observe_no_session_id_no_op(facade):
    nudger = MemoryNudger(facade)
    assert nudger.observe("I work at X", session_id="") is None


def test_llm_confirmation_overrides_regex_value(facade):
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {
            "content": '{"namespace":"user_profile","key":"employer","value":"Anthropic PBC"}'
        }}]
    }
    nudger = MemoryNudger(facade, llm=mock_llm)
    hit = nudger.observe("I work at Anthropic.", session_id="s1")
    assert hit is not None
    assert hit.value == "Anthropic PBC"


def test_llm_failure_falls_back_to_regex_hit(facade):
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.side_effect = RuntimeError("boom")
    nudger = MemoryNudger(facade, llm=mock_llm)
    hit = nudger.observe("I work at Anthropic.", session_id="s1")
    assert hit is not None
    assert "Anthropic" in hit.value


def test_llm_returns_null_falls_back_to_regex_hit(facade):
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "null"}}]
    }
    nudger = MemoryNudger(facade, llm=mock_llm)
    hit = nudger.observe("I work at Anthropic.", session_id="s1")
    assert hit is not None


def test_make_nudger_factory(facade):
    n = make_nudger(facade)
    assert isinstance(n, MemoryNudger)


def test_nudge_hit_to_dict():
    h = NudgeHit(namespace="user_profile", key="employer", value="Anthropic")
    assert h.as_dict() == {"namespace": "user_profile",
                           "key": "employer", "value": "Anthropic"}
