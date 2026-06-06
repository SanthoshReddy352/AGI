"""P3.2 — FTS5 full-text search over turns in SessionStore."""
import pytest
from core.stores.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=str(tmp_path / "test.db"))
    s._ensure_storage()
    return s


def _seed(store, session_id, turns):
    store.start_session(session_id)
    for role, text in turns:
        store.append_turn_row(session_id, role, text)


def test_fts_search_finds_matching_turn(store):
    _seed(store, "s1", [("user", "the sky is blue today")])
    results = store.fts_search("blue")
    assert len(results) == 1
    assert results[0]["text"] == "the sky is blue today"


def test_fts_search_empty_query_returns_empty(store):
    _seed(store, "s1", [("user", "some content here")])
    assert store.fts_search("") == []
    assert store.fts_search("   ") == []


def test_fts_search_no_match_returns_empty(store):
    _seed(store, "s1", [("user", "hello world")])
    results = store.fts_search("zzznomatch")
    assert results == []


def test_fts_search_result_fields(store):
    _seed(store, "sess1", [("assistant", "The weather is sunny.")])
    results = store.fts_search("sunny")
    assert len(results) == 1
    r = results[0]
    assert "id" in r
    assert r["session_id"] == "sess1"
    assert r["role"] == "assistant"
    assert "weather" in r["text"]
    assert "created_at" in r


def test_fts_search_limit_respected(store):
    _seed(store, "s1", [
        ("user", "apples are red"),
        ("user", "apples are green"),
        ("user", "apples are yellow"),
    ])
    results = store.fts_search("apples", limit=2)
    assert len(results) <= 2


def test_fts_search_across_multiple_sessions(store):
    _seed(store, "s1", [("user", "chocolate cake is delicious")])
    _seed(store, "s2", [("user", "chocolate ice cream is great")])
    results = store.fts_search("chocolate")
    assert len(results) == 2
    session_ids = {r["session_id"] for r in results}
    assert session_ids == {"s1", "s2"}


def test_fts_search_case_insensitive(store):
    _seed(store, "s1", [("user", "Python programming language")])
    results = store.fts_search("python")
    assert len(results) == 1


def test_fts_search_multi_word_query(store):
    _seed(store, "s1", [
        ("user", "the quick brown fox"),
        ("user", "the slow brown bear"),
    ])
    results = store.fts_search("quick fox")
    assert len(results) == 1
    assert "quick" in results[0]["text"]


def test_fts_search_does_not_return_unrelated_turns(store):
    _seed(store, "s1", [
        ("user", "I love pizza"),
        ("user", "I love sushi"),
        ("assistant", "Great choices!"),
    ])
    results = store.fts_search("pizza")
    assert all("pizza" in r["text"] for r in results)
    assert len(results) == 1


def test_fts_search_default_limit_is_ten(store):
    session_id = "bigses"
    store.start_session(session_id)
    for i in range(15):
        store.append_turn_row(session_id, "user", f"matching keyword entry {i}")
    results = store.fts_search("matching keyword")
    assert len(results) <= 10
