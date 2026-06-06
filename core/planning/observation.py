"""Canonical Observation model + helpers.

The Pydantic ``Observation`` schema is defined in
:mod:`core.planning.schemas`. This module re-exports it and adds two
helpers used by capability handlers and the replanner:

* :func:`stash_observation` — record a parser dict on the active
  :class:`TurnContext` so downstream steps and the replanner can read
  structured fields (open_ports, live_hosts, records, ...).
* :func:`get_observation` — retrieve a previously-stashed observation
  by step_id.
"""
from __future__ import annotations

from typing import Any

from core.logger import logger
from core.turn_context import current_turn

from .schemas import Observation

__all__ = ["Observation", "stash_observation", "get_observation"]


def stash_observation(step_id: str, observation: dict[str, Any] | Observation) -> None:
    """Store *observation* on the active TurnContext under *step_id*.

    Accepts either a parser dict (the natural output of
    :func:`modules.security_tools.parsers.nmap_parser.parse_nmap_xml` &
    friends) or a validated :class:`Observation` instance. Both are
    normalized to dict form for uniform downstream access.
    """
    ctx = current_turn()
    if ctx is None:
        logger.debug("[observation] no active turn — skipping stash for %s", step_id)
        return
    if isinstance(observation, Observation):
        payload = observation.model_dump()
    elif isinstance(observation, dict):
        payload = dict(observation)
    else:
        logger.warning(
            "[observation] unsupported observation type %r for %s; not stashed",
            type(observation).__name__, step_id,
        )
        return
    ctx.observations[step_id] = payload


def get_observation(step_id: str) -> dict | None:
    ctx = current_turn()
    if ctx is None:
        return None
    return ctx.observations.get(step_id)
