"""Browser tools — open URLs/searches and play & control video.

Two tiers:

* **Playwright controlled Chromium** (preferred): a real, visible browser Namma Agent
  drives, so ``play_youtube`` autoplays the first result fullscreen and
  ``media_control`` does play/pause/seek±/next/previous on the live video.
* **stdlib ``webbrowser`` fallback**: when Playwright isn't installed, links open
  in the user's default browser (no programmatic media control).

``open_browser_url`` / ``search_google`` always use the default browser (just
opening a link). Playback routes through the controlled window so it's
controllable.
"""
from __future__ import annotations

import threading
import urllib.parse
import webbrowser

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry, ToolResult

# Lazily-built singleton controller (None until first playback call). Tests may
# set this directly to inject a fake.
_controller = None
_controller_lock = threading.Lock()

# Aliases for media_control's `action`, mapped to (controller_action, default_secs).
_MEDIA_ALIASES = {
    "play": ("play", 0), "resume": ("play", 0),
    "pause": ("pause", 0), "stop": ("stop", 0),
    "toggle": ("toggle", 0), "playpause": ("toggle", 0),
    "forward": ("forward", 10), "skip": ("forward", 10), "ahead": ("forward", 10),
    "back": ("back", 10), "backward": ("back", 10), "rewind": ("back", 10),
    "next": ("next", 0), "previous": ("previous", 0), "prev": ("previous", 0),
    "restart": ("restart", 0), "replay": ("restart", 0),
    "fullscreen": ("fullscreen", 0),
    "volume": ("volume", 0.5), "mute": ("volume", 0.0),
}


def _engine() -> str:
    """'playwright' when the controlled browser is usable, else 'webbrowser'."""
    try:
        from namma_agent.config import load_config
        from namma_agent.core.browser_controller import BrowserController

        cfg = load_config().get("browser") or {}
        if cfg.get("engine", "playwright") == "webbrowser":
            return "webbrowser"
        return "playwright" if BrowserController.available() else "webbrowser"
    except Exception:  # noqa: BLE001
        return "webbrowser"


def _get_controller():
    global _controller
    with _controller_lock:
        if _controller is None:
            from namma_agent.config import load_config
            from namma_agent.core.browser_controller import BrowserController

            cfg = load_config().get("browser") or {}
            _controller = BrowserController(
                headless=bool(cfg.get("headless", False)),
                preferred=cfg.get("preferred", "auto"),
                use_system_profile=bool(cfg.get("use_system_profile", False)),
                profile_dir=cfg.get("profile_dir", "~/.namma_agent/browser-profile"),
                fullscreen=bool(cfg.get("fullscreen", True)),
            )
        return _controller


# ── plain opening (default browser) ─────────────────────────────────────────

def _open_default(url: str, what: str) -> ToolResult:
    try:
        opened = webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))
    if not opened:
        return ToolResult(ok=False, content="", error="no usable web browser found")
    return ToolResult(ok=True, content=f"Opened {what}: {url}", data={"url": url})


def _open_url(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, content="", error="no url given")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return _open_default(url, "page")


def _search_google(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    q = urllib.parse.quote_plus(query)
    return _open_default(f"https://www.google.com/search?q={q}", f"Google search for {query!r}")


# ── playback (controlled browser when available) ────────────────────────────

def _play_youtube(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    if _engine() == "playwright":
        try:
            info = _get_controller().play_youtube(query, fullscreen=args.get("fullscreen", True))
            return ToolResult(ok=True, content=f"Playing on YouTube: {info.get('title') or query}",
                              data=info)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser] play_youtube via Playwright failed: %s", exc)
            # fall through to stdlib
    q = urllib.parse.quote_plus(query)
    return _open_default(f"https://www.youtube.com/results?search_query={q}",
                         f"YouTube search for {query!r}")


def _play_youtube_music(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    if _engine() == "playwright":
        try:
            info = _get_controller().play_youtube_music(query)
            return ToolResult(ok=True, content=f"Playing on YouTube Music: {info.get('title') or query}",
                              data=info)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser] play_youtube_music via Playwright failed: %s", exc)
            # fall through to stdlib
    q = urllib.parse.quote_plus(query)
    return _open_default(f"https://music.youtube.com/search?q={q}",
                         f"YouTube Music search for {query!r}")


def _media_control(args: dict) -> ToolResult:
    action = (args.get("action") or "").strip().lower()
    if action not in _MEDIA_ALIASES:
        return ToolResult(ok=False, content="",
                          error=f"unknown action {action!r}; try: " + ", ".join(sorted(_MEDIA_ALIASES)))
    if _engine() != "playwright":
        return ToolResult(ok=False, content="",
                          error="media control needs the controlled browser (Playwright); "
                                "it isn't available, so play a video with play_youtube first.")
    ctrl_action, default_secs = _MEDIA_ALIASES[action]
    seconds = float(args.get("seconds", default_secs) or default_secs)
    try:
        if ctrl_action == "fullscreen":
            info = _get_controller().fullscreen()
        else:
            info = _get_controller().media(ctrl_action, seconds)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"media control failed: {exc}")
    label = action if not seconds else f"{action} {int(seconds)}s"
    return ToolResult(ok=True, content=f"Done: {label}.", data=info)


def register(registry: ToolRegistry) -> None:
    registry.register("open_browser_url", "Open a URL in the user's web browser.", {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "the URL (scheme optional)"}},
        "required": ["url"],
    }, _open_url)

    registry.register("search_google", "Open a Google search results page in the browser.", {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "what to search for"}},
        "required": ["query"],
    }, _search_google)

    registry.register(
        "play_youtube",
        "Play a YouTube video: searches, opens the first result in a controllable "
        "browser, and autoplays it fullscreen. Then use media_control to play/pause/seek.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "video title or terms"},
                "fullscreen": {"type": "boolean", "description": "open fullscreen (default true)"},
            },
            "required": ["query"],
        }, _play_youtube)

    registry.register(
        "play_youtube_music",
        "Play music on YouTube Music: searches and plays the first result in the "
        "controllable browser. Then use media_control to play/pause/seek/next/previous.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "song/artist/album"}},
            "required": ["query"],
        }, _play_youtube_music)

    registry.register(
        "media_control",
        "Control the currently playing video in Namma Agent's browser: play, pause, toggle, "
        "forward/back (by seconds), next, previous, restart, stop, volume.",
        {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "play | pause | toggle | forward | back | next | previous | "
                                   "restart | stop | volume",
                },
                "seconds": {
                    "type": "number",
                    "description": "for forward/back: seconds to seek (e.g. 50, 20); for volume: 0.0-1.0",
                },
            },
            "required": ["action"],
        }, _media_control)
