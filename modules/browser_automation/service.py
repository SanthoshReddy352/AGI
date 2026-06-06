"""Browser media automation service.

Playwright's sync API is thread-affine: every call must come from the thread
that started the Playwright loop. Voice commands are dispatched from the
TaskRunner, which spawns a fresh daemon thread per turn — so before this
refactor, the second voice command would crash with
``cannot switch to a different thread (which happens to have exited)``.

To fix that and make media controls feel instant, all Playwright work runs on
a single dedicated daemon thread (``BrowserMediaService._worker``). Public
methods enqueue jobs and block on a Future for the result. The same worker
also services the fast-path media-control invocations from STT, so
"Friday pause" reaches Playwright in milliseconds without going through the
router/LLM.
"""
from __future__ import annotations

import json
import os
import platform as _platform
import queue
import shutil
import subprocess
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote_plus, urljoin

from core.logger import logger


# Init script injected into every page so backgrounded tabs do NOT auto-pause
# when the user switches focus to a different platform tab. Without this,
# YouTube pauses video playback when its tab is hidden, which is exactly what
# the user complained about when starting YouTube Music while a YouTube video
# was playing.
_KEEP_PLAYING_SCRIPT = """
(() => {
    try {
        Object.defineProperty(document, 'hidden', { value: false, configurable: true });
        Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true });
        document.addEventListener('visibilitychange', (event) => event.stopImmediatePropagation(), true);
    } catch (_) {}
    try {
        const origAdd = EventTarget.prototype.addEventListener;
        EventTarget.prototype.addEventListener = function (type, listener, options) {
            if (type === 'visibilitychange' || type === 'webkitvisibilitychange') return;
            return origAdd.call(this, type, listener, options);
        };
    } catch (_) {}
})();
"""


@dataclass
class _Job:
    fn: Callable
    args: tuple
    kwargs: dict
    future: Future


class BrowserMediaService:
    # Command timeout (seconds). Long enough for first-time browser launch
    # (Playwright + Chromium can take 8-15s on a cold cache) but short enough
    # that a hung worker doesn't lock the conversation.
    DEFAULT_TIMEOUT_S = 60.0
    FAST_TIMEOUT_S = 8.0

    def __init__(self, app):
        self.app = app
        self.profile_dir = ""
        self._playwright = None
        self._context = None
        self._pages: dict[str, object] = {}
        self._current_platform: str | None = None
        self._current_browser_name: str | None = None
        # Last media we successfully started, so a "play"/"pause" after the
        # tab/context unexpectedly dies can transparently relaunch + replay
        # instead of dead-ending on "ask me to open it again".
        self._last_media: dict[str, str] = {}
        self._fallback_profile_root = os.path.join(
            os.path.expanduser("~"),
            ".cache",
            "friday",
            "browser-profile",
        )

        self._jobs: "queue.Queue[_Job | None]" = queue.Queue()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="friday-browser",
            daemon=True,
        )
        self._worker_thread.start()

    # ------------------------------------------------------------------
    # Public API — every method below dispatches to the worker thread.
    # ------------------------------------------------------------------

    def open_browser_url(self, url, browser_name="chrome", platform="browser"):
        return self._submit(self._do_open_browser_url, url, browser_name, platform)

    def play_youtube(self, query, browser_name="chrome"):
        return self._submit(self._do_play_youtube, query, browser_name)

    def play_youtube_music(self, query, browser_name="chrome"):
        return self._submit(self._do_play_youtube_music, query, browser_name)

    def browser_media_control(self, action, platform=None, query="", seconds=0):
        return self._submit(self._do_browser_media_control, action, platform, query, seconds)

    def search_google(self, query, browser_name="chrome"):
        return self._submit(self._do_search_google, query, browser_name)

    def fast_media_command(self, action):
        """Hot path used by STT for instant pause/resume/next/previous etc.

        Returns a short status string. Does NOT raise — failures are logged
        and an empty string is returned so the voice pipeline can stay quiet.
        """
        try:
            return self._submit(
                self._do_browser_media_control,
                action,
                None,
                "",
                0,
                timeout=self.FAST_TIMEOUT_S,
            )
        except Exception as exc:
            logger.warning("[browser] fast_media_command(%s) failed: %s", action, exc)
            return ""

    def scroll_page(self, platform="browser", pixels=420):
        return self._submit(self._do_scroll_page, platform, pixels)

    def scroll_to_top(self, platform="browser"):
        return self._submit(self._do_scroll_to_top, platform)

    def extract_visible_sections(self, platform="browser", min_chars=90, max_chars=900, max_sections=3):
        return self._submit(
            self._do_extract_visible_sections,
            platform,
            min_chars,
            max_chars,
            max_sections,
        )

    def shutdown(self):
        """Stop the worker thread and tear down Playwright cleanly."""
        try:
            self._submit(self._cleanup_playwright, timeout=5.0)
        except Exception:
            pass
        self._jobs.put(None)

    def reset_session(self) -> None:
        """Drop all tracked media tabs without tearing down Playwright.

        Used by `/new` and `/clear` so a fresh conversation can't reach
        back into the prior session's YouTube/Music/Search tabs via
        pause/resume/next. The Playwright browser stays alive (cheap to
        keep, expensive to relaunch); only our handles + the actual
        page tabs are dropped.

        Safe to call from any thread — dispatches to the worker.
        """
        try:
            self._submit(self._do_reset_session, timeout=self.FAST_TIMEOUT_S)
        except Exception as exc:
            logger.warning("[browser] reset_session failed: %s", exc)

    def _do_reset_session(self) -> str:
        pages = list(self._pages.items())
        self._pages.clear()
        self._current_platform = None
        for platform, page in pages:
            try:
                if page is None:
                    continue
                # Best-effort close; ignore stale/already-closed pages.
                close = getattr(page, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            except Exception:
                logger.debug("[browser] reset_session: close failed for %s", platform, exc_info=False)
        return "reset"

    # ------------------------------------------------------------------
    # Worker plumbing
    # ------------------------------------------------------------------

    def _submit(self, fn, *args, timeout: float | None = None, **kwargs):
        """Submit a job and block on the result.

        If we're already on the worker thread (happens when one operation
        calls another via the public API), run inline to avoid deadlock.
        """
        if threading.current_thread() is self._worker_thread:
            return fn(*args, **kwargs)
        future: Future = Future()
        self._jobs.put(_Job(fn=fn, args=args, kwargs=kwargs, future=future))
        return future.result(timeout=timeout if timeout is not None else self.DEFAULT_TIMEOUT_S)

    def _worker_loop(self):
        while True:
            job = self._jobs.get()
            if job is None:
                break
            try:
                result = job.fn(*job.args, **job.kwargs)
                job.future.set_result(result)
            except Exception as exc:
                job.future.set_exception(exc)

    # ------------------------------------------------------------------
    # Worker-side implementations (run on the worker thread only)
    # ------------------------------------------------------------------

    def _do_open_browser_url(self, url, browser_name, platform):
        page = self._get_page(browser_name=browser_name, platform=platform, url=url)
        if isinstance(page, str):
            return self._open_url_fallback(url, browser_name=browser_name, platform=platform, reason=page)
        try:
            page.goto(url, wait_until="domcontentloaded")
            self._current_platform = platform
            return f"Opening {platform.replace('_', ' ')} in {browser_name}."
        except Exception as exc:
            logger.error("Browser open failed: %s", exc)
            return self._open_url_fallback(
                url,
                browser_name=browser_name,
                platform=platform,
                reason=f"Failed to open {platform.replace('_', ' ')} in {browser_name}: {exc}",
            )

    @staticmethod
    def _focus_blocks_media() -> bool:
        """True while a focus session is active. During focus, starting or
        resuming browser media is refused (the only sound should be FRIDAY's
        own voice). Lazy import keeps this module independent of the focus
        service. Pause/stop are never gated — focus mode itself uses them."""
        try:
            from core.reasoning.agentic_services.focus_mode import FocusModeWorkflow  # noqa: PLC0415
            return FocusModeWorkflow.is_active()
        except Exception:
            return False

    _FOCUS_REFUSAL = (
        "You're in a focus session, so I'm keeping browser media like YouTube "
        "and YouTube Music off — the only sound should be me. Say 'Friday end "
        "focus' if you want to stop the session."
    )

    def _do_play_youtube(self, query, browser_name):
        if self._focus_blocks_media():
            return self._FOCUS_REFUSAL
        return self._play_video(
            query=query,
            browser_name=browser_name,
            platform="youtube",
            home_url="https://www.youtube.com",
            search_url=f"https://www.youtube.com/results?search_query={quote_plus(query)}",
            first_result_selector="ytd-video-renderer a#video-title",
        )

    def _do_play_youtube_music(self, query, browser_name):
        if self._focus_blocks_media():
            return self._FOCUS_REFUSAL
        # If a YouTube video is already playing, force it to keep playing
        # *after* we navigate the new YouTube Music tab — browsers tend to
        # pause backgrounded video on focus change. We resume it post-launch.
        was_playing_youtube = self._page_is_playing("youtube")

        result = self._play_video(
            query=query,
            browser_name=browser_name,
            platform="youtube_music",
            home_url="https://music.youtube.com",
            search_url=f"https://music.youtube.com/search?q={quote_plus(query)}",
            first_result_selector="ytmusic-responsive-list-item-renderer a[href*='watch']",
        )

        if was_playing_youtube:
            self._resume_play("youtube")
        return result

    def _do_browser_media_control(self, action, platform, query, seconds=0):
        # During a focus session, refuse to start/resume playback (but allow
        # pause/stop/seek/next/previous — focus mode pauses media via this very
        # method, and the user may still want to silence something).
        if action in ("play", "resume") and self._focus_blocks_media():
            return self._FOCUS_REFUSAL
        platform = platform or self._current_platform or "youtube"
        page = self._pages.get(platform)
        # Multi-tab fix (2026-05-23): verify the tab is actually still
        # alive BEFORE we claim success on play/resume. Previously a
        # closed-tab path would attempt set_media_state, swallow the
        # exception via `page.keyboard.press` fallback failing silently,
        # and STILL report "Resumed youtube." even though nothing happened.
        if page is not None:
            # `page.is_closed()` can lie (return False) when it's the whole
            # context/browser that died, not just the tab — so also verify the
            # context is usable. Catching it HERE means we relaunch cleanly
            # instead of failing inside page.evaluate (the 2026-05-29 bug).
            try:
                context_dead = self._context is not None and not self._context_is_usable()
                if page.is_closed() or context_dead:
                    page = None
                    self._pages.pop(platform, None)
            except Exception:
                page = None
                self._pages.pop(platform, None)

        if page is None:
            if action in ("play", "resume"):
                # Relaunch + replay the remembered media (works for bare "play"
                # too — no need for the caller to re-supply the query).
                relaunched = self._relaunch_last_media(platform, query)
                if relaunched:
                    return relaunched
                # Nothing playing and nothing remembered — refuse instead of
                # reporting a phantom resume.
                return (
                    f"There's no active {platform.replace('_', ' ')} tab. "
                    "Ask me to play something first, e.g. 'play sahiba on youtube'."
                )
            return "I don't have an active browser media session yet."

        try:
            try:
                page.bring_to_front()
            except Exception:
                pass

            if action in ("pause", "resume", "play"):
                ok = self._set_media_state(page, "pause" if action == "pause" else "play")
                if not ok:
                    # Fallback to keyboard shortcut (YouTube uses "k", YouTube Music uses Space).
                    try:
                        self._focus_player(page, platform)
                        page.keyboard.press(" " if platform == "youtube_music" else "k")
                    except Exception as kb_exc:
                        logger.warning("Keyboard fallback for %s failed: %s", action, kb_exc)
                        if self._is_closed_target_error(kb_exc):
                            return self._closed_target_response(action, platform, query)
                        return f"I couldn't {action} {platform.replace('_', ' ')} — the player didn't respond."
                verb = "Paused" if action == "pause" else "Resumed"
                return f"{verb} {platform.replace('_', ' ')}."
            if action == "next":
                if not self._click_player_button(page, platform, "next"):
                    self._focus_player(page, platform)
                    page.keyboard.press("Shift+N")
                return f"Skipped to next on {platform.replace('_', ' ')}."
            if action == "previous":
                # YouTube Music's previous button restarts the current track
                # when playback is past a few seconds. Reset currentTime first
                # so a single press always moves to the previous song.
                if platform == "youtube_music":
                    self._seek_absolute(page, 0)
                if not self._click_player_button(page, platform, "previous"):
                    self._focus_player(page, platform)
                    page.keyboard.press("Shift+P")
                return f"Previous track on {platform.replace('_', ' ')}."
            if action in ("seek_forward", "seek_backward"):
                delta = int(seconds or 10)
                if action == "seek_backward":
                    delta = -delta
                self._seek_relative(page, delta)
                if delta >= 0:
                    return f"Skipped forward {abs(delta)} seconds on {platform.replace('_', ' ')}."
                return f"Skipped back {abs(delta)} seconds on {platform.replace('_', ' ')}."
            if action == "forward":
                self._seek_relative(page, int(seconds) if seconds else 10)
                return f"Skipped forward {int(seconds) if seconds else 10} seconds on {platform.replace('_', ' ')}."
            if action == "backward":
                self._seek_relative(page, -(int(seconds) if seconds else 10))
                return f"Skipped back {int(seconds) if seconds else 10} seconds on {platform.replace('_', ' ')}."
            if action == "mute":
                page.keyboard.press("m")
                return f"Toggled mute on {platform.replace('_', ' ')}."
            return f"I don't know how to '{action}' in the browser yet."
        except Exception as exc:
            logger.error("Browser media control failed: %s", exc)
            if self._is_closed_target_error(exc):
                return self._closed_target_response(action, platform, query)
            return "I couldn't reach the browser playback. Try opening the page again."

    def _do_search_google(self, query, browser_name):
        query = (query or "").strip()
        if not query:
            return "What should I search for, sir?"
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        page = self._get_page(browser_name=browser_name, platform="google_search", url=url)
        if isinstance(page, str):
            return self._open_url_fallback(
                url,
                browser_name=browser_name,
                platform="google_search",
                reason=page,
                action_label=f"Searching Google for {query}",
            )
        try:
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.bring_to_front()
            except Exception:
                pass
            return f"Searching Google for {query}."
        except Exception as exc:
            logger.error("Google search failed: %s", exc)
            return self._open_url_fallback(
                url,
                browser_name=browser_name,
                platform="google_search",
                reason=f"Failed to search Google: {exc}",
                action_label=f"Searching Google for {query}",
            )

    def _do_scroll_page(self, platform, pixels):
        page = self._pages.get(platform)
        if page is None:
            return f"I don't have an active {platform.replace('_', ' ')} browser page yet."
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            scrolled = page.evaluate(
                """
                (amount) => {
                    const visibleArea = (el) => {
                        const rect = el.getBoundingClientRect();
                        const width = Math.max(0, Math.min(rect.right, window.innerWidth) - Math.max(rect.left, 0));
                        const height = Math.max(0, Math.min(rect.bottom, window.innerHeight) - Math.max(rect.top, 0));
                        return width * height;
                    };
                    const candidates = Array.from(document.querySelectorAll("main, #root, .main-content, .panel-content, [class*='panel' i], [class*='content' i], body, html"))
                        .filter((el) => el.scrollHeight > el.clientHeight + 24)
                        .map((el) => ({ el, area: visibleArea(el) }))
                        .filter((item) => item.area > 20000)
                        .sort((a, b) => b.area - a.area);
                    const target = candidates[0]?.el;
                    if (!target) return false;
                    target.scrollBy({ top: amount, left: 0, behavior: "smooth" });
                    return true;
                }
                """,
                int(pixels),
            )
            if not scrolled:
                page.mouse.wheel(0, int(pixels))
        except Exception:
            page.evaluate("(amount) => window.scrollBy({ top: amount, left: 0, behavior: 'smooth' })", int(pixels))
        return f"Scrolled {platform.replace('_', ' ')}."

    def _do_scroll_to_top(self, platform):
        page = self._pages.get(platform)
        if page is None:
            return f"I don't have an active {platform.replace('_', ' ')} browser page yet."
        try:
            page.bring_to_front()
        except Exception:
            pass
        page.evaluate(
            """
            () => {
                window.scrollTo({ top: 0, left: 0, behavior: "instant" });
                for (const el of document.querySelectorAll("main, #root, .main-content, .panel-content, [class*='panel' i], [class*='content' i]")) {
                    if (el.scrollHeight > el.clientHeight + 24) {
                        el.scrollTo({ top: 0, left: 0, behavior: "instant" });
                    }
                }
            }
            """
        )
        return f"Reset {platform.replace('_', ' ')} scroll."

    def _do_extract_visible_sections(self, platform, min_chars, max_chars, max_sections):
        page = self._pages.get(platform)
        if page is None:
            return []
        try:
            page.bring_to_front()
        except Exception:
            pass
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass
        try:
            sections = page.evaluate(
                """
                ({ minChars, maxChars, maxSections }) => {
                    const normalize = (value) => String(value || "")
                        .replace(/\\s+/g, " ")
                        .replace(/\\b(read more|share|source|updated)\\b\\s*:?/ig, "")
                        .trim();
                    const viewportTop = 0;
                    const viewportBottom = window.innerHeight || document.documentElement.clientHeight;
                    const selector = [
                        "main section",
                        "article",
                        "section",
                        "main p",
                        "main li",
                        "main div",
                        "[role='article']",
                        "[data-testid*='summary' i]",
                        "[class*='summary' i]",
                        "[class*='content' i]",
                        "[class*='card' i]"
                    ].join(",");
                    const candidates = Array.from(document.querySelectorAll(selector));
                    const rows = [];
                    const seen = new Set();
                    for (const element of candidates) {
                        const rect = element.getBoundingClientRect();
                        if (rect.width < 160 || rect.height < 36) continue;
                        if (rect.bottom < viewportTop + 24 || rect.top > viewportBottom - 24) continue;
                        const style = window.getComputedStyle(element);
                        if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) continue;
                        let text = normalize(element.innerText || element.textContent || "");
                        if (text.length < minChars) continue;
                        const childTexts = Array.from(element.children || [])
                            .map((child) => normalize(child.innerText || child.textContent || ""))
                            .filter((childText) => childText.length >= minChars);
                        if (childTexts.some((childText) => childText.length > text.length * 0.72)) continue;
                        if (text.length > maxChars) text = `${text.slice(0, maxChars).trim()}...`;
                        const key = text.toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        rows.push({ top: rect.top, text });
                    }
                    rows.sort((a, b) => a.top - b.top);
                    return rows.slice(0, maxSections).map((row) => row.text);
                }
                """,
                {
                    "minChars": int(min_chars),
                    "maxChars": int(max_chars),
                    "maxSections": int(max_sections),
                },
            )
        except Exception as exc:
            logger.debug("Visible section extraction failed for %s: %s", platform, exc)
            return []
        if not isinstance(sections, list):
            return []
        return [str(section).strip() for section in sections if str(section).strip()]

    # ------------------------------------------------------------------
    # Internal helpers (worker thread only)
    # ------------------------------------------------------------------

    def _play_video(self, query, browser_name, platform, home_url, search_url, first_result_selector):
        page = self._get_page(browser_name=browser_name, platform=platform, url=home_url)
        if isinstance(page, str):
            return self._open_url_fallback(
                search_url,
                browser_name=browser_name,
                platform=platform,
                reason=page,
                action_label=f"Opening search results for {query} on {platform.replace('_', ' ')}",
            )
        try:
            page.goto(search_url, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            target_url = self._resolve_first_result_url(page, first_result_selector, home_url)
            if target_url:
                page.goto(target_url, wait_until="domcontentloaded")
            else:
                locator = page.locator(first_result_selector).first
                locator.wait_for(state="attached", timeout=8000)
                try:
                    locator.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass
                locator.click(force=True)
                page.wait_for_load_state("domcontentloaded")
            self._prepare_media_page(page, platform)
            self._current_platform = platform
            self._last_media = {
                "platform": platform,
                "query": query,
                "browser_name": browser_name,
            }
            return f"Playing {query} on {platform.replace('_', ' ')} in {browser_name}."
        except Exception as exc:
            logger.error("Browser playback failed: %s", exc)
            return self._open_url_fallback(
                search_url,
                browser_name=browser_name,
                platform=platform,
                reason=f"Failed to play {query} on {platform.replace('_', ' ')}: {exc}",
                action_label=f"Opening search results for {query} on {platform.replace('_', ' ')}",
            )

    def _page_is_playing(self, platform):
        page = self._pages.get(platform)
        if page is None:
            return False
        try:
            return bool(
                page.evaluate(
                    """
                    () => {
                        const media = document.querySelector("video, audio");
                        if (!media) return false;
                        return !media.paused && !media.ended && media.readyState >= 2;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _set_media_state(self, page, target):
        try:
            return bool(
                page.evaluate(
                    """
                    (target) => {
                        const media = document.querySelector("video, audio");
                        if (!media) return false;
                        if (target === 'pause') {
                            if (!media.paused) media.pause();
                            return true;
                        }
                        if (media.paused) media.play().catch(() => {});
                        return true;
                    }
                    """,
                    target,
                )
            )
        except Exception as exc:
            # A dead tab/context must bubble up so the caller can relaunch —
            # don't swallow it into a False that triggers the (also-doomed)
            # keyboard fallback.
            if self._is_closed_target_error(exc):
                raise
            logger.warning("Browser media state %s failed: %s", target, exc)
            return False

    def _relaunch_last_media(self, platform, query):
        """Re-open and replay the last media we started. Returns the play
        result string, or None when there's nothing remembered to replay."""
        plat = platform or self._last_media.get("platform") or "youtube"
        replay_query = query or self._last_media.get("query") or ""
        browser = self._last_media.get("browser_name") or "chrome"
        if not replay_query:
            return None
        logger.info("[browser] relaunching last media (%s: %r) after a closed tab/context.", plat, replay_query)
        if plat == "youtube_music":
            return self._do_play_youtube_music(replay_query, browser)
        return self._do_play_youtube(replay_query, browser)

    def _closed_target_response(self, action, platform, query):
        """Uniform handling when a media action hits a dead tab/context:
        transparently relaunch + replay for play/resume; honest message
        otherwise. Drops the stale page handle first."""
        self._pages.pop(platform, None)
        if action in ("play", "resume"):
            relaunched = self._relaunch_last_media(platform, query)
            if relaunched:
                return relaunched
            return (
                f"There's no active {platform.replace('_', ' ')} tab. "
                "Ask me to play something, e.g. 'play sahiba on youtube'."
            )
        return f"The {platform.replace('_', ' ')} playback stopped — its tab was closed."

    def _click_player_button(self, page, platform, action):
        if platform == "youtube_music":
            selectors = (
                ".next-button" if action == "next" else ".previous-button",
                f"ytmusic-player-bar tp-yt-paper-icon-button[aria-label*='{ 'Next' if action == 'next' else 'Previous'}' i]",
                f"ytmusic-player-bar button[aria-label*='{ 'Next' if action == 'next' else 'Previous'}' i]",
                f"button[aria-label*='{ 'Next' if action == 'next' else 'Previous'}' i]",
            )
        else:
            selectors = (
                ".ytp-next-button" if action == "next" else ".ytp-prev-button",
                f"button[aria-label*='{ 'Next' if action == 'next' else 'Previous'}' i]",
            )
        try:
            return bool(
                page.evaluate(
                    """
                    (selectors) => {
                        for (const sel of selectors) {
                            const el = document.querySelector(sel);
                            if (el && !el.disabled) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }
                    """,
                    list(selectors),
                )
            )
        except Exception as exc:
            logger.warning("Click %s button failed on %s: %s", action, platform, exc)
            return False

    def _focus_player(self, page, platform):
        try:
            selector = (
                "ytmusic-player-bar"
                if platform == "youtube_music"
                else ".html5-video-player"
            )
            page.evaluate(
                """
                (selector) => {
                    const el = document.querySelector(selector);
                    if (el && typeof el.focus === 'function') el.focus({preventScroll: true});
                }
                """,
                selector,
            )
        except Exception:
            pass

    def _seek_absolute(self, page, seconds):
        try:
            page.evaluate(
                """
                (target) => {
                    const media = document.querySelector("video, audio");
                    if (!media) return;
                    media.currentTime = Math.max(0, target);
                }
                """,
                int(seconds),
            )
        except Exception:
            pass

    def _seek_relative(self, page, delta_seconds):
        try:
            page.evaluate(
                """
                (delta) => {
                    const media = document.querySelector("video, audio");
                    if (!media) return;
                    const current = media.currentTime || 0;
                    const target = Math.max(0, Math.min((media.duration || current + delta), current + delta));
                    media.currentTime = target;
                }
                """,
                int(delta_seconds),
            )
        except Exception as exc:
            logger.warning("Browser seek by %ss failed: %s", delta_seconds, exc)

    def _resume_play(self, platform):
        page = self._pages.get(platform)
        if page is None:
            return
        try:
            page.evaluate(
                """
                () => {
                    const media = document.querySelector("video, audio");
                    if (media && media.paused) media.play().catch(() => {});
                }
                """
            )
        except Exception:
            pass

    def _get_page(self, browser_name, platform, url):
        page = self._pages.get(platform)
        try:
            if page and not page.is_closed():
                page.bring_to_front()
                return page
        except Exception:
            page = None

        last_exc = None
        for attempt in range(2):
            context = self._ensure_context(browser_name)
            if isinstance(context, str):
                return context
            try:
                # Multi-tab fix (2026-05-23): NEVER repurpose another platform's
                # tab — that's what was killing youtube playback every time the
                # user did "Google for capital of france" with music running.
                # Only reuse the first page if (a) no platform-keyed tab is
                # alive anywhere, and (b) the existing first page isn't already
                # owned by another platform key. Otherwise open a fresh tab.
                page = self._find_reusable_page(context, platform)
                if page is None:
                    page = context.new_page()
                try:
                    page.add_init_script(_KEEP_PLAYING_SCRIPT)
                except Exception:
                    pass
                self._pages[platform] = page
                return page
            except Exception as exc:
                last_exc = exc
                if not self._is_closed_target_error(exc):
                    raise
                logger.warning(
                    "Browser page creation hit a closed context on attempt %s. Recreating browser automation context.",
                    attempt + 1,
                )
                self._cleanup_playwright()
        if last_exc is not None:
            logger.error("Browser automation session closed unexpectedly while creating a page: %s", last_exc)
            return self._playwright_help_message(last_exc)
        return "Browser automation could not create a browser page."

    def _find_reusable_page(self, context, platform):
        """Return a context page suitable to host *platform*, or None.

        A page is reusable when:
          1. It's not already claimed by a different platform in
             ``self._pages`` (i.e. we don't steal the youtube tab to
             host a google search).
          2. It's not closed.

        First call into a brand-new context — when ``self._pages`` is
        empty AND only one page exists — returns that page so we don't
        leave an about:blank ghost tab.
        """
        try:
            existing_pages = list(context.pages)
        except Exception:
            return None
        if not existing_pages:
            return None
        claimed_ids = set()
        for plat, p in self._pages.items():
            if plat == platform:
                continue
            try:
                if p and not p.is_closed():
                    claimed_ids.add(id(p))
            except Exception:
                continue
        for p in existing_pages:
            try:
                if p.is_closed():
                    continue
            except Exception:
                continue
            if id(p) in claimed_ids:
                continue
            return p
        return None

    def _ensure_context(self, browser_name):
        if self._context is not None and self._context_is_usable():
            return self._context
        if self._context is not None:
            logger.warning("Browser automation context was no longer usable. Reinitializing it.")
            self._cleanup_playwright()

        try:
            import playwright
            from playwright.sync_api import sync_playwright
        except Exception:
            return (
                "Browser automation is unavailable because Playwright is not installed. "
                "Install it and run 'playwright install chromium' to enable browser workflows."
            )

        if not self._playwright_driver_available(playwright):
            return (
                "Browser automation is installed but the Playwright driver files are missing. "
                "Full browser control needs a working Playwright install."
            )

        executable_path = self._resolve_browser_path(browser_name)
        if executable_path is None:
            if browser_name == "chrome":
                fallback = self._resolve_browser_path("chromium")
                if fallback is None:
                    return "I couldn't find Chrome or Chromium on this system."
                executable_path = fallback
                browser_name = "chromium"
            else:
                return f"I couldn't find {browser_name} on this system."

        profile_settings = self._prepare_launch_profile_settings(browser_name)
        try:
            self._playwright = sync_playwright().start()
            chromium = self._playwright.chromium
            self._context = self._launch_context(chromium, executable_path, browser_name, profile_settings)
            return self._context
        except Exception as exc:
            if self._is_profile_in_use_error(exc) and profile_settings.get("mode") == "system":
                logger.warning(
                    "Chrome profile '%s' is busy. Falling back to a cloned signed-in profile snapshot for automation.",
                    profile_settings.get("profile_directory") or "default",
                )
                try:
                    cloned_settings = self._clone_profile_settings(profile_settings, browser_name)
                    self._context = self._launch_context(chromium, executable_path, browser_name, cloned_settings)
                    return self._context
                except Exception as clone_exc:
                    self._cleanup_playwright()
                    logger.error("Failed to start browser automation from cloned profile: %s", clone_exc)
                    return self._playwright_help_message(clone_exc)
            self._cleanup_playwright()
            logger.error("Failed to start browser automation: %s", exc)
            return self._playwright_help_message(exc)

    def _resolve_browser_path(self, browser_name):
        candidates = {
            "chrome": ["google-chrome", "google-chrome-stable"],
            "chromium": ["chromium", "chromium-browser"],
        }
        if _platform.system() == "Windows":
            candidates["chrome"] = ["chrome.exe", "chrome", 
                                    r"C:\Program Files\Google\Chrome\Application\chrome.exe", 
                                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
            candidates["chromium"] = ["chromium.exe", "chromium"]
            
        for candidate in candidates.get(browser_name, [browser_name]):
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
            if _platform.system() == "Windows" and os.path.exists(candidate):
                return candidate
        return None

    def _open_url_fallback(self, url, browser_name, platform, reason="", action_label=""):
        executable_path = self._resolve_browser_path(browser_name)
        if executable_path is None and browser_name == "chrome":
            executable_path = self._resolve_browser_path("chromium")
            if executable_path:
                browser_name = "chromium"

        try:
            if executable_path:
                if _platform.system() == "Windows":
                    subprocess.Popen(
                        [executable_path, url],
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        [executable_path, url],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            else:
                if _platform.system() == "Windows":
                    os.startfile(url)
                elif _platform.system() == "Darwin":
                    subprocess.Popen(
                        ["open", url],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.Popen(
                        ["xdg-open", url],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            label = action_label or f"Opening {platform.replace('_', ' ')} in {browser_name}"
            if reason:
                logger.warning("Browser automation fallback used: %s", reason)
                return f"{label}. Browser automation is unavailable, so I opened the page directly."
            return f"{label}."
        except Exception as exc:
            logger.error("Browser fallback failed: %s", exc)
            if reason:
                return f"{reason}. I also couldn't open the URL directly: {exc}"
            return f"Failed to open {platform.replace('_', ' ')} in {browser_name}: {exc}"

    def _playwright_help_message(self, exc):
        message = str(exc)
        lowered = message.lower()
        if "cli.js" in message or "module not found" in lowered or "connection closed while reading from the driver" in lowered:
            return (
                "Browser automation is installed but the Playwright driver is not set up correctly. "
                "I can still open pages directly, but full browser control needs a working Playwright install."
            )
        if "user data directory is already in use" in lowered or "singletonlock" in lowered:
            return (
                "Chrome is already using that profile, so Playwright could not attach to it. "
                "FRIDAY can usually reuse a signed-in snapshot automatically, but this launch still failed."
            )
        return f"Failed to start browser automation: {message}"

    def _cleanup_playwright(self):
        try:
            if self._context is not None:
                self._context.close()
        except Exception:
            pass
        self._context = None
        self._pages = {}
        self._current_browser_name = None
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._playwright = None

    def _playwright_driver_available(self, playwright_module):
        package_root = os.path.dirname(getattr(playwright_module, "__file__", "") or "")
        if not package_root:
            return False
        driver_dir = os.path.join(package_root, "driver")
        node_path = os.path.join(driver_dir, "node")
        cli_path = os.path.join(driver_dir, "package", "cli.js")
        return os.path.exists(driver_dir) and (os.path.exists(node_path) or os.path.exists(cli_path))

    def _context_is_usable(self):
        if self._context is None:
            return False
        try:
            _ = self._context.pages
            return True
        except Exception:
            return False

    def _resolve_profile_settings(self, browser_name):
        use_system_profile = self._config_get(
            "browser_automation.use_system_profile",
            browser_name in {"chrome", "chromium"},
        )
        if use_system_profile:
            profile_root = self._config_get(
                f"browser_automation.{browser_name}_user_data_dir",
                self._default_profile_root(browser_name),
            )
            if profile_root and os.path.isdir(profile_root):
                profile_directory = self._config_get(
                    f"browser_automation.{browser_name}_profile_directory",
                    "",
                ) or self._detect_profile_directory(profile_root)
                launch_args = []
                if profile_directory and os.path.isdir(os.path.join(profile_root, profile_directory)):
                    launch_args.append(f"--profile-directory={profile_directory}")
                return {
                    "user_data_dir": profile_root,
                    "profile_directory": profile_directory,
                    "launch_args": launch_args,
                    "mode": "system",
                }

        fallback_root = os.path.join(self._fallback_profile_root, browser_name)
        return {
            "user_data_dir": fallback_root,
            "profile_directory": "",
            "launch_args": [],
            "mode": "isolated",
        }

    def _prepare_launch_profile_settings(self, browser_name):
        profile_settings = self._resolve_profile_settings(browser_name)
        if profile_settings.get("mode") != "system":
            return profile_settings
        try:
            return self._clone_profile_settings(profile_settings, browser_name)
        except Exception as exc:
            logger.warning(
                "Could not refresh a signed-in browser profile clone from '%s': %s. Falling back to an isolated automation profile.",
                profile_settings.get("user_data_dir"),
                exc,
            )
            isolated_root = os.path.join(self._fallback_profile_root, browser_name)
            return {
                "user_data_dir": isolated_root,
                "profile_directory": "",
                "launch_args": [],
                "mode": "isolated",
            }

    def _default_profile_root(self, browser_name):
        if browser_name == "chromium":
            return os.path.expanduser("~/.config/chromium")
        return os.path.expanduser("~/.config/google-chrome")

    def _detect_profile_directory(self, profile_root):
        local_state_path = os.path.join(profile_root, "Local State")
        try:
            if os.path.exists(local_state_path):
                with open(local_state_path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                last_used = (
                    data.get("profile", {}).get("last_used")
                    or data.get("profile", {}).get("last_active_profiles", [None])[0]
                )
                if last_used and os.path.isdir(os.path.join(profile_root, last_used)):
                    return last_used
        except Exception as exc:
            logger.warning("Could not read browser Local State from %s: %s", local_state_path, exc)

        if os.path.isdir(os.path.join(profile_root, "Default")):
            return "Default"

        profile_dirs = sorted(
            name
            for name in os.listdir(profile_root)
            if name.startswith("Profile ") and os.path.isdir(os.path.join(profile_root, name))
        )
        return profile_dirs[0] if profile_dirs else ""

    def _config_get(self, key, default=None):
        config = getattr(self.app, "config", None)
        if config and hasattr(config, "get"):
            value = config.get(key, default)
            if value == "":
                return default
            return value
        return default

    def _is_closed_target_error(self, exc):
        message = str(exc).lower()
        return "target page, context or browser has been closed" in message

    def _is_profile_in_use_error(self, exc):
        message = str(exc).lower()
        return "processsingleton" in message or "user data directory is already in use" in message

    def _reset_profile_exit_state(self, profile_dir, profile_directory):
        pref_files = []
        if profile_directory:
            pref_files.append(os.path.join(profile_dir, profile_directory, "Preferences"))
        else:
            pref_files.append(os.path.join(profile_dir, "Default", "Preferences"))
            pref_files.append(os.path.join(profile_dir, "Preferences"))
        
        for pref_file in pref_files:
            if os.path.exists(pref_file):
                try:
                    with open(pref_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    modified = False
                    if "profile" in data and isinstance(data["profile"], dict):
                        if data["profile"].get("exit_type") != "Normal":
                            data["profile"]["exit_type"] = "Normal"
                            modified = True
                        if data["profile"].get("exited_cleanly") is not True:
                            data["profile"]["exited_cleanly"] = True
                            modified = True
                    else:
                        data["profile"] = {"exit_type": "Normal", "exited_cleanly": True}
                        modified = True
                    
                    if modified:
                        with open(pref_file, "w", encoding="utf-8") as f:
                            json.dump(data, f)
                        logger.info("Successfully reset Chrome profile exit state to normal for %s", pref_file)
                except Exception as e:
                    logger.warning("Failed to reset exit type in %s: %s", pref_file, e)

    def _launch_context(self, chromium, executable_path, browser_name, profile_settings):
        self.profile_dir = profile_settings["user_data_dir"]
        self._current_browser_name = browser_name
        os.makedirs(self.profile_dir, exist_ok=True)
        self._reset_profile_exit_state(self.profile_dir, profile_settings.get("profile_directory"))
        launch_args = list(profile_settings["launch_args"])
        launch_args.extend(self._default_launch_args())
        logger.info(
            "Launching browser automation with profile root '%s'%s",
            self.profile_dir,
            f" and profile '{profile_settings['profile_directory']}'" if profile_settings["profile_directory"] else "",
        )
        context = chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            executable_path=executable_path,
            headless=False,
            args=launch_args,
            ignore_default_args=self._playwright_ignore_default_args(),
            no_viewport=True,
        )
        try:
            context.add_init_script("delete Object.getPrototypeOf(navigator).webdriver")
        except Exception as exc:
            logger.warning("Could not inject stealth init script: %s", exc)
        # Diagnostics: log if the context/browser dies on its own (helps pin
        # down the recurring "tab was closed" on Windows). The handlers fire on
        # Playwright's dispatcher thread — keep them to a cheap log line.
        try:
            context.on("close", lambda: logger.warning(
                "[browser] persistent context closed (browser window/process gone)."))
            browser = getattr(context, "browser", None)
            if browser is not None:
                browser.on("disconnected", lambda _b=None: logger.warning(
                    "[browser] chromium disconnected — the browser process exited."))
        except Exception as exc:
            logger.debug("[browser] could not attach lifecycle listeners: %s", exc)
        return context

    def _clone_profile_settings(self, profile_settings, browser_name):
        source_root = profile_settings["user_data_dir"]
        profile_directory = profile_settings.get("profile_directory") or self._detect_profile_directory(source_root)
        clone_root = os.path.join(self._fallback_profile_root, f"{browser_name}-system-clone")
        if os.path.isdir(clone_root):
            shutil.rmtree(clone_root, ignore_errors=True)
        os.makedirs(clone_root, exist_ok=True)

        for filename in ("Local State", "First Run"):
            source_path = os.path.join(source_root, filename)
            if os.path.exists(source_path):
                shutil.copy2(source_path, os.path.join(clone_root, filename))

        profile_source = os.path.join(source_root, profile_directory) if profile_directory else ""
        if profile_source and os.path.isdir(profile_source):
            shutil.copytree(
                profile_source,
                os.path.join(clone_root, profile_directory),
                dirs_exist_ok=True,
                ignore=self._profile_clone_ignore,
            )

        return {
            "user_data_dir": clone_root,
            "profile_directory": profile_directory,
            "launch_args": [f"--profile-directory={profile_directory}"] if profile_directory else [],
            "mode": "cloned",
        }

    def _profile_clone_ignore(self, directory, names):
        ignored_names = {
            "SingletonLock",
            "SingletonSocket",
            "SingletonCookie",
            "lockfile",
            "Cache",
            "Code Cache",
            "GPUCache",
            "Crashpad",
            "GrShaderCache",
            "ShaderCache",
            "Safe Browsing",
            "OptimizationHints",
            "Subresource Filter",
            "CacheStorage",
            "ScriptCache",
        }
        return {
            name
            for name in names
            if name in ignored_names or name.endswith(".lock")
        }

    def _default_launch_args(self):
        args = [
            "--start-fullscreen",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-features=AutoplayIgnoreWebAudio,MediaSessionService",
            "--disable-blink-features=AutomationControlled",
            "--hide-crash-restore-bubble",
            "--test-type",
        ]
        if _platform.system() == "Linux":
            args.extend(["--disable-vulkan", "--ozone-platform=x11"])
        return args

    def _playwright_ignore_default_args(self):
        return [
            "--password-store=basic",
            "--use-mock-keychain",
            "--enable-automation",
        ]

    def _resolve_first_result_url(self, page, selector, base_url):
        selectors = [f"{selector}:visible", selector]
        for candidate in selectors:
            locator = page.locator(candidate).first
            try:
                locator.wait_for(state="attached", timeout=8000)
                href = locator.get_attribute("href")
            except Exception:
                continue
            if href:
                return urljoin(base_url, href)
        return ""

    def _prepare_media_page(self, page, platform_name):
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(1200)
        try:
            page.bring_to_front()
        except Exception:
            pass

        self._start_media_playback(page)
        if platform_name == "youtube":
            self._focus_browser_window(platform_name, fullscreen=False)
            self._enter_fullscreen(page)
            if not self._player_is_fullscreen(page) and not self._browser_is_fullscreen(page):
                logger.warning("HTML5 fullscreen failed to activate. Falling back to OS window manager fullscreen.")
                self._focus_browser_window(platform_name, fullscreen=True)
        else:
            self._exit_fullscreen(page)
            self._focus_browser_window(platform_name, fullscreen=False)

    def _start_media_playback(self, page):
        try:
            page.evaluate(
                """
                () => {
                    const media = document.querySelector("video, audio");
                    if (media && media.paused) {
                        media.play().catch(() => {});
                    }
                }
                """
            )
        except Exception:
            pass

    def _enter_fullscreen(self, page):
        # Find the window ID first so we can use native fallback keys
        window_id = self._find_matching_window_id(["youtube"])
        
        # Wait for YouTube Polymer player and video element readiness
        try:
            player = page.locator(".html5-video-player").first
            player.wait_for(state="attached", timeout=5000)
            video = page.locator("video").first
            video.wait_for(state="attached", timeout=5000)
            
            # Poll to ensure the video has actually loaded a source (readyState >= 2)
            page.wait_for_function(
                "() => { const v = document.querySelector('video'); return v && v.readyState >= 2; }",
                timeout=5000
            )
            logger.info("YouTube video element and player are fully ready.")
        except Exception as e:
            logger.warning("Timed out waiting for YouTube video/player to be fully ready: %s", e)

        for attempt in range(3):
            if self._player_is_fullscreen(page):
                return
            
            # Layer 1: Trusted Double-click on the video player or video element
            try:
                player = page.locator(".html5-video-player").first
                player.dblclick(timeout=3000)
                page.wait_for_timeout(800)
                if self._player_is_fullscreen(page):
                    return
            except Exception as e:
                logger.warning("Failed to double-click player: %s", e)

            try:
                video = page.locator("video").first
                video.dblclick(timeout=2000)
                page.wait_for_timeout(800)
                if self._player_is_fullscreen(page):
                    return
            except Exception as e:
                logger.warning("Failed to double-click video: %s", e)

            # Layer 2: Click the native YouTube fullscreen button (using trusted click, no force=True)
            if self._click_youtube_fullscreen_button(page):
                page.wait_for_timeout(800)
                if self._player_is_fullscreen(page):
                    return

            # Layer 3: Focus the player container and press "f"
            try:
                page.locator(".html5-video-player").first.focus()
                page.wait_for_timeout(200)
                page.keyboard.press("f")
                page.wait_for_timeout(800)
                if self._player_is_fullscreen(page):
                    return
            except Exception as e:
                logger.warning("Failed to focus and press 'f': %s", e)

            # Layer 4: Native F11/f keystrokes using xdotool
            if window_id:
                try:
                    logger.info("Attempting native F11/f fallback via xdotool")
                    # Ensure browser window is focused/activated first
                    self._focus_browser_window("youtube", fullscreen=False)
                    page.wait_for_timeout(300)
                    
                    # Try to enter fullscreen at browser level using native F11
                    if not self._browser_is_fullscreen(page):
                        self._send_native_key(window_id, "F11")
                        page.wait_for_timeout(1000)
                    
                    # Try to toggle fullscreen at player level using native f
                    self._send_native_key(window_id, "f")
                    page.wait_for_timeout(800)
                    
                    if self._player_is_fullscreen(page) or self._browser_is_fullscreen(page):
                        return
                except Exception as e:
                    logger.warning("Failed native fallback sequence: %s", e)

    def _send_native_key(self, window_id, key):
        if not window_id or not shutil.which("xdotool"):
            return False
        try:
            logger.info("Sending native key '%s' to window ID %s via xdotool", key, window_id)
            # Ensure browser window is focused/activated and active in X11 first
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", window_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            time.sleep(0.15)  # Let X11 focus settle
            # Send the key globally to the active window, which is extremely robust
            subprocess.run(
                ["xdotool", "key", key],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            return True
        except Exception as exc:
            logger.warning("Failed to send native key via xdotool: %s", exc)
            return False

    def _exit_fullscreen(self, page):
        try:
            is_fullscreen = bool(
                page.evaluate("() => !!document.fullscreenElement")
            )
        except Exception:
            is_fullscreen = False
        if not is_fullscreen:
            return
        try:
            page.evaluate(
                "async () => { if (document.fullscreenElement) { await document.exitFullscreen(); } }"
            )
            page.wait_for_timeout(400)
        except Exception:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                pass

    def _player_is_fullscreen(self, page):
        try:
            return bool(
                page.evaluate(
                    """
                    () => {
                        return !!document.fullscreenElement;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _browser_is_fullscreen(self, page):
        try:
            return bool(
                page.evaluate(
                    """
                    () => {
                        return window.innerHeight === window.screen.height || 
                               window.matchMedia('(display-mode: fullscreen)').matches ||
                               !!document.fullscreenElement;
                    }
                    """
                )
            )
        except Exception:
            return False

    def _click_youtube_fullscreen_button(self, page):
        try:
            # Hover over the player to make the controls visible
            player = page.locator(".html5-video-player").first
            player.hover(timeout=3000)
            page.wait_for_timeout(500)
        except Exception as e:
            logger.warning("Could not hover over video player: %s", e)
            
        for selector in ("button.ytp-fullscreen-button", ".ytp-fullscreen-button"):
            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=3000)
                locator.click(timeout=3000)
                return True
            except Exception as e:
                logger.warning("Could not click selector %s: %s", selector, e)
                continue
        return False

    def _focus_browser_window(self, platform_name, fullscreen=False):
        if _platform.system() != "Linux":
            return
        if not shutil.which("wmctrl"):
            return

        title_terms = ["YouTube Music"] if platform_name == "youtube_music" else ["YouTube"]
        window_id = self._find_matching_window_id(title_terms)
        if not window_id:
            return

        commands = [
            ["wmctrl", "-ia", window_id],
            ["wmctrl", "-ir", window_id, "-b", "add,maximized_vert,maximized_horz"],
        ]
        if shutil.which("xdotool"):
            commands.insert(1, ["xdotool", "windowactivate", "--sync", window_id])
        if fullscreen:
            commands.append(["wmctrl", "-ir", window_id, "-b", "add,fullscreen"])
        else:
            commands.append(["wmctrl", "-ir", window_id, "-b", "remove,fullscreen"])

        for command in commands:
            try:
                subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
            except Exception:
                continue

    def _find_matching_window_id(self, title_terms):
        deadline = time.monotonic() + 5
        title_terms = [term.lower() for term in title_terms]
        profile_sig = getattr(self, "profile_dir", "").lower() or ".cache/friday/browser-profile"
        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["wmctrl", "-lx"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=2,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception:
                return ""
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            
            # Step 1: Match by Friday's specific automated profile directory path first (highly reliable!)
            for line in reversed(lines):
                lowered = line.lower()
                if profile_sig in lowered:
                    return line.split()[0]
                    
            # Step 2: Fallback to title terms matching
            for line in reversed(lines):
                lowered = line.lower()
                if not any(term in lowered for term in title_terms):
                    continue
                if "google-chrome" not in lowered and "chromium" not in lowered:
                    continue
                return line.split()[0]
                
            time.sleep(0.25)
        return ""
