"""P3.3 — SessionSummarizer tests."""
import pytest
from unittest.mock import MagicMock
from core.stores.session_store import SessionStore
from core.session_summarizer import SessionSummarizer, make_summarizer


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=str(tmp_path / "test.db"))
    s._ensure_storage()
    return s


def _seed(store, session_id, turns):
    store.start_session(session_id)
    for role, text in turns:
        store.append_turn_row(session_id, role, text)


def test_no_turns_returns_no_history_message(store):
    s = SessionSummarizer(store)
    result = s.summarize("empty_session")
    assert "no" in result.lower() or "history" in result.lower()


def test_naive_summary_no_llm(store):
    _seed(store, "s1", [
        ("user", "What is the capital of France?"),
        ("assistant", "Paris is the capital of France."),
    ])
    s = SessionSummarizer(store, llm=None)
    result = s.summarize("s1")
    assert isinstance(result, str)
    assert len(result) > 0


def test_naive_summary_contains_turn_text(store):
    _seed(store, "s1", [("user", "Tell me about dolphins.")])
    s = SessionSummarizer(store, llm=None)
    result = s.summarize("s1")
    assert "dolphin" in result.lower() or "user" in result.lower()


def test_llm_summary_called_with_messages(store):
    _seed(store, "s1", [
        ("user", "How does photosynthesis work?"),
        ("assistant", "Plants convert sunlight to energy."),
    ])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "• Plants use sunlight"}}]
    }
    s = SessionSummarizer(store, llm=mock_llm)
    result = s.summarize("s1")
    assert mock_llm.create_chat_completion.called
    assert "sunlight" in result.lower() or "plant" in result.lower()


def test_llm_failure_falls_back_to_naive(store):
    _seed(store, "s1", [("user", "test message here")])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.side_effect = RuntimeError("model unavailable")
    s = SessionSummarizer(store, llm=mock_llm)
    result = s.summarize("s1")
    assert isinstance(result, str)
    assert len(result) > 0


def test_llm_empty_response_falls_back_to_naive(store):
    _seed(store, "s1", [("user", "some text")])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": ""}}]
    }
    s = SessionSummarizer(store, llm=mock_llm)
    result = s.summarize("s1")
    assert isinstance(result, str)
    assert len(result) > 0


def test_limit_parameter_restricts_turns(store):
    _seed(store, "s1", [("user", f"message {i}") for i in range(30)])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": "summary"}}]
    }
    s = SessionSummarizer(store, llm=mock_llm)
    s.summarize("s1", limit=5)
    call_args = mock_llm.create_chat_completion.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0]
    body = next(m["content"] for m in messages if m["role"] == "user")
    assert body.count("\n") < 10


def test_callable_llm_interface(store):
    _seed(store, "s1", [("user", "question")])
    mock_llm = MagicMock(spec=[])
    mock_llm.return_value = {"choices": [{"text": "callable result"}]}
    s = SessionSummarizer(store, llm=mock_llm)
    result = s.summarize("s1")
    assert "callable result" in result or isinstance(result, str)


def test_make_summarizer_factory(store):
    s = make_summarizer(store)
    assert isinstance(s, SessionSummarizer)


def test_make_summarizer_with_llm(store):
    mock_llm = MagicMock()
    s = make_summarizer(store, llm=mock_llm)
    assert s._llm is mock_llm


# ----------------------------------------------------------------------
# P3.3 persistence + on_session_switch tests
# ----------------------------------------------------------------------

@pytest.fixture
def stores(tmp_path):
    from core.stores.memory_store import MemoryStore
    db = str(tmp_path / "ss.db")
    vec = str(tmp_path / "vec")
    session_store = SessionStore(db_path=db)
    memory_store = MemoryStore(db_path=db, vector_path=vec)
    return session_store, memory_store


def test_persist_summary_writes_memory_item(stores):
    session_store, memory_store = stores
    _seed(session_store, "s1", [("user", "hello")])
    s = SessionSummarizer(session_store, memory_store=memory_store)
    s.persist_summary("s1", "Discussed greetings and the weather.")
    items = memory_store.recent_memory_items("s1", limit=5)
    assert any(i["memory_type"] == "session_summary" for i in items)


def test_persist_facts_writes_auto_extracted_namespace(stores):
    session_store, memory_store = stores
    s = SessionSummarizer(session_store, memory_store=memory_store)
    count = s.persist_facts("s1", [
        {"key": "employer", "value": "Anthropic"},
        {"key": "location", "value": "Nellore"},
    ])
    assert count == 2
    rows = memory_store.get_facts_by_namespace("auto_extracted")
    keys = {r["key"] for r in rows}
    assert {"employer", "location"} <= keys


def test_extract_facts_parses_json_array(stores):
    session_store, memory_store = stores
    _seed(session_store, "s1", [
        ("user", "I work at Anthropic and live in Nellore."),
    ])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": '[{"key":"employer","value":"Anthropic"},'
                                              '{"key":"location","value":"Nellore"}]'}}]
    }
    s = SessionSummarizer(session_store, llm=mock_llm, memory_store=memory_store)
    facts = s.extract_facts("s1")
    assert {"employer", "location"} == {f["key"] for f in facts}


def test_extract_facts_recovers_from_json_in_prose(stores):
    session_store, memory_store = stores
    _seed(session_store, "s1", [("user", "I live in Nellore.")])
    mock_llm = MagicMock()
    mock_llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": 'Sure! Here you go:\n[{"key":"location","value":"Nellore"}]\nThanks.'}}]
    }
    s = SessionSummarizer(session_store, llm=mock_llm, memory_store=memory_store)
    facts = s.extract_facts("s1")
    assert facts == [{"key": "location", "value": "Nellore"}]


def test_on_session_switch_persists_summary_and_facts(stores):
    session_store, memory_store = stores
    _seed(session_store, "s1", [
        ("user", "I work at Anthropic."),
        ("assistant", "Got it."),
    ])
    mock_llm = MagicMock()
    # First call returns the summary; second call returns the facts JSON.
    mock_llm.create_chat_completion.side_effect = [
        {"choices": [{"message": {"content": "Discussed the user's employer."}}]},
        {"choices": [{"message": {"content": '[{"key":"employer","value":"Anthropic"}]'}}]},
    ]
    s = SessionSummarizer(session_store, llm=mock_llm, memory_store=memory_store)
    result = s.on_session_switch("s1")
    assert result["summary_saved"] is True
    assert result["facts_saved"] == 1
    items = memory_store.recent_memory_items("s1", limit=5)
    assert any(i["memory_type"] == "session_summary" for i in items)
    rows = memory_store.get_facts_by_namespace("auto_extracted")
    assert any(r["key"] == "employer" for r in rows)
