# Track 5.2e: these are NOT linear slot-fill workflows — they're stateful
# background managers (subprocess + threading) and agentic LLM loops.
# Renamed from `core/reasoning/workflows/` to make the distinction
# structural: a "workflow" in FRIDAY now means a YAML-templatable
# slot-fill flow; anything stateful or LLM-loopy is an agentic service.
from core.reasoning.agentic_services.research_mode import ResearchWorkflow
from core.reasoning.agentic_services.focus_mode import FocusModeWorkflow
from core.reasoning.agentic_services.research_planner import ResearchPlannerWorkflow

__all__ = ["ResearchWorkflow", "FocusModeWorkflow", "ResearchPlannerWorkflow"]
