"""Track 5.1c — focused GoalStore integration tests."""
from __future__ import annotations

import sqlite3

import pytest

from core.stores import GoalStore


@pytest.fixture()
def store(tmp_path):
    return GoalStore(str(tmp_path / "friday.db"))


def test_creates_only_its_own_tables(store):
    conn = sqlite3.connect(store.db_path)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()}
    assert names == {"goals", "goal_progress"}


# ----------------------------------------------------------------------
# create + list + get
# ----------------------------------------------------------------------

def test_create_goal_and_list(store):
    gid = store.create_goal("Ship 5.1c", description="three new stores",
                            level="task", session_id="s1")
    goals = store.list_goals(session_id="s1")
    assert [g["id"] for g in goals] == [gid]
    assert goals[0]["title"] == "Ship 5.1c"
    assert goals[0]["status"] == "active"
    assert goals[0]["score"] == 0.0
    assert goals[0]["health"] == "on_track"


def test_get_goal_returns_none_for_unknown(store):
    assert store.get_goal("nope") is None


def test_list_goals_filters_by_status(store):
    a = store.create_goal("active", session_id="s1")
    b = store.create_goal("done", session_id="s1")
    store.update_goal_status(b, "completed")
    active_ids = {g["id"] for g in store.list_goals(session_id="s1", status="active")}
    done_ids = {g["id"] for g in store.list_goals(session_id="s1", status="completed")}
    assert active_ids == {a}
    assert done_ids == {b}


# ----------------------------------------------------------------------
# score + health tiers + progress log
# ----------------------------------------------------------------------

def test_update_goal_score_writes_progress_row_and_recomputes_health(store):
    gid = store.create_goal("test", session_id="s1")
    assert store.update_goal_score(gid, 0.8, note="great progress") is True
    assert store.get_goal(gid)["score"] == 0.8
    assert store.get_goal(gid)["health"] == "on_track"

    assert store.update_goal_score(gid, 0.5) is True
    assert store.get_goal(gid)["health"] == "at_risk"

    assert store.update_goal_score(gid, 0.2) is True
    assert store.get_goal(gid)["health"] == "behind"

    # Three progress rows for one goal.
    conn = sqlite3.connect(store.db_path)
    rows = conn.execute(
        "SELECT score_before, score_after FROM goal_progress WHERE goal_id = ? ORDER BY id",
        (gid,),
    ).fetchall()
    assert rows == [(0.0, 0.8), (0.8, 0.5), (0.5, 0.2)]


def test_update_goal_score_returns_false_for_unknown(store):
    assert store.update_goal_score("not-real", 0.5) is False


def test_update_goal_status_returns_false_for_unknown(store):
    assert store.update_goal_status("not-real", "completed") is False


# ----------------------------------------------------------------------
# ContextStore delegators stay byte-equivalent
# ----------------------------------------------------------------------

def test_context_store_goal_methods_share_store_state(tmp_path):
    from core.stores import ContextStore
    cs = ContextStore(
        db_path=str(tmp_path / "friday.db"),
        vector_path=str(tmp_path / "chroma"),
    )
    gid = cs.create_goal("via context store", session_id="s1")
    # Direct path sees it.
    direct = cs._goal_store.get_goal(gid)
    assert direct is not None
    assert direct["title"] == "via context store"
