"""P3.16 — CheckpointManager save/load/resume."""
import os
import pytest

from core.runtime.checkpoint_manager import CheckpointManager


@pytest.fixture()
def mgr(tmp_path):
    return CheckpointManager(checkpoints_dir=str(tmp_path))


def test_save_and_load(mgr):
    state = {"step": 2, "urls_done": ["https://a.com"]}
    mgr.save("task_abc", state)
    loaded = mgr.load("task_abc")
    assert loaded == state


def test_load_missing_returns_none(mgr):
    assert mgr.load("no_such_task") is None


def test_delete_existing(mgr):
    mgr.save("t1", {"x": 1})
    assert mgr.delete("t1") is True
    assert mgr.load("t1") is None


def test_delete_nonexistent_returns_false(mgr):
    assert mgr.delete("ghost") is False


def test_list_tasks_empty(mgr):
    assert mgr.list_tasks() == []


def test_list_tasks(mgr):
    mgr.save("task_a", {})
    mgr.save("task_b", {})
    tasks = mgr.list_tasks()
    assert set(tasks) == {"task_a", "task_b"}


def test_new_task_id_is_unique(mgr):
    ids = {mgr.new_task_id() for _ in range(20)}
    assert len(ids) == 20


def test_new_task_id_is_hex(mgr):
    tid = mgr.new_task_id()
    assert len(tid) == 12
    int(tid, 16)  # raises ValueError if not hex


def test_overwrite_checkpoint(mgr):
    mgr.save("t", {"v": 1})
    mgr.save("t", {"v": 2})
    assert mgr.load("t")["v"] == 2


def test_missing_dir_created_on_init(tmp_path):
    d = tmp_path / "deep" / "nested"
    mgr = CheckpointManager(checkpoints_dir=str(d))
    assert os.path.isdir(str(d))
