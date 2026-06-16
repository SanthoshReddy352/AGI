"""Phase C — controlled-browser tools (play_youtube + media_control).

Uses a fake controller so CI never launches a real browser.
"""
from __future__ import annotations

import pytest

import friday.tools.browser as browser
from friday.core.tools import ToolRegistry


class _FakeController:
    def __init__(self):
        self.calls = []

    def play_youtube(self, query, fullscreen=True):
        self.calls.append(("play_youtube", query, fullscreen))
        return {"title": f"{query} (video)", "url": "https://youtube.com/watch?v=abc"}

    def play_youtube_music(self, query):
        self.calls.append(("play_youtube_music", query))
        return {"title": f"{query} (song)", "url": "https://music.youtube.com/watch?v=xyz"}

    def media(self, action, seconds=0.0):
        self.calls.append(("media", action, seconds))
        return {"paused": action == "pause", "position": seconds, "duration": 200}

    def fullscreen(self):
        self.calls.append(("fullscreen",))
        return {"fullscreen": True}

    def status(self):
        return {"playing": True, "position": 5, "duration": 200}


@pytest.fixture
def reg_with_fake(monkeypatch):
    fake = _FakeController()
    monkeypatch.setattr(browser, "_engine", lambda: "playwright")
    monkeypatch.setattr(browser, "_get_controller", lambda: fake)
    reg = ToolRegistry()
    browser.register(reg)
    return reg, fake


def test_tools_registered(reg_with_fake):
    reg, _ = reg_with_fake
    assert {"play_youtube", "media_control", "play_youtube_music",
            "open_browser_url", "search_google"} <= set(reg.names())


def test_play_youtube_uses_controller(reg_with_fake):
    reg, fake = reg_with_fake
    out = reg.execute("play_youtube", {"query": "lofi beats"})
    assert out.ok and "lofi beats" in out.content
    assert fake.calls[0] == ("play_youtube", "lofi beats", True)


def test_play_youtube_music_uses_controller(reg_with_fake):
    reg, fake = reg_with_fake
    out = reg.execute("play_youtube_music", {"query": "daft punk"})
    assert out.ok and "daft punk" in out.content
    assert ("play_youtube_music", "daft punk") in fake.calls


def test_play_youtube_music_fallback(monkeypatch):
    monkeypatch.setattr(browser, "_engine", lambda: "webbrowser")
    opened = {}
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: opened.setdefault("url", url) or True)
    reg = ToolRegistry()
    browser.register(reg)
    out = reg.execute("play_youtube_music", {"query": "jazz"})
    assert out.ok and "music.youtube.com" in opened["url"]


def test_detect_default_browser_runs():
    from friday.core.browser_controller import detect_default_browser
    # Should return a string (possibly empty) without raising.
    assert isinstance(detect_default_browser(), str)


def test_media_forward_seconds(reg_with_fake):
    reg, fake = reg_with_fake
    out = reg.execute("media_control", {"action": "skip", "seconds": 50})
    assert out.ok
    assert ("media", "forward", 50.0) in fake.calls


def test_media_back_default_seconds(reg_with_fake):
    reg, fake = reg_with_fake
    reg.execute("media_control", {"action": "rewind"})
    assert ("media", "back", 10.0) in fake.calls


def test_media_aliases(reg_with_fake):
    reg, fake = reg_with_fake
    for action, expected in [("resume", "play"), ("playpause", "toggle"),
                             ("prev", "previous"), ("next", "next")]:
        reg.execute("media_control", {"action": action})
        assert any(c[0] == "media" and c[1] == expected for c in fake.calls), action


def test_media_fullscreen_routes_to_fullscreen(reg_with_fake):
    reg, fake = reg_with_fake
    reg.execute("media_control", {"action": "fullscreen"})
    assert ("fullscreen",) in fake.calls


def test_unknown_action(reg_with_fake):
    reg, _ = reg_with_fake
    out = reg.execute("media_control", {"action": "explode"})
    assert not out.ok and "unknown action" in out.error


def test_media_control_without_engine(monkeypatch):
    monkeypatch.setattr(browser, "_engine", lambda: "webbrowser")
    reg = ToolRegistry()
    browser.register(reg)
    out = reg.execute("media_control", {"action": "pause"})
    assert not out.ok and "controlled browser" in out.error


def test_play_youtube_fallback_when_no_engine(monkeypatch):
    monkeypatch.setattr(browser, "_engine", lambda: "webbrowser")
    opened = {}
    monkeypatch.setattr(browser.webbrowser, "open", lambda url: opened.setdefault("url", url) or True)
    reg = ToolRegistry()
    browser.register(reg)
    out = reg.execute("play_youtube", {"query": "test song"})
    assert out.ok and "youtube.com/results" in opened["url"]
