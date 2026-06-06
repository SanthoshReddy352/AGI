import difflib
import re
from dataclasses import dataclass, field

from core.logger import logger


# Words that indicate the user wants to abandon the active workflow.
# Matched fuzzily to catch common typos ("cancle", "canecl", etc.).
_WORKFLOW_CANCEL_TOKENS = frozenset({
    "cancel", "abort", "nevermind", "stop", "quit", "exit", "halt", "drop",
})
_WORKFLOW_CANCEL_FILLER = frozenset({
    "that", "it", "please", "the", "this", "a", "ok", "okay", "mind",
    "friday", "hey",
})


def _is_workflow_cancel(text: str) -> bool:
    """Return True when *text* is a bare cancellation command with no substantive follow-up."""
    normalized = re.sub(r"[^a-z\s]", "", (text or "").strip().lower())
    words = normalized.split()
    meaningful = [w for w in words if w not in _WORKFLOW_CANCEL_FILLER]
    if not meaningful:
        return False
    for word in meaningful:
        if word in _WORKFLOW_CANCEL_TOKENS:
            return True
        # fuzzy match for typos like "cancle" → "cancel" (ratio ≥ 0.82)
        if difflib.get_close_matches(word, _WORKFLOW_CANCEL_TOKENS, n=1, cutoff=0.82):
            return True
    return False


# Track 5.2d-retire: the yes/no parsers + their token sets (Issue 4's
# write-confirmation + dictate-or-generate slots) moved to
# `modules/system_control/file_workflow_helpers.py` along with the rest
# of the FileWorkflow dispatcher.

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - optional dependency
    END = "__end__"
    StateGraph = None


@dataclass
class WorkflowResult:
    handled: bool
    response: str = ""
    workflow_name: str = ""
    state: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class BaseWorkflow:
    name = ""

    def __init__(self, app):
        self.app = app
        self._compiled_graph = None

    def _memory(self):
        """Return MemoryService when wired (production); fall back to the
        raw ContextStore for tests that mount workflows on partial apps."""
        return getattr(self.app, "memory_service", None) or self.app.context_store

    def should_start(self, user_text, context=None):
        return False

    def can_continue(self, user_text, state, context=None):
        return bool(state)

    def run(self, user_text, session_id, context=None):
        initial_state = {
            "user_text": user_text,
            "session_id": session_id,
            "context": dict(context or {}),
            "result": WorkflowResult(handled=False, workflow_name=self.name),
        }
        if StateGraph is None:
            return self._handle(initial_state)["result"]

        if self._compiled_graph is None:
            graph = StateGraph(dict)
            graph.add_node("handle", self._handle)
            graph.set_entry_point("handle")
            graph.add_edge("handle", END)
            self._compiled_graph = graph.compile()

        final_state = self._compiled_graph.invoke(initial_state)
        return final_state["result"]

    def _handle(self, state):
        raise NotImplementedError


class FileWorkflow(BaseWorkflow):
    """Track 5.2d-retire: thin delegation shim around
    :mod:`modules.system_control.file_workflow_helpers`.

    The original 230-line slot-machine + dispatcher was relocated:
    helpers + regex live in the module; this class survives only as
    the dispatch hook ``WorkflowOrchestrator.continue_active`` looks up
    by ``name = "file_workflow"``. ``can_continue`` and ``_handle``
    are 4-line forwards. The Issue 10 mid-flow target-switch regex
    is now in the helpers module AND exposed as the
    ``detect_new_filename`` capability that backs the YAML template's
    ``cancel_when:`` predicate.
    """

    name = "file_workflow"

    def can_continue(self, user_text, state, context=None):
        from modules.system_control.file_workflow_helpers import (  # noqa: PLC0415
            can_continue_file_workflow,
        )
        return can_continue_file_workflow(user_text, state)

    def _handle(self, state):
        # Track 5.2d-retire: full body relocated to
        # ``modules.system_control.file_workflow_helpers.handle_file_workflow_turn``.
        # Kept as a tiny dispatcher so the orchestrator's per-workflow
        # call surface is unchanged.
        from modules.system_control.file_workflow_helpers import (  # noqa: PLC0415
            handle_file_workflow_turn,
        )
        outcome = handle_file_workflow_turn(
            self.app, state["user_text"], state["session_id"],
        )
        state["result"] = WorkflowResult(
            handled=outcome["handled"],
            workflow_name=self.name,
            response=outcome["response"],
            state=outcome["state"],
        )
        return state


class BrowserMediaWorkflow(BaseWorkflow):
    """Track 5.2d-retire: thin delegation shim around
    :mod:`modules.browser_automation.media_helpers`.

    The original 280-line passive dispatcher (boundary check +
    intent parser + service dispatch) was relocated: helpers + regex
    live in the module; this class survives only as the dispatch hook
    ``WorkflowOrchestrator.continue_active`` looks up by
    ``name = "browser_media"``. Both ``should_start`` / ``can_continue``
    / ``_handle`` are 4-line forwards. The boundary check is also
    exposed as the ``detect_media_command`` capability, and the intent
    parser + service dispatcher as ``browser_media_dispatch``.
    """

    name = "browser_media"

    def should_start(self, user_text, context=None):
        lower_text = (user_text or "").lower()
        return "youtube" in lower_text or "youtube music" in lower_text

    def can_continue(self, user_text, state, context=None):
        from modules.browser_automation.media_helpers import (  # noqa: PLC0415
            is_likely_media_command,
        )
        lower_text = (user_text or "").lower().strip()
        if self.should_start(user_text, context=context):
            return True
        return is_likely_media_command(lower_text)

    def _handle(self, state):
        from modules.browser_automation.media_helpers import (  # noqa: PLC0415
            dispatch_media_intent,
            parse_media_intent,
        )
        user_text = state["user_text"]
        session_id = state["session_id"]
        context = dict(state.get("context") or {})
        workflow_state = (
            self._memory().get_active_workflow(session_id, workflow_name=self.name)
            or {}
        )
        intent = parse_media_intent(user_text, workflow_state, context)
        if not intent:
            state["result"] = WorkflowResult(
                handled=False, workflow_name=self.name, state=workflow_state,
            )
            return state

        service = getattr(self.app, "browser_media_service", None)
        response = dispatch_media_intent(service, intent)

        updated_state = {
            "status": "active",
            "pending_slots": [],
            "last_action": intent.get("action", ""),
            "target": {
                "browser_name": intent.get("browser_name", "chrome"),
                "platform": intent.get("platform", "youtube"),
                "query": intent.get("query", ""),
            },
            "result_summary": response,
            "browser_name": intent.get("browser_name", "chrome"),
            "platform": intent.get("platform", "youtube"),
            "query": intent.get("query", ""),
        }
        if service is not None:
            self._memory().save_workflow_state(session_id, self.name, updated_state)
        state["result"] = WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response=response,
            state=updated_state,
            metadata=intent,
        )
        return state


# launch-hardening §5.4 Step 3: ReminderWorkflow (the delegation shim that
# forwarded every reminder follow-up turn to TaskManagerPlugin.handle_reminder_followup)
# was retired. The reminder slot-fill is now the declarative `set_reminder` YAML
# template: TaskManagerPlugin.handle_set_reminder starts it via
# WorkflowOrchestrator.start_template_slot_fill, and follow-up turns resume
# through TemplateWorkflow.run_slot_fill_turn via continue_active — the same path
# every other template uses. CalendarEventWorkflow (below) is intentionally NOT
# retired: it drives the Google-Calendar path (WorkspaceAgent._handle_create_event),
# a different backend than the local create_calendar_event template.


class CalendarEventWorkflow(BaseWorkflow):
    """Track 5.2b-deferred: reclassified as a permanent delegation shim.

    Audit found this class is a 48-line delegation shim: the real
    slot-fill state machine lives in
    ``WorkspaceAgent._handle_create_event``, which interleaves natural-
    language datetime parsing with summary capture. The same
    architectural reasoning as :class:`ReminderWorkflow` applies — the
    class survives as a dispatch hook for
    ``WorkflowOrchestrator.continue_active``; the workflow itself is
    not templatable without unwinding the domain handler.
    """

    name = "calendar_event_workflow"

    def can_continue(self, user_text, state, context=None):
        if not state:
            return False
        return state.get("workflow_name") == self.name and bool(state.get("pending_slots"))

    def _handle(self, state):
        user_text = state["user_text"]
        session_id = state["session_id"]
        workflow_state = self._memory().get_active_workflow(session_id, workflow_name=self.name) or {}

        ext = self._get_workspace_extension()
        if ext is None:
            state["result"] = WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response="Calendar event creation requires the workspace agent to be loaded.",
            )
            return state

        pending_slots = list(workflow_state.get("pending_slots") or [])
        saved_summary = workflow_state.get("summary", "")
        description = workflow_state.get("description", "")

        # Inject the saved summary so the handler doesn't ask for it again.
        args = {}
        if "start_dt" in pending_slots and saved_summary:
            args = {"summary": saved_summary, "description": description}

        response = ext._handle_create_event(user_text, args)
        updated = self._memory().get_active_workflow(session_id, workflow_name=self.name) or {}
        state["result"] = WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response=response,
            state=updated,
        )
        return state

    def _get_workspace_extension(self):
        loader = getattr(self.app, "extension_loader", None)
        if loader is None:
            return None
        return loader.get_extension("WorkspaceAgent")


class TemplateWorkflow(BaseWorkflow):
    """BaseWorkflow adapter for a single YAML workflow template.

    Templates are not voice-text-triggered; they're invoked explicitly by
    the planner (Phase 3) after intent + workflow-selection prompts pick
    one by name. ``should_start()`` therefore always returns False —
    matching the v2 design where dispatch is plan-driven, not pattern-driven.

    Execution path: compile template + slots into a ToolPlan, hand the
    plan to TaskGraphExecutor (or OrderedToolExecutor on single-step or
    when DAG execution is disabled).
    """

    def __init__(self, app, template, compiler):
        super().__init__(app)
        self._template = template
        self._compiler = compiler
        self.name = template.workflow_name

    @property
    def template(self):
        return self._template

    def should_start(self, user_text, context=None):
        return False

    def can_continue(self, user_text, state, context=None):
        if not state:
            return False
        if state.get("workflow_name") != self.name:
            return False
        if state.get("status") == "completed":
            return False
        # Track 5.2a: an in-flight slot-fill workflow continues whenever it
        # has an `awaiting_slot` marker (the next turn fills that slot).
        return bool(state.get("awaiting_slot")) or bool(state.get("pending_slots"))

    def run(self, user_text, session_id, context=None):
        # Track 5.2a: if the workflow is parked on a slot-fill question,
        # route this turn through the slot-fill resume path. Falls back
        # to the BaseWorkflow.run for non-slot-fill templates so the
        # existing run_with_slots / run_with_replanning paths stay intact.
        state = self._memory().get_active_workflow(
            session_id, workflow_name=self.name,
        ) or {}
        if state.get("awaiting_slot"):
            return self.run_slot_fill_turn(user_text, session_id)
        return super().run(user_text, session_id, context=context)

    def compile_with_slots(self, slots, *, turn_id: str = "", ack: str = ""):
        """Return a CompiledPlan (caller can inspect missing_slots before exec)."""
        return self._compiler.compile(self._template, slots, turn_id=turn_id, ack=ack)

    def run_with_slots(self, slots, session_id, *, turn_id: str = "", user_text: str = ""):
        """Compile + execute. Returns a WorkflowResult."""
        compiled = self.compile_with_slots(slots, turn_id=turn_id)
        if compiled.missing_slots:
            return WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response=compiled.plan.reply,
                state={"missing_slots": compiled.missing_slots},
            )
        executor = self._select_executor(compiled.plan)
        response = executor.execute(compiled.plan, user_text or "", turn=None)
        return WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response=str(response or ""),
            state={"slots": compiled.resolved_slots},
        )

    def run_with_replanning(
        self,
        slots,
        session_id,
        *,
        turn_id: str = "",
        user_text: str = "",
        replan_controller=None,
    ):
        """Step-at-a-time execution with bounded observation-driven replanning.

        Unlike :meth:`run_with_slots`, this iterates steps in topological
        order and consults :class:`core.planning.replan_controller.ReplanController`
        after each one. Decisions: continue → next step, retry → rerun with
        adjusted args, ask_user → halt + report question, stop/refuse →
        halt + report reason.

        Falls back to the one-shot path when no replan_controller is
        available, preserving existing behavior.
        """
        compiled = self.compile_with_slots(slots, turn_id=turn_id)
        if compiled.missing_slots:
            return WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response=compiled.plan.reply,
                state={"missing_slots": compiled.missing_slots},
            )

        controller = replan_controller or getattr(self.app, "replan_controller", None)
        if controller is None:
            return self.run_with_slots(
                slots, session_id, turn_id=turn_id, user_text=user_text,
            )

        from core.capability_broker import ToolPlan as _ToolPlan  # noqa: PLC0415
        from core.planning.replan_controller import WorkflowRunState  # noqa: PLC0415
        from core.task_graph_executor import _Node, topological_waves  # noqa: PLC0415
        from core.turn_context import current_turn  # noqa: PLC0415

        steps = list(compiled.plan.steps or [])
        # Build a stable, dependency-respecting ordering. Within a wave the
        # order is arbitrary but we serialize them so replanning is sane.
        nodes = [
            _Node(step=s, node_id=s.node_id or f"step{i}",
                  depends_on=list(s.depends_on or []),
                  retries=s.retries, input_index=i)
            for i, s in enumerate(steps)
        ]
        try:
            waves = topological_waves(nodes)
        except ValueError as exc:
            return WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response=f"I can't run that — the plan has a dependency cycle: {exc}",
                state={"slots": compiled.resolved_slots, "failed": True},
            )
        ordered_steps = [n.step for wave in waves for n in wave]

        run_state = WorkflowRunState(workflow_name=self.name)
        responses: list[str] = []
        final_decision = "continue"
        final_reason = ""
        executor = self.app.ordered_tool_executor

        # Phase 7: source / channel detection for approval + progress.
        from core.turn_context import current_turn as _ct  # noqa: PLC0415
        ctx = _ct() if _ct else None
        turn_source = (getattr(ctx, "source", "") if ctx else "") or ""
        comms = getattr(self.app, "comms", None)
        consent_service = getattr(self.app, "consent_service", None)
        # Resolve the capability registry once for descriptor lookups.
        registry = getattr(self.app, "capability_registry", None)

        total_steps = len(ordered_steps)
        for step_index, step in enumerate(ordered_steps):
            attempt_args = dict(step.args or {})
            attempts_done = 0

            # Phase 7: security approval gate. Fires only when the
            # capability explicitly opts in (requires_authorization=True or
            # side_effect in {write,critical} or network_scope=public).
            descriptor = (
                registry.get_descriptor(step.capability_name) if registry else None
            )
            approval_outcome = self._gate_step_approval(
                descriptor=descriptor,
                consent_service=consent_service,
                comms=comms,
                turn_source=turn_source,
            )
            if approval_outcome == "deny":
                final_decision = "refuse"
                final_reason = f"approval denied for {step.node_id!r}"
                responses.append(f"Cancelled: {final_reason}.")
                break
            if approval_outcome == "timeout":
                final_decision = "stop"
                final_reason = f"approval timed out for {step.node_id!r}"
                responses.append(f"Cancelled: {final_reason}.")
                break

            while True:
                run_state.total_steps += 1
                step.args = attempt_args     # apply current attempt's args
                single_plan = _ToolPlan(
                    turn_id=compiled.plan.turn_id,
                    mode="tool",
                    ack="",
                    steps=[step],
                    requires_confirmation=False,
                )
                response = executor.execute(single_plan, user_text or "", turn=None)
                attempts_done += 1
                # Pull the stashed observation; fall back to a synthetic
                # "success" envelope when the handler didn't stash one.
                ctx = current_turn()
                observation = (
                    (ctx.observations.get(step.node_id) if ctx else None)
                    or {"status": "success", "summary": str(response or ""),
                        "structured_data": {}, "errors": []}
                )
                decision = controller.decide_next(
                    run_state, observation,
                    step_id=step.node_id,
                    original_args=attempt_args,
                )
                logger.info(
                    "[replan] step=%s status=%s decision=%s reason=%s",
                    step.node_id, observation.get("status"),
                    decision.decision, (decision.reason_summary or "")[:120],
                )

                if decision.decision == "continue":
                    responses.append(str(response or ""))
                    # Phase 7: emit a progress update to the source channel.
                    self._emit_step_progress(
                        comms=comms,
                        step_index=step_index,
                        total=total_steps,
                        step_id=step.node_id,
                        observation=observation,
                    )
                    break
                if decision.decision == "retry":
                    # Apply any updated_args the controller proposed.
                    if decision.updated_args:
                        attempt_args = {**attempt_args, **dict(decision.updated_args)}
                    # Safety: don't loop forever even if the controller fails
                    # to update retries_used (the cap below is the final stop).
                    if attempts_done > (controller.max_step_retries + 1):
                        final_decision = "stop"
                        final_reason = (
                            f"runaway retry on {step.node_id!r}; aborted by safety cap"
                        )
                        break
                    continue
                if decision.decision in {"ask_user", "stop", "refuse", "escalate"}:
                    final_decision = decision.decision
                    final_reason = decision.reason_summary or decision.question
                    if decision.question:
                        responses.append(decision.question)
                    elif final_reason:
                        responses.append(final_reason)
                    break
                # Unknown decision — be conservative.
                final_decision = "stop"
                final_reason = f"unknown decision {decision.decision!r}"
                break
            if final_decision != "continue":
                break

        # Phase 8: persist successful, user-approved runs to the plan
        # archive for future few-shot retrieval.
        if final_decision == "continue":
            self._archive_run(
                user_text=user_text,
                slots=compiled.resolved_slots,
                steps=ordered_steps,
                session_id=session_id,
            )

        return WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response="\n".join(r for r in responses if r),
            state={
                "slots": compiled.resolved_slots,
                "final_decision": final_decision,
                "reason": final_reason,
                "total_steps": run_state.total_steps,
                "elapsed_sec": run_state.elapsed_sec(),
                "retries_by_step": {
                    sid: s.retries_used for sid, s in run_state.step_states.items()
                },
            },
        )

    def _archive_run(self, *, user_text: str, slots: dict, steps: list, session_id: str) -> None:
        archive = getattr(self.app, "plan_archive", None)
        if archive is None:
            return
        # Only archive when we have something meaningful to embed — voice
        # turns that lost the original transcript (e.g. resume flows) should
        # not pollute the archive with empty strings.
        text = (user_text or "").strip()
        if not text:
            return
        plan_shape = [getattr(s, "capability_name", "") for s in steps]
        try:
            archive.save(
                user_text=text,
                workflow_name=self.name,
                slot_values=dict(slots or {}),
                plan_shape=plan_shape,
                outcome="success",
                user_approved=True,
                session_id=session_id or "",
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[plan_archive] save failed: %s", exc)

    # ------------------------------------------------------------------
    # Phase 7: per-step approval + progress streaming
    # ------------------------------------------------------------------

    def _gate_step_approval(
        self,
        *,
        descriptor,
        consent_service,
        comms,
        turn_source: str,
    ) -> str:
        """Return ``"allow"``, ``"deny"``, or ``"timeout"``.

        Consults :class:`ConsentService.evaluate_security_action` and, when
        an approval is required AND the turn originated on Telegram,
        round-trips the prompt via ``comms.telegram.request_approval``.

        For non-Telegram sources (voice / GUI / unknown), the gate
        currently auto-allows — Phase 7 keeps the per-channel approval
        story focused on Telegram; voice/GUI approval is future work.
        """
        if consent_service is None:
            return "allow"
        try:
            result = consent_service.evaluate_security_action(descriptor)
        except Exception as exc:
            logger.warning("[approval] consent evaluation failed: %s — allowing", exc)
            return "allow"
        if not getattr(result, "needs_confirmation", False):
            return "allow"

        prompt = getattr(result, "prompt", "") or "Approval needed for this step."
        if turn_source == "telegram" and comms is not None:
            telegram = getattr(comms, "telegram", None)
            if telegram is not None and getattr(telegram, "available", False):
                response = telegram.request_approval(prompt, timeout=180)
                if response == "approve":
                    return "allow"
                if response in {"deny", "cancel"}:
                    return "deny"
                if response == "timeout":
                    return "timeout"
                return "deny"
            # No telegram available — refuse-by-default for security tasks.
            return "deny"
        # Voice/GUI: auto-allow (existing voice consent path remains in
        # CapabilityBroker for legacy capabilities).
        return "allow"

    def _emit_step_progress(
        self,
        *,
        comms,
        step_index: int,
        total: int,
        step_id: str,
        observation: dict,
    ) -> None:
        if comms is None or not hasattr(comms, "send_progress"):
            return
        status = (observation or {}).get("status") or "success"
        summary = ((observation or {}).get("summary") or "")[:120]
        line = f"Step {step_index + 1}/{total} ({step_id}): {status}"
        if summary:
            line += f" — {summary}"
        try:
            comms.send_progress(line)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[progress] send_progress failed: %s", exc)

    def _select_executor(self, plan):
        # Mirror the v2 selection rule: use the graph executor only when the
        # config opts in *and* the plan has >1 steps. Single-step templates
        # go through the ordered executor for compatibility with existing
        # side-effect hooks.
        cfg = getattr(self.app, "config", None)
        engine = "ordered"
        if cfg and hasattr(cfg, "get"):
            engine = (cfg.get("routing.execution_engine") or "ordered").lower()
        if engine == "parallel" and len(plan.steps) > 1 and hasattr(self.app, "task_graph_executor"):
            return self.app.task_graph_executor
        return self.app.ordered_tool_executor

    def _handle(self, state):
        # Default BaseWorkflow path is unused for template workflows — they
        # are run via run_with_slots() or run_slot_fill_turn(). If invoked
        # via the default BaseWorkflow.run() path, refuse cleanly.
        state["result"] = WorkflowResult(
            handled=False,
            workflow_name=self.name,
            response="Template workflows are dispatched by the planner, not by user text.",
        )
        return state

    # ------------------------------------------------------------------
    # Track 5.2a — multi-turn slot-fill primitive
    # ------------------------------------------------------------------

    def start_slot_fill(self, session_id: str, initial_slots: dict | None = None,
                        *, turn_id: str = "") -> WorkflowResult:
        """Enter the workflow's slot-fill loop for the first time.

        Persists the initial slots into the workflow state (so the next
        turn lands in :meth:`run_slot_fill_turn` via
        :meth:`WorkflowOrchestrator.continue_active`) and returns the
        first ask-step's question (or runs immediately if all slots
        are already filled).
        """
        return self._advance_slot_fill(
            session_id, dict(initial_slots or {}), turn_id=turn_id, user_text="",
        )

    def run_slot_fill_turn(self, user_text: str, session_id: str,
                           *, turn_id: str = "") -> WorkflowResult:
        """Resume an in-flight slot-fill workflow with the user's reply.

        Looks up the stored ``awaiting_slot`` from the workflow state,
        extracts a value (via ``extract_with`` capability or raw text),
        then re-advances. If the user's reply fills the last ask-step,
        the capability steps run and the workflow completes.

        Track 5.2c: before extracting the next slot, evaluate the
        template's ``cancel_when:`` predicate. If it fires (e.g. the user
        named a new filename mid-flow), clear the workflow state and
        return ``handled=False`` so the orchestrator falls through to
        normal routing for the new intent.
        """
        memory = self._memory()
        state = memory.get_active_workflow(session_id, workflow_name=self.name) or {}
        slots = dict(state.get("slots") or {})
        awaiting_slot = state.get("awaiting_slot") or ""
        awaiting_step_id = state.get("awaiting_step_id") or ""

        executor = getattr(self.app, "capability_executor", None)
        if self._compiler.evaluate_cancel(
            self._template, slots, user_text,
            capability_executor=executor,
        ):
            try:
                memory.clear_workflow_state(session_id, self.name)
            except Exception:
                pass
            return WorkflowResult(
                handled=False,
                workflow_name=self.name,
                response=self._template.cancel_response or "",
                state={},
            )

        if awaiting_slot:
            # Track 5.2b: always record an entry for the answered slot —
            # even when the extracted value is "". Empty value means
            # "user skipped"; the workflow advances rather than re-asking.
            slots[awaiting_slot] = self._extract_slot_for_step(
                awaiting_step_id, user_text,
            )
        return self._advance_slot_fill(
            session_id, slots, turn_id=turn_id, user_text=user_text,
        )

    def _advance_slot_fill(
        self, session_id: str, slots: dict,
        *, turn_id: str, user_text: str,
    ) -> WorkflowResult:
        executor = getattr(self.app, "capability_executor", None)
        compiled = self._compiler.compile(
            self._template, slots, turn_id=turn_id,
            capability_executor=executor, user_text=user_text,
        )
        if compiled.awaiting_slot:
            # Park: persist current slots + which slot the next turn fills.
            self._memory().save_workflow_state(session_id, self.name, {
                "workflow_name": self.name,
                "status": "active",
                "slots": dict(slots),
                "pending_slots": list(compiled.missing_slots),
                "awaiting_slot": compiled.awaiting_slot,
                "awaiting_step_id": compiled.awaiting_step_id,
                "last_action": "ask_" + compiled.awaiting_slot,
            })
            return WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response=compiled.plan.reply or "",
                state={
                    "slots": dict(slots),
                    "awaiting_slot": compiled.awaiting_slot,
                },
            )
        # All ask-steps filled — run the capability steps and complete.
        if compiled.missing_slots:
            # Required-inputs missing (non-ask slot). Surface the clarify
            # response but don't clear state; the caller can supply later.
            return WorkflowResult(
                handled=True,
                workflow_name=self.name,
                response=compiled.plan.reply,
                state={"slots": dict(slots), "missing_slots": compiled.missing_slots},
            )
        executor = self._select_executor(compiled.plan)
        response = (
            executor.execute(compiled.plan, user_text or "", turn=None)
            if compiled.plan.steps else ""
        )
        # Mark workflow complete so continue_active stops resuming it.
        self._memory().save_workflow_state(session_id, self.name, {
            "workflow_name": self.name,
            "status": "completed",
            "slots": dict(slots),
            "pending_slots": [],
            "last_action": "completed",
            "result_summary": str(response or "")[:200],
        })
        return WorkflowResult(
            handled=True,
            workflow_name=self.name,
            response=str(response or ""),
            state={"slots": dict(slots), "status": "completed"},
        )

    def _extract_slot_for_step(self, step_id: str, user_text: str) -> str:
        for step in self._template.steps:
            if step.step_id == step_id:
                executor = getattr(self.app, "capability_executor", None)
                return self._compiler.extract_slot_value(
                    step, user_text, capability_executor=executor,
                )
        return (user_text or "").strip()


class WorkflowOrchestrator:
    def __init__(self, app):
        self.app = app
        self.workflows = {}
        self.templates = {}             # workflow_name -> TemplateWorkflow
        self.register(FileWorkflow(app))
        self.register(BrowserMediaWorkflow(app))
        # launch-hardening §5.4 Step 3: ReminderWorkflow retired — the reminder
        # slot-fill is now the `set_reminder` YAML template (TaskManagerPlugin
        # starts it via start_template_slot_fill, followups resume through
        # TemplateWorkflow.run_slot_fill_turn). CalendarEventWorkflow stays: it
        # drives the *Google* calendar path (WorkspaceAgent._handle_create_event),
        # a different backend than the local create_calendar_event template — see
        # docs/launch_hardening_status.md §5.4.
        self.register(CalendarEventWorkflow(app))
        self._load_yaml_templates()
        try:
            # Track 5.2e: relocated from `core.reasoning.workflows` —
            # these are agentic services (stateful background managers +
            # LLM loops), not linear slot-fill workflows.
            from core.reasoning.agentic_services import (  # noqa: PLC0415
                ResearchWorkflow,
                FocusModeWorkflow,
                ResearchPlannerWorkflow,
            )
            self.register(ResearchWorkflow(app))
            self.register(FocusModeWorkflow(app))
            self.register(ResearchPlannerWorkflow(app))
        except Exception as exc:  # pragma: no cover
            logger.warning("[workflow] Could not load agentic services: %s", exc)
    def register(self, workflow):
        self.workflows[workflow.name] = workflow

    def run(self, workflow_name, user_text, session_id, context=None):
        workflow = self.workflows.get(workflow_name)
        if workflow is None:
            return WorkflowResult(handled=False, workflow_name=workflow_name)
        logger.info("[workflow] Running workflow: %s", workflow_name)
        return workflow.run(user_text, session_id, context=context)

    def continue_active(self, user_text, session_id, context=None):
        memory = getattr(self.app, "memory_service", None) or self.app.context_store
        active = memory.get_active_workflow(session_id)
        if not active:
            return WorkflowResult(handled=False)

        # Cancel command → clear workflow state and acknowledge; do not feed
        # the cancel word to the workflow step (it would be misinterpreted as
        # an answer to whatever the workflow was asking for).
        #
        # BUT a cancel-shaped utterance that is actually a targeted command for
        # a DIFFERENT workflow must not be hijacked. "stop the focus session"
        # while a browser_media workflow is active starts with "stop", so the
        # bare-cancel detector matched and it cancelled media instead of ending
        # focus (2026-05-29 bug — also why media was "forgotten"). If another
        # registered workflow would START on this text, it's a new command, not
        # a cancel of the active one — fall through to normal routing.
        if _is_workflow_cancel(user_text) and not self._targets_other_workflow(
            user_text, active.get("workflow_name", "")
        ):
            workflow_name = active.get("workflow_name", "")
            try:
                memory.clear_workflow_state(session_id, workflow_name)
            except Exception:
                pass
            logger.info("[workflow] Cancelled active workflow '%s' by user request.", workflow_name)
            # Batch 3 / Issue 3: fire the bus so DialogState pending-* fields
            # reset alongside the workflow. The audible TTS isn't speaking
            # here so we don't need a "tts" signal — workflow scope is right.
            try:
                from core.interrupt_bus import get_interrupt_bus  # noqa: PLC0415
                get_interrupt_bus().signal("workflow_cancel", scope="workflow")
            except Exception as exc:
                logger.debug("[workflow] interrupt-bus signal skipped: %s", exc)
            return WorkflowResult(
                handled=True,
                workflow_name=workflow_name,
                response="Okay, cancelled, sir.",
            )

        workflow = self.workflows.get(active.get("workflow_name"))
        if workflow is None or not workflow.can_continue(user_text, active, context=context):
            return WorkflowResult(handled=False, workflow_name=active.get("workflow_name", ""))
        return workflow.run(user_text, session_id, context=context)

    def _targets_other_workflow(self, user_text, active_name: str) -> bool:
        """True when *user_text* would start a workflow OTHER than the active
        one — i.e. it's a targeted command (e.g. "stop the focus session"),
        not a bare cancel of whatever happens to be active. Used to stop the
        bare-cancel path from hijacking such commands."""
        for name, workflow in self.workflows.items():
            if name == active_name:
                continue
            try:
                if workflow.should_start(user_text):
                    return True
            except Exception:
                continue
        return False

    def detect_workflow(self, user_text, session_id, context=None):
        active = (getattr(self.app, "memory_service", None) or self.app.context_store).get_active_workflow(session_id)
        if active:
            workflow = self.workflows.get(active.get("workflow_name"))
            if workflow and workflow.can_continue(user_text, active, context=context):
                return workflow.name
        for workflow in self.workflows.values():
            if workflow.should_start(user_text, context=context):
                return workflow.name
        return ""

    # ------------------------------------------------------------------
    # YAML template support
    # ------------------------------------------------------------------

    def _load_yaml_templates(self):
        """Load every YAML workflow template under core/workflows/templates/
        and register a TemplateWorkflow for each. Failures are logged and
        skipped — a single malformed template must not break startup."""
        try:
            from core.workflows import (  # noqa: PLC0415
                WorkflowTemplateCompiler,
                load_templates,
            )
        except Exception as exc:  # pragma: no cover - import-time defensive
            logger.warning("[workflow] template loader unavailable: %s", exc)
            return
        try:
            templates = load_templates()
        except Exception as exc:
            logger.warning("[workflow] failed to load YAML templates: %s", exc)
            return

        registry = getattr(self.app, "capability_registry", None)
        compiler = WorkflowTemplateCompiler(registry=registry)
        for name, tpl in templates.items():
            tw = TemplateWorkflow(self.app, tpl, compiler)
            self.templates[name] = tw
            self.register(tw)
        if templates:
            logger.info(
                "[workflow] loaded %d YAML template(s): %s",
                len(templates), ", ".join(sorted(templates)),
            )

    def list_templates(self) -> list[str]:
        return sorted(self.templates)

    def get_template(self, name: str):
        return self.templates.get(name)

    def start_template_slot_fill(
        self,
        template_name: str,
        session_id: str,
        initial_slots: dict | None = None,
        *,
        turn_id: str = "",
    ) -> WorkflowResult:
        """Kick off a YAML template's multi-turn slot-fill loop.

        Resolves the template by name, persists the starting state, and
        returns the first question (or, if all slots are already filled,
        executes the capability steps and returns the final response).
        Subsequent user turns land in :meth:`TemplateWorkflow.run_slot_fill_turn`
        via :meth:`continue_active`.
        """
        tw = self.templates.get(template_name)
        if tw is None:
            return WorkflowResult(
                handled=False,
                workflow_name=template_name,
                response=f"Unknown workflow template: {template_name!r}",
            )
        return tw.start_slot_fill(session_id, initial_slots, turn_id=turn_id)

    def run_template(
        self,
        name: str,
        slots: dict,
        session_id: str,
        *,
        turn_id: str = "",
        user_text: str = "",
        with_replanning: bool | None = None,
    ):
        """Compile + execute a registered template by name.

        Returns a :class:`WorkflowResult`. If the template is unknown or has
        unfilled required slots, ``handled=True`` with a human-readable
        ``response``; the executor is never invoked.

        When ``with_replanning`` is True (or the orchestrator's app config
        sets ``routing.use_replanning: true``), the template runs through
        the step-at-a-time loop with a bounded :class:`ReplanController`.
        """
        tw = self.templates.get(name)
        if tw is None:
            return WorkflowResult(
                handled=False,
                workflow_name=name,
                response=f"Unknown workflow template: {name!r}",
            )

        if with_replanning is None:
            cfg = getattr(self.app, "config", None)
            with_replanning = bool(
                cfg.get("routing.use_replanning") if cfg and hasattr(cfg, "get") else False
            )

        if with_replanning:
            return tw.run_with_replanning(
                slots, session_id,
                turn_id=turn_id, user_text=user_text,
                replan_controller=getattr(self.app, "replan_controller", None),
            )
        return tw.run_with_slots(
            slots, session_id, turn_id=turn_id, user_text=user_text,
        )
