"""Model-narrated spoken progress — the headline v2 feature.

Real assistants talk while they work. Three layers, all spoken via the ``speak``
callback (wired to Piper TTS in Phase 6):

1. **Preamble** — when the model returns natural text *alongside* a tool call
   ("Sure, let me scan that subnet"), that genuine model line is spoken
   immediately, before the tool runs.
2. **Long-task progress** — if a tool is still running after configured delays,
   a short, context-aware "still working" line is spoken. By default these are
   generated from the tool + args (fast, offline, deterministic); a
   ``phrase_generator`` hook can swap in a model-rephrased line.
3. **Step narration** — on ``tool_finished`` a one-line human summary can be
   spoken before the next step.

Progress is suppressed once the final answer starts streaming (the agent stops
emitting ``tool_started`` and emits ``turn_completed``); pending timers are
cancelled on ``tool_finished`` / ``turn_completed``.

Plug it into the agent with ``Agent(emit=narration.handle_event)`` (usually via
:func:`friday.core.events.fanout` alongside the GUI sink).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from friday.core.logger import logger

SpeakFn = Callable[[str], None]
# phrase_generator(tool_name, args, attempt_index) -> spoken line
PhraseFn = Callable[[str, dict, int], str]

# Map tool-name patterns to human gerund phrases for templated progress lines.
_TOOL_PHRASES = [
    ("scan", "running the scan"),
    ("nmap", "running the scan"),
    ("search", "searching"),
    ("browser", "loading the page"),
    ("navigate", "loading the page"),
    ("download", "downloading that"),
    ("read", "reading that"),
    ("write", "writing that out"),
    ("file", "working with the files"),
    ("install", "installing that"),
    ("execute", "running that"),
    ("shell", "running that command"),
    ("code", "running the code"),
    ("image", "working on the image"),
    ("document", "going through the document"),
]


def humanize_tool(tool_name: str) -> str:
    name = (tool_name or "").lower()
    for needle, phrase in _TOOL_PHRASES:
        if needle in name:
            return phrase
    return "working on that"


def _default_phrase(tool_name: str, args: dict, attempt: int) -> str:
    activity = humanize_tool(tool_name)
    if attempt == 0:
        return f"Still {activity}…"
    if attempt == 1:
        return f"Almost there — still {activity}."
    return "Hang on, this one's taking a moment."


class NarrationEngine:
    def __init__(
        self,
        speak: SpeakFn,
        *,
        progress_delays: tuple[float, ...] = (4.0, 12.0, 25.0),
        phrase_generator: Optional[PhraseFn] = None,
        narrate_preamble: bool = True,
        narrate_tool_results: bool = False,
    ):
        self.speak = speak
        self.progress_delays = tuple(progress_delays)
        self.phrase_generator = phrase_generator or _default_phrase
        self.narrate_preamble = narrate_preamble
        self.narrate_tool_results = narrate_tool_results
        self._lock = threading.RLock()
        # active progress timers, keyed by session id
        self._timers: dict[str, list[threading.Timer]] = {}
        self._finalized: set[str] = set()

    # -- agent event hook --------------------------------------------------

    def handle_event(self, event_type: str, payload: dict) -> None:
        sid = payload.get("session_id", "")
        if event_type == "turn_started":
            self._finalized.discard(sid)
        elif event_type == "preamble":
            if self.narrate_preamble and payload.get("text", "").strip():
                self._say(payload["text"].strip())
        elif event_type == "tool_started":
            self._start_progress(sid, payload.get("tool", ""), payload.get("args", {}))
        elif event_type == "tool_finished":
            self._cancel(sid)
            if self.narrate_tool_results and payload.get("ok") and payload.get("summary"):
                self._say(self._summarize(payload["tool"], payload["summary"]))
        elif event_type in ("turn_completed", "turn_failed"):
            self._finalized.add(sid)
            self._cancel(sid)

    # -- progress timers ---------------------------------------------------

    def _start_progress(self, sid: str, tool: str, args: dict) -> None:
        self._cancel(sid)  # only one tool's progress narrated at a time
        timers: list[threading.Timer] = []
        for i, delay in enumerate(self.progress_delays):
            t = threading.Timer(delay, self._fire_progress, args=(sid, tool, args, i))
            t.daemon = True
            t.start()
            timers.append(t)
        with self._lock:
            self._timers[sid] = timers

    def _fire_progress(self, sid: str, tool: str, args: dict, attempt: int) -> None:
        # Don't speak if the turn already finalized (timer raced completion).
        if sid in self._finalized:
            return
        try:
            line = self.phrase_generator(tool, args, attempt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[narration] phrase generator failed: %s", exc)
            line = _default_phrase(tool, args, attempt)
        if line:
            self._say(line)

    def _cancel(self, sid: str) -> None:
        with self._lock:
            timers = self._timers.pop(sid, [])
        for t in timers:
            t.cancel()

    # -- helpers -----------------------------------------------------------

    def _say(self, text: str) -> None:
        try:
            self.speak(text)
        except Exception as exc:  # noqa: BLE001
            logger.error("[narration] speak failed: %s", exc)

    @staticmethod
    def _summarize(tool: str, summary: str) -> str:
        snippet = summary.strip().splitlines()[0][:120]
        return snippet
