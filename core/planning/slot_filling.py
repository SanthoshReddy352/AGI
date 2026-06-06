"""Unified slot-filling foundation (Track 2.4 → built in Phase 3).

Before this module, three slot-filling mechanisms lived side by side and
each consumer wired them up by hand:

  1. **Deterministic extractors** — :mod:`core.planning.slot_extractors`
     (regex pulls like ``extract_quoted_content``).
  2. **Template ``ask:``/``slot:`` steps** — the multi-turn loop driven by
     :class:`core.workflows.template_compiler.WorkflowTemplateCompiler`.
  3. **LLM extraction** — :meth:`core.planning.qwen_planner.QwenPlanner.fill_slots`.

A new tool/workflow that needed slots re-implemented an ad-hoc precedence
chain (try regex → fall back to the model → ask the user) in its handler.
That is exactly the duplication Track 5.1 fought elsewhere.

:class:`SlotFiller` is the single front door. Given a list of
:class:`SlotSpec` declarations and the user's text, it fills what it can
**cheapest-first** — caller-supplied values, then deterministic
extractors, then (only for still-missing *required* slots) one LLM call —
and reports which slots remain missing plus the next question to ask.

The engine is pure: it never touches the network directly, never mutates
its inputs, and works with ``planner=None`` (deterministic-only mode) so
test apps and offline runs degrade gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.logger import logger

from . import slot_extractors


# A deterministic extractor maps the user's text to a slot value, returning
# "" when it finds nothing. Keep the signature single-argument so specs stay
# declarative; richer context goes through the LLM fallback.
Extractor = Callable[[str], str]


# ----------------------------------------------------------------------
# Named extractor registry — lets a SlotSpec reference a shared extractor
# by string (so templates / config can declare `extractor: quoted_content`
# without importing Python callables).
# ----------------------------------------------------------------------

_NAMED_EXTRACTORS: dict[str, Extractor] = {
    "quoted_content": slot_extractors.extract_quoted_content,
    "datetime": slot_extractors.extract_datetime,
}


def register_extractor(name: str, fn: Extractor) -> None:
    """Register a deterministic extractor under *name* so SlotSpecs can
    reference it by string. Idempotent; later registrations win."""
    _NAMED_EXTRACTORS[name] = fn


def get_extractor(name: str) -> Extractor | None:
    return _NAMED_EXTRACTORS.get(name)


@dataclass
class SlotSpec:
    """Declarative description of one slot a tool/workflow needs.

    * ``name`` — the key the filled value lands under.
    * ``required`` — when True, a missing value blocks the workflow and
      drives ``next_question``; optional slots fall back to ``default``.
    * ``prompt`` — the question to ask the user when the slot is missing
      (mirrors a template ``ask:`` line). Defaults to a generic phrasing.
    * ``extractor`` — a deterministic extractor: either a callable
      ``(text) -> str`` or the string name of a registered extractor.
      Tried before the LLM. ``""`` return means "no match".
    * ``default`` — value used for an *optional* slot when nothing extracts.
    * ``aliases`` — alternate keys the LLM (or an upstream parser) may use
      for this slot; the filler normalizes them back to ``name``.
    """

    name: str
    required: bool = True
    prompt: str = ""
    extractor: Extractor | str | None = None
    default: Any = None
    aliases: tuple[str, ...] = ()

    def resolve_extractor(self) -> Extractor | None:
        if self.extractor is None:
            return None
        if isinstance(self.extractor, str):
            return get_extractor(self.extractor)
        return self.extractor

    def question(self) -> str:
        return self.prompt or f"What is the {self.name.replace('_', ' ')}?"


@dataclass
class SlotResult:
    """Outcome of :meth:`SlotFiller.fill`.

    ``filled`` is the merged slot dict (caller values + extracted + LLM +
    defaults). ``missing`` lists *required* slots still unfilled.
    ``next_question`` is the prompt for the first missing slot (``""`` when
    nothing is missing). ``sources`` records where each value came from
    ("known" | "extractor" | "llm" | "default") for diagnostics/logging.
    """

    filled: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    next_question: str = ""
    sources: dict[str, str] = field(default_factory=dict)
    confidence: float = 1.0

    @property
    def complete(self) -> bool:
        return not self.missing


class SlotFiller:
    """Cheapest-first slot filler unifying extractors + template asks + LLM.

    Construct once (optionally with a :class:`QwenPlanner`-like object that
    exposes ``fill_slots(user_text, selected) -> SlotFill``) and reuse. The
    LLM is consulted *only* when deterministic extraction leaves a required
    slot empty and ``use_llm`` is True, so the common case stays offline.
    """

    def __init__(
        self,
        planner: Any = None,
        *,
        use_llm: bool = True,
        workflow_name: str = "",
    ):
        self._planner = planner
        self._use_llm = use_llm and planner is not None
        self._workflow_name = workflow_name

    # ------------------------------------------------------------------

    def fill(
        self,
        specs: list[SlotSpec],
        user_text: str,
        known: dict[str, Any] | None = None,
    ) -> SlotResult:
        """Fill *specs* from *user_text*, layering on any *known* values.

        Precedence (first non-empty wins): caller-supplied ``known`` →
        deterministic extractor → LLM → optional ``default``.
        """
        slots: dict[str, Any] = {}
        sources: dict[str, str] = {}

        # 1. Carry caller-supplied / previously-filled values (incl. aliases).
        known = dict(known or {})
        for spec in specs:
            value = self._known_value(spec, known)
            if not _is_empty(value):
                slots[spec.name] = value
                sources[spec.name] = "known"

        # 2. Deterministic extractors — cheap, offline, no model.
        text = (user_text or "").strip()
        if text:
            for spec in specs:
                if spec.name in slots:
                    continue
                extractor = spec.resolve_extractor()
                if extractor is None:
                    continue
                try:
                    value = extractor(text) or ""
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("[slot_fill] extractor for %r failed: %s", spec.name, exc)
                    value = ""
                if not _is_empty(value):
                    slots[spec.name] = value
                    sources[spec.name] = "extractor"

        confidence = 1.0
        # 3. LLM fallback — only for still-missing *required* slots.
        missing_required = [
            s for s in specs if s.required and s.name not in slots
        ]
        if missing_required and self._use_llm and text:
            llm_conf = self._fill_with_llm(specs, slots, sources, text)
            if llm_conf is not None:
                confidence = llm_conf

        # 4. Defaults for any slot still unset that declares one.
        for spec in specs:
            if spec.name not in slots and spec.default is not None:
                slots[spec.name] = spec.default
                sources[spec.name] = "default"

        # 5. Compute the missing-required set + the next question to ask.
        missing = [s.name for s in specs if s.required and s.name not in slots]
        next_question = ""
        if missing:
            first = next(s for s in specs if s.name == missing[0])
            next_question = first.question()

        return SlotResult(
            filled=slots,
            missing=missing,
            next_question=next_question,
            sources=sources,
            confidence=confidence,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _known_value(spec: SlotSpec, known: dict[str, Any]) -> Any:
        if spec.name in known:
            return known[spec.name]
        for alias in spec.aliases:
            if alias in known:
                return known[alias]
        return None

    def _fill_with_llm(
        self,
        specs: list[SlotSpec],
        slots: dict[str, Any],
        sources: dict[str, str],
        user_text: str,
    ) -> float | None:
        """Consult the planner's ``fill_slots`` for missing slots.

        Mutates *slots*/*sources* in place for any newly-filled value and
        returns the model's confidence (or None when the call failed / the
        planner is unavailable). Failures are swallowed — a model hiccup
        must never break deterministic filling.
        """
        selected = {
            "name": self._workflow_name or "request",
            "required_slots": [s.name for s in specs if s.required],
            "optional_slots": [s.name for s in specs if not s.required],
        }
        try:
            result = self._planner.fill_slots(user_text, selected)
        except Exception as exc:
            logger.debug("[slot_fill] LLM fill_slots failed: %s", exc)
            return None

        filled = dict(getattr(result, "filled_slots", {}) or {})
        by_name = {s.name: s for s in specs}
        alias_to_name = {
            alias: s.name for s in specs for alias in s.aliases
        }
        for key, value in filled.items():
            target = key if key in by_name else alias_to_name.get(key)
            if target is None or target in slots or _is_empty(value):
                continue
            slots[target] = value
            sources[target] = "llm"
        try:
            return float(getattr(result, "confidence", 1.0))
        except (TypeError, ValueError):
            return 1.0

    # ------------------------------------------------------------------
    # Template bridge — derive SlotSpecs from a YAML workflow template's
    # ask-steps so the template ask:/slot: mechanism and handler-side
    # slot-fill share one declaration source.
    # ------------------------------------------------------------------

    @staticmethod
    def specs_from_template(template, *, capability_executor: Any = None) -> list[SlotSpec]:
        """Build :class:`SlotSpec` list from a ``WorkflowTemplate``'s ask-steps.

        Each ``ask:``/``slot:`` step becomes a required SlotSpec whose
        ``prompt`` is the ask text. A step's ``extract_with: <capability>``
        is wrapped into a deterministic extractor that calls the capability
        via *capability_executor* (mirroring
        :meth:`WorkflowTemplateCompiler.extract_slot_value`). Optional slots
        come from the template's ``optional_inputs``.
        """
        optional = set(getattr(template, "optional_inputs", []) or [])
        specs: list[SlotSpec] = []
        for step in getattr(template, "steps", []) or []:
            if not getattr(step, "is_ask_step", False):
                continue
            extractor = _capability_extractor(
                step.extract_with, capability_executor,
            ) if step.extract_with else None
            specs.append(SlotSpec(
                name=step.slot,
                required=step.slot not in optional,
                prompt=step.ask,
                extractor=extractor,
            ))
        return specs


def _capability_extractor(capability_name: str, capability_executor: Any) -> Extractor | None:
    if not capability_name or capability_executor is None:
        return None

    def _extract(text: str) -> str:
        try:
            result = capability_executor.execute(
                capability_name, text, {"text": text},
            )
        except Exception:
            return ""
        if result is None:
            return ""
        if isinstance(result, dict):
            return str(result.get("value") or result.get("text") or "")
        output = getattr(result, "output", None)
        if output is not None and getattr(result, "ok", True):
            return str(output)
        return str(result)

    return _extract


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []
