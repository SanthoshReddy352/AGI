"""Slash-command dispatcher for the GUI + Telegram input surfaces.

Lightweight pre-routing layer: when the user's input begins with `/`,
we look up the command and dispatch directly instead of running the
intent recognizer + LLM planner.

Each command is registered as a `(name, handler, description)` tuple.
Handlers receive `(app, rest_text)` and must return a response string
(or empty string if there's nothing to say).

Lock-state semantics: slash commands that hit a capability internally
will still be gated by `CapabilityExecutor`. Pure runtime-state slashes
(`/new`, `/help`, `/lock`, `/unlock`) work even when the screen is
locked because they have to.
"""
from __future__ import annotations

from typing import Callable

from core.logger import logger


SlashHandler = Callable[["object", str], str]


def is_slash_command(text: str) -> bool:
    stripped = (text or "").lstrip()
    if not stripped.startswith("/"):
        return False
    # `/path/to/file` is not a slash command — those go through the
    # file-path resolver. A real slash command has no second `/` in the
    # head word.
    head = stripped.split(None, 1)[0]
    return "/" not in head[1:] and len(head) > 1


def _split(rest: str) -> tuple[str, str]:
    parts = (rest or "").strip().split(None, 1)
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _new_session(app, rest: str) -> str:
    """Reset the conversation: clear in-memory history + start a new session.

    Beyond the obvious history-and-session-row reset, this also tears
    down cross-turn state that the old code left dangling — those leaks
    let the next conversation reach back into the prior session's
    pause/play targets, pending wipes, and live shell jobs:

      • `browser_media_service.reset_session()` closes tracked tabs and
        drops `_pages` so "pause" / "resume" can't act on the prior
        YouTube tab.
      • `core.shell_prefix.cancel_active_session("/new")` kills any
        live `!cmd` process so its stdin can't be poisoned by a
        follow-up that belongs to the new conversation.
      • `pending_memory_wipe` on the OUTGOING session row is cleared so
        a stale "yes wipe everything" can't fire after the reset.
    """
    # 1. Stop any live shell session.
    try:
        from core import shell_prefix as _shell  # noqa: PLC0415
        _shell.cancel_active_session(reason="/new")
    except Exception as exc:
        logger.debug("[/new] shell cancel failed: %s", exc)

    # 2. Drop browser media handles BEFORE rotating the session id,
    #    so the next pause/play has nothing to act on.
    browser = getattr(app, "browser_media_service", None)
    if browser is not None and hasattr(browser, "reset_session"):
        try:
            browser.reset_session()
        except Exception as exc:
            logger.debug("[/new] browser reset failed: %s", exc)

    # 3. Clear any pending memory-wipe flag on the OUTGOING session,
    #    so an unrelated "yes wipe everything" in the new conversation
    #    can't accidentally confirm a wipe queued before /new.
    context_store = getattr(app, "context_store", None)
    outgoing_session_id = getattr(app, "session_id", None)
    if context_store is not None and outgoing_session_id:
        try:
            state = context_store.get_session_state(outgoing_session_id) or {}
            if state.get("pending_memory_wipe"):
                state.pop("pending_memory_wipe", None)
                context_store.save_session_state(outgoing_session_id, state)
        except Exception as exc:
            logger.debug("[/new] outgoing pending-wipe clear failed: %s", exc)

    # 3b. Expire ALL active workflow rows for the outgoing session.
    #     Without this, a pending `research_planner` step
    #     (`awaiting_readout`) or `browser_media` step from the prior
    #     conversation can intercept the first message of the new one.
    #     2026-05-24 07:30 bug: a dangling research_planner row turned
    #     "Bye" into a 1-paragraph briefing readout instead of a
    #     shutdown. We catch this at /new so nothing leaks across.
    if context_store is not None and outgoing_session_id and hasattr(
        context_store, "expire_all_workflows"
    ):
        try:
            n = context_store.expire_all_workflows(outgoing_session_id)
            if n:
                logger.info("[/new] expired %d active workflow row(s) on session %s",
                            n, outgoing_session_id[:8])
        except Exception as exc:
            logger.debug("[/new] workflow expire failed: %s", exc)

    # 4. Reset the in-memory history and dialog state.
    context = getattr(app, "assistant_context", None)
    if context is not None:
        try:
            context.history.clear()
        except Exception as exc:
            logger.debug("[/new] history clear failed: %s", exc)
    if context_store is not None and hasattr(context_store, "start_session"):
        try:
            new_id = context_store.start_session({"entrypoint": "slash_new"})
            app.session_id = new_id
            if hasattr(context, "bind_context_store"):
                context.bind_context_store(context_store, new_id)
        except Exception as exc:
            logger.debug("[/new] session reset failed: %s", exc)
    dialog_state = getattr(app, "dialog_state", None)
    if dialog_state and hasattr(dialog_state, "reset_pending"):
        try:
            dialog_state.reset_pending("slash_new")
        except Exception:
            pass

    # 5. Reset the routing state's per-turn flags (restricted media
    #    control mode, last decision, etc.) so the new conversation
    #    starts in a clean routing context.
    routing_state = getattr(app, "routing_state", None)
    if routing_state is not None and hasattr(routing_state, "reset_for_turn"):
        try:
            routing_state.reset_for_turn()
        except Exception as exc:
            logger.debug("[/new] routing reset failed: %s", exc)

    return "New conversation started."


def _research(app, rest: str) -> str:
    topic = (rest or "").strip()
    if not topic:
        return "Usage: /research <topic>"
    # The capability is named `research_topic` (registered by
    # `modules/research_agent/plugin.py`); the old slash command was
    # looking for `research_agent`, which never matched. Probe both for
    # forward-compat with any rename.
    for name in ("research_topic", "research_agent", "research"):
        if _capability_exists(app, name):
            return _execute_capability(app, name, {"topic": topic, "query": topic}, raw=f"research {topic}")
    return "Capability 'research_topic' is not registered on this build."


def _quick(app, rest: str) -> str:
    """Instant web-backed answer in chat — nothing saved (SearchFlox)."""
    query = (rest or "").strip()
    if not query:
        return "Usage: /quick <question>"
    if _capability_exists(app, "quick_answer"):
        return _execute_capability(app, "quick_answer", {"query": query}, raw=query)
    # Fall back to plain web search if the web plugin's quick_answer is absent.
    return _web(app, rest)


def _fast(app, rest: str) -> str:
    """Fast research: ~2-min latest-info summary (research quick pipeline)."""
    topic = (rest or "").strip()
    if not topic:
        return "Usage: /fast <topic>"
    if _capability_exists(app, "research_topic"):
        return _execute_capability(
            app, "research_topic",
            {"topic": topic, "mode": "quick"},
            raw=f"quick research {topic}",
        )
    return "Capability 'research_topic' is not registered on this build."


def _deep(app, rest: str) -> str:
    """Deep research: heavy multi-source executive summary, saved to disk."""
    topic = (rest or "").strip()
    if not topic:
        return "Usage: /deep <topic>"
    if _capability_exists(app, "research_topic"):
        return _execute_capability(
            app, "research_topic",
            {"topic": topic, "mode": "deep"},
            raw=f"deep research {topic}",
        )
    return "Capability 'research_topic' is not registered on this build."


def _fetch(app, rest: str) -> str:
    url = (rest or "").strip()
    if not url:
        return "Usage: /fetch <url>"
    if _capability_exists(app, "web_extract"):
        return _execute_capability(app, "web_extract", {"url": url}, raw=f"fetch {url}")
    return "No web_extract capability is registered. Is the `modules/web` plugin loaded?"


def _crawl(app, rest: str) -> str:
    parts = (rest or "").strip().split(None, 1)
    if not parts:
        return "Usage: /crawl <url> [instructions]"
    url = parts[0]
    instructions = parts[1] if len(parts) > 1 else ""
    if _capability_exists(app, "web_crawl"):
        return _execute_capability(
            app, "web_crawl",
            {"url": url, "instructions": instructions},
            raw=f"crawl {url}",
        )
    return "No web_crawl capability is registered. Is the `modules/web` plugin loaded?"


def _screenshot(app, rest: str) -> str:
    return _execute_capability(app, "take_screenshot", {}, raw="take a screenshot")


def _web(app, rest: str) -> str:
    query = (rest or "").strip()
    if not query:
        return "Usage: /web <query>"
    for name in ("web_search", "search_web", "duckduckgo_search"):
        if _capability_exists(app, name):
            return _execute_capability(app, name, {"query": query}, raw=query)
    return "No web-search capability is registered."


def _voice(app, rest: str) -> str:
    arg = (rest or "").strip().lower()
    if arg in ("on", "unmute"):
        return _execute_capability(app, "enable_voice", {}, raw="enable voice")
    if arg in ("off", "mute"):
        return _execute_capability(app, "disable_voice", {}, raw="disable voice")
    if arg in ("", "status"):
        return _execute_capability(app, "get_voice_status", {}, raw="voice status")
    return "Usage: /voice on|off|status"


def _lock(app, rest: str) -> str:
    """Lock the real OS session (laptop/desktop), not the FRIDAY PIN gate."""
    try:
        from modules.system_control.os_lock import lock_os_session  # noqa: PLC0415
    except Exception:
        return "Screen lock is unavailable on this build."
    ok, msg = lock_os_session()
    if ok:
        monitor = getattr(app, "lock_monitor", None)
        if monitor is not None:
            monitor.note_locked()  # gate + Telegram notice immediately
    return msg


def _unlock(app, rest: str) -> str:
    return (
        "The screen is unlocked with your system password at the lock "
        "screen — I can't unlock it for you."
    )


def _help(app, rest: str) -> str:
    lines = ["Available slash commands:"]
    for name, _, description in REGISTRY:
        lines.append(f"  /{name:<11} — {description}")
    lines.append("")
    lines.append("Tip: prefix any message with ! to run it as a shell command.")
    return "\n".join(lines)


# Order in this list determines the order in /help output.
REGISTRY: list[tuple[str, SlashHandler, str]] = [
    ("new",        _new_session, "Reset the conversation and start a new session"),
    ("clear",      _new_session, "Alias for /new"),
    ("web",        _web,         "Web search — returns result links: /web <query>"),
    ("quick",      _quick,       "Instant answer in chat, nothing saved: /quick <question>"),
    ("fast",       _fast,        "Fast research — ~2-min latest summary: /fast <topic>"),
    ("deep",       _deep,        "Deep research — heavy briefing saved to disk: /deep <topic>"),
    ("research",   _research,    "Hand off to the research agent: /research <topic>"),
    ("fetch",      _fetch,       "Fetch a URL as plain text: /fetch <url>"),
    ("crawl",      _crawl,       "Crawl a URL with instructions: /crawl <url> <what to look for>"),
    ("screenshot", _screenshot,  "Take a full-screen screenshot"),
    ("voice",      _voice,       "Toggle voice mode: /voice on|off|status"),
    ("lock",       _lock,        "Lock the computer screen (OS session lock)"),
    ("unlock",     _unlock,      "How to unlock the screen"),
    ("help",       _help,        "Show this help text"),
]
_BY_NAME = {name: handler for name, handler, _ in REGISTRY}


def dispatch(app, text: str) -> str | None:
    """Return the response when *text* is a slash command, else None.

    Caller is responsible for emitting the user message into the chat
    log; this function just produces the assistant's response string.
    """
    if not is_slash_command(text):
        return None
    head, rest = _split(text.lstrip()[1:])  # strip the leading '/'
    handler = _BY_NAME.get(head.lower())
    if handler is None:
        return f"Unknown slash command: /{head}. Try /help."
    try:
        return handler(app, rest) or ""
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[slash] /%s failed: %s", head, exc)
        return f"/{head} failed: {exc}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capability_exists(app, name: str) -> bool:
    registry = getattr(app, "capability_registry", None)
    if registry is None:
        return False
    return registry.get_handler(name) is not None


def _execute_capability(app, name: str, args: dict, raw: str = "") -> str:
    executor = getattr(app, "capability_executor", None)
    if executor is None:
        return f"Capability executor is not wired in; cannot run {name}."
    if not _capability_exists(app, name):
        return f"Capability '{name}' is not registered on this build."
    result = executor.execute(name, raw or "", args)
    if not getattr(result, "ok", False):
        return getattr(result, "error", "") or f"{name} failed."
    return str(getattr(result, "output", "") or "")
