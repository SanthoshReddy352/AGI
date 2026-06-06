"""Pytest fixtures for cross-turn conversation tests."""
from __future__ import annotations

import os
import sys

import pytest

# Ensure project root is on sys.path so `from core.app import FridayApp` works
# from inside this subdirectory.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from tests.conversation._harness import (  # noqa: E402
    Conversation,
    ConversationRunner,
    TurnRecord,
    conversation,
)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "conversation: cross-turn behavior tests driving the full v2 pipeline "
        "(Track 0.1 of FRIDAY Consolidation Direction)",
    )


@pytest.fixture
def conversation_runner() -> ConversationRunner:
    """Fresh FridayApp wrapped in a runner. One app per test."""
    return ConversationRunner()


@pytest.fixture
def convo_fn():
    """Convenience: `convo_fn(["turn1", "turn2"])` runs a sealed conversation."""
    return conversation


__all__ = [
    "Conversation",
    "ConversationRunner",
    "TurnRecord",
    "conversation",
]
