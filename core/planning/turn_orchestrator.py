"""TurnOrchestrator — single control flow for a turn.

Phase 3 of the v2 architecture (docs/friday_architecture.md §8).

Replaces the five competing v1 paths (TaskRunner / direct _execute_turn /
fast_media_command / dictation early-exit / no-capabilities legacy) with
one method: `handle(TurnRequest) -> TurnResponse`.

Sequence (per §8 sequence diagram):

  1. Build a context bundle from MemoryBroker.
  2. Ask WorkflowCoordinator if an active workflow can absorb the input.
  3. If not, classify intent (IntentEngine).
  4. Build the plan (PlannerEngine — fast path for high-confidence
     intents, full pipeline otherwise).
  5. Execute via the configured executor (TaskGraphExecutor in parallel
     mode, OrderedToolExecutor otherwise).
  6. Curate memory and emit the structured TurnResponse.

The orchestrator does NOT own turn-feedback events, voice cancellation,
or the TurnContext lifecycle — those belong to TurnManager. The
orchestrator is invoked by TurnManager when the v2 dispatch flag is on
(`routing.orchestrator: "v2"`); the legacy path stays as the default.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from core.logger import logger
from core.planning.context_resolver import ContextResolver
from core.planning.intent_engine import HIGH_THRESHOLD
from core.planning.spans import Span, attach_recorder


SourceLiteral = Literal["voice", "text", "gui", "user", "task_runner"]


@dataclass
class TurnRequest:
    text: str
    source: str = "user"
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    turn_id: str = ""

    def __post_init__(self):
        if not self.turn_id:
            self.turn_id = uuid.uuid4().hex


@dataclass
class TurnResponse:
    response: str
    spoken_ack: str | None = None
    source: str = "planner"        # "intent" | "planner" | "workflow" | "chat"
    trace_id: str = ""
    duration_ms: float = 0.0
    plan_mode: str = ""
    error: str | None = None


class TurnOrchestrator:
    """The v2 single-entrypoint turn handler."""

    def __init__(
        self,
        app,
        intent_engine,
        planner_engine,
        workflow_coordinator,
        memory_broker=None,
        context_resolver=None,
    ):
        self.app = app
        self._intent = intent_engine
        self._planner = planner_engine
        self._workflow = workflow_coordinator
        self._memory = memory_broker
        # Track 1.4 (keystone): single resolver between plan construction and
        # execution. The resolver rewrites chat→file when a pronoun-bearing
        # short question refers to an artifact in scope. Default-construct
        # so existing callers don't need to wire it explicitly.
        self._resolver = context_resolver or ContextResolver(app)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def handle(self, request: TurnRequest, ctx=None, *, on_plan_ready=None) -> TurnResponse:
        started = time.monotonic()
        trace_id = getattr(ctx, "trace_id", "") or request.turn_id
        session_id = request.session_id or getattr(self.app, "session_id", "")

        # Track 0.4: attach a per-turn span recorder. Six named checkpoints
        # (context_built, intent_classified, plan_built, plan_validated,
        # tool_executed, response_finalized) get a span each so we can answer
        # "why was turn X slow" without per-investigation instrumentation.
        attach_recorder(ctx)

        # Track 3.1: reset the per-turn router-fire counter at dispatch
        # entry. Every routing decision in the v2 chain calls
        # `increment_router_fire`; the test pin asserts the count is
        # exactly 1 per turn (no double-routing).
        metrics = getattr(self.app, "runtime_metrics", None)
        if metrics is not None and hasattr(metrics, "begin_turn"):
            metrics.begin_turn()

        # 1. Context bundle
        with Span(ctx, "context_built"):
            bundle = self._build_context_bundle(request.text, session_id)
        logger.debug("[timing] context_built elapsed=%.0f", (time.monotonic() - started) * 1000)
        if ctx is not None:
            try:
                ctx.context_bundle = bundle
            except AttributeError:
                pass

        # 2. Pending online confirmation check — must come before intent/workflow
        # so "yes" / "no" after an online-consent prompt resolves the pending
        # action rather than being misrouted to confirm_yes / confirm_no.
        pending_plan = self._check_pending_confirmation(request.text, request.turn_id, session_id)
        if pending_plan is not None:
            logger.debug("[timing] pending_confirmation elapsed=%.0f", (time.monotonic() - started) * 1000)
            logger.info("[ROUTE] source=confirmation tool=%s", getattr(pending_plan, "tool_name", "") or "")
            if metrics is not None and hasattr(metrics, "increment_router_fire"):
                metrics.increment_router_fire()
            response_text = self._execute(pending_plan, request.text)
            self._curate_memory(request.text, response_text, bundle, session_id)
            return TurnResponse(
                response=response_text,
                spoken_ack=getattr(pending_plan, "ack", None) or None,
                source="deterministic",
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                plan_mode=getattr(pending_plan, "mode", ""),
            )

        # 3. Active workflow check
        wf = self._workflow.try_resume(request.text, session_id, context=bundle)
        if wf.handled:
            logger.debug("[timing] workflow elapsed=%.0f", (time.monotonic() - started) * 1000)
            logger.info("[ROUTE] source=workflow elapsed_ms=%.0f", (time.monotonic() - started) * 1000)
            if metrics is not None and hasattr(metrics, "increment_router_fire"):
                metrics.increment_router_fire()
            # A successful workflow turn bypasses the intent recognizer, so any
            # pending_file_name_request (e.g. from a prior "open it" → "Which file?")
            # is never consumed. Clear it so it doesn't pollute the next real turn.
            _ds = getattr(self.app, "dialog_state", None)
            if _ds is not None and getattr(_ds, "pending_file_name_request", None):
                _ds.pending_file_name_request = None
            self._curate_memory(request.text, wf.response, bundle, session_id)
            return TurnResponse(
                response=wf.response,
                spoken_ack=None,
                source="workflow",
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                plan_mode="workflow",
            )

        # 5. Intent classification
        with Span(ctx, "intent_classified"):
            intent = self._intent.classify(request.text, ctx=ctx)
        logger.debug("[timing] intent_classified elapsed=%.0f", (time.monotonic() - started) * 1000)

        # 6. Plan construction
        try:
            with Span(ctx, "plan_built"):
                plan = self._planner.plan(request.text, ctx=ctx, intent=intent)
            logger.debug("[timing] plan_built elapsed=%.0f", (time.monotonic() - started) * 1000)
        except Exception as exc:
            logger.exception("[turn_orch] plan() failed: %s", exc)
            return TurnResponse(
                response=f"I ran into a problem planning that: {exc}",
                source="planner",
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                error=str(exc),
            )

        # 6a. Context resolution — Track 1.4 keystone. Runs between plan
        # construction and validation. Rewrites a chat-mode plan into a
        # file capability when the utterance contains an artifact pronoun
        # ("what's in it?" after `read my.txt`). Conservative scope today;
        # later PRs migrate scattered per-handler resolution here.
        try:
            decision = self._resolver.try_rescue(request.text, plan, session_id)
        except Exception as exc:
            logger.debug("[turn_orch] context resolver skipped: %s", exc)
            decision = None
        if decision is not None and decision.applied:
            logger.info("[turn_orch] context resolver rewrite: %s", decision.reason)
            plan = decision.rewrite
        logger.debug("[timing] after_context_resolve elapsed=%.0f", (time.monotonic() - started) * 1000)

        # 6b. Plan validation + repair (Phase 4). Fatal issues short-circuit
        # to a refusal reply; repairable issues are auto-fixed in place.
        with Span(ctx, "plan_validated"):
            plan, validation = self._validate_plan(plan)
        logger.debug("[timing] plan_validated elapsed=%.0f", (time.monotonic() - started) * 1000)
        if validation is not None and not validation.valid:
            reason = validation.first_fatal_message or "plan failed safety validation"
            logger.warning("[turn_orch] plan rejected by validator: %s", reason)
            return TurnResponse(
                response=f"I can't run that: {reason}",
                source="planner",
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                plan_mode="refuse",
            )

        plan_source = self._plan_source(intent, plan)
        logger.info(
            "[ROUTE] source=%s tool=%s mode=%s intent_conf=%.2f elapsed_ms=%.0f",
            plan_source,
            self._primary_tool(plan),
            getattr(plan, "mode", "") or "",
            getattr(intent, "confidence", 0.0) if intent else 0.0,
            (time.monotonic() - started) * 1000,
        )

        # Track 3.1: record the routing decision. Exactly one
        # increment per turn is the contract pinned by
        # `test_single_routing_decision_per_turn`. The increment lives
        # AFTER the plan_source decision so it counts the canonical
        # dispatch (workflow / confirmation paths short-circuit above
        # and call increment_router_fire themselves).
        if metrics is not None and hasattr(metrics, "increment_router_fire"):
            metrics.increment_router_fire()

        # Adaptive Intent Recognition (Phase 1): persist the routing
        # observation. Best-effort — never let learning telemetry break a
        # turn. `confirmed` stays 0 (unknown) here; the confirmation loop
        # (Phase 2) backfills yes/no on a later turn.
        self._record_routing_observation(
            request, session_id, plan_source, plan, intent,
        )

        # Fire ack + progress timers before execution so they reach TTS
        # before the (potentially slow) tool response arrives.
        if on_plan_ready is not None:
            try:
                on_plan_ready(plan)
            except Exception:
                pass

        # 5. Execute
        try:
            with Span(ctx, "tool_executed"):
                response_text = self._execute(plan, request.text)
        except Exception as exc:
            logger.exception("[turn_orch] execute() failed: %s", exc)
            return TurnResponse(
                response=f"I ran into a problem running that: {exc}",
                spoken_ack=getattr(plan, "ack", None) or None,
                source=plan_source,
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                plan_mode=getattr(plan, "mode", ""),
                error=str(exc),
            )

        # Adaptive Intent (Phase 4/5): bump the tool's usage profile after a
        # successful real-tool dispatch — feeds the time-of-day / frequency
        # tie-breaker. Phrase-level learning (note_hit) is captured at source
        # in the broker (lexical / confirmation / learned paths).
        self._bump_intent_profile(plan)

        # 7. Memory curation + response finalization
        with Span(ctx, "response_finalized"):
            self._curate_memory(request.text, response_text, bundle, session_id)
            response = TurnResponse(
                response=response_text,
                spoken_ack=getattr(plan, "ack", None) or None,
                source=plan_source,
                trace_id=trace_id,
                duration_ms=(time.monotonic() - started) * 1000,
                plan_mode=getattr(plan, "mode", ""),
            )
        return response

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_plan(self, plan):
        """Run PlanValidator + PlanRepair against ``plan`` and return
        ``(possibly_repaired_plan, validation_result_or_None)``.

        Returns ``(plan, None)`` when validation is unavailable (test
        harnesses with partial apps) or when the plan mode doesn't need
        validation.
        """
        registry = getattr(self.app, "capability_registry", None)
        if registry is None:
            return plan, None
        try:
            from core.planning.plan_validator import PlanValidator, RunContext  # noqa: PLC0415
            from core.planning.plan_repair import PlanRepair  # noqa: PLC0415
        except Exception:
            return plan, None

        run_ctx = self._build_run_context()
        validator = PlanValidator(registry)
        result = validator.validate(plan, run_ctx)
        if result.valid and not result.issues:
            return plan, result

        # Attempt repair for non-fatal issues. Repair leaves fatal issues
        # untouched; the caller short-circuits on those.
        repair = PlanRepair(registry)
        repaired, remaining = repair.try_repair(plan, result)
        if remaining and any(
            i.severity == "fatal" for i in remaining
        ):
            # Re-validate the repaired plan to surface only the still-fatal
            # set in the returned ValidationResult.
            final = validator.validate(repaired, run_ctx)
            return repaired, final
        return repaired, result

    def _build_run_context(self):
        """Build a RunContext from app.config (best-effort)."""
        from core.planning.plan_validator import RunContext  # noqa: PLC0415
        cfg = getattr(self.app, "config", None)
        scopes: list[str] = []
        if cfg and hasattr(cfg, "get"):
            scopes = list(cfg.get("security.authorized_scopes") or [])
        return RunContext(
            authorized_scopes=scopes,
            user_risk_ceiling="critical",
            requires_authorization=True,
        )

    def _check_pending_confirmation(self, text: str, turn_id: str, session_id: str):
        """Return a ToolPlan if there's a pending online confirmation to resolve.

        Delegates to CapabilityBroker.check_pending_confirmation so the same
        logic handles yes/no in both the v1 (broker.build_plan) and v2 paths.
        Returns None when there is no pending confirmation or the text is not
        a confirmation gesture.
        """
        broker = getattr(self.app, "capability_broker", None)
        if broker is None:
            return None
        try:
            return broker.check_pending_confirmation(text, turn_id)
        except Exception:
            logger.debug("[turn_orch] pending confirmation check failed", exc_info=True)
            return None

    def _build_context_bundle(self, text: str, session_id: str) -> dict:
        # Prefer MemoryService.build_context_bundle when it is available — that
        # surface enriches the broker output with Mem0 facts. Fall back to the
        # bare MemoryBroker on partial app mounts (tests / minimal harnesses).
        if not session_id:
            return {}
        service = getattr(self.app, "memory_service", None)
        if service is not None and hasattr(service, "build_context_bundle"):
            try:
                return service.build_context_bundle(session_id, text) or {}
            except Exception:
                logger.debug("[turn_orch] memory_service bundle build failed", exc_info=True)
        broker = self._memory or getattr(self.app, "memory_broker", None)
        if broker is None:
            return {}
        try:
            return broker.build_context_bundle(text, session_id) or {}
        except Exception:
            logger.debug("[turn_orch] memory bundle build failed", exc_info=True)
            return {}

    def _curate_memory(self, text: str, response: str, bundle: dict, session_id: str) -> None:
        if not session_id:
            return
        delegation = getattr(self.app, "delegation_manager", None)
        curator = getattr(delegation, "memory_curator", None) if delegation else None
        if curator is None:
            return
        persona = (bundle or {}).get("persona") or {}
        try:
            curator.curate(
                session_id=session_id,
                user_text=text,
                assistant_text=response,
                persona_id=persona.get("persona_id", ""),
            )
        except Exception:
            logger.debug("[turn_orch] memory curation failed", exc_info=True)

    def _execute(self, plan, text: str) -> str:
        """Pick the executor exactly like ConversationAgent does, then run.

        Reuses the existing conversation_agent dispatch so the v2 path
        doesn't drift from the v1 selection rule.
        """
        agent = getattr(self.app, "conversation_agent", None)
        if agent is not None and hasattr(agent, "_select_executor"):
            executor = agent._select_executor(plan)
        else:
            executor = self.app.ordered_tool_executor
        return executor.execute(plan, text, turn=None)

    def _record_routing_observation(self, request, session_id, plan_source,
                                     plan, intent) -> None:
        """Persist one routing decision to the IntentLearningStore.

        Best-effort and never raises into the turn path. Stores the tool,
        the routing source, and the intent confidence as the score signal.
        """
        store = getattr(self.app, "intent_learning_store", None)
        if store is None:
            return
        try:
            store.record_observation(
                request.text,
                self._primary_tool(plan),
                plan_source,
                turn_id=getattr(request, "turn_id", "") or "",
                session_id=session_id or "",
                plan_mode=getattr(plan, "mode", "") or "",
                score=getattr(intent, "confidence", 0.0) if intent else 0.0,
            )
        except Exception:
            logger.debug("[turn_orch] routing observation skipped", exc_info=True)

    def _bump_intent_profile(self, plan) -> None:
        """Increment the dispatched tool's usage profile (best-effort).

        Only real tool dispatches count — skip clarify/reply/chat and the
        llm_chat fallback, which aren't capability usage worth biasing toward.
        """
        if getattr(plan, "mode", "") != "tool":
            return
        cfg = getattr(self.app, "config", None)
        if cfg is not None and hasattr(cfg, "get") and not cfg.get("routing.learning_enabled", True):
            return
        tool = self._primary_tool(plan)
        if not tool or tool == "llm_chat":
            return
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "bump_profile"):
            return
        try:
            store.bump_profile(tool)
            # Phase 5: capture the args the tool actually ran with so the
            # favourite-arg defaults can fill 'which app / which browser' later.
            steps = getattr(plan, "steps", None) or []
            args = getattr(steps[0], "args", None) if steps else None
            if args and hasattr(store, "record_args"):
                store.record_args(tool, args)
        except Exception:
            logger.debug("[turn_orch] profile bump skipped", exc_info=True)

    @staticmethod
    def _primary_tool(plan) -> str:
        """The tool a plan dispatches to, for telemetry/learning.

        ToolPlan carries its target in ``steps[0].capability_name`` (there is
        no ``tool_name`` field); clarify/reply/chat plans have no own tool.
        """
        steps = getattr(plan, "steps", None) or []
        if steps:
            return getattr(steps[0], "capability_name", "") or ""
        return getattr(plan, "tool_name", "") or ""

    @staticmethod
    def _plan_source(intent, plan) -> str:
        """Classify where the plan came from for telemetry."""
        origin = getattr(plan, "route_origin", "") or ""
        if origin:
            return origin
        if getattr(plan, "mode", "") in {"reply", "clarify"}:
            return "deterministic"
        if intent is not None and intent.confidence >= HIGH_THRESHOLD:
            return "intent"
        if getattr(plan, "mode", "") == "chat":
            return "chat"
        return "planner"
