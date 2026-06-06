"""Compile a YAML workflow template into a runtime ToolPlan.

Substitutions supported in argument values:

  {{slot_name}}             - user-supplied slot (required or optional input)
  {{slot|default:value}}    - slot with literal default
  ${step_id.field}          - upstream step output reference (Phase 5 will
                              resolve dotted paths against structured
                              Observations; for now the runtime injection in
                              TaskGraphExecutor wires the dependency's
                              text output under the bare key `step_id`)

The compiler:

  * Verifies every required_input slot has a value.
  * Verifies every step's capability exists in the registry (so we fail
    fast before execution rather than mid-workflow).
  * Substitutes {{...}} placeholders inside argument string values.
  * Carries ``${step_id...}`` references through unchanged — the executor
    handles upstream injection at runtime.
  * Produces a list of ``ToolStep`` instances ready to be wrapped in a
    ``ToolPlan(mode='tool', steps=...)``.

It does NOT execute anything, talk to the LLM, or contact the network. It
is a pure function of (template, slots, registry).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.capability_broker import ToolPlan, ToolStep
from core.capability_registry import CapabilityExecutionResult, CapabilityRegistry

from .template_loader import WorkflowTemplate, WorkflowTemplateStep


_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)"        # 1: slot name
    r"(?:\s*\|\s*default\s*:\s*([^}]+?))?"   # 2: optional default
    r"\s*\}\}"
)


class CompileError(ValueError):
    """Raised when a template cannot be compiled into a runnable plan."""


@dataclass
class CompiledPlan:
    template_name: str
    plan: ToolPlan
    resolved_slots: dict[str, Any]
    missing_slots: list[str]
    # Track 5.2a — multi-turn slot-fill metadata. When the compile result
    # parked the workflow with a question, `awaiting_slot` names the slot
    # whose answer the next turn will fill (and which extractor to use).
    awaiting_slot: str = ""
    awaiting_step_id: str = ""


class WorkflowTemplateCompiler:
    def __init__(self, registry: CapabilityRegistry | None = None):
        self.registry = registry

    def compile(
        self,
        template: WorkflowTemplate,
        slots: dict[str, Any] | None = None,
        *,
        turn_id: str = "",
        ack: str = "",
        capability_executor: Any = None,
        user_text: str = "",
    ) -> CompiledPlan:
        slots = dict(slots or {})

        # Track 5.2a — multi-turn slot-fill primitive. Walk ask-steps in
        # declaration order; the first one whose slot is unfilled becomes
        # the question to ask this turn. Once every ask-step's slot is
        # filled (including with an empty value, indicating a user skip),
        # fall through to the standard capability-step compile.
        # Track 5.2c: skip ask-steps whose `when:` predicate evaluates
        # false (slot stays unset; downstream {{slot}} resolves to "").
        next_ask = self._next_unfilled_ask_step(
            template, slots,
            capability_executor=capability_executor, user_text=user_text,
        )
        if next_ask is not None:
            # Track 5.2b: interpolate already-filled {{slot}} references
            # into the question text so e.g. step 2 can address the user
            # by the name they just gave in step 1.
            question = self._substitute(next_ask.ask, slots) if next_ask.ask else ""
            return CompiledPlan(
                template_name=template.workflow_name,
                plan=ToolPlan(turn_id=turn_id, mode="clarify",
                              reply=question),
                resolved_slots=slots,
                missing_slots=[next_ask.slot],
                awaiting_slot=next_ask.slot,
                awaiting_step_id=next_ask.step_id,
            )

        missing = [
            name for name in template.required_inputs
            if name not in slots or slots[name] in (None, "", [])
        ]
        if missing:
            return CompiledPlan(
                template_name=template.workflow_name,
                plan=ToolPlan(turn_id=turn_id, mode="clarify",
                              reply=f"Missing required input(s): {', '.join(missing)}"),
                resolved_slots=slots,
                missing_slots=missing,
            )

        capability_steps = [s for s in template.steps if not s.is_ask_step]
        if self.registry is not None:
            unknown = [
                step.capability for step in capability_steps
                if not self.registry.has_capability(step.capability)
            ]
            if unknown:
                raise CompileError(
                    f"template {template.workflow_name!r} references "
                    f"unknown capability/capabilities: {sorted(set(unknown))}"
                )

        # Track 5.2c: filter out capability steps whose `when:` predicate
        # evaluates false. The dependency on a skipped step still works at
        # the YAML level — runtime injection in TaskGraphExecutor only
        # resolves observations for steps that actually ran.
        capability_steps = [
            s for s in capability_steps
            if self._predicate_passes(
                s.when, slots, user_text, capability_executor,
            )
        ]

        steps_out: list[ToolStep] = []
        for raw_step in capability_steps:
            args = self._resolve_args(raw_step.args, slots)
            descriptor = (
                self.registry.get_descriptor(raw_step.capability)
                if self.registry is not None else None
            )
            side_effect = (
                raw_step.side_effect_level
                if raw_step.side_effect_level != "read"
                else (descriptor.side_effect_level if descriptor else "read")
            )
            connectivity = descriptor.connectivity if descriptor else "local"
            timeout_ms = raw_step.timeout_ms or self._default_timeout_ms(descriptor)
            steps_out.append(ToolStep(
                capability_name=raw_step.capability,
                args=args,
                raw_text="",
                side_effect_level=side_effect,
                connectivity=connectivity,
                timeout_ms=timeout_ms,
                parallel_safe=False,
                node_id=raw_step.step_id,
                depends_on=list(raw_step.depends_on),
                retries=raw_step.retries,
                fallback_capability="",
            ))

        plan = ToolPlan(
            turn_id=turn_id,
            mode="tool",
            ack=ack or f"Running workflow: {template.workflow_name}.",
            steps=steps_out,
            requires_confirmation=any(
                s.requires_confirmation for s in capability_steps
            ),
            estimated_latency=self._estimate_latency(steps_out),
            final_style="",
        )
        return CompiledPlan(
            template_name=template.workflow_name,
            plan=plan,
            resolved_slots=slots,
            missing_slots=[],
        )

    # ------------------------------------------------------------------
    # Track 5.2a — multi-turn slot-fill helpers
    # ------------------------------------------------------------------

    def _next_unfilled_ask_step(
        self,
        template: WorkflowTemplate,
        slots: dict[str, Any],
        *,
        capability_executor: Any = None,
        user_text: str = "",
    ) -> WorkflowTemplateStep | None:
        # Track 5.2b: "filled" = the slot key is present in `slots`, even
        # if its value is an empty string. The skip-token convention
        # (Onboarding's "no" / "skip" / "later") writes the empty string
        # into the slot so the workflow advances to the next question
        # rather than re-asking. `required_inputs` (non-ask slots passed
        # in from outside) keeps the stricter "non-empty" check.
        # Track 5.2c: an ask-step whose `when:` predicate evaluates false
        # is silently skipped (the slot stays unset). This lets a YAML
        # template like FileWorkflow branch — e.g. only ask the
        # "dictate or generate?" question after the user said "yes" to
        # the write-confirmation step.
        for step in template.steps:
            if not step.is_ask_step:
                continue
            if step.slot in slots:
                continue
            if not self._predicate_passes(
                step.when, slots, user_text, capability_executor,
            ):
                continue
            return step
        return None

    # ------------------------------------------------------------------
    # Track 5.2c — predicate evaluation (`when:` / `cancel_when:`)
    # ------------------------------------------------------------------

    def _predicate_passes(
        self,
        expression: str,
        slots: dict[str, Any],
        user_text: str,
        capability_executor: Any,
    ) -> bool:
        """Evaluate a `when:` predicate. Empty expression → always pass.

        Expression forms supported (kept intentionally small — the YAML is
        declarative, not a programming language):

          * ``""`` (empty)             → pass.
          * ``"capability_name"``      → call the capability; truthy result
                                         passes. Signature mirrors
                                         ``extract_with``: ``execute(name,
                                         user_text, {"text": user_text,
                                         "slots": slots})``.
          * ``"not:capability_name"``  → invert the capability result.
          * ``"slot:<name>"``          → truthy when the named slot has a
                                         non-empty value.
          * ``"not:slot:<name>"``      → inverse of the above.

        Anything that raises during evaluation is treated as "pass" — we'd
        rather over-include a step than silently swallow user intent. The
        cancel-when path uses :meth:`evaluate_cancel` and gets the opposite
        bias (failure → don't cancel).
        """
        expr = (expression or "").strip()
        if not expr:
            return True
        negate = False
        if expr.startswith("not:"):
            negate = True
            expr = expr[4:].strip()
        if expr.startswith("slot:"):
            slot_name = expr[5:].strip()
            value = slots.get(slot_name)
            truthy = bool(value)
            return (not truthy) if negate else truthy
        # Capability-backed predicate.
        if capability_executor is None:
            return True
        try:
            result = capability_executor.execute(
                expr, user_text or "",
                {"text": user_text or "", "slots": dict(slots)},
            )
        except Exception:
            return True
        truthy = bool(result if not isinstance(result, dict)
                      else result.get("value", result.get("ok", False)))
        return (not truthy) if negate else truthy

    def evaluate_cancel(
        self,
        template: WorkflowTemplate,
        slots: dict[str, Any] | None,
        user_text: str,
        *,
        capability_executor: Any = None,
    ) -> bool:
        """Return True when the template's ``cancel_when:`` fires.

        Used by :class:`TemplateWorkflow.run_slot_fill_turn` (and any other
        resume path) to detect mid-flow target switches — e.g. the user
        named a different filename than the one the workflow is parked on
        (FileWorkflow's Issue-10 case). On failure to evaluate, returns
        False so we don't silently drop a live workflow.
        """
        expr = (template.cancel_when or "").strip()
        if not expr:
            return False
        slots = dict(slots or {})
        # Cancel predicates default to False on evaluation failure — we'd
        # rather keep the workflow alive than silently terminate it.
        negate = False
        if expr.startswith("not:"):
            negate = True
            expr = expr[4:].strip()
        if expr.startswith("slot:"):
            value = slots.get(expr[5:].strip())
            truthy = bool(value)
            return (not truthy) if negate else truthy
        if capability_executor is None:
            return False
        try:
            result = capability_executor.execute(
                expr, user_text or "",
                {"text": user_text or "", "slots": dict(slots)},
            )
        except Exception:
            return False
        truthy = bool(result if not isinstance(result, dict)
                      else result.get("value", result.get("ok", False)))
        return (not truthy) if negate else truthy

    def extract_slot_value(
        self,
        step: WorkflowTemplateStep,
        user_text: str,
        *,
        capability_executor=None,
    ) -> str:
        """Turn a user reply into a slot value for the given ask-step.

        If the step declares ``extract_with: <capability>``, call that
        capability with ``{"text": user_text}`` and use the string return
        value. Otherwise (and on any failure), strip and return the raw
        user text. The caller is responsible for handling skip-tokens or
        empty-answer policy — this helper is pure value extraction.
        """
        if not step.is_ask_step:
            raise CompileError(
                f"extract_slot_value called on non-ask step {step.step_id!r}"
            )
        raw = (user_text or "").strip()
        if step.extract_with and capability_executor is not None:
            try:
                result = capability_executor.execute(
                    step.extract_with, raw, {"text": raw},
                )
                if result is None:
                    return raw
                if isinstance(result, CapabilityExecutionResult):
                    return str(result.output) if result.ok else raw
                if isinstance(result, dict):
                    return str(result.get("value") or result.get("text") or raw)
                return str(result)
            except Exception:
                return raw
        return raw

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_args(self, args: dict[str, Any], slots: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in (args or {}).items():
            out[key] = self._resolve_value(value, slots)
        return out

    def _resolve_value(self, value: Any, slots: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._substitute(value, slots)
        if isinstance(value, list):
            return [self._resolve_value(item, slots) for item in value]
        if isinstance(value, dict):
            return {k: self._resolve_value(v, slots) for k, v in value.items()}
        return value

    def _substitute(self, value: str, slots: dict[str, Any]) -> str:
        # Repeatedly resolve {{...}} placeholders. Carry ${step.field} verbatim.
        def replace(match: re.Match) -> str:
            slot = match.group(1)
            default = match.group(2)
            if slot in slots and slots[slot] not in (None, "", []):
                raw = slots[slot]
                if isinstance(raw, CapabilityExecutionResult):
                    return str(raw.output) if raw.ok else str(raw)
                return str(raw)
            if default is not None:
                return str(default).strip()
            # Optional slot with no default and no value — leave the placeholder
            # so the runtime can see it (and so the compiler-level
            # required-slot check above is the authoritative source for
            # "missing"); but in practice required_inputs catches all of these.
            return ""
        return _PLACEHOLDER_RE.sub(replace, value)

    @staticmethod
    def _default_timeout_ms(descriptor) -> int:
        if descriptor is None:
            return 8000
        latency = (getattr(descriptor, "latency_class", None) or "interactive").lower()
        return {
            "fast": 4000,
            "interactive": 8000,
            "slow": 30000,
            "very_slow": 120000,
        }.get(latency, 8000)

    @staticmethod
    def _estimate_latency(steps: list[ToolStep]) -> str:
        total_ms = sum(s.timeout_ms for s in steps)
        if total_ms <= 8000:
            return "interactive"
        if total_ms <= 30000:
            return "slow"
        return "very_slow"
