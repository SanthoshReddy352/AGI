"""Track 5.2d-retire: pure-function home for the media-command boundary
check and the intent → action mapping that used to live inside
`BrowserMediaWorkflow`.

Lifted out so the YAML template + capability path can reuse the same
logic the legacy class did, and so tests don't have to instantiate the
deprecated workflow class to exercise the boundary semantics.

Two public surfaces:

  * :func:`is_likely_media_command` — boundary predicate; matches a
    user utterance against the "this is a media control command, not
    conversational text" rule from Issue 9 (the "...next year is my
    promotion" misroute). Backs the ``detect_media_command``
    capability used by the ``browser_media`` YAML template's
    ``when:`` predicate.

  * :func:`parse_media_intent` — translates a user utterance + the
    current workflow state into an action dict
    (``{"action": ..., "platform": ..., "browser_name": ..., "query":
    ...}``) that ``dispatch_media_intent`` can hand to the
    ``BrowserMediaService``. The pair backs ``browser_media_dispatch``.

No I/O, no class state — pure functions over strings + dicts.
"""
from __future__ import annotations

import re
from typing import Any


# Verbs that, when present, indicate narrative / personal-fact speech
# rather than a media command. If any appears, never resume the media
# workflow even if a media keyword ("next", "play") is also present.
# (Issue 9 — the "...next year is my promotion" hijack.)
_NON_MEDIA_VERBS = (
    "remember", "remembered", "learn", "learned", "learning",
    "know", "knew", "knows", "work", "works", "working", "worked",
    "said", "say", "says", "tell", "told", "telling",
    "think", "thought", "thinking", "feel", "felt", "feeling",
    "believe", "believed", "wonder", "wondered", "promised",
)

# Compound phrases that pair with "next" / "previous" but never mean
# "next track" / "previous chapter".
_TEMPORAL_NEXT_RE = re.compile(
    r"\bnext\s+(?:year|month|week|time|session|chapter|step|page|"
    r"morning|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
)

_MEDIA_NOUNS = (
    "video", "song", "track", "music", "youtube", "tune", "podcast",
    "episode", "playlist", "playback",
)

_MEDIA_KEYWORDS = frozenset({
    "pause", "resume", "next", "skip", "play", "previous",
    "forward", "back", "backward", "revert", "rewind",
})

# "open it (again)" / "reopen" / "play it again" / "resume that" — a request
# to re-open the previously-played media after its tab was closed. Distinct
# from a fresh "play <query>": it references the prior media by pronoun
# ("it" / "that") or a media noun, or is a bare "reopen". Backs both the
# boundary predicate (is_likely_media_command) and parse_media_intent so
# "open it again" continues the browser_media workflow instead of falling
# through to the open_file capability (2026-05-29 log bug).
_REOPEN_MEDIA_RE = re.compile(
    r"\bre-?open\b"
    r"|\b(?:open|play|start|resume|put\s+on)\s+"
    r"(?:it|that|this|the\s+(?:video|song|track|music|tune|tab|playback|playlist))"
    r"(?:\s+(?:again|back(?:\s+(?:on|up))?))?\b",
)

_SEEK_RE = re.compile(
    r"(\d+)\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes)\b",
)
_SEEK_UNIT_RE = re.compile(
    r"\d+\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes)\b",
)


def is_likely_media_command(lower_text: str) -> bool:
    """Return True when *lower_text* looks like an actual media-control
    intent rather than conversational text that happens to contain a
    media verb.

    Conditions:
      * No personal-fact verb in the sentence ("work", "remember",
        "said", …).
      * No temporal "next year / month / week / time" phrase.
      * Either short (<=5 tokens) — bare imperatives like "pause",
        "next", "skip 30 seconds" — OR the utterance contains an
        explicit media noun.

    Accepts already-lowercased text so callers don't double-normalize.
    """
    text = (lower_text or "").lower().strip()
    if not text:
        return False
    if any(re.search(rf"\b{v}\b", text) for v in _NON_MEDIA_VERBS):
        return False
    if _TEMPORAL_NEXT_RE.search(text):
        return False
    if "music instead" in text or "youtube instead" in text:
        return True
    # "open it again" / "reopen" — no media KEYWORD, but an unambiguous
    # re-open continuation. Only consulted when a media workflow is active.
    if _REOPEN_MEDIA_RE.search(text):
        return True
    tokens = text.split()
    has_keyword = any(t.strip(".,!?") in _MEDIA_KEYWORDS for t in tokens)
    if not has_keyword:
        return False
    if len(tokens) <= 5:
        return True
    return any(noun in text for noun in _MEDIA_NOUNS)


def is_reopen_media_command(lower_text: str) -> bool:
    """Return True when *lower_text* is a re-open continuation ("open it
    again" / "reopen" / "play it again" / "resume that" / "open the video
    again"). Public companion to :data:`_REOPEN_MEDIA_RE` so the
    IntentRecognizer's ``_parse_browser_media`` can share the same matcher
    instead of duplicating the pattern."""
    return bool(_REOPEN_MEDIA_RE.search((lower_text or "").lower()))


def _extract_browser_name(text: str) -> str:
    if "chromium" in text:
        return "chromium"
    if "chrome" in text:
        return "chrome"
    return ""


def _extract_seek_seconds(lower_text: str) -> int | None:
    match = _SEEK_RE.search(lower_text)
    if not match:
        return None
    unit_match = _SEEK_UNIT_RE.search(lower_text)
    unit = (unit_match.group(1) if unit_match else "s").lower()
    value = int(match.group(1))
    if unit.startswith("m"):
        value *= 60
    return value


def parse_media_intent(
    user_text: str,
    workflow_state: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return an action dict, or None when *user_text* doesn't match
    any media intent.

    The action dict has shape::

        {"action": "play"|"pause"|"resume"|"next"|"previous"|"forward"|
                   "backward"|"open"|"seek_forward"|"seek_backward",
         "platform": "youtube"|"youtube_music",
         "browser_name": "chrome"|"chromium",
         "query": "...",
         "seconds": int (only for seek_*),
        }
    """
    workflow_state = workflow_state or {}
    context = context or {}
    lower_text = (user_text or "").strip().lower()
    browser_name = (
        context.get("browser_name")
        or _extract_browser_name(lower_text)
        or "chrome"
    )

    # Context-driven shortcuts (e.g. a planner that already classified).
    if context.get("action") == "open_browser_url":
        return {
            "action": "open",
            "platform": (
                "youtube_music"
                if "music.youtube.com" in context.get("url", "")
                else "youtube"
            ),
            "browser_name": browser_name,
        }
    if context.get("action") in {"play_youtube", "play_youtube_music"}:
        return {
            "action": "play",
            "platform": (
                "youtube_music"
                if context["action"] == "play_youtube_music" else "youtube"
            ),
            "browser_name": browser_name,
            "query": context.get("query", ""),
        }
    if context.get("action") == "browser_media_control":
        return {
            "action": context.get("control", ""),
            "platform": workflow_state.get("platform") or "youtube",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
        }

    # Re-open the previously-played media ("open it again" / "reopen" /
    # "play it again"). Replays the remembered query so the same video
    # resumes; if no query was captured, just re-open the platform. Must run
    # before the bare "^play <x>" fresh-search guard so "play it again" isn't
    # dropped, and before the keyword map so "play" isn't read as a resume.
    if _REOPEN_MEDIA_RE.search(lower_text):
        query = workflow_state.get("query", "")
        return {
            "action": "play" if query else "open",
            "platform": workflow_state.get("platform") or "youtube",
            "browser_name": workflow_state.get("browser_name") or browser_name,
            "query": query,
        }

    play_music = re.search(r"\bplay\s+(.+?)\s+(?:in|on)\s+youtube music\b", lower_text)
    if play_music:
        return {
            "action": "play",
            "platform": "youtube_music",
            "browser_name": browser_name,
            "query": play_music.group(1).strip(),
        }

    play_video = re.search(r"\bplay\s+(.+?)\s+(?:in|on)\s+youtube\b", lower_text)
    if play_video:
        return {
            "action": "play",
            "platform": "youtube",
            "browser_name": browser_name,
            "query": play_video.group(1).strip(),
        }

    if re.search(r"\bopen\s+youtube music\b", lower_text):
        return {"action": "open", "platform": "youtube_music", "browser_name": browser_name}
    if re.search(r"\bopen\s+youtube\b", lower_text):
        return {"action": "open", "platform": "youtube", "browser_name": browser_name}

    # "play <subject>" without a matching "in/on youtube" suffix is a fresh
    # search — do NOT collapse it to a media-control resume.
    if re.match(r"^play\s+\S+", lower_text):
        return None

    seek_seconds = _extract_seek_seconds(lower_text)
    if seek_seconds is not None:
        backward_words = ("back", "backward", "backwards", "rewind", "behind", "previous")
        direction = (
            "seek_backward" if any(w in lower_text for w in backward_words)
            else "seek_forward"
        )
        return {
            "action": direction,
            "platform": workflow_state.get("platform") or "youtube",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
            "seconds": seek_seconds,
        }

    if re.search(r"\b(forward|ahead)\b", lower_text):
        return {
            "action": "forward",
            "platform": workflow_state.get("platform") or "youtube",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
        }
    if re.search(r"\b(backward|backwards|rewind|go back)\b", lower_text):
        return {
            "action": "backward",
            "platform": workflow_state.get("platform") or "youtube",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
        }

    media_map = {
        "pause": "pause",
        "resume": "resume",
        "play": "resume",
        "next": "next",
        "skip": "next",
        "previous": "previous",
        "revert": "backward",
    }
    for keyword, cmd in media_map.items():
        if keyword in lower_text:
            return {
                "action": cmd,
                "platform": workflow_state.get("platform") or "youtube",
                "browser_name": browser_name,
                "query": workflow_state.get("query", ""),
            }

    if "music instead" in lower_text:
        return {
            "action": "play" if workflow_state.get("query") else "open",
            "platform": "youtube_music",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
        }

    if "youtube instead" in lower_text:
        return {
            "action": "play" if workflow_state.get("query") else "open",
            "platform": "youtube",
            "browser_name": browser_name,
            "query": workflow_state.get("query", ""),
        }

    return None


def dispatch_media_intent(service: Any, intent: dict[str, Any]) -> str:
    """Map an action dict to the appropriate ``BrowserMediaService`` call.

    The legacy ``BrowserMediaWorkflow._handle`` body. Pure I/O dispatch
    — no state mutation; the caller owns workflow-state persistence.
    Returns the human-readable response from the service.
    """
    if service is None:
        return "Browser automation is not available yet."
    action = intent.get("action") or ""
    platform = intent.get("platform") or "youtube"
    browser_name = intent.get("browser_name") or "chrome"
    query = intent.get("query") or ""

    if action == "open":
        url = (
            "https://music.youtube.com" if platform == "youtube_music"
            else "https://www.youtube.com"
        )
        return service.open_browser_url(url, browser_name=browser_name, platform=platform)
    if action == "play":
        if platform == "youtube_music":
            return service.play_youtube_music(query, browser_name=browser_name)
        return service.play_youtube(query, browser_name=browser_name)
    if action in ("seek_forward", "seek_backward"):
        seconds = int(intent.get("seconds") or 10)
        return service.browser_media_control(
            action, platform=platform, query=query, seconds=seconds,
        )
    return service.browser_media_control(action, platform=platform, query=query)
