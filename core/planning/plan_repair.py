"""Deterministic plan repair.

The validator (``plan_validator.PlanValidator``) tags issues as either
``fatal`` (security boundary — must short-circuit) or ``repairable``
(model-typo class problems we can fix without changing intent).

Repair is intentionally conservative: it only addresses problems that
have a clear, single fix. Anything ambiguous gets left for the
LLM-retry path in ``QwenPlanner``.

Also exposes :func:`bridge_v2_to_runtime` for converting an LLM-drafted
:class:`ToolPlanV2` Pydantic object into the runtime :class:`ToolPlan` /
:class:`ToolStep` shape the executors consume.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.capability_broker import ToolPlan, ToolStep
from core.capability_registry import CapabilityRegistry
from core.logger import logger

from .plan_validator import ValidationIssue, ValidationResult
from .schemas import ToolPlanV2


_SIDE_EFFECT_NORMALIZE = {
    "r": "read", "read": "read", "ro": "read", "readonly": "read",
    "w": "write", "write": "write", "mutate": "write", "modify": "write",
    "c": "critical", "critical": "critical", "destroy": "critical",
}


class PlanRepair:
    """Apply safe automatic fixes to a ToolPlan based on validator issues."""

    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def try_repair(
        self, plan: ToolPlan, result: ValidationResult,
    ) -> tuple[ToolPlan, list[ValidationIssue]]:
        """Return ``(repaired_plan, remaining_issues)``.

        Remaining issues are those that could not be auto-repaired. If
        ``result.repairable_only`` was True and every issue was handled,
        the returned issues list is empty.
        """
        steps = list(plan.steps or [])
        remaining: list[ValidationIssue] = []
        repaired_count = 0

        for issue in result.issues:
            if issue.code == "unknown_arg":
                if self._drop_unknown_arg(steps, issue):
                    repaired_count += 1
                    continue
            elif issue.code == "side_effect_typo":
                if self._normalize_side_effect(steps, issue):
                    repaired_count += 1
                    continue
            remaining.append(issue)

        # Always normalize side-effect spellings (cheap, independent of issues).
        for step in steps:
            normalized = _SIDE_EFFECT_NORMALIZE.get(
                (step.side_effect_level or "read").lower(),
                step.side_effect_level,
            )
            if normalized != step.side_effect_level:
                step.side_effect_level = normalized
                repaired_count += 1

        if repaired_count:
            logger.info("[plan_repair] applied %d fix(es)", repaired_count)

        repaired_plan = replace(plan, steps=steps)
        return repaired_plan, remaining

    # ------------------------------------------------------------------
    # Individual fixes
    # ------------------------------------------------------------------

    def _drop_unknown_arg(self, steps: list[ToolStep], issue: ValidationIssue) -> bool:
        """Remove arg keys the LLM invented that are not in the input schema."""
        # Find the offending step and the arg key encoded in the message.
        marker = "arg "
        start = issue.message.find(marker)
        if start < 0:
            return False
        end = issue.message.find("'", start + len(marker) + 1)
        if end < 0:
            return False
        key = issue.message[start + len(marker) + 1:end]
        for step in steps:
            if step.node_id == issue.step_id and key in (step.args or {}):
                new_args = dict(step.args)
                new_args.pop(key, None)
                step.args = new_args
                return True
        return False

    def _normalize_side_effect(self, steps: list[ToolStep], issue: ValidationIssue) -> bool:
        for step in steps:
            if step.node_id == issue.step_id:
                normalized = _SIDE_EFFECT_NORMALIZE.get(
                    (step.side_effect_level or "read").lower(),
                )
                if normalized and normalized != step.side_effect_level:
                    step.side_effect_level = normalized
                    return True
        return False


# ---------------------------------------------------------------------------
# Bridge: ToolPlanV2 (Pydantic, LLM output) -> ToolPlan (runtime shape)
# ---------------------------------------------------------------------------

def bridge_v2_to_runtime(
    v2: ToolPlanV2,
    *,
    turn_id: str,
    ack: str = "",
    registry: CapabilityRegistry | None = None,
) -> ToolPlan:
    """Convert an LLM-drafted :class:`ToolPlanV2` to the executor-ready
    :class:`ToolPlan` shape. Pulls descriptor metadata (latency, connectivity,
    side-effect level) from the registry when available.
    """
    if v2.mode in {"clarify", "refuse"}:
        return ToolPlan(
            turn_id=turn_id,
            mode="reply",
            reply=v2.ask_user or "; ".join(v2.safety_notes) or "I can't do that.",
            ack=ack,
        )
    if v2.mode == "chat":
        return ToolPlan(turn_id=turn_id, mode="chat", ack=ack)

    steps: list[ToolStep] = []
    for s in v2.steps:
        desc = registry.get_descriptor(s.capability) if registry else None
        connectivity = desc.connectivity if desc else "local"
        side_effect = s.side_effect_level or (desc.side_effect_level if desc else "read")
        timeout_ms = _default_timeout_ms(desc)
        steps.append(ToolStep(
            capability_name=s.capability,
            args=dict(s.args or {}),
            raw_text="",
            side_effect_level=side_effect,
            connectivity=connectivity,
            timeout_ms=timeout_ms,
            parallel_safe=False,
            node_id=s.step_id,
            depends_on=list(s.depends_on or []),
            retries=0,
            fallback_capability="",
        ))

    requires_confirmation = any(s.requires_confirmation for s in v2.steps)
    return ToolPlan(
        turn_id=turn_id,
        mode="tool",
        ack=ack,
        steps=steps,
        requires_confirmation=requires_confirmation,
        estimated_latency=_estimate_latency(steps),
    )


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


def _estimate_latency(steps: list[ToolStep]) -> str:
    total_ms = sum(s.timeout_ms for s in steps)
    if total_ms <= 8000:
        return "interactive"
    if total_ms <= 30000:
        return "slow"
    return "very_slow"
