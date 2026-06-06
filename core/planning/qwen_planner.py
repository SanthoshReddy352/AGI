"""Qwen-driven structured planner.

This is the LLM-facing surface for the Kali workflow planner. It exposes
one method per prompt template, each of which:

  1. Renders the Jinja template with the given inputs.
  2. Calls ``LocalModelManager`` 's tool model with
     ``response_format={"type": "json_object"}``.
  3. Repairs common JSON defects (markdown fences, trailing commas, Python
     literals, ``<think>`` blocks).
  4. Validates the result against a Pydantic schema.
  5. On validation failure, retries ONCE with the validator's error
     message appended to the prompt as a correction instruction.
  6. Raises ``QwenPlannerError`` on second failure.

The class is intentionally pure (no globals). It does not touch the
network, the registry, or any executor — its sole responsibility is to
turn user text + context into a typed Pydantic object that downstream
deterministic code can act on.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Callable

import jinja2
from pydantic import BaseModel, ValidationError

from core.logger import logger

from .json_repair import repair_and_parse
from .schemas import (
    IntentClassification,
    Observation,
    ReplanDecision,
    SlotFill,
    ToolPlanV2,
    WorkflowSelection,
)


_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


class QwenPlannerError(RuntimeError):
    """Raised when the model fails to produce schema-valid output after a retry."""


@dataclass
class _CallResult:
    parsed: dict | list | None
    raw_text: str
    error: str = ""


class QwenPlanner:
    """Schema-driven wrapper around the tool model.

    Constructor takes a ``model_manager`` so the same instance used by
    ``ModelRouter`` can be reused (single LLM load on disk).
    """

    def __init__(
        self,
        model_manager,
        *,
        timeout_ms: int = 12000,
        max_tokens: int = 512,
        top_p: float = 0.2,
        prompt_dir: str | None = None,
    ):
        self._model_manager = model_manager
        self._timeout_ms = int(timeout_ms)
        self._max_tokens = int(max_tokens)
        self._top_p = float(top_p)
        self._tool_llm = None
        self._lock = threading.Lock()
        self._failed = False
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(prompt_dir or _PROMPT_DIR),
            autoescape=False,
            keep_trailing_newline=True,
            undefined=jinja2.StrictUndefined,
        )

    # ------------------------------------------------------------------
    # Public API — one method per prompt template / schema pair
    # ------------------------------------------------------------------

    def classify_intent(self, user_text: str) -> IntentClassification:
        return self._invoke(
            template="intent_classification.j2",
            schema=IntentClassification,
            variables={"user_text": user_text},
        )

    def select_workflow(
        self,
        user_text: str,
        workflows: list[dict[str, Any]],
        *,
        retrieved_examples: list[dict] | None = None,
    ) -> WorkflowSelection:
        return self._invoke(
            template="workflow_selection.j2",
            schema=WorkflowSelection,
            variables={
                "user_text": user_text,
                "workflows": workflows,
                "retrieved_examples": retrieved_examples or [],
            },
        )

    def fill_slots(self, user_text: str, selected: dict[str, Any]) -> SlotFill:
        return self._invoke(
            template="slot_fill.j2",
            schema=SlotFill,
            variables={"user_text": user_text, "selected": selected},
        )

    def draft_plan(
        self,
        user_text: str,
        capabilities: list[dict[str, Any]],
        *,
        target_context: str = "",
        permission_context: str = "",
        retrieved_examples: list[dict] | None = None,
    ) -> ToolPlanV2:
        return self._invoke(
            template="plan_draft.j2",
            schema=ToolPlanV2,
            variables={
                "user_text": user_text,
                "capabilities": capabilities,
                "target_context": target_context,
                "permission_context": permission_context,
                "retrieved_examples": retrieved_examples or [],
            },
        )

    def summarize_observation(self, observation_json: dict) -> Observation:
        return self._invoke(
            template="observation_summary.j2",
            schema=Observation,
            variables={"observation_json": json.dumps(observation_json, ensure_ascii=False)},
        )

    def replan(
        self,
        workflow_state: dict,
        observation: dict,
        *,
        policy_summary: str = "Respect scope, side-effect, and authorization rules.",
    ) -> ReplanDecision:
        return self._invoke(
            template="replan.j2",
            schema=ReplanDecision,
            variables={
                "workflow_state_json": json.dumps(workflow_state, ensure_ascii=False),
                "observation_json": json.dumps(observation, ensure_ascii=False),
                "policy_summary": policy_summary,
            },
        )

    # ------------------------------------------------------------------
    # Capability card compaction (used to keep the prompt small)
    # ------------------------------------------------------------------

    @staticmethod
    def compact_capability_cards(descriptors: list) -> list[dict[str, Any]]:
        """Build prompt-sized capability cards from CapabilityDescriptors.

        Only fields the model needs for selection are exposed; full input
        schemas remain server-side until a capability is chosen.

        2026-05-24 — when a tool has a `data/tool_catalog.yaml` entry,
        the card includes up to 6 `example_phrases` as `examples`. These
        are few-shot pattern matches the small Qwen-4B planner can
        leverage directly. Selector accuracy on phrasings outside the
        regex coverage has been the planner's weakest spot; example
        phrases close that gap without bloating the prompt.
        """
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
        except Exception:
            catalog = None

        out: list[dict[str, Any]] = []
        for d in descriptors:
            name = getattr(d, "name", "") or ""
            selector_hint = (getattr(d, "description", "") or "").strip()
            required = list((getattr(d, "input_schema", {}) or {}).keys())

            examples: list[str] = []
            catalog_entry = catalog.entry_for(name) if catalog is not None else None
            if catalog_entry:
                # Prefer the catalog summary if the description is empty
                # or shorter than what we curated.
                if catalog_entry.summary and len(catalog_entry.summary) > len(selector_hint):
                    selector_hint = catalog_entry.summary
                examples = list(catalog_entry.example_phrases[:6])

            card: dict[str, Any] = {
                "name": name,
                "selector_hint": selector_hint[:200],
                "risk": (getattr(d, "side_effect_level", "read") or "read"),
                "network_scope": (getattr(d, "network_scope", "local") or "local"),
                "requires_authorization": bool(getattr(d, "requires_authorization", False)),
                "required_slots": required,
            }
            if examples:
                card["examples"] = examples
            out.append(card)
        return out

    @staticmethod
    def compact_workflow_cards(templates: dict) -> list[dict[str, Any]]:
        """Build prompt-sized workflow cards from a templates dict."""
        out = []
        for name, tpl in templates.items():
            out.append({
                "name": name,
                "description": (tpl.description or "").strip()[:200],
                "required_inputs": list(tpl.required_inputs or []),
                "optional_inputs": list(tpl.optional_inputs or []),
            })
        return out

    # ------------------------------------------------------------------
    # Internal — model invocation, repair, validation, retry
    # ------------------------------------------------------------------

    def _invoke(self, template: str, schema: type[BaseModel], variables: dict[str, Any]):
        prompt = self._render(template, variables)
        first = self._call_model(prompt)
        result, error = self._validate(first, schema)
        if result is not None:
            return result
        # Retry once with the error message appended.
        repair_prompt = (
            f"{prompt}\n\nYour previous JSON failed validation: {error}\n"
            f"Return ONLY a corrected JSON object matching the schema."
        )
        logger.info("[qwen_planner] retrying %s after validation error: %s", template, error[:140])
        second = self._call_model(repair_prompt)
        result, error = self._validate(second, schema)
        if result is not None:
            return result
        raise QwenPlannerError(
            f"{template}: model output failed validation twice — last error: {error}"
        )

    def _render(self, template: str, variables: dict[str, Any]) -> str:
        tpl = self._env.get_template(template)
        return tpl.render(**variables)

    def _call_model(self, prompt: str) -> _CallResult:
        llm = self._get_tool_llm()
        if llm is None:
            raise QwenPlannerError("tool model unavailable")

        temperature = self._model_manager.profile("tool").temperature

        def _call():
            messages = [{"role": "user", "content": prompt}]
            if hasattr(llm, "create_chat_completion"):
                kwargs: dict[str, Any] = {
                    "messages": messages,
                    "max_tokens": self._max_tokens,
                    "temperature": temperature,
                    "top_p": self._top_p,
                    "response_format": {"type": "json_object"},
                }
                try:
                    return llm.create_chat_completion(**kwargs)
                except TypeError:
                    kwargs.pop("response_format", None)
                    return llm.create_chat_completion(**kwargs)
            # Legacy completion-only fallback.
            return {
                "choices": [{
                    "message": {
                        "content": llm(
                            prompt,
                            max_tokens=self._max_tokens,
                            temperature=temperature,
                        )["choices"][0]["text"]
                    }
                }]
            }

        timeout_s = max(1, self._timeout_ms) / 1000
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                raw = future.result(timeout=timeout_s)
            except FutureTimeout:
                raise QwenPlannerError(f"tool model timed out after {self._timeout_ms}ms")
            except Exception as exc:
                raise QwenPlannerError(f"tool model error: {exc}")

        text = self._extract_text(raw)
        return _CallResult(parsed=None, raw_text=text)

    @staticmethod
    def _extract_text(raw: Any) -> str:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content
                # Some APIs put plain text under choices[0]["text"]
                text = choices[0].get("text")
                if isinstance(text, str):
                    return text
        return ""

    def _validate(
        self, call_result: _CallResult, schema: type[BaseModel]
    ) -> tuple[BaseModel | None, str]:
        text = (call_result.raw_text or "").strip()
        if not text:
            return None, "empty model output"
        try:
            parsed = repair_and_parse(text)
        except ValueError as exc:
            return None, f"json repair failed: {exc}"
        if not isinstance(parsed, dict):
            return None, f"expected JSON object, got {type(parsed).__name__}"
        try:
            obj = schema.model_validate(parsed)
        except ValidationError as exc:
            return None, f"schema validation failed: {exc.errors(include_url=False)}"
        return obj, ""

    def _get_tool_llm(self):
        if self._tool_llm is not None:
            return self._tool_llm
        if self._failed:
            return None
        if not self._model_manager.is_loaded("tool"):
            return None
        with self._lock:
            if self._tool_llm is not None:
                return self._tool_llm
            model = self._model_manager.get_tool_model()
            if model is None:
                self._failed = True
                return None
            self._tool_llm = model
        return self._tool_llm
