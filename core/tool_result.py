"""Tool result classification (P3.22).

classify() maps a (tool_name, result) pair to one of four outcome
categories so the router can retry, surface, or audit-log correctly.

  ok         — normal success; no action needed beyond returning to user
  soft_fail  — tool ran but produced an error message; log a warning
  retryable  — transient failure (timeout, connection); retry once
  fatal      — hard failure (permission denied); audit-log and surface
"""
from __future__ import annotations

from typing import Literal

_Outcome = Literal["ok", "soft_fail", "retryable", "fatal"]

_RETRYABLE = (
    "timeout", "timed out", "connection refused",
    "temporarily unavailable", "try again", "network error",
)
_FATAL = (
    "permission denied", "access denied", "unauthorized",
    "operation not permitted", "not allowed",
)
_SOFT_FAIL = (
    "error running command", "failed to", "could not ",
    "unable to", "error:", "exception:", "traceback",
)


def classify(tool_name: str, result: object) -> _Outcome:
    """Return the outcome category for a tool result."""
    if result is None:
        return "soft_fail"
    text = str(result).lower()
    if any(f in text for f in _RETRYABLE):
        return "retryable"
    if any(f in text for f in _FATAL):
        return "fatal"
    if any(f in text for f in _SOFT_FAIL):
        return "soft_fail"
    return "ok"


def is_failure(outcome: _Outcome) -> bool:
    return outcome in ("soft_fail", "retryable", "fatal")
