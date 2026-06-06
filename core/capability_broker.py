"""CapabilityBroker — convert user intent into a ToolPlan.

Phase 5: No longer depends on CommandRouter for routing decisions.
Uses app.route_scorer (RouteScorer), app.intent_recognizer (IntentRecognizer),
and app.workflow_orchestrator (WorkflowOrchestrator) directly.
CommandRouter is still alive but CapabilityBroker is fully decoupled from it.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field


@dataclass
class ToolStep:
    capability_name: str
    args: dict = field(default_factory=dict)
    raw_text: str = ""
    side_effect_level: str = "read"
    connectivity: str = "local"
    timeout_ms: int = 8000
    parallel_safe: bool = False
    # Phase 4 (v2): DAG metadata used by TaskGraphExecutor.
    # node_id is the identifier other steps reference in `depends_on`.
    # If left blank the executor assigns "step{idx}" at runtime.
    # An empty depends_on means the step has no inputs — it lands in wave 0
    # and runs in parallel with every other unconstrained step.
    node_id: str = ""
    depends_on: list[str] = field(default_factory=list)
    retries: int = 0
    fallback_capability: str = ""


@dataclass
class ToolPlan:
    turn_id: str
    mode: str
    ack: str = ""
    steps: list[ToolStep] = field(default_factory=list)
    requires_confirmation: bool = False
    estimated_latency: str = "interactive"
    final_style: str = ""
    reply: str = ""
    delegation: dict = field(default_factory=dict)
    # Adaptive Intent Phase 4: tags a plan whose tool came from a promoted
    # learned phrasing so telemetry can log source="learned".
    route_origin: str = ""


class CapabilityBroker:
    TOOL_ORIENTED_STARTERS = (
        "open", "launch", "start", "bring up", "run", "execute", "take", "capture",
        "find", "search", "locate", "set", "save", "read", "show", "list", "check",
        "summarize", "summary", "remind", "enable", "disable", "turn", "mute",
        "unmute", "increase", "decrease", "lower", "raise", "pause", "stop", "play",
    )

    def __init__(self, app):
        self.app = app
        self._consent_preapproved = False

    def _memory(self):
        """Return MemoryService when wired (production); fall back to the
        raw ContextStore for ad-hoc test apps. Both surfaces expose the
        pending-online / session-state / log_online_permission methods we
        call below."""
        return getattr(self.app, "memory_service", None) or self.app.context_store

    # Track 3.2c (Consolidation Direction): the orchestration logic that
    # used to live in `build_plan` has been moved to
    # `core/planning/planner_engine.py:PlannerEngine.plan`. The per-step
    # helpers below (`_plan_pending_online`, `_plan_actions`,
    # `_find_best_route`, `_try_propose_online_consent`, etc.) remain on
    # CapabilityBroker because they're stable, well-tested utilities the
    # PlannerEngine composes — re-implementing them here would just be
    # copy-paste with no behavior change.

    def _try_propose_online_consent(self, cleaned_text: str, turn_id: str, style_hint: str):
        registry = getattr(self.app, "capability_registry", None)
        if registry is None:
            return None
        text_tokens = {w for w in re.findall(r"\w+", cleaned_text.lower()) if len(w) > 3}
        if not text_tokens:
            return None
        for descriptor in registry.list_capabilities(connectivity="online"):
            if descriptor.name == "llm_chat":
                continue
            if descriptor.permission_mode != "ask_first":
                continue
            descriptor_text = f"{descriptor.name} {descriptor.description}".lower()
            descriptor_tokens = set(re.findall(r"\w+", descriptor_text))
            if not (text_tokens & descriptor_tokens):
                continue
            step = ToolStep(
                capability_name=descriptor.name,
                args={},
                raw_text=cleaned_text,
                side_effect_level=descriptor.side_effect_level,
                connectivity="online",
            )
            return self._build_online_proposal(step, cleaned_text, turn_id, style_hint)
        return None

    # ------------------------------------------------------------------
    # Phase 5: decoupled routing primitives
    # ------------------------------------------------------------------

    def _try_continue_workflow(self, text: str):
        """Continue an active workflow using WorkflowOrchestrator directly.

        Phase 5: was self.app.router.continue_active_workflow(text).
        Falls back to router method if orchestrator is unavailable.
        """
        orchestrator = getattr(self.app, "workflow_orchestrator", None)
        session_id = getattr(self.app, "session_id", None)
        if orchestrator and session_id:
            try:
                result = orchestrator.continue_active(
                    text, session_id, context={}
                )
                if result and getattr(result, "handled", False):
                    return getattr(result, "response", None)
            except Exception:
                pass
        # Compatibility fallback: router still alive during Phase 5
        router = getattr(self.app, "router", None)
        if router and hasattr(router, "continue_active_workflow"):
            return router.continue_active_workflow(text)
        return None

    def _plan_actions(self, text: str) -> list[dict]:
        """Plan multi-step actions using IntentRecognizer directly.

        Phase 5: was self.app.router.plan_actions(text).
        """
        recognizer = getattr(self.app, "intent_recognizer", None)
        if recognizer:
            try:
                return recognizer.plan(text) or []
            except Exception:
                pass
        # Compatibility fallback
        router = getattr(self.app, "router", None)
        if router and hasattr(router, "plan_actions"):
            return router.plan_actions(text) or []
        return []

    def _find_best_route(self, text: str, min_score: int = 20) -> dict | None:
        """Find the best matching route using RouteScorer directly.

        Phase 5: was self.app.router.find_best_route(text, min_score).
        """
        scorer = getattr(self.app, "route_scorer", None)
        if scorer:
            return scorer.find_best_route(text, min_score=min_score)
        # Compatibility fallback
        router = getattr(self.app, "router", None)
        if router and hasattr(router, "find_best_route"):
            return router.find_best_route(text, min_score=min_score)
        return None

    # ------------------------------------------------------------------
    # Pending-online state management
    # ------------------------------------------------------------------

    # Batch 5 / Issue 8 confirmation-bleed: pending_online entries auto-
    # expire after this many seconds. If the user takes longer than this
    # before answering, a "yes" must NOT resolve a stale online proposal
    # — typical breakage was "yes" being applied to the wrong workflow
    # because the file workflow had advanced in the meantime.
    _PENDING_ONLINE_TTL_S = 60.0

    def _plan_pending_online(self, cleaned_text: str, turn_id: str, style_hint: str):
        session_state = self._memory().get_session_state(self.app.session_id) or {}
        pending = dict(session_state.get("pending_online") or {})
        # Drop expired entries before evaluating yes/no — protects against
        # confirmation cross-talk where "yes" to an unrelated later
        # prompt would resurrect a long-stale online tool.
        if pending and self._is_pending_expired(pending):
            self._memory().clear_pending_online(self.app.session_id)
            pending = {}
        if self.app.consent_service.is_negative_confirmation(cleaned_text) and pending:
            self._memory().log_online_permission(self.app.session_id, pending.get("tool_name", ""), "declined", reason="user_confirmation")
            self._memory().clear_pending_online(self.app.session_id)
            return ToolPlan(
                turn_id=turn_id,
                mode="clarify",
                reply="Okay. I'll stay offline unless you want me to use an online skill.",
                final_style=style_hint,
            )
        if not self.app.consent_service.is_positive_confirmation(cleaned_text):
            return None
        if not pending:
            return None
        tool_name = pending.get("tool_name", "")
        descriptor = self.app.capability_registry.get_descriptor(tool_name) if tool_name else None
        # Port #3: voice-approval safety gate — destructive actions cannot be
        # approved by voice to prevent misheard "yes" from triggering harm.
        gate = self.app.consent_service.gate_voice_approval(
            tool_name, descriptor, stt_confidence=1.0
        )
        if gate.needs_confirmation:
            return ToolPlan(
                turn_id=turn_id,
                mode="clarify",
                reply=gate.prompt,
                final_style=style_hint,
            )
        self._memory().log_online_permission(self.app.session_id, tool_name, "approved", reason="user_confirmation")
        # Track 4.2: cache the approval on the consent service so the next
        # turn that uses the same tool silent-allows instead of re-prompting.
        try:
            self.app.consent_service.mark_approved(tool_name)
        except Exception:
            pass
        if descriptor is not None:
            self._memory().clear_pending_online(self.app.session_id)
            return ToolPlan(
                turn_id=turn_id,
                mode="tool",
                ack=pending.get("ack") or "",
                steps=[ToolStep(
                    capability_name=tool_name,
                    args=dict(pending.get("args") or {}),
                    raw_text=pending.get("text", cleaned_text),
                    side_effect_level=descriptor.side_effect_level,
                    connectivity=descriptor.connectivity,
                    timeout_ms=self._tool_timeout_ms(),
                )],
                estimated_latency=descriptor.latency_class,
                final_style=style_hint,
            )
        # No specific online tool was captured — re-route the *original*
        # request text with consent pre-approved so the online detection
        # step in build_plan() won't re-prompt.
        self._memory().clear_pending_online(self.app.session_id)
        original_text = (pending.get("text") or "").strip()
        if original_text:
            self._consent_preapproved = True
            try:
                return self.build_plan(original_text, turn_id, style_hint=style_hint)
            finally:
                self._consent_preapproved = False
        return None

    # ------------------------------------------------------------------
    # Step builders
    # ------------------------------------------------------------------

    def _action_to_step(self, action: dict, fallback_text: str) -> ToolStep:
        # Old router format: {"route": {...}, "args": {...}, "text": "..."}
        # New IntentRecognizer format: {"tool": "...", "args": {...}, "text": "..."}
        if "route" in action:
            route = action["route"]
        else:
            tool_name = action.get("tool", "")
            route = self._find_best_route(tool_name, min_score=0)
            if route is None:
                # Build a minimal route from the tool name
                route = {"spec": {"name": tool_name}, "callback": None, "score": 0}
        return self._route_to_step(route, action.get("text", fallback_text), dict(action.get("args", {})))

    def _route_to_step(self, route: dict, raw_text: str, args: dict) -> ToolStep:
        name = route["spec"]["name"]
        descriptor = self.app.capability_registry.get_descriptor(name)
        return ToolStep(
            capability_name=name,
            args=dict(args or {}),
            raw_text=raw_text,
            side_effect_level=getattr(descriptor, "side_effect_level", "read"),
            connectivity=getattr(descriptor, "connectivity", "local"),
            timeout_ms=self._tool_timeout_ms(),
        )

    def _first_online_confirmation_needed(self, steps: list[ToolStep], text: str):
        for step in steps:
            descriptor = self.app.capability_registry.get_descriptor(step.capability_name)
            if self.app.consent_service.evaluate(step.capability_name, descriptor, text).needs_confirmation:
                return step
        return None

    def check_pending_confirmation(self, text: str, turn_id: str, style_hint: str = "") -> "ToolPlan | None":
        """Public wrapper — used by v2 TurnOrchestrator to handle a pending
        yes/no before routing. Online-consent prompts take precedence over a
        mid-band intent confirmation (the online one is more consequential)."""
        online = self._plan_pending_online(text, turn_id, style_hint)
        if online is not None:
            return online
        return self._plan_pending_intent(text, turn_id, style_hint)

    # ------------------------------------------------------------------
    # Adaptive Intent Recognition Phase 4 — learned-phrase auto-dispatch
    # ------------------------------------------------------------------

    def _maybe_learned_dispatch(self, cleaned_text: str, turn_id: str, style_hint: str):
        """Auto-dispatch a phrasing the user confirmed PROMOTE_AFTER times.

        Exact (normalized-key) lookup against promoted learned phrasings —
        the highest-precision learned path, treated like a deterministic
        match (`route_origin="learned"`). Runs before the fuzzy lexical layer.
        """
        if not self._learning_enabled():
            return None
        if not self._config_get("routing.learned_dispatch_enabled", True):
            return None
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "promoted_lookup"):
            return None
        try:
            row = store.promoted_lookup(cleaned_text)
        except Exception:
            return None
        if not row:
            return None
        tool_name = row.get("tool", "")
        descriptor = self.app.capability_registry.get_descriptor(tool_name) if tool_name else None
        if descriptor is None:
            return None
        step = ToolStep(
            capability_name=tool_name, args=self._apply_arg_defaults(tool_name, {}),
            raw_text=cleaned_text,
            side_effect_level=descriptor.side_effect_level,
            connectivity=descriptor.connectivity,
            timeout_ms=self._tool_timeout_ms(),
        )
        self._note_intent_hit(cleaned_text, tool_name)  # reinforce last_used
        return ToolPlan(
            turn_id=turn_id, mode="tool", steps=[step],
            ack=self._ack_for_steps([step], cleaned_text),
            estimated_latency=self._estimated_latency([step]),
            final_style=style_hint, route_origin="learned",
        )

    # ------------------------------------------------------------------
    # Adaptive Intent Recognition Phase 3 — fuzzy / lexical layer
    # ------------------------------------------------------------------

    def _maybe_lexical_route(self, cleaned_text: str, turn_id: str, style_hint: str):
        """Dispatch via the fuzzy lexical router on a high-confidence match.

        Sits between the deterministic best-route and the LLM planner: it
        rescues STT/typo near-misses cheaply. Returns a tool ToolPlan or None.
        Promoted learned phrasings (Phase 4) are fed in as extra index entries.
        """
        if not self._config_get("routing.lexical_enabled", True):
            return None
        router = getattr(self.app, "router", None)
        lex = getattr(router, "lexical_router", None) if router else None
        if lex is None or not hasattr(lex, "route"):
            return None
        try:
            tools = getattr(router, "_tools_by_name", None)
            if tools:
                lex.build_index(tools, extra_phrases=self._promoted_phrase_pairs())
            match = lex.route(cleaned_text)
        except Exception:
            return None
        if not match:
            return None
        tool_name = match["tool"]
        descriptor = self.app.capability_registry.get_descriptor(tool_name)
        if descriptor is None:
            return None
        step = ToolStep(
            capability_name=tool_name, args={}, raw_text=cleaned_text,
            side_effect_level=descriptor.side_effect_level,
            connectivity=descriptor.connectivity,
            timeout_ms=self._tool_timeout_ms(),
        )
        # Phase 4 capture-at-source: a fuzzy near-miss is a learnable signal —
        # accrue a hit so a repeatedly-used phrasing promotes to exact dispatch.
        self._note_intent_hit(cleaned_text, tool_name)
        return ToolPlan(
            turn_id=turn_id, mode="tool", steps=[step],
            ack=self._ack_for_steps([step], cleaned_text),
            estimated_latency=self._estimated_latency([step]),
            final_style=style_hint, route_origin="lexical",
        )

    def _promoted_phrase_pairs(self) -> list[tuple[str, str]]:
        """(raw_phrase, tool) for promoted learned phrasings — Phase 4 hook."""
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "promoted_phrases"):
            return []
        try:
            return [(p.get("raw") or p.get("normalized") or "", p["tool"])
                    for p in store.promoted_phrases() if p.get("tool")]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Adaptive Intent Recognition Phase 2 — mid-band confirmation loop
    # ------------------------------------------------------------------

    # Same TTL as pending_online: a stale "did you mean …?" must not be
    # resolved by a much-later "yes" aimed at something else.
    _PENDING_INTENT_TTL_S = 60.0

    def _maybe_confirm_intent(self, cleaned_text: str, turn_id: str, style_hint: str):
        """If the embedding router has a mid-band match, propose a confirmation.

        Returns a clarify ToolPlan ("Did you mean to …?") or None. Called by
        PlannerEngine just before the chat fallback, so we only ask when no
        deterministic / high-confidence path claimed the turn.
        """
        if not self._config_get("routing.intent_confirmation_enabled", True):
            return None
        router = getattr(self.app, "router", None)
        embed = getattr(router, "embedding_router", None) if router else None
        if embed is None or not hasattr(embed, "confirm_candidate"):
            return None
        try:
            tools = getattr(router, "_tools_by_name", None)
            if tools:
                embed.build_index(tools)
            candidate = embed.confirm_candidate(cleaned_text)
        except Exception:
            return None
        if not candidate:
            return None
        return self._propose_intent_confirmation(
            candidate["tool"], cleaned_text, turn_id, style_hint, candidate["score"]
        )

    def _propose_intent_confirmation(self, tool_name: str, text: str, turn_id: str,
                                     style_hint: str, score: float) -> ToolPlan:
        from datetime import datetime  # noqa: PLC0415
        self._memory().set_pending_intent(
            self.app.session_id,
            {
                "tool_name": tool_name,
                "text": text,
                "score": float(score),
                "proposed_at": datetime.now().isoformat(),
                "turn_id": turn_id,
            },
        )
        return ToolPlan(
            turn_id=turn_id,
            mode="clarify",
            reply=self._intent_confirm_question(tool_name),
            requires_confirmation=True,
            final_style=style_hint,
        )

    def _intent_confirm_question(self, tool_name: str) -> str:
        """Short 'did you mean …?' prompt, preferring the catalog summary."""
        summary = ""
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
            entry = catalog.entry_for(tool_name) if catalog else None
            summary = (entry.summary if entry else "") or ""
        except Exception:
            summary = ""
        label = summary.strip().rstrip(".") if summary else tool_name.replace("_", " ")
        return f"Did you want me to {label[0].lower() + label[1:]}? Say yes or no."

    def _plan_pending_intent(self, cleaned_text: str, turn_id: str, style_hint: str):
        """Resolve a pending mid-band confirmation with the user's yes/no.

        Yes → dispatch the tool *and* record the confirmed phrasing→tool hit
        (the learning signal Phase 4 promotes on). No → record a correction so
        the pairing is demoted/blocked, never re-suggested.
        """
        state = self._memory().get_session_state(self.app.session_id) or {}
        pending = dict(state.get("pending_intent") or {})
        if pending and self._is_pending_expired(pending):
            self._memory().clear_pending_intent(self.app.session_id)
            pending = {}
        if not pending:
            return None
        tool_name = pending.get("tool_name", "")
        original_text = pending.get("text", "") or cleaned_text
        if self.app.consent_service.is_negative_confirmation(cleaned_text):
            self._note_intent_correction(original_text, tool_name)
            self._memory().clear_pending_intent(self.app.session_id)
            return ToolPlan(
                turn_id=turn_id, mode="clarify",
                reply="Okay, never mind. Try rephrasing and I'll have another go.",
                final_style=style_hint,
            )
        if not self.app.consent_service.is_positive_confirmation(cleaned_text):
            return None
        self._memory().clear_pending_intent(self.app.session_id)
        descriptor = self.app.capability_registry.get_descriptor(tool_name) if tool_name else None
        if descriptor is None:
            return None
        self._note_intent_hit(original_text, tool_name)
        return ToolPlan(
            turn_id=turn_id, mode="tool",
            ack=tool_name.replace("_", " "),
            steps=[ToolStep(
                capability_name=tool_name,
                args={},
                raw_text=original_text,
                side_effect_level=descriptor.side_effect_level,
                connectivity=descriptor.connectivity,
                timeout_ms=self._tool_timeout_ms(),
            )],
            estimated_latency=getattr(descriptor, "latency_class", "interactive"),
            final_style=style_hint,
        )

    def _learning_enabled(self) -> bool:
        """Master privacy switch — when false, no learning is captured or used."""
        return bool(self._config_get("routing.learning_enabled", True))

    def _note_intent_hit(self, text: str, tool_name: str) -> None:
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not tool_name or not self._learning_enabled():
            return
        try:
            store.note_hit(text, tool_name)
            store.bump_profile(tool_name)
        except Exception:
            pass

    def _note_intent_correction(self, text: str, tool_name: str) -> None:
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not tool_name:
            return
        try:
            store.note_correction(text, tool_name)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Adaptive Intent Phase 5 — favourite-arg defaults
    # ------------------------------------------------------------------

    # Only "which X" preference args are auto-filled — never content args
    # (query/topic/text), so we never replay a stale song or search term.
    _PREF_ARG_KEYS = frozenset({"app", "browser", "player", "service",
                                "provider", "engine", "device"})

    def _apply_arg_defaults(self, tool_name: str, args: dict) -> dict:
        """Fill *missing* preference-style args from the user's favourites.

        Tie-breaker-grade biasing: only keys absent from ``args`` and on the
        preference safelist are filled, so a confident explicit arg always wins.
        """
        if not self._learning_enabled():
            return args
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "favorite_args"):
            return args
        try:
            favs = store.favorite_args(tool_name)
        except Exception:
            return args
        merged = dict(args or {})
        for key, value in favs.items():
            if key in self._PREF_ARG_KEYS and key not in merged:
                merged[key] = value
        return merged

    def _is_pending_expired(self, pending: dict) -> bool:
        """Return True iff the pending_online entry has crossed its TTL.

        Missing ``proposed_at`` is treated as fresh — legacy entries
        written before the TTL was introduced still resolve once, after
        which any further user input will populate the new timestamp.
        """
        proposed_at = pending.get("proposed_at")
        if not proposed_at:
            return False
        try:
            from datetime import datetime  # noqa: PLC0415
            ts = datetime.fromisoformat(proposed_at)
            age_s = (datetime.now() - ts).total_seconds()
        except Exception:
            return False
        return age_s > self._PENDING_ONLINE_TTL_S

    def _build_online_proposal(self, step: ToolStep, text: str, turn_id: str, style_hint: str) -> ToolPlan:
        from datetime import datetime  # noqa: PLC0415
        slot_signature = f"{step.capability_name}|{sorted((step.args or {}).items())!r}"
        self._memory().set_pending_online(
            self.app.session_id,
            {
                "tool_name": step.capability_name,
                "args": dict(step.args or {}),
                "text": step.raw_text or text,
                "ack": step.capability_name.replace("_", " "),
                # Batch 5 / Issue 8 confirmation-bleed: timestamp + slot
                # signature lets _plan_pending_online drop entries the
                # user wandered away from before answering yes/no.
                "proposed_at": datetime.now().isoformat(),
                "slot_signature": slot_signature,
                "turn_id": turn_id,
            },
        )
        reply = self._short_consent_question(step.capability_name, dict(step.args or {}))
        return ToolPlan(
            turn_id=turn_id,
            mode="clarify",
            reply=reply,
            requires_confirmation=True,
            final_style=style_hint,
        )

    def _short_consent_question(self, tool_name: str, args: dict) -> str:
        """Generate a short yes/no consent question instead of reading the full description."""
        # Tool-specific short labels with key arg substituted where available
        topic = (args.get("topic") or args.get("query") or args.get("search") or "").strip()
        if tool_name == "research_topic":
            subject = f" '{topic}'" if topic else ""
            return f"Research{subject} online? Say yes or no."
        if tool_name in {"play_youtube", "play_youtube_music"}:
            subject = f" '{topic}'" if topic else ""
            return f"Play{subject} online? Say yes or no."
        if tool_name.startswith("weather"):
            return "Check the weather online? Say yes or no."
        if "search" in tool_name or "web" in tool_name:
            subject = f" '{topic}'" if topic else ""
            return f"Search{subject} online? Say yes or no."
        label = tool_name.replace("_", " ")
        return f"Go online for {label}? Say yes or no."

    # ------------------------------------------------------------------
    # Ack / latency helpers
    # ------------------------------------------------------------------

    def _ack_for_steps(self, steps: list[ToolStep], user_text: str = "") -> str:
        if not steps:
            return ""
        if len(steps) > 1:
            return "On it."
        step = steps[0]
        descriptor = self.app.capability_registry.get_descriptor(step.capability_name)
        latency = getattr(descriptor, "latency_class", step.timeout_ms)
        if step.capability_name == "llm_chat":
            return self._chat_ack(step.raw_text or user_text)
        # Phase 9: contextual ack via DialogueManager
        dialogue_manager = getattr(self.app, "dialogue_manager", None)
        if dialogue_manager and (step.connectivity == "online" or latency in {"slow", "generative", "background"}):
            ack = dialogue_manager._ack_from_text(user_text or step.raw_text)
            if ack:
                return ack
        if step.connectivity == "online":
            return "On it."
        if latency in {"slow", "generative", "background"}:
            return "One moment."
        return ""

    def _chat_ack(self, text: str) -> str:
        return ""

    def _estimated_latency(self, steps: list[ToolStep]) -> str:
        classes = []
        for step in steps:
            descriptor = self.app.capability_registry.get_descriptor(step.capability_name)
            classes.append(getattr(descriptor, "latency_class", "interactive"))
        if "generative" in classes:
            return "generative"
        if "slow" in classes or len(steps) > 1:
            return "slow"
        return "interactive"

    def _should_use_planner(self, text: str) -> bool:
        router = getattr(self.app, "router", None)
        if not getattr(router, "enable_llm_tool_routing", False):
            return False
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        return normalized.startswith(self.TOOL_ORIENTED_STARTERS)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _clean(self, text: str, source: str = "user") -> str:
        assistant_context = getattr(self.app, "assistant_context", None)
        if assistant_context and hasattr(assistant_context, "clean_user_text"):
            cleaned = assistant_context.clean_user_text(text, source=source)
            if cleaned:
                return cleaned
        return text

    def _record_route_duration(self, started_at: float) -> None:
        feedback = getattr(self.app, "turn_feedback", None)
        active_turn = getattr(self.app, "_active_turn_record", None)
        if feedback and active_turn:
            active_turn.metrics["route_duration_ms"] = round((self._now() - started_at) * 1000, 1)

    def _tool_timeout_ms(self) -> int:
        return int(self._config_get("routing.tool_timeout_ms", 8000) or 8000)

    def _config_get(self, key, default=None):
        config = getattr(self.app, "config", None)
        if config and hasattr(config, "get"):
            return config.get(key, default)
        return default

    def _now(self) -> float:
        return time.monotonic()
