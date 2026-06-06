"""Pydantic v2 schemas for the Qwen JSON planner.

Each schema is the *contract* between the model's output and downstream
deterministic code. Pydantic validates the structure; everything outside
the schema is repaired (best-effort) or rejected.

Conventions:
- All enums use lowercase string literals so Qwen's output is easy to match.
- All fields are explicit (no implicit defaults that hide model omissions),
  except where the deterministic pipeline needs a graceful empty.
- ``extra="forbid"`` would be too strict for a 4B model; we use ``"ignore"``
  and rely on the validator/compiler to reject unknown values.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


IntentType = Literal[
    "chat", "single_tool", "workflow", "multi_step", "clarify", "refuse"
]
RiskLevel = Literal["low", "medium", "high", "critical"]
SideEffect = Literal["read", "write", "critical"]
PlanMode = Literal["tool", "workflow", "clarify", "refuse", "chat"]
ObservationStatus = Literal["success", "failure", "partial", "timeout"]
ReplanAction = Literal[
    "continue", "retry", "ask_user", "stop", "escalate", "refuse"
]


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent_type: IntentType
    domain: str = ""
    confidence: float = 0.0
    risk_level: RiskLevel = "low"
    requires_authorization: bool = False
    missing_slots: list[str] = Field(default_factory=list)
    reason_summary: str = ""


class WorkflowSelection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    intent_type: Literal["workflow", "single_tool", "clarify", "refuse"]
    selected_workflow: str | None = None
    selected_capability: str | None = None
    confidence: float = 0.0
    missing_slots: list[str] = Field(default_factory=list)
    next_question: str = ""
    refusal_reason: str = ""
    reason_summary: str = ""


class SlotFill(BaseModel):
    model_config = ConfigDict(extra="ignore")

    filled_slots: dict = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    next_question: str = ""
    reason_summary: str = ""


class ToolPlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_id: str
    capability: str
    mode: str = ""
    args: dict = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    side_effect_level: SideEffect = "read"
    expected_observation: str = ""
    success_condition: str = ""


class ToolPlanV2(BaseModel):
    """Plan produced by the LLM. Validated by PlanValidator (Phase 4) before
    execution. Intentionally separate from ``core.capability_broker.ToolPlan``,
    which is the deterministic runtime shape — the compiler bridges them."""
    model_config = ConfigDict(extra="ignore")

    mode: PlanMode
    steps: list[ToolPlanStep] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    ask_user: str = ""
    safety_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class Observation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_id: str = ""
    capability: str = ""
    status: ObservationStatus = "success"
    summary: str = ""
    structured_data: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    next_step_hints: list[str] = Field(default_factory=list)


class ReplanDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: ReplanAction
    next_step_id: str = ""
    updated_args: dict = Field(default_factory=dict)
    question: str = ""
    reason_summary: str = ""
    confidence: float = 0.0
