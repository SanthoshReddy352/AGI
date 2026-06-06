"""Deterministic plan validator.

Every plan — whether built by the deterministic IntentRecognizer / RouteScorer
fast path, the CapabilityBroker, or the LLM-driven QwenPlanner — must pass
through this validator BEFORE the executor receives it. The validator is
the authoritative source for safety decisions; the LLM is never trusted to
police itself.

Checks performed (in order):

  1. All `capability_name` values exist in the CapabilityRegistry.
  2. `args` keys are a subset of the capability's declared `input_schema`
     (only when `input_schema` is non-empty; many existing capabilities
     declare parameters in `tool_spec` rather than `input_schema`, so this
     check is best-effort).
  3. `depends_on` references existing step `node_id` values.
  4. Steps form a DAG (no cycles). Reuses
     ``TaskGraphExecutor.topological_waves`` for parity with the executor.
  5. Each step's effective network_scope is consistent with the run
     context's authorized scope. Target literals in args are matched
     against the descriptor's declared scope AND, when authorization is
     required, the configured `security.authorized_scopes` list.
  6. No step exceeds the user's risk-level ceiling for the turn.
  7. Argument values contain none of the deny-listed dangerous flags
     (`block_dangerous_flags`).

A `ValidationResult` is returned; the orchestrator decides whether to
short-circuit to a refusal reply (unrepairable) or hand to
:class:`PlanRepair` for normalization (repairable).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.capability_broker import ToolPlan, ToolStep
from core.capability_registry import CapabilityRegistry
from core.kernel.permissions import PermissionService

def _block_dangerous_flags(value: str) -> str | None:
    """Lazy lookup — defers the modules.* import so core/ stays import-clean.

    core/ must not import from modules/ at top level (enforced by
    tests/test_import_graph.py). Doing the import on first call keeps the
    deny-list check available without violating that boundary.
    """
    try:
        from modules.security_tools.safety import block_dangerous_flags  # noqa: PLC0415
    except Exception:
        return None
    return block_dangerous_flags(value)


SEVERITY_FATAL = "fatal"        # must short-circuit; not repairable
SEVERITY_REPAIRABLE = "repairable"
SEVERITY_WARN = "warn"          # informational; does not block execution


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = SEVERITY_FATAL
    step_id: str = ""

    def __str__(self) -> str:
        prefix = f"[{self.code}]"
        if self.step_id:
            prefix = f"[{self.code} step={self.step_id}]"
        return f"{prefix} {self.message}"


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def fatal_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_FATAL]

    @property
    def repairable_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_REPAIRABLE]

    @property
    def first_fatal_message(self) -> str:
        f = self.fatal_issues
        return f[0].message if f else ""

    @property
    def repairable_only(self) -> bool:
        """True iff there are issues but none are fatal."""
        return bool(self.issues) and not self.fatal_issues


# Unified ceiling scale. Accepts either side_effect_level vocabulary
# (read/write/critical) or risk_level vocabulary (low/medium/high/critical)
# in the RunContext.user_risk_ceiling field.
_CEILING_RANK = {
    "read": 0, "low": 0,
    "write": 1, "medium": 1,
    "high": 2,
    "critical": 3,
}
_SIDE_EFFECT_RANK = {"read": 0, "write": 1, "critical": 3}


@dataclass
class RunContext:
    """Caller-supplied context for scope / authorization decisions.

    All fields are optional; missing values default to permissive (the
    capability's own declarations remain authoritative). Keep this small —
    the validator only needs what a turn-level policy actually constrains.
    """
    authorized_scopes: list[str] = field(default_factory=list)
    user_risk_ceiling: str = "critical"   # accept up to and including this tier
    requires_authorization: bool = True   # session policy default


class PlanValidator:
    """Deterministic validator. Stateless; reuse per-process safely."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        permission_service: PermissionService | None = None,
    ):
        self.registry = registry
        self.perms = permission_service or PermissionService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, plan: ToolPlan, run_context: RunContext | None = None) -> ValidationResult:
        run = run_context or RunContext()
        issues: list[ValidationIssue] = []

        # Non-tool plan modes (reply / clarify / refuse / chat / delegate / planner)
        # have nothing for the executor to gate; pass through.
        if (plan.mode or "") not in {"tool", "chat"}:
            return ValidationResult(valid=True, issues=[])

        steps = list(getattr(plan, "steps", []) or [])
        if not steps:
            return ValidationResult(valid=True, issues=[])

        # 1. Capability existence
        for step in steps:
            if not self.registry.has_capability(step.capability_name):
                issues.append(ValidationIssue(
                    code="unknown_capability",
                    message=f"capability {step.capability_name!r} is not registered",
                    severity=SEVERITY_FATAL,
                    step_id=step.node_id,
                ))

        # 2. Argument shape (best-effort)
        for step in steps:
            desc = self.registry.get_descriptor(step.capability_name)
            if desc is None or not desc.input_schema:
                continue
            allowed_keys = set(desc.input_schema.keys())
            for key in (step.args or {}).keys():
                # __step_id__ is an executor-injected key (Phase 5) — never
                # produced by the LLM and not part of any input schema.
                if key == "__step_id__":
                    continue
                if key not in allowed_keys and not self._is_step_injection_key(key, steps):
                    # If the arg is meant to be an upstream-injected output
                    # (the executor injects under the dependency's node_id),
                    # don't flag it. Otherwise repairable: the key likely
                    # came from a model that invented a parameter.
                    issues.append(ValidationIssue(
                        code="unknown_arg",
                        message=f"arg {key!r} is not declared in {step.capability_name!r} input schema",
                        severity=SEVERITY_REPAIRABLE,
                        step_id=step.node_id,
                    ))

        # 3 + 4. depends_on validity and acyclicity
        ids = {s.node_id for s in steps if s.node_id}
        for step in steps:
            for dep in step.depends_on or []:
                if dep not in ids:
                    issues.append(ValidationIssue(
                        code="unknown_dependency",
                        message=f"depends_on references unknown step {dep!r}",
                        severity=SEVERITY_FATAL,
                        step_id=step.node_id,
                    ))
        if not [i for i in issues if i.code == "unknown_dependency"]:
            cycle_issue = self._detect_cycle(steps)
            if cycle_issue is not None:
                issues.append(cycle_issue)

        # 5. Network scope / authorization (only for steps that declared it)
        for step in steps:
            desc = self.registry.get_descriptor(step.capability_name)
            if desc is None:
                continue
            target = self._extract_target_arg(step.args or {})
            scope = (desc.network_scope or "local").lower()
            if target and scope != "local":
                # Capability scope check
                scope_ok, scope_reason = self.perms.check_network_scope(target, scope)
                if not scope_ok:
                    issues.append(ValidationIssue(
                        code="scope_violation",
                        message=scope_reason,
                        severity=SEVERITY_FATAL,
                        step_id=step.node_id,
                    ))
                # Authorized-scope check (defense in depth)
                if desc.requires_authorization and run.requires_authorization and run.authorized_scopes:
                    auth_ok, auth_reason = self.perms.check_authorized_target(
                        target, run.authorized_scopes,
                    )
                    if not auth_ok:
                        issues.append(ValidationIssue(
                            code="unauthorized_target",
                            message=auth_reason,
                            severity=SEVERITY_FATAL,
                            step_id=step.node_id,
                        ))

        # 6. Risk ceiling
        ceiling = _CEILING_RANK.get((run.user_risk_ceiling or "critical").lower(), 3)
        for step in steps:
            level = (step.side_effect_level or "read").lower()
            tier_rank = _SIDE_EFFECT_RANK.get(level, 0)
            if tier_rank > ceiling:
                issues.append(ValidationIssue(
                    code="risk_exceeded",
                    message=(
                        f"step side_effect_level={level!r} exceeds turn ceiling "
                        f"{run.user_risk_ceiling!r}"
                    ),
                    severity=SEVERITY_FATAL,
                    step_id=step.node_id,
                ))

        # 7. Dangerous flag denial across all argument values
        for step in steps:
            for key, value in (step.args or {}).items():
                if not isinstance(value, str):
                    continue
                hit = _block_dangerous_flags(value)
                if hit:
                    issues.append(ValidationIssue(
                        code="dangerous_flag",
                        message=f"arg {key!r} contains denied token {hit!r}",
                        severity=SEVERITY_FATAL,
                        step_id=step.node_id,
                    ))

        valid = not any(i.severity == SEVERITY_FATAL for i in issues)
        return ValidationResult(valid=valid, issues=issues)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_step_injection_key(key: str, steps: list[ToolStep]) -> bool:
        """Return True iff `key` matches a step node_id — TaskGraphExecutor
        injects upstream outputs into args under each dependency's node_id."""
        return any(s.node_id == key for s in steps)

    @staticmethod
    def _extract_target_arg(args: dict[str, Any]) -> str:
        """Return the first plausible target/host/subnet/url argument value."""
        for key in ("target", "target_host", "host", "subnet",
                    "target_subnet", "domain", "url", "base_url"):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    @staticmethod
    def _detect_cycle(steps: list[ToolStep]) -> ValidationIssue | None:
        """Reuse the executor's topology routine for parity. Returns a fatal
        cycle issue if the graph cannot be linearized."""
        try:
            from core.task_graph_executor import _Node, topological_waves
        except Exception:  # pragma: no cover - import shouldn't fail in normal builds
            return None
        nodes = []
        for idx, step in enumerate(steps):
            nodes.append(_Node(
                step=step,
                node_id=step.node_id or f"step{idx}",
                depends_on=list(step.depends_on or []),
                retries=step.retries,
                input_index=idx,
            ))
        try:
            topological_waves(nodes)
        except ValueError as exc:
            return ValidationIssue(
                code="dependency_cycle",
                message=str(exc),
                severity=SEVERITY_FATAL,
            )
        return None
