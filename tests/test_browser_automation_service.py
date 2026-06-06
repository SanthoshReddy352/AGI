import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.browser_automation.service import BrowserMediaService


class DummyConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_browser_service_prefers_last_used_chrome_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    chrome_root = tmp_path / ".config" / "google-chrome"
    default_profile = chrome_root / "Default"
    default_profile.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps({"profile": {"last_used": "Default"}}),
        encoding="utf-8",
    )

    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))

    settings = service._resolve_profile_settings("chrome")

    assert settings["user_data_dir"] == str(chrome_root)
    assert settings["profile_directory"] == "Default"
    assert "--profile-directory=Default" in settings["launch_args"]


def test_get_page_recreates_closed_browser_context():
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    contexts = []

    class ClosedContext:
        pages = []

        def new_page(self):
            raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")

    class HealthyContext:
        def __init__(self):
            self.pages = []

        def new_page(self):
            return "healthy-page"

    contexts.extend([ClosedContext(), HealthyContext()])
    cleanup_calls = []

    def fake_ensure_context(browser_name):
        return contexts.pop(0)

    service._ensure_context = fake_ensure_context
    service._cleanup_playwright = lambda: cleanup_calls.append("cleanup")

    page = service._get_page("chrome", "youtube_music", "https://music.youtube.com")

    assert page == "healthy-page"
    assert cleanup_calls == ["cleanup"]
    assert service._pages["youtube_music"] == "healthy-page"


def test_get_page_returns_help_message_after_repeated_closed_contexts():
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    cleanup_calls = []

    class ClosedContext:
        pages = []

        def new_page(self):
            raise RuntimeError("BrowserContext.new_page: Target page, context or browser has been closed")

    service._ensure_context = lambda browser_name: ClosedContext()
    service._cleanup_playwright = lambda: cleanup_calls.append("cleanup")

    page = service._get_page("chrome", "youtube_music", "https://music.youtube.com")

    assert "Browser automation" in page or "Failed to start browser automation" in page
    assert cleanup_calls == ["cleanup", "cleanup"]


def test_browser_service_clones_profile_when_live_profile_is_locked(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    chrome_root = tmp_path / ".config" / "google-chrome"
    default_profile = chrome_root / "Default"
    default_profile.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps({"profile": {"last_used": "Default"}}),
        encoding="utf-8",
    )
    (default_profile / "Preferences").write_text("{}", encoding="utf-8")
    (default_profile / "Cookies").write_text("cookie-db", encoding="utf-8")
    (default_profile / "SingletonLock").write_text("locked", encoding="utf-8")
    (default_profile / "Cache").mkdir()

    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))

    locked_settings = service._resolve_profile_settings("chrome")
    cloned_settings = service._clone_profile_settings(locked_settings, "chrome")

    assert cloned_settings["mode"] == "cloned"
    assert cloned_settings["profile_directory"] == "Default"
    assert os.path.exists(os.path.join(cloned_settings["user_data_dir"], "Local State"))
    assert os.path.exists(os.path.join(cloned_settings["user_data_dir"], "Default", "Cookies"))
    assert not os.path.exists(os.path.join(cloned_settings["user_data_dir"], "Default", "SingletonLock"))
    assert not os.path.exists(os.path.join(cloned_settings["user_data_dir"], "Default", "Cache"))


def test_browser_service_prepares_signed_in_clone_outside_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    chrome_root = tmp_path / ".config" / "google-chrome"
    default_profile = chrome_root / "Default"
    default_profile.mkdir(parents=True)
    (chrome_root / "Local State").write_text(
        json.dumps({"profile": {"last_used": "Default"}}),
        encoding="utf-8",
    )
    (default_profile / "Cookies").write_text("cookie-db", encoding="utf-8")

    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))

    launch_settings = service._prepare_launch_profile_settings("chrome")

    assert launch_settings["mode"] == "cloned"
    assert launch_settings["profile_directory"] == "Default"
    assert launch_settings["user_data_dir"].startswith(str(tmp_path / ".cache" / "friday"))
    assert os.path.exists(os.path.join(launch_settings["user_data_dir"], "Default", "Cookies"))


def test_prepare_media_page_fullscreens_only_youtube():
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    calls = []

    class DummyPage:
        def wait_for_load_state(self, state):
            calls.append(("load", state))

        def wait_for_timeout(self, ms):
            calls.append(("timeout", ms))

        def bring_to_front(self):
            calls.append(("front", None))

    page = DummyPage()
    service._start_media_playback = lambda current_page: calls.append(("play", current_page))
    service._focus_browser_window = lambda platform_name, fullscreen=False: calls.append(("focus", platform_name, fullscreen))
    service._enter_fullscreen = lambda current_page: calls.append(("enter_fullscreen", current_page))
    service._exit_fullscreen = lambda current_page: calls.append(("exit_fullscreen", current_page))

    service._prepare_media_page(page, "youtube")
    service._prepare_media_page(page, "youtube_music")

    assert ("enter_fullscreen", page) in calls
    assert ("exit_fullscreen", page) in calls
    assert ("focus", "youtube", False) in calls
    assert ("focus", "youtube", True) in calls
    assert ("focus", "youtube_music", False) in calls


def test_launch_context_uses_real_password_store_settings(tmp_path):
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    profile_root = tmp_path / "chrome-clone"
    profile_root.mkdir()
    captured = {}

    class DummyChromium:
        def launch_persistent_context(self, **kwargs):
            captured.update(kwargs)
            return "context"

    context = service._launch_context(
        DummyChromium(),
        "/usr/bin/google-chrome",
        "chrome",
        {
            "user_data_dir": str(profile_root),
            "profile_directory": "Default",
            "launch_args": ["--profile-directory=Default"],
            "mode": "cloned",
        },
    )

    assert context == "context"
    assert captured["ignore_default_args"] == ["--password-store=basic", "--use-mock-keychain", "--enable-automation"]
    assert captured["no_viewport"] is True


# ---------------------------------------------------------------------------
# Multi-tab fixes (2026-05-23)
# ---------------------------------------------------------------------------


class _FakePage:
    """Minimal Playwright-page stand-in for multi-tab tests."""

    def __init__(self, label):
        self.label = label
        self.closed = False
        self.init_scripts = []
        self.front_calls = 0

    def is_closed(self):
        return self.closed

    def bring_to_front(self):
        self.front_calls += 1

    def add_init_script(self, src):
        self.init_scripts.append(src)


class _FakeContext:
    def __init__(self, initial_pages=None):
        self.pages = list(initial_pages or [])
        self.new_page_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        p = _FakePage(f"new-{self.new_page_calls}")
        self.pages.append(p)
        return p


def test_get_page_does_not_steal_other_platform_tab():
    """Regression: google_search must NOT repurpose the youtube tab.

    Repro of the 2026-05-23 16:40 'Google for capital of france -> kills
    youtube' scenario. Before the fix, _get_page returned context.pages[0]
    (the youtube tab) and self._pages["google_search"] pointed at it,
    then _do_search_google.page.goto(google_url) navigated youtube away.
    """
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    yt_page = _FakePage("youtube")
    service._pages["youtube"] = yt_page

    ctx = _FakeContext(initial_pages=[yt_page])
    service._ensure_context = lambda browser_name: ctx

    google_page = service._get_page("chrome", "google_search", "https://google.com")

    # A NEW tab must be created — youtube's page must not be repurposed.
    assert google_page is not yt_page
    assert ctx.new_page_calls == 1
    assert service._pages["youtube"] is yt_page  # original mapping intact
    assert service._pages["google_search"] is google_page
    assert not yt_page.closed


def test_get_page_reuses_blank_first_page_when_no_platform_claimed():
    """When the context has one untouched page and no platform owns it,
    reuse it (so we don't leave an about:blank ghost tab behind)."""
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    blank = _FakePage("blank")
    ctx = _FakeContext(initial_pages=[blank])
    service._ensure_context = lambda browser_name: ctx

    page = service._get_page("chrome", "google_search", "https://google.com")
    assert page is blank
    assert ctx.new_page_calls == 0


def test_browser_media_play_refuses_when_no_active_tab_and_no_query():
    """Regression: 'play' with closed youtube tab and no query previously
    reported a phantom 'Resumed youtube.' Now it must refuse honestly."""
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    closed = _FakePage("youtube")
    closed.closed = True
    service._pages["youtube"] = closed

    result = service._do_browser_media_control(
        action="play", platform="youtube", query="", seconds=0
    )

    assert "no active" in result.lower() or "ask me to play" in result.lower()
    # Stale mapping cleared.
    assert "youtube" not in service._pages


def test_browser_media_play_with_closed_tab_and_query_relaunches():
    """If the tab is closed BUT the user provided a query, relaunch via
    _do_play_youtube rather than reporting phantom success."""
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    closed = _FakePage("youtube")
    closed.closed = True
    service._pages["youtube"] = closed

    relaunched = {"called": False, "query": None}

    def fake_relaunch(query, browser_name):
        relaunched["called"] = True
        relaunched["query"] = query
        return f"Playing {query} on YouTube."

    service._do_play_youtube = fake_relaunch

    result = service._do_browser_media_control(
        action="play", platform="youtube", query="sahiba", seconds=0
    )
    assert relaunched["called"] is True
    assert relaunched["query"] == "sahiba"
    assert "sahiba" in result.lower()


# ---------------------------------------------------------------------------
# 2026-05-29: transparent recovery when the tab/context dies mid-control.
# ---------------------------------------------------------------------------


_CLOSED_MSG = "Page.evaluate: Target page, context or browser has been closed"


class _DeadPage(_FakePage):
    """A page that looks alive (is_closed()==False) but throws the
    closed-target error on any interaction — mimics a dead context whose
    page handle hasn't caught up."""

    def evaluate(self, *_a, **_k):
        raise RuntimeError(_CLOSED_MSG)

    class _KB:
        def press(self, *_a, **_k):
            raise RuntimeError(_CLOSED_MSG)

    @property
    def keyboard(self):
        return self._KB()


def test_resume_on_dead_tab_relaunches_remembered_media():
    """The 2026-05-29 bug: 'play' after the tab silently died dead-ended on
    'Ask me to open it again' even though we knew the last song. Now it must
    transparently relaunch + replay — even for a bare resume (no query)."""
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    service._last_media = {"platform": "youtube", "query": "sahiba", "browser_name": "chrome"}
    service._pages["youtube"] = _DeadPage("youtube")

    seen = {}
    service._do_play_youtube = lambda q, b: seen.setdefault("q", q) or f"Playing {q} on youtube in {b}."

    result = service._do_browser_media_control(action="resume", platform="youtube", query="", seconds=0)
    assert seen.get("q") == "sahiba"
    assert "sahiba" in result.lower()
    assert "ask me to open it again" not in result.lower()


def test_bare_play_with_no_page_relaunches_from_memory():
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    service._last_media = {"platform": "youtube", "query": "sahiba", "browser_name": "chrome"}
    # No page tracked at all.
    seen = {}
    service._do_play_youtube = lambda q, b: seen.setdefault("q", q) or f"Playing {q}."
    result = service._do_browser_media_control(action="play", platform="youtube", query="", seconds=0)
    assert seen.get("q") == "sahiba"
    assert "sahiba" in result.lower()


def test_pause_on_dead_tab_does_not_phantom_replay():
    """A pause on a dead tab must NOT start playback again — it just reports
    the tab is gone."""
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    service._last_media = {"platform": "youtube", "query": "sahiba", "browser_name": "chrome"}
    service._pages["youtube"] = _DeadPage("youtube")
    called = {"play": False}
    service._do_play_youtube = lambda q, b: called.__setitem__("play", True) or "Playing."
    result = service._do_browser_media_control(action="pause", platform="youtube", query="", seconds=0)
    assert called["play"] is False
    assert "stopped" in result.lower() or "closed" in result.lower()


def test_relaunch_last_media_returns_none_without_memory():
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    assert service._last_media == {}
    assert service._relaunch_last_media("youtube", "") is None


# ---------------------------------------------------------------------------
# Focus-session media gate (2026-05-29) — browser media is blocked while a
# focus session is active; the only sound should be FRIDAY's own voice.
# ---------------------------------------------------------------------------

def test_play_youtube_refused_during_focus(monkeypatch):
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    monkeypatch.setattr(service, "_focus_blocks_media", lambda: True)
    msg = service._do_play_youtube("lofi beats", "chrome")
    assert "focus session" in msg.lower()
    assert "youtube" in msg.lower()


def test_play_youtube_music_refused_during_focus(monkeypatch):
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    monkeypatch.setattr(service, "_focus_blocks_media", lambda: True)
    msg = service._do_play_youtube_music("focus playlist", "chrome")
    assert "focus session" in msg.lower()


def test_resume_refused_but_pause_allowed_during_focus(monkeypatch):
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    monkeypatch.setattr(service, "_focus_blocks_media", lambda: True)
    # play/resume are refused so focus can't be undone
    assert "focus session" in service._do_browser_media_control("resume", "youtube", "").lower()
    assert "focus session" in service._do_browser_media_control("play", "youtube", "").lower()
    # pause is NOT gated — focus mode itself pauses media through this method
    out = service._do_browser_media_control("pause", "youtube", "")
    assert "focus session" not in out.lower()


def test_focus_blocks_media_reads_focus_state(monkeypatch):
    import core.reasoning.agentic_services.focus_mode as fm
    service = BrowserMediaService(SimpleNamespace(config=DummyConfig()))
    monkeypatch.setattr(fm.FocusModeWorkflow, "is_active", staticmethod(lambda: True))
    assert service._focus_blocks_media() is True
    monkeypatch.setattr(fm.FocusModeWorkflow, "is_active", staticmethod(lambda: False))
    assert service._focus_blocks_media() is False
