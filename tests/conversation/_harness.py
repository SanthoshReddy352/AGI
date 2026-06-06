"""Cross-turn behavior test harness — Track 0.1 of FRIDAY Consolidation Direction.

Drives a sequence of user turns through the real v2 pipeline on a single
FridayApp instance and exposes fluent assertions on the resulting state.

Intentional non-goals:
  - No mocking of the intent / router / resolver layers. Mocks here defeat
    the purpose: every UX bug we are fixing survived 378 unit tests that
    mocked too much.
  - No magic data-dir isolation in this first revision. Tests that mutate
    persistent state should opt into the `isolated_data_dir` fixture (added
    in a follow-up) or operate on idempotent commands.

Tests construct conversations via:

    convo = conversation(["create my.txt", "read it"])
    convo.assert_tool_called("read_file", target="my.txt")

Or, for finer control, via the `conversation_runner` pytest fixture which
returns a `ConversationRunner` that can interleave assertions with turns.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnRecord:
    """Snapshot of one turn's observable state."""

    text: str
    source: str
    response: str
    tool_name: str | None = None
    tool_args: dict = field(default_factory=dict)
    route_source: str = ""
    spoken_ack: str = ""
    duration_ms: float = 0.0

    def __repr__(self) -> str:
        return (
            f"TurnRecord(text={self.text!r}, tool={self.tool_name!r}, "
            f"args={self.tool_args!r}, response={self.response!r})"
        )


class Conversation:
    """Result of running a list of turns. Exposes fluent assertions.

    All assertions operate on the *last* turn by default. Use `.turn(i)` to
    target a specific turn in the sequence.
    """

    def __init__(self, app: Any, turns: list[TurnRecord] | None = None):
        self.app = app
        self.turns: list[TurnRecord] = list(turns or [])

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    @property
    def last(self) -> TurnRecord:
        if not self.turns:
            raise AssertionError("Conversation has no turns yet")
        return self.turns[-1]

    def turn(self, index: int) -> "_TurnAssertion":
        """Target a specific turn (0-indexed) for the next assertion chain."""
        if index < 0 or index >= len(self.turns):
            raise AssertionError(f"Turn index {index} out of range (have {len(self.turns)})")
        return _TurnAssertion(self, self.turns[index])

    # ------------------------------------------------------------------
    # Fluent assertions (on last turn)
    # ------------------------------------------------------------------

    def assert_tool_called(self, name: str, **expected_args: Any) -> "Conversation":
        _assert_tool_called(self.last, name, expected_args)
        return self

    def assert_tool_not_called(self, name: str) -> "Conversation":
        _assert_tool_not_called(self.last, name)
        return self

    def assert_any_tool_called(self) -> "Conversation":
        if not self.last.tool_name:
            raise AssertionError(
                f"Expected some tool to be called; got tool_name={self.last.tool_name!r} "
                f"on turn {self.last!r}"
            )
        return self

    def assert_response_contains(self, needle: str) -> "Conversation":
        _assert_response_contains(self.last, needle)
        return self

    def assert_response_does_not_contain(self, needle: str) -> "Conversation":
        _assert_response_does_not_contain(self.last, needle)
        return self

    def assert_response_non_empty(self) -> "Conversation":
        if not (self.last.response or "").strip():
            raise AssertionError(f"Response was empty for turn {self.last!r}")
        return self

    def assert_route_source(self, source: str) -> "Conversation":
        if self.last.route_source != source:
            raise AssertionError(
                f"Expected route source {source!r}, got {self.last.route_source!r}"
            )
        return self


class _TurnAssertion:
    """Same assertion API as Conversation, but pinned to a specific turn."""

    def __init__(self, convo: Conversation, record: TurnRecord):
        self._convo = convo
        self._rec = record

    def assert_tool_called(self, name: str, **expected_args: Any) -> "_TurnAssertion":
        _assert_tool_called(self._rec, name, expected_args)
        return self

    def assert_tool_not_called(self, name: str) -> "_TurnAssertion":
        _assert_tool_not_called(self._rec, name)
        return self

    def assert_response_contains(self, needle: str) -> "_TurnAssertion":
        _assert_response_contains(self._rec, needle)
        return self

    def assert_response_does_not_contain(self, needle: str) -> "_TurnAssertion":
        _assert_response_does_not_contain(self._rec, needle)
        return self

    def then(self) -> Conversation:
        """Return to the whole-conversation assertion chain."""
        return self._convo


# ----------------------------------------------------------------------
# Shared assertion helpers — operate on a TurnRecord, raise AssertionError
# ----------------------------------------------------------------------


def _assert_tool_called(rec: TurnRecord, name: str, expected_args: dict) -> None:
    if rec.tool_name != name:
        raise AssertionError(
            f"Expected tool {name!r}, got {rec.tool_name!r}. Turn: {rec!r}"
        )
    for key, want in expected_args.items():
        got = rec.tool_args.get(key)
        if got != want:
            raise AssertionError(
                f"Tool {name!r} arg {key!r}: expected {want!r}, got {got!r}. "
                f"All args: {rec.tool_args!r}"
            )


def _assert_tool_not_called(rec: TurnRecord, name: str) -> None:
    if rec.tool_name == name:
        raise AssertionError(
            f"Tool {name!r} was called unexpectedly on turn {rec!r}"
        )


def _assert_response_contains(rec: TurnRecord, needle: str) -> None:
    haystack = (rec.response or "").lower()
    if needle.lower() not in haystack:
        raise AssertionError(
            f"Response did not contain {needle!r}. Got: {rec.response!r}"
        )


def _assert_response_does_not_contain(rec: TurnRecord, needle: str) -> None:
    haystack = (rec.response or "").lower()
    if needle.lower() in haystack:
        raise AssertionError(
            f"Response unexpectedly contained {needle!r}. Got: {rec.response!r}"
        )


# ----------------------------------------------------------------------
# Runner — drives turns through a real FridayApp
# ----------------------------------------------------------------------


class ConversationRunner:
    """Owns a FridayApp and feeds it user turns synchronously.

    Uses `source="cli"` so process_input runs through `_execute_turn`
    synchronously (no TaskRunner thread to join), giving deterministic
    test behavior.

    Plugins are NOT loaded by default — booting all 30+ plugins per test
    adds ~50 seconds, which is untenable for a growing test suite. Tests
    that need a specific capability registered should pass
    `load_plugins=["system_control"]` (a list of plugin package names under
    modules/) or `load_plugins=True` to load everything (slow). When skipped,
    tool dispatch falls through to "no handler matched" and behavior pins
    relying on a tool firing should opt in explicitly.
    """

    def __init__(
        self,
        app: Any | None = None,
        source: str = "cli",
        load_plugins: bool | list[str] = False,
    ):
        if app is None:
            from core.app import FridayApp  # noqa: PLC0415
            app = FridayApp()
            # FridayApp.__init__ constructs ConfigManager but does NOT call
            # .load() — production calls it from main.py. Tests need the
            # real config (specifically `routing.orchestrator: v2`) so the
            # ContextResolver and other v2-only hooks actually fire. Load
            # quietly; if config.yaml is unreadable, fall back to defaults.
            try:
                app.config.load()
            except Exception:
                pass
            if load_plugins:
                _boot_plugins(app, load_plugins)
        self.app = app
        self.source = source

    def turn(self, text: str, source: str | None = None) -> TurnRecord:
        src = source or self.source
        t0 = time.monotonic()
        try:
            raw = self.app.process_input(text, source=src)
        except Exception as exc:
            raise AssertionError(
                f"process_input raised on turn {text!r}: {type(exc).__name__}: {exc}"
            ) from exc
        duration_ms = (time.monotonic() - t0) * 1000.0

        decision = getattr(self.app.routing_state, "last_decision", None)
        tool_name = getattr(decision, "tool_name", "") or None
        tool_args = dict(getattr(decision, "args", {}) or {})
        route_source = getattr(decision, "source", "") or ""
        spoken_ack = getattr(decision, "spoken_ack", "") or ""

        return TurnRecord(
            text=text,
            source=src,
            response=raw or "",
            tool_name=tool_name,
            tool_args=tool_args,
            route_source=route_source,
            spoken_ack=spoken_ack,
            duration_ms=duration_ms,
        )

    def run(self, turns: list[str]) -> Conversation:
        convo = Conversation(app=self.app)
        for text in turns:
            convo.turns.append(self.turn(text))
        return convo


def conversation(
    turns: list[str],
    *,
    app: Any | None = None,
    source: str = "cli",
    load_plugins: bool | list[str] = False,
) -> Conversation:
    """Convenience: run a list of user turns on a fresh FridayApp."""
    return ConversationRunner(app=app, source=source, load_plugins=load_plugins).run(turns)


def _boot_plugins(app: Any, which: bool | list[str]) -> None:
    """Load plugins into `app`. Mirrors PluginManager.load_plugins() but with
    selective loading so tests can boot only the subset they need."""
    import importlib  # noqa: PLC0415
    import os  # noqa: PLC0415
    from core.logger import logger  # noqa: PLC0415

    modules_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "modules")
    if not os.path.isdir(modules_dir):
        return
    if which is True:
        wanted = None  # all
    else:
        wanted = {str(name).strip().lower() for name in which}
    loaded = []
    for item in sorted(os.listdir(modules_dir)):
        if item.startswith("__") or not os.path.isdir(os.path.join(modules_dir, item)):
            continue
        if wanted is not None and item.lower() not in wanted:
            continue
        try:
            module = importlib.import_module(f"modules.{item}")
            if hasattr(module, "setup"):
                instance = module.setup(app)
                if instance is not None:
                    loaded.append(instance)
        except Exception as exc:
            logger.debug("[harness] plugin %r skipped: %s", item, exc)
    # Retain a ref so plugin instances aren't GC'd mid-test.
    app._test_plugins = loaded
