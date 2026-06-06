"""P3.16 — ProcessRegistry and runtime interrupt."""
import os
import signal
import subprocess
import sys
import time

import pytest

from core.runtime.process_registry import ProcessRegistry, ProcessEntry, get_process_registry
from core.runtime.interrupt import cancel_process, cancel_session, cancel_current


# ── ProcessRegistry ────────────────────────────────────────────────────────────

def test_register_and_get():
    r = ProcessRegistry()
    r.register(1234, label="nmap", session_id="s1")
    entry = r.get(1234)
    assert entry is not None
    assert entry.pid == 1234
    assert entry.label == "nmap"
    assert entry.session_id == "s1"


def test_unregister():
    r = ProcessRegistry()
    r.register(9999, label="test", session_id="s")
    r.unregister(9999)
    assert r.get(9999) is None


def test_all_for_session():
    r = ProcessRegistry()
    r.register(1, label="a", session_id="alpha")
    r.register(2, label="b", session_id="beta")
    r.register(3, label="c", session_id="alpha")
    results = r.all_for_session("alpha")
    assert len(results) == 2
    assert all(e.session_id == "alpha" for e in results)


def test_all_returns_all_entries():
    r = ProcessRegistry()
    r.register(10, label="x", session_id="s")
    r.register(20, label="y", session_id="t")
    assert len(r.all()) == 2


def test_clear():
    r = ProcessRegistry()
    r.register(100, label="test", session_id="s")
    r.clear()
    assert r.all() == []


def test_cancel_nonexistent_pid_returns_false():
    # PID 999999999 should not exist
    result = cancel_process(999999999, timeout_sec=0.1)
    assert result is False


def test_global_singleton_is_same_object():
    a = get_process_registry()
    b = get_process_registry()
    assert a is b


def test_cancel_current_empty_registry_returns_zero():
    registry = get_process_registry()
    registry.clear()
    assert cancel_current(timeout_sec=0.1) == 0


def test_cancel_session_no_matching_entries():
    registry = get_process_registry()
    registry.clear()
    registry.register(1, label="other", session_id="other_session")
    count = cancel_session("nonexistent_session", timeout_sec=0.1)
    assert count == 0
    registry.clear()


def test_process_entry_has_started_at():
    before = time.time()
    entry = ProcessEntry(pid=1, label="l", session_id="s")
    assert entry.started_at >= before
