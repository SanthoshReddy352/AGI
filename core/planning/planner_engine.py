"""PlannerEngine — turn user text + intent into an executable ToolPlan.

Phase 3 of the v2 architecture (docs/friday_architecture.md §9). Track
3.2c (Consolidation Direction): owns the full plan-construction
pipeline. Previously delegated to `CapabilityBroker.build_plan`; that
method has been deleted and its orchestration logic moved here. The
broker is retained for the per-step helpers it implements
(`_plan_pending_online`, `_plan_actions`, `_find_best_route`,
`_try_propose_online_consent`, etc.) — those are stable utilities, not
worth re-implementing.

The fast path remains: when IntentEngine returned a high-confidence
multi-action result, build the ToolPlan directly from those actions
and skip the broker's re-classification entirely.
"""
from __future__ import annotations

from core.capability_broker import ToolPlan, ToolStep
from core.planning.intent_engine import HIGH_THRESHOLD, IntentResult


class PlannerEngine:
    """v2 planner that produces a `ToolPlan` for a turn."""

    def __init__(self, capability_broker):
        self._broker = capability_broker

    def plan(self, text: str, ctx=None, intent: IntentResult | None = None) -> ToolPlan:
        """Build the plan for a turn.

        Fast path: high-confidence multi-action `intent` → synthesise
        ToolPlan from those actions directly.

        Slow path (Track 3.2c): orchestrate the broker's per-step
        helpers — pending-online check, workflow continuation, intent
        recognizer, deterministic best-route, LLM-planner fallback,
        chat fallback, online-consent proposal, generic clarify.
        Same six-stage pipeline as the deleted `build_plan`; same
        return shapes.
        """
        if intent is not None and intent.confidence >= HIGH_THRESHOLD and intent.actions:
            fast_plan = self._plan_from_intent(intent, text, ctx)
            if fast_plan is not None:
                return fast_plan

        broker = self._broker
        source = self._attr(ctx, "source", "user")
        turn_id = self._attr(ctx, "turn_id", "")
        style_hint = self._attr(ctx, "style_hint", "")
        cleaned_text = broker._clean(text, source=source)
        route_start = broker._now()

        # 1. Pending online confirmation
        pending_plan = broker._plan_pending_online(cleaned_text, turn_id, style_hint)
        if pending_plan:
            broker._record_route_duration(route_start)
            return pending_plan

        # 2. Active workflow continuation
        workflow_result = broker._try_continue_workflow(cleaned_text)
        if workflow_result is not None:
            broker._record_route_duration(route_start)
            return ToolPlan(
                turn_id=turn_id, mode="reply",
                reply=workflow_result, final_style=style_hint,
            )

        # 3. Multi-action plan via IntentRecognizer
        action_plan = broker._plan_actions(cleaned_text)
        if action_plan:
            steps = [broker._action_to_step(a, cleaned_text) for a in action_plan]
            broker._record_route_duration(route_start)
            return ToolPlan(
                turn_id=turn_id, mode="tool", steps=steps,
                ack=broker._ack_for_steps(steps, cleaned_text),
                estimated_latency=broker._estimated_latency(steps),
                final_style=style_hint,
            )

        # 4. Deterministic best-route
        best_route = broker._find_best_route(cleaned_text, min_score=80)
        if best_route and best_route["spec"]["name"] != "llm_chat":
            step = broker._route_to_step(best_route, cleaned_text, {})
            broker._record_route_duration(route_start)
            return ToolPlan(
                turn_id=turn_id, mode="tool", steps=[step],
                ack=broker._ack_for_steps([step], cleaned_text),
                estimated_latency=broker._estimated_latency([step]),
                final_style=style_hint,
            )

        # 4a. Learned-phrase auto-dispatch (Phase 4). A phrasing the user
        # confirmed PROMOTE_AFTER times routes deterministically with
        # source="learned" — the day-by-day adaptation payoff. Exact match,
        # so it runs before the fuzzy lexical layer.
        learned_plan = broker._maybe_learned_dispatch(cleaned_text, turn_id, style_hint)
        if learned_plan is not None:
            broker._record_route_duration(route_start)
            return learned_plan

        # 4b. Fuzzy / lexical layer (Phase 3). Between the deterministic
        # best-route and the LLM planner: rapidfuzz token_set_ratio over
        # catalog + promoted learned phrasings catches STT/typo near-misses
        # cheaply, only on a high-confidence + margin-clearing match.
        lexical_plan = broker._maybe_lexical_route(cleaned_text, turn_id, style_hint)
        if lexical_plan is not None:
            broker._record_route_duration(route_start)
            return lexical_plan

        # 5. LLM planner fallback
        if broker._should_use_planner(cleaned_text):
            broker._record_route_duration(route_start)
            return ToolPlan(
                turn_id=turn_id, mode="planner",
                ack="Let me work that out.",
                estimated_latency="generative",
                final_style=style_hint,
            )

        # 5b. Mid-confidence embedding band → confirmation loop (Phase 2).
        # Before dropping to chat, if the embedding router has a match in the
        # [confirm_low, dispatch_threshold) band, ask "did you mean …?" rather
        # than letting the small chat model fabricate a success. The yes/no
        # answer on the next turn becomes the day-by-day learning signal.
        confirm_plan = broker._maybe_confirm_intent(cleaned_text, turn_id, style_hint)
        if confirm_plan is not None:
            broker._record_route_duration(route_start)
            return confirm_plan

        # 6. Chat fallback
        registry = broker.app.capability_registry
        if registry.has_capability("llm_chat"):
            descriptor = registry.get_descriptor("llm_chat")
            broker._record_route_duration(route_start)
            return ToolPlan(
                turn_id=turn_id, mode="chat",
                ack=broker._chat_ack(cleaned_text),
                steps=[ToolStep(
                    capability_name="llm_chat",
                    args={"query": cleaned_text},
                    raw_text=cleaned_text,
                    side_effect_level=getattr(descriptor, "side_effect_level", "read"),
                    connectivity=getattr(descriptor, "connectivity", "local"),
                    timeout_ms=broker._tool_timeout_ms(),
                )],
                estimated_latency="generative",
                final_style=style_hint,
            )

        # 7. Online-consent rescue (Track 0.1b)
        consent_plan = broker._try_propose_online_consent(cleaned_text, turn_id, style_hint)
        if consent_plan is not None:
            broker._record_route_duration(route_start)
            return consent_plan

        # 8. Generic clarify
        broker._record_route_duration(route_start)
        return ToolPlan(
            turn_id=turn_id, mode="clarify",
            reply="I need a bit more detail before I can do that.",
            final_style=style_hint,
        )

    # ------------------------------------------------------------------
    # Fast-path: build a ToolPlan from a high-confidence IntentResult
    # ------------------------------------------------------------------

    def _plan_from_intent(
        self, intent: IntentResult, text: str, ctx
    ) -> ToolPlan | None:
        """Convert IntentResult.actions → ToolPlan, skipping the broker.

        Returns None if any action references a capability that needs
        consent or is otherwise sensitive — those still flow through the
        broker so the existing safety logic owns them.
        """
        steps: list[ToolStep] = []
        registry = self._capability_registry()
        consent = self._consent_service()

        for idx, action in enumerate(intent.actions):
            tool_name = action.get("tool") or ""
            if not tool_name:
                return None
            descriptor = (
                registry.get_descriptor(tool_name) if registry is not None else None
            )
            # Defer to the broker for anything that needs a confirmation
            # gesture or online consent. Only deterministic, locally-safe
            # paths are eligible for the fast path.
            if descriptor is not None and consent is not None:
                try:
                    decision = consent.evaluate(tool_name, descriptor, text)
                    if getattr(decision, "needs_confirmation", False):
                        return None
                except Exception:
                    return None
            steps.append(
                ToolStep(
                    capability_name=tool_name,
                    args=dict(action.get("args") or {}),
                    raw_text=text,
                    node_id=f"intent{idx}",
                    timeout_ms=self._tool_timeout_ms(),
                )
            )

        if not steps:
            return None

        return ToolPlan(
            turn_id=self._attr(ctx, "turn_id", ""),
            mode="tool",
            steps=steps,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _attr(self, ctx, name, default):
        if ctx is None:
            return default
        return getattr(ctx, name, default) if not isinstance(ctx, dict) else ctx.get(name, default)

    def _context_bundle(self, ctx) -> dict:
        if ctx is None:
            return {}
        bundle = getattr(ctx, "context_bundle", None) if not isinstance(ctx, dict) else ctx.get("context_bundle")
        return dict(bundle or {})

    def _capability_registry(self):
        return getattr(self._broker, "app", None) and getattr(self._broker.app, "capability_registry", None)

    def _consent_service(self):
        app = getattr(self._broker, "app", None)
        return getattr(app, "consent_service", None) if app is not None else None

    def _tool_timeout_ms(self) -> int:
        app = getattr(self._broker, "app", None)
        config = getattr(app, "config", None) if app is not None else None
        if config is not None and hasattr(config, "get"):
            try:
                return int(config.get("routing.tool_timeout_ms", 8000) or 8000)
            except (TypeError, ValueError):
                pass
        return 8000
