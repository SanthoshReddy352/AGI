"""P3.12 — Delegate subagent."""
import threading
import time

import pytest
from unittest.mock import MagicMock

from core.delegate import Delegate, make_delegate


def _make_router(response="mocked answer"):
    router = MagicMock()
    router.process_text = MagicMock(return_value=response)
    return router


def test_run_returns_string():
    d = Delegate(_make_router("hello"))
    result = d.run("what time is it?")
    assert result == "hello"


def test_run_router_called_with_query():
    router = _make_router()
    d = Delegate(router)
    d.run("my query")
    router.process_text.assert_called_once_with("my query")


def test_run_on_exception_returns_error_string():
    router = MagicMock()
    router.process_text.side_effect = RuntimeError("boom")
    d = Delegate(router)
    result = d.run("query")
    assert "Delegation failed" in result or "boom" in result


def test_run_async_calls_callback():
    done = threading.Event()
    received = []

    def cb(r):
        received.append(r)
        done.set()

    d = Delegate(_make_router("async result"))
    d.run_async("test", callback=cb)
    done.wait(timeout=5)
    assert received == ["async result"]


def test_run_async_returns_thread():
    d = Delegate(_make_router())
    t = d.run_async("q")
    assert isinstance(t, threading.Thread)


def test_run_and_wait_success():
    d = Delegate(_make_router("waited result"))
    result, timed_out = d.run_and_wait("q", timeout_sec=5)
    assert result == "waited result"
    assert timed_out is False


def test_run_and_wait_timeout():
    def _slow_router():
        r = MagicMock()
        def _slow(q):
            time.sleep(10)
            return "never"
        r.process_text = _slow
        return r

    d = Delegate(_slow_router())
    result, timed_out = d.run_and_wait("q", timeout_sec=0.2)
    assert timed_out is True
    assert "taking longer" in result.lower() or result


def test_make_delegate_factory():
    router = _make_router()
    d = make_delegate(router)
    assert isinstance(d, Delegate)
    assert d._router is router


def test_run_non_string_result_cast():
    router = MagicMock()
    router.process_text.return_value = 42
    d = Delegate(router)
    result = d.run("q")
    assert isinstance(result, str)
