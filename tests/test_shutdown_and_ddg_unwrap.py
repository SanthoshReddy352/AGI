"""Regression tests for two live-session bugs surfaced 2026-05-24 17:58.

1. DDG result URLs are wrapped in `https://duckduckgo.com/l/?uddg=…`
   tracking redirects. The wrappers 400 when trafilatura fetches them,
   so research lost every web hit; they also can't be opened in a
   browser as-is.
2. Exit was laggy and sometimes triggered Qt's force-quit dialog
   because `_snapshot_session_on_exit` (an LLM call) and
   `lifecycle.stop_all()` ran unbounded inside the Qt closeEvent.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ── DDG unwrap (additional cases not in test_research_quick_mode.py) ──


@pytest.mark.parametrize("wrapped,real", [
    # Trailing &amp;rut — html-entity escape variant that DDG emits.
    ("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com%2Fpath&amp;rut=xyz",
     "https://a.com/path"),
    # No-www variant
    ("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fb.com%2F",
     "https://b.com/"),
    # Query-string in the encoded URL preserved.
    ("https://duckduckgo.com/l/?uddg=https%3A%2F%2Fc.com%2Fpath%3Fq%3D1&rut=z",
     "https://c.com/path?q=1"),
])
def test_unwrap_handles_real_ddg_shapes(wrapped, real):
    from modules.web.plugin import _unwrap_ddg_redirect
    assert _unwrap_ddg_redirect(wrapped) == real


def test_unwrap_skips_non_ddg_urls():
    from modules.web.plugin import _unwrap_ddg_redirect
    for url in (
        "https://example.com/article",
        "http://news.ycombinator.com/item?id=1",
        "https://en.wikipedia.org/wiki/Linux",
    ):
        assert _unwrap_ddg_redirect(url) == url


# ── bounded shutdown ─────────────────────────────────────────────────


def _make_app_with_slow_lifecycle(snapshot_delay: float, lifecycle_delay: float):
    """Build a stub FridayApp whose snapshot + lifecycle stop sleep
    for the given durations. Used to verify the bounded shutdown."""
    from core.app import FridayApp

    app = FridayApp.__new__(FridayApp)
    app._shutdown_requested = False
    app.stt = None
    app.tts = None

    # Stub the slow steps so we control timing.
    def slow_snapshot():
        time.sleep(snapshot_delay)

    def slow_stop_all():
        time.sleep(lifecycle_delay)

    app._snapshot_session_on_exit = slow_snapshot
    app.lifecycle = SimpleNamespace(stop_all=slow_stop_all)
    return app


def test_shutdown_respects_deadline_when_snapshot_hangs():
    """If the LLM-based snapshot hangs, shutdown still returns within
    the deadline."""
    from core.app import FridayApp

    app = _make_app_with_slow_lifecycle(
        snapshot_delay=10.0,  # would normally block 10s
        lifecycle_delay=0.05,
    )

    started = time.monotonic()
    app.shutdown(deadline_s=1.5)
    elapsed = time.monotonic() - started

    # Allow some slack but must be well under the 10s hang.
    assert elapsed < 3.0, f"shutdown took {elapsed:.2f}s with hung snapshot"


def test_shutdown_respects_deadline_when_lifecycle_hangs():
    """If a plugin's stop() hangs, the bounded shutdown lets the
    process die rather than waiting forever."""
    app = _make_app_with_slow_lifecycle(
        snapshot_delay=0.05,
        lifecycle_delay=10.0,
    )

    started = time.monotonic()
    app.shutdown(deadline_s=1.0)
    elapsed = time.monotonic() - started

    assert elapsed < 2.5, f"shutdown took {elapsed:.2f}s with hung lifecycle"


def test_shutdown_is_idempotent():
    """Calling shutdown twice doesn't double-run the steps."""
    snap_calls = []
    stop_calls = []

    from core.app import FridayApp
    app = FridayApp.__new__(FridayApp)
    app._shutdown_requested = False
    app.stt = None
    app.tts = None
    app._snapshot_session_on_exit = lambda: snap_calls.append(1)
    app.lifecycle = SimpleNamespace(stop_all=lambda: stop_calls.append(1))

    app.shutdown(deadline_s=2.0)
    app.shutdown(deadline_s=2.0)

    assert len(snap_calls) == 1
    assert len(stop_calls) == 1


def test_shutdown_completes_quickly_in_happy_path():
    """When neither snapshot nor lifecycle hangs, total wall-clock is
    well under the deadline."""
    app = _make_app_with_slow_lifecycle(
        snapshot_delay=0.05,
        lifecycle_delay=0.05,
    )
    started = time.monotonic()
    app.shutdown(deadline_s=3.0)
    elapsed = time.monotonic() - started
    assert elapsed < 0.5, f"happy-path shutdown took {elapsed:.2f}s"
