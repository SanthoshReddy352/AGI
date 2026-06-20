"""Native desktop-window launcher: icon assets, per-OS backend choice, and the
Linux PyGObject bridge that keeps the app from silently falling back to a browser
tab. These run offline — no window is ever opened."""
from __future__ import annotations

import os
from pathlib import Path

import namma_agent.app as app


def test_sparkle_icon_assets_exist():
    """The brand sparkle icons must ship so the window never shows the stock
    Python/pywebview icon."""
    assets = Path(app.__file__).resolve().parent / "assets"
    assert (assets / "sparkle.png").is_file()
    assert (assets / "sparkle.ico").is_file()


def test_icon_path_matches_platform(monkeypatch):
    monkeypatch.setattr(app.os, "name", "nt")
    assert app._icon_path().endswith("sparkle.ico")
    monkeypatch.setattr(app.os, "name", "posix")
    assert app._icon_path().endswith("sparkle.png")


def test_icon_path_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(app, "_ASSETS", tmp_path)  # empty dir → no icon
    assert app._icon_path() is None


def test_gui_order_windows_prefers_edgechromium(monkeypatch):
    """Windows must lead with EdgeChromium; the legacy MSHTML fallback is what
    made the window laggy."""
    monkeypatch.setattr(app.platform, "system", lambda: "Windows")
    order = app._gui_order()
    assert order[0] == "edgechromium"


def test_gui_order_linux_prefers_gtk(monkeypatch):
    monkeypatch.setattr(app.platform, "system", lambda: "Linux")
    assert app._gui_order()[0] == "gtk"


def test_ensure_linux_backend_noop_off_linux(monkeypatch):
    """On Windows/macOS the bridge must not touch sys.path."""
    monkeypatch.setattr(app.platform, "system", lambda: "Windows")
    before = list(app.sys.path)
    app._ensure_linux_gui_backend()
    assert app.sys.path == before


def test_set_windows_app_id_noop_off_windows(monkeypatch):
    """No-op (and no crash) when not on Windows."""
    monkeypatch.setattr(app.os, "name", "posix")
    app._set_windows_app_id("Namma Agent")  # must not raise
