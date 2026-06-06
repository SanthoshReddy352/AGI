"""ResearchPlannerWorkflow — agentic service: pre-research conversational planner.

Track 5.2e: although the planner walks a small state machine, it is
NOT a linear YAML-templatable slot-fill flow. It interleaves user
turns with an async LLM research job (`researching` state waits on
`on_complete`), drives state transitions via free-text LLM
re-interpretation of replies, and emits side-effecting voice
read-outs. Templating it would force the YAML model to support async
job futures and LLM re-prompting mid-flow. It lives under
`core/reasoning/agentic_services/` (renamed from
`core/reasoning/workflows/`).

State machine:

    awaiting_topic   → "What should I research?"
    awaiting_mode    → "speed / balanced / quality?"
    awaiting_sources → "How many sources? (1-N)"
    awaiting_focus   → "Any particular angle, or general?"
    awaiting_confirm → recap, "Shall I proceed?"
    researching      → research kicked off, async on_complete will message
    awaiting_readout → "Briefing ready — read it aloud?"
    done             → terminal

The service is started by the ResearchAgentPlugin (not by ``should_start``
matching utterances) so it doesn't compete with the existing
`research_mode` service or the deterministic router. Once active,
``WorkflowOrchestrator.continue_active`` delivers subsequent user turns
to ``can_continue`` → ``run`` → ``_handle``.

The class name is kept as `ResearchPlannerWorkflow` (and
`name = "research_planner"`) for state-storage and dispatch
compatibility with `WorkflowOrchestrator`.
"""
from __future__ import annotations

import re

from core.logger import logger
from core.workflow_orchestrator import BaseWorkflow, WorkflowResult


_NEGATIVE_TOKENS = ("no", "skip", "cancel", "stop", "nope", "nah", "forget", "abort", "don't", "do not")

# 2026-05-24 — shutdown / new-conversation phrasings that hit
# `awaiting_readout` must NOT trigger a briefing readout. Without this,
# the dangling research_planner workflow turns "Bye" into a 1-paragraph
# summary recital instead of letting `shutdown_assistant` fire. Treated
# the same as `_NEGATIVE_TOKENS`: gracefully end the workflow and return
# a one-liner ack so the router can move on to the real intent next turn.
_BAILOUT_TOKENS = (
    "bye", "goodbye", "good bye", "see you", "see ya", "later", "farewell",
    "exit", "quit", "shutdown", "shut down", "close", "/new", "/clear",
    "never mind", "nevermind", "leave it", "drop it",
)
_AFFIRMATIVE_TOKENS = ("yes", "yeah", "yep", "sure", "ok", "okay", "go", "do it", "proceed", "go ahead", "please do")

_MODE_CAPS = {
    # New pipelines (Steps 5b / 5c) — used by default after 2026-05-24.
    "quick": 5,
    "deep": 12,
    # Legacy modes — kept so explicit "speed"/"balanced"/"quality"
    # phrasings still resolve and route through the old agentic loop
    # in `service._run_research_locked`.
    "speed": 4,
    "balanced": 8,
    "quality": 12,
}

# Default mode and source count — used when the user doesn't specify.
_DEFAULT_PLANNER_MODE = "deep"  # 2026-05-24 — new pipeline is now default for "research X"
_DEFAULT_PLANNER_SOURCES = 12

_AWAITING_STEPS = frozenset({
    "awaiting_topic",
    "awaiting_focus",
    "awaiting_readout",
})


class ResearchPlannerWorkflow(BaseWorkflow):
    name = "research_planner"

    # Never auto-start. The plugin is responsible for entering this workflow
    # so we don't compete with the existing `research_mode` quick-summary
    # workflow or with deterministic routing.
    def should_start(self, user_text, context=None):
        return False

    def can_continue(self, user_text, state, context=None):
        return state.get("step") in _AWAITING_STEPS

    # ------------------------------------------------------------------
    # External entry point: called by the plugin to enter the workflow.
    # ------------------------------------------------------------------

    def begin(self, topic: str, session_id: str, *, mode: str | None = None) -> str:
        """Save the initial state and return the first (and usually only) prompt.

        2026-05-24 Step 5d — when *mode* is explicitly "quick" or
        "deep" (the intent parser detected it from phrasings like
        "tldr X" or "deep dive on Y"), skip the "any specific angle?"
        prompt and kick off research immediately. Without the override
        the parser-detected depth is silently dropped by the focus
        step, defeating the point of explicit phrasings.
        """
        topic = (topic or "").strip(" .!?:'\"")
        explicit_mode = (mode or "").lower().strip()

        if not topic:
            initial = {
                "step": "awaiting_topic",
                "mode": explicit_mode or _DEFAULT_PLANNER_MODE,
                "max_sources": _DEFAULT_PLANNER_SOURCES,
            }
            self._memory().save_workflow_state(session_id, self.name, initial)
            return "What would you like me to research, sir?"

        # Explicit-mode fast path — straight to kick-off, no focus prompt.
        if explicit_mode in {"quick", "deep"}:
            ws = {
                "step": "awaiting_focus",  # _kick_off_research expects this shape
                "topic": topic,
                "mode": explicit_mode,
                "max_sources": _DEFAULT_PLANNER_SOURCES,
                "focus": "",
            }
            return self._kick_off_research(
                state={"user_text": "", "session_id": session_id},
                ws=ws,
                session_id=session_id,
            )["result"].response

        state = {
            "step": "awaiting_focus",
            "topic": topic,
            "mode": _DEFAULT_PLANNER_MODE,
            "max_sources": _DEFAULT_PLANNER_SOURCES,
            "focus": None,
        }
        self._memory().save_workflow_state(session_id, self.name, state)
        return (
            f"Researching '{topic}' — up to {_DEFAULT_PLANNER_SOURCES} sources. "
            "Any specific angle? Say 'general' to start now, or describe your focus. "
            "You can also say 'speed' or 'balanced', or 'quick' / 'deep' to adjust the depth."
        )

    # ------------------------------------------------------------------
    # Per-turn handler
    # ------------------------------------------------------------------

    def _handle(self, state):
        user_text = (state.get("user_text") or "").strip()
        session_id = state["session_id"]
        ws = self._memory().get_active_workflow(session_id, workflow_name=self.name) or {}
        step = ws.get("step")

        if step == "awaiting_topic":
            topic = user_text.strip(" .!?:'\"")
            if not topic:
                return self._reply(state, ws, "I still need a topic, sir — what should I research?")
            ws["topic"] = topic
            ws["step"] = "awaiting_focus"
            self._save(session_id, ws)
            return self._reply(state, ws,
                f"Researching '{topic}' in quality mode with up to {_DEFAULT_PLANNER_SOURCES} sources. "
                "Any specific angle? Say 'general' to start now.")

        if step == "awaiting_focus":
            if self._is_negative(user_text) or user_text.strip(" .!?:'\"").lower() in ("general", "broad", "any", "none", ""):
                focus = ""
            else:
                focus = user_text.strip(" .!?:'\"")
                # Allow inline mode/source overrides in the focus reply
                mode_override = self._parse_mode(user_text)
                if mode_override != "balanced" or any(m in user_text.lower() for m in _MODE_CAPS):
                    ws["mode"] = mode_override
                    ws["max_sources"] = min(ws.get("max_sources", _DEFAULT_PLANNER_SOURCES), _MODE_CAPS[mode_override])
                n_override = self._parse_sources_inline(user_text)
                if n_override:
                    ws["max_sources"] = min(n_override, _MODE_CAPS[ws.get("mode", _DEFAULT_PLANNER_MODE)])
            ws["focus"] = focus
            return self._kick_off_research(state, ws, session_id)

        if step == "awaiting_readout":
            # Shutdown / bail-out phrasings end the workflow WITHOUT
            # reading the briefing. The user clearly meant something
            # else (bye, /new, never mind); don't read the summary
            # at them by accident. The router will route the same
            # message through the normal chain on the next turn — but
            # because the workflow returned `handled=False`, the
            # outer orchestrator falls through to `_parse_exit` /
            # `_parse_clear` etc.
            if self._is_bailout(user_text):
                ws["step"] = "done"
                self._save(session_id, ws)
                state["result"] = WorkflowResult(
                    handled=False,
                    workflow_name=self.name,
                    state=ws,
                )
                return state
            if self._is_negative(user_text):
                ws["step"] = "done"
                self._save(session_id, ws)
                folder = ws.get("folder", "friday-research")
                folder_name = folder.rsplit("/", 1)[-1]
                return self._reply(state, ws,
                    f"Understood. The briefing is in friday-research/{folder_name} when you want it.")
            summary_text = self._summary_for_speech(ws.get("summary_path", ""))
            ws["step"] = "done"
            self._save(session_id, ws)
            return self._reply(state, ws, summary_text)

        # No matching step — bail out so the router can take over.
        state["result"] = WorkflowResult(handled=False, workflow_name=self.name, state=ws)
        return state

    # ------------------------------------------------------------------
    # Research kick-off and async completion
    # ------------------------------------------------------------------

    def _kick_off_research(self, state, ws, session_id):
        agent = getattr(self.app, "research_agent", None)
        if agent is None:
            ws["step"] = "done"
            self._save(session_id, ws)
            return self._reply(state, ws,
                "Research agent isn't loaded right now, sir.")

        topic = ws["topic"]
        focus = ws.get("focus") or ""
        full_topic = f"{topic} ({focus})" if focus else topic

        ws["step"] = "researching"
        ws["source"] = "telegram" if getattr(self.app, "telegram_turn_active", False) else "user"
        self._save(session_id, ws)

        # Capture what we need so the async callback can update workflow state
        # without holding any reference to the LangGraph state dict.
        bound_session = session_id
        prior_ws = dict(ws)

        def _on_complete(report):
            self._on_research_done(report, bound_session, prior_ws)

        try:
            agent.start_research(
                full_topic,
                max_sources=ws["max_sources"],
                mode=ws["mode"],
                on_complete=_on_complete,
            )
        except Exception as exc:
            logger.exception("[research-planner] start_research failed")
            ws["step"] = "done"
            self._save(session_id, ws)
            return self._reply(state, ws,
                f"Couldn't start research: {exc}")

        return self._reply(state, ws,
            f"Researching '{full_topic}' in {ws['mode']} mode across {ws['max_sources']} sources. "
            f"I'll let you know when it's ready.")

    def _on_research_done(self, report, session_id, prior_ws):
        """Async completion: update workflow state + announce the result.

        Runs on the research worker thread, so we must not touch any
        per-turn LangGraph state — only the persisted workflow_state row.
        """
        ws = dict(prior_ws)
        ws["folder"] = getattr(report, "folder", "")
        ws["summary_path"] = getattr(report, "summary_path", "")
        ws["report_topic"] = getattr(report, "topic", "")

        if getattr(report, "error", None):
            ws["step"] = "done"
            self._save(session_id, ws)
            self._announce(
                f"Research on '{report.topic}' hit a snag, sir: {report.error}"
            )
            return

        ws["step"] = "awaiting_readout"
        self._save(session_id, ws)

        sources = getattr(report, "sources", []) or []
        usable = sum(
            1 for s in sources
            if getattr(s, "summary", "") and not getattr(s, "error", None)
        )
        folder_name = (getattr(report, "folder", "") or "").rsplit("/", 1)[-1]
        msg = (
            f"Briefing on '{report.topic}' is ready. "
            f"{usable} of {len(sources)} sources made it in. "
            f"Saved to friday-research/{folder_name}. "
            "Reply 'yes' to get the summary here, or 'no' to skip."
            if ws.get("source") == "telegram" else
            f"Briefing on '{report.topic}' is ready. "
            f"{usable} of {len(sources)} sources made it in. "
            f"Saved to friday-research/{folder_name}. "
            "Want me to read the summary aloud?"
        )

        if ws.get("source") == "telegram":
            comms = getattr(self.app, "comms", None)
            if comms and comms.telegram.available:
                comms.telegram.send(msg)
                return
        self._announce(msg)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _save(self, session_id, ws):
        self._memory().save_workflow_state(session_id, self.name, ws)

    def _reply(self, state, ws, message):
        state["result"] = WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response=message,
            state=ws,
        )
        return state

    def _announce(self, message):
        emit = getattr(self.app, "emit_assistant_message", None)
        if callable(emit):
            try:
                emit(message, source="research")
                return
            except Exception:
                logger.exception("[research-planner] emit_assistant_message failed")
        bus = getattr(self.app, "event_bus", None)
        if bus is not None:
            bus.publish("voice_response", message)

    def _parse_mode(self, text: str) -> str:
        """Recognise the user's depth preference from a free-text reply.

        2026-05-24 Step 5d — "quick"/"fast"/"brief"/"rapid" → `quick`
        (new composable pipeline). "thorough"/"deep"/"exhaustive"/
        "comprehensive"/"detailed" → `deep` (new domain-aware
        pipeline). Legacy mode names (speed / balanced / quality) are
        still recognised so `mode: speed` keeps routing to the old
        agentic loop for the few callers that still use it.
        """
        t = (text or "").lower()
        # Exact mode-name mentions win first.
        for mode in _MODE_CAPS:
            if re.search(rf"\b{re.escape(mode)}\b", t):
                return mode
        if any(w in t for w in ("quick", "fast", "brief", "rapid", "shallow")):
            return "quick"
        if any(w in t for w in ("thorough", "deep", "exhaustive", "comprehensive", "detailed")):
            return "deep"
        return "deep"  # default to the new pipeline

    def _parse_sources(self, text: str, mode: str) -> int:
        cap = _MODE_CAPS.get(mode, 8)
        m = re.search(r"\d+", text or "")
        if not m:
            return min(5, cap)
        try:
            n = int(m.group(0))
        except ValueError:
            return min(5, cap)
        return max(1, min(n, cap))

    def _parse_sources_inline(self, text: str) -> int:
        """Extract an explicit source count from a free-form reply (e.g. '6 sources')."""
        m = re.search(r"\b(\d+)\s+source", (text or "").lower())
        if not m:
            return 0
        try:
            return int(m.group(1))
        except ValueError:
            return 0

    def _is_negative(self, text: str) -> bool:
        t = (text or "").lower().strip(" .!?")
        if not t:
            return False
        if t in _NEGATIVE_TOKENS:
            return True
        return any(re.search(r"\b" + re.escape(tok) + r"\b", t) for tok in _NEGATIVE_TOKENS)

    def _is_bailout(self, text: str) -> bool:
        """Match shutdown / new-conversation / nevermind phrasings that
        should end the awaiting_readout step WITHOUT reading the briefing."""
        t = (text or "").lower().strip(" .!?")
        if not t:
            return False
        if t in _BAILOUT_TOKENS:
            return True
        return any(re.search(r"\b" + re.escape(tok) + r"\b", t) for tok in _BAILOUT_TOKENS)

    def _summary_for_speech(self, path: str) -> str:
        if not path:
            return "I couldn't find the summary file, sir."
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as exc:
            return f"Couldn't open the summary: {exc}"

        # Markdown stripping for TTS — strip think tags, headings, citations, emphasis.
        text = content
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^#+\s*", "", text, flags=re.M)
        text = re.sub(r"\[(\d+)\]", r"reference \1", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.M)
        text = re.sub(r"\n{2,}", ". ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) > 1500:
            text = text[:1500].rsplit(".", 1)[0] + "."
        return f"Reading the briefing now. {text}"
