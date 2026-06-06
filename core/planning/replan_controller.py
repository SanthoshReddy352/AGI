"""Bounded observation → replanning loop.

After each step in a workflow runs, :class:`ReplanController` looks at the
structured observation and decides what to do next. Deterministic rules
fire first; the LLM-driven :class:`QwenPlanner.replan` is consulted only
for genuinely ambiguous failure modes (and only if a planner is wired).

Hard caps prevent runaway loops:

  * ``max_workflow_steps``      — total step executions per workflow run.
  * ``max_step_retries``        — per-step retry budget (excluding the
                                  initial attempt).
  * ``workflow_total_timeout_sec`` — wall-clock cap on the whole run.

Deterministic decision rules (in evaluation order):

  status == ``success``                            → continue
  status == ``partial``                            → continue (downstream
                                                    steps decide if they
                                                    can use partial data)
  status == ``timeout`` AND retries_left > 0       → retry (bumped budget)
  status == ``timeout`` AND retries_left == 0      → stop
  errors mention ``scope`` / ``authorization``     → refuse
  errors mention ``missing`` / ``required``        → ask_user
  status == ``failure`` with no clear category     → escalate (LLM) /
                                                    stop if no planner
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from core.logger import logger

from .schemas import Observation, ReplanDecision


# Hard ceilings — exceed these and any decision is forced to "stop".
DEFAULT_MAX_WORKFLOW_STEPS = 12
DEFAULT_MAX_STEP_RETRIES = 2
DEFAULT_WORKFLOW_TIMEOUT_SEC = 300


_SCOPE_ERROR_RE = re.compile(
    r"\b(scope|authorization|unauthorized|out[- ]of[- ]scope|forbidden|denied)\b",
    re.IGNORECASE,
)
_MISSING_ERROR_RE = re.compile(
    r"\b(missing|required|not[- ]?(found|provided)|unknown\s+(target|host|domain))\b",
    re.IGNORECASE,
)
_TRANSIENT_ERROR_RE = re.compile(
    r"\b(temporar(y|ily)|transient|busy|retry(?:able)?|reset by peer)\b",
    re.IGNORECASE,
)


@dataclass
class StepRunState:
    """Per-step tracking the controller updates between attempts."""
    step_id: str
    retries_used: int = 0
    last_args: dict = field(default_factory=dict)


@dataclass
class WorkflowRunState:
    """Per-workflow tracking for the controller."""
    workflow_name: str = ""
    started_at: float = field(default_factory=time.monotonic)
    total_steps: int = 0
    step_states: dict[str, StepRunState] = field(default_factory=dict)

    def elapsed_sec(self) -> float:
        return time.monotonic() - self.started_at

    def step_state(self, step_id: str) -> StepRunState:
        return self.step_states.setdefault(step_id, StepRunState(step_id=step_id))


class ReplanController:
    """Decide post-step actions inside a bounded execution loop."""

    def __init__(
        self,
        *,
        max_workflow_steps: int = DEFAULT_MAX_WORKFLOW_STEPS,
        max_step_retries: int = DEFAULT_MAX_STEP_RETRIES,
        workflow_total_timeout_sec: int = DEFAULT_WORKFLOW_TIMEOUT_SEC,
        qwen_planner=None,
    ):
        self.max_workflow_steps = int(max_workflow_steps)
        self.max_step_retries = int(max_step_retries)
        self.workflow_total_timeout_sec = int(workflow_total_timeout_sec)
        self.qwen_planner = qwen_planner

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decide_next(
        self,
        run_state: WorkflowRunState,
        observation: dict,
        *,
        step_id: str,
        original_args: dict | None = None,
    ) -> ReplanDecision:
        """Return a :class:`ReplanDecision` for the just-completed step."""

        # Cap checks first — these override anything the observation says.
        if run_state.total_steps >= self.max_workflow_steps:
            return ReplanDecision(
                decision="stop",
                reason_summary=(
                    f"workflow step cap reached "
                    f"({run_state.total_steps}/{self.max_workflow_steps})"
                ),
                confidence=1.0,
            )
        if run_state.elapsed_sec() >= self.workflow_total_timeout_sec:
            return ReplanDecision(
                decision="stop",
                reason_summary=(
                    f"workflow wall-clock cap reached "
                    f"({run_state.elapsed_sec():.0f}s >= {self.workflow_total_timeout_sec}s)"
                ),
                confidence=1.0,
            )

        status = (observation.get("status") or "").lower()
        errors = list(observation.get("errors") or [])
        step_state = run_state.step_state(step_id)

        # Happy path.
        if status in ("success", "partial"):
            return ReplanDecision(
                decision="continue",
                reason_summary=f"step {step_id!r} status={status}",
                confidence=1.0,
            )

        # Timeouts → bounded retry with a slightly relaxed budget if we can.
        if status == "timeout":
            if step_state.retries_used < self.max_step_retries:
                step_state.retries_used += 1
                bumped_args = self._bump_timeout_args(original_args or {})
                return ReplanDecision(
                    decision="retry",
                    next_step_id=step_id,
                    updated_args=bumped_args,
                    reason_summary=(
                        f"timeout on {step_id!r}; "
                        f"retry {step_state.retries_used}/{self.max_step_retries} with bumped timeout"
                    ),
                    confidence=0.7,
                )
            return ReplanDecision(
                decision="stop",
                reason_summary=(
                    f"timeout on {step_id!r} after {self.max_step_retries} retry/retries"
                ),
                confidence=1.0,
            )

        # Failure / refused — categorize by error text.
        joined_errors = " | ".join(errors).lower()
        summary = (observation.get("summary") or "").lower()
        body = joined_errors + " " + summary
        reason = observation.get("reason") or ""
        if isinstance(reason, str):
            body += " " + reason.lower()

        if _SCOPE_ERROR_RE.search(body):
            return ReplanDecision(
                decision="refuse",
                reason_summary=(
                    f"scope/authorization error on {step_id!r}: "
                    f"{(reason or joined_errors or summary)[:120]}"
                ),
                confidence=1.0,
            )
        if _MISSING_ERROR_RE.search(body):
            return ReplanDecision(
                decision="ask_user",
                next_step_id=step_id,
                question=self._ask_question_from_errors(errors, summary, step_id),
                reason_summary=f"required input missing on {step_id!r}",
                confidence=0.9,
            )
        if _TRANSIENT_ERROR_RE.search(body) and step_state.retries_used < self.max_step_retries:
            step_state.retries_used += 1
            return ReplanDecision(
                decision="retry",
                next_step_id=step_id,
                updated_args=dict(original_args or {}),
                reason_summary=(
                    f"transient error on {step_id!r}; "
                    f"retry {step_state.retries_used}/{self.max_step_retries}"
                ),
                confidence=0.6,
            )

        # Unclassified failure — escalate to the LLM planner if available.
        if self.qwen_planner is not None:
            try:
                workflow_state_payload = {
                    "workflow_name": run_state.workflow_name,
                    "current_step_id": step_id,
                    "total_steps": run_state.total_steps,
                    "step_states": {
                        sid: {"retries_used": s.retries_used}
                        for sid, s in run_state.step_states.items()
                    },
                }
                decision = self.qwen_planner.replan(
                    workflow_state=workflow_state_payload,
                    observation=observation,
                )
                if decision.decision in {"continue", "retry", "ask_user", "stop", "escalate", "refuse"}:
                    return decision
                # Bad decision payload — fall through to default stop.
                logger.warning("[replan] LLM returned unrecognized decision %r", decision.decision)
            except Exception as exc:
                logger.warning("[replan] LLM replan failed: %s — defaulting to stop", exc)

        # Default: stop with a clean reason. We never silently retry an
        # unknown failure mode — that's how runaway loops happen.
        return ReplanDecision(
            decision="stop",
            reason_summary=(
                f"unclassified failure on {step_id!r}: "
                f"{(observation.get('summary') or joined_errors)[:120]}"
            ),
            confidence=0.9,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bump_timeout_args(args: dict) -> dict:
        """Return a copy of *args* with any explicit ``timeout`` field doubled."""
        out = dict(args or {})
        for key in ("timeout_sec", "timeout_ms", "timeout"):
            if key in out:
                try:
                    out[key] = int(out[key]) * 2
                except (TypeError, ValueError):
                    pass
        # We do NOT add a timeout if the original args didn't have one —
        # the wrapper's own default applies.
        return out

    @staticmethod
    def _ask_question_from_errors(errors: list[str], summary: str, step_id: str) -> str:
        # Take the first error line that looks human-readable.
        for err in errors:
            if isinstance(err, str) and err.strip():
                return f"I need a bit more info to continue {step_id!r}: {err.strip()}"
        if summary:
            return f"I couldn't continue {step_id!r}: {summary}. Can you clarify?"
        return f"I need a missing detail to continue {step_id!r}. Can you provide it?"
