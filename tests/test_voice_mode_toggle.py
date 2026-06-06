"""P3.19 — voice mode toggle (TTS mute/unmute)."""
import json
from types import SimpleNamespace

import pytest

from modules.voice_io.voice_mode import (
    VoiceModeController,
    make_voice_mode_controller,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def app():
    return SimpleNamespace(tts_muted=False)


@pytest.fixture
def state_path(tmp_path):
    return str(tmp_path / "runtime_state.json")


def test_mute_sets_app_flag(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    msg = vm.set("mute")
    assert "mute" in msg.lower()
    assert app.tts_muted is True


def test_unmute_clears_app_flag(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    vm.set("mute")
    vm.set("unmute")
    assert app.tts_muted is False


def test_text_only_mutes(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    vm.set("text_only")
    assert app.tts_muted is True


def test_unknown_state_returns_error_and_no_change(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    msg = vm.set("xyzzy")
    assert "don't recognize" in msg.lower() or "recognize" in msg.lower()
    assert app.tts_muted is False


def test_timed_mute_clears_after_duration(app, state_path):
    clock = _FakeClock()
    vm = VoiceModeController(app, state_path=state_path, clock=clock)
    vm.set("mute", duration_minutes=1)
    assert vm.is_muted() is True
    clock.advance(30)
    assert vm.is_muted() is True
    clock.advance(31)
    assert vm.is_muted() is False
    assert app.tts_muted is False


def test_state_persists_to_disk(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    vm.set("mute")
    with open(state_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["voice"]["muted"] is True


def test_state_restored_on_reload(state_path):
    a1 = SimpleNamespace(tts_muted=False)
    vm = VoiceModeController(a1, state_path=state_path)
    vm.set("mute")
    # Fresh controller (simulates a restart) — same path.
    a2 = SimpleNamespace(tts_muted=False)
    VoiceModeController(a2, state_path=state_path)
    assert a2.tts_muted is True


def test_factory(app, state_path):
    vm = make_voice_mode_controller(app, state_path=state_path)
    assert isinstance(vm, VoiceModeController)


def test_unmute_after_timed_mute_clears_timer(app, state_path):
    clock = _FakeClock()
    vm = VoiceModeController(app, state_path=state_path, clock=clock)
    vm.set("mute", duration_minutes=5)
    vm.set("unmute")
    clock.advance(1000)
    assert vm.is_muted() is False
    assert app.tts_muted is False


def test_alias_normalization(app, state_path):
    vm = VoiceModeController(app, state_path=state_path)
    msg = vm.set("text-only")
    assert app.tts_muted is True
    assert "mute" in msg.lower() or "speak again" in msg.lower()
