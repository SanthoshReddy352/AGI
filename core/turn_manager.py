from __future__ import annotations

import uuid

from core.planning import TurnRequest
from core.tracing import trace_scope
from core.planning.references import attach as attach_references
from core.turn_context import TurnContext, turn_scope


class TurnManager:
    def __init__(self, app, conversation_agent):
        self.app = app
        self.conversation_agent = conversation_agent

    def handle_turn(self, text: str, source: str = "user"):
        feedback = getattr(self.app, "turn_feedback", None)
        turn = feedback.start_turn(text, source=source) if feedback else None
        # Reuse the TurnRecord's uuid as the trace_id so logs/events line up
        # with metrics records without a second correlation column.
        turn_id = getattr(turn, "turn_id", None) or uuid.uuid4().hex
        ctx = TurnContext(
            turn_id=turn_id,
            session_id=self.app.session_id,
            trace_id=turn_id,
            source=source,
            text=text,
            references=attach_references(
                getattr(self.app, "context_store", None),
                self.app.session_id,
            ),
            _routing_state=getattr(self.app, "routing_state", None),
            _dialog_state=getattr(self.app, "dialog_state", None),
        )
        self.app.current_turn_context = ctx
        with trace_scope(turn_id), turn_scope(ctx):
            self.app._active_turn_record = turn
            session_id = self.app.session_id
            memory = getattr(self.app, "memory_service", None) or self.app.context_store
            state = memory.get_session_state(session_id) or {}
            state["last_source"] = source
            memory.save_session_state(session_id, state)
            try:
                # Track 3.2 (Consolidation Direction): the v2 orchestrator is
                # now the ONLY dispatch path. The two v1 fallback branches
                # (`router.process_text` for no-capabilities apps, and
                # `conversation_agent.build_tool_plan` for the legacy v1
                # ConversationAgent flow) were retired. The
                # `_use_v2_orchestrator` predicate is still consulted so
                # tests that mount a partial app without `turn_orchestrator`
                # get a clear AssertionError instead of silently routing
                # through dead v1 code.
                if not self._use_v2_orchestrator():
                    raise RuntimeError(
                        "Track 3.2: v1 turn dispatch retired — the v2 "
                        "orchestrator (`app.turn_orchestrator`) must be "
                        "wired and `routing.orchestrator: v2` set in config."
                    )
                response = self._handle_via_orchestrator(
                    ctx, text, source, turn, feedback
                )
                speak_final = not self.app.routing_state.voice_already_spoken
                if feedback and turn:
                    feedback.complete_turn(turn, response, speak_final=speak_final, ok=True)
                    self.app._last_turn_speech_managed = True
                return response
            except Exception as exc:
                if feedback and turn:
                    feedback.fail_turn(turn, str(exc))
                    self.app._last_turn_speech_managed = True
                raise
            finally:
                # Track 0.4b: retain the most-recent TurnContext on the app
                # for introspection (test_spans_e2e reads `_last_turn_context`
                # to inspect span recordings after the turn). The
                # `current_turn_context` slot still clears so any consumer
                # checking "is a turn active right now" sees None.
                self.app._last_turn_context = ctx
                self.app._active_turn_record = None
                self.app.current_turn_context = None

    # ------------------------------------------------------------------
    # Phase 3 (v2): single-flow dispatch through TurnOrchestrator
    # ------------------------------------------------------------------

    def _use_v2_orchestrator(self) -> bool:
        """True when the v2 single-flow orchestrator should handle this turn.

        Track 3.2 (Consolidation Direction): v2 is now unconditional when
        the orchestrator is wired. The legacy opt-in via
        `routing.orchestrator: "v2"` is still honored for explicit
        override but the default flipped from "v1" to "v2" — passing
        `v1` raises in handle_turn since the v1 dispatch was deleted.
        """
        if getattr(self.app, "turn_orchestrator", None) is None:
            return False
        config = getattr(self.app, "config", None)
        if config is None or not hasattr(config, "get"):
            # No config loaded (test apps); v2 orchestrator is wired, use it.
            return True
        value = str(config.get("routing.orchestrator", "v2") or "v2").lower()
        return value == "v2"

    def _handle_via_orchestrator(self, ctx, text, source, turn, feedback):
        """Run the turn through TurnOrchestrator while preserving the
        feedback / progress / acknowledgement events the legacy path
        emits, so external observers (TTS, GUI, metrics) see no
        difference between the two dispatch modes."""
        request = TurnRequest(
            text=text,
            source=source,
            session_id=self.app.session_id,
            turn_id=ctx.turn_id,
        )

        _ack_sent = [False]

        def on_plan_ready(plan):
            if not (feedback and turn):
                return
            ack = getattr(plan, "ack", None) or ""
            mode = getattr(plan, "mode", "") or ""
            latency = getattr(plan, "estimated_latency", "interactive") or "interactive"
            if ack:
                feedback.emit_ack(turn, ack)
                _ack_sent[0] = True
            # Start progress timers for anything that can take > 2.5s:
            # online tools, slow/generative/background latency, or LLM chat.
            if ack or mode == "chat" or latency in ("slow", "generative", "background"):
                feedback.start_progress_timers(turn)

        response = self.app.turn_orchestrator.handle(request, ctx=ctx, on_plan_ready=on_plan_ready)
        # Fallback: forward spoken_ack from TurnResponse when on_plan_ready
        # never fired (e.g. mocked orchestrator in tests).
        if feedback and turn and response.spoken_ack and not _ack_sent[0]:
            feedback.emit_ack(turn, response.spoken_ack)
        if response.error:
            raise RuntimeError(response.error)
        return response.response
