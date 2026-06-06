"""Unit tests for the Porcupine-backed in-app wake detector.

These tests fake the ``pvporcupine`` engine so they run without a Picovoice
access key, real audio, or the native library — they exercise the wrapper's
buffering, detection, and graceful-degradation contract that the STT engine
depends on.
"""
import numpy as np
import pytest

from modules.voice_io import wake_detector as wd


class _FakePorcupine:
    """Fires once after it has consumed ``fire_after`` frames of audio."""

    frame_length = 512
    sample_rate = 16000

    def __init__(self, fire_after=1):
        self._fire_after = fire_after
        self._frames_seen = 0

    def process(self, frame):
        assert len(frame) == self.frame_length  # Porcupine requires exact frames
        self._frames_seen += 1
        return 0 if self._frames_seen >= self._fire_after else -1


def _install_fake(monkeypatch, fire_after=1):
    fake_module = type("M", (), {"create": lambda **kw: _FakePorcupine(fire_after)})
    monkeypatch.setitem(__import__("sys").modules, "pvporcupine", fake_module)
    monkeypatch.setattr(wd, "resolve_keyword", lambda *a, **k: ("/fake/keyword.ppn", "Hey Friday", True))
    monkeypatch.setenv("FRIDAY_PORCUPINE_KEY", "test-key")


def test_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("FRIDAY_PORCUPINE_KEY", raising=False)
    det = wd.WakeWordDetector()
    assert det.initialize() is False
    assert "FRIDAY_PORCUPINE_KEY" in det.unavailable_reason
    # process_frame must never raise even when unavailable.
    assert det.process_frame(np.zeros(800, dtype=np.float32)) is False


def test_detects_after_enough_audio(monkeypatch):
    _install_fake(monkeypatch, fire_after=2)
    det = wd.WakeWordDetector()
    assert det.initialize() is True
    # An 800-sample float block yields one full 512-frame; the fake needs 2
    # frames, so the first block should not fire and the second should.
    block = np.zeros(800, dtype=np.float32)
    assert det.process_frame(block) is False
    assert det.process_frame(block) is True


def test_buffers_partial_blocks(monkeypatch):
    """Blocks smaller than frame_length accumulate until a full frame exists."""
    _install_fake(monkeypatch, fire_after=1)
    det = wd.WakeWordDetector()
    det.initialize()
    # 300 + 300 = 600 >= 512 -> first full frame produced on the second block.
    assert det.process_frame(np.zeros(300, dtype=np.float32)) is False
    assert det.process_frame(np.zeros(300, dtype=np.float32)) is True


def test_legacy_onnx_path_ignored(monkeypatch):
    """A leftover .onnx wake_model_path from old config must not be used."""
    _install_fake(monkeypatch, fire_after=1)
    det = wd.WakeWordDetector("models/hey_friday.onnx")
    assert det.keyword_override is None
    assert det.initialize() is True
