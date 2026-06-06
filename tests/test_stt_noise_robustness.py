"""STT signal-to-noise pipeline: SNR estimation, adaptive decode, normalization.

Covers the noise-robustness layer added so a single speaker in a *noisy* room
gets beam-search decoding + level normalization, while a quiet room keeps the
fast greedy path. See docs/testing_guide.md T-2.x and config.yaml voice.stt_*.
"""
import os
import sys
from unittest.mock import MagicMock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.voice_io.stt import STTEngine


def _engine():
    """STTEngine whose app has no config object, so config reads use defaults.

    (A bare MagicMock would make ``int(config.get(...))`` return 1 and mask the
    real defaults, since MagicMock auto-implements ``__int__``/``__float__``.)
    """
    app = MagicMock()
    app.config = None
    return STTEngine(app)


def _tone(seconds=2.0, freq=200, amp=0.3, sr=16000):
    t = np.linspace(0, seconds, int(seconds * sr), dtype=np.float32)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# ── SNR estimation ──────────────────────────────────────────────────────────

def test_snr_high_for_clean_speech_with_gaps():
    stt = _engine()
    sr = stt.target_samplerate
    clean = _tone()
    clean[: sr // 4] = 0.0  # leading silence
    clean[-sr // 4:] = 0.0  # trailing silence
    assert stt._estimate_snr_db(clean) > stt.snr_noisy_db


def test_snr_low_for_broadband_noise():
    stt = _engine()
    rng = np.random.default_rng(0)
    noisy = _tone() + 0.1 * rng.standard_normal(2 * stt.target_samplerate).astype(np.float32)
    assert stt._estimate_snr_db(noisy) < stt.snr_noisy_db


def test_snr_short_buffer_defaults_to_clean():
    stt = _engine()
    # Too short to judge -> return a large value so we keep the fast path.
    assert stt._estimate_snr_db(np.zeros(100, dtype=np.float32)) >= 99.0


# ── Adaptive decode kwargs ──────────────────────────────────────────────────

def test_quiet_uses_greedy_decode():
    stt = _engine()
    kw = stt._build_transcribe_kwargs(snr_db=30.0)
    assert kw["beam_size"] == stt.beam_size == 1
    assert kw["temperature"] == 0.0  # scalar, no fallback ladder when clean


def test_noisy_uses_beam_search_and_temperature_fallback():
    stt = _engine()
    kw = stt._build_transcribe_kwargs(snr_db=5.0)
    assert kw["beam_size"] == stt.beam_size_noisy == 5
    assert isinstance(kw["temperature"], list) and len(kw["temperature"]) > 1


def test_kwargs_carry_vad_and_hallucination_guards():
    stt = _engine()
    kw = stt._build_transcribe_kwargs(snr_db=30.0)
    assert kw["vad_filter"] is True
    assert "vad_parameters" in kw
    for guard in ("no_speech_threshold", "log_prob_threshold", "compression_ratio_threshold"):
        assert guard in kw


# ── Level normalization ─────────────────────────────────────────────────────

def test_normalize_lifts_quiet_speaker_without_clipping():
    stt = _engine()
    quiet = _tone(amp=0.01)
    out = stt._normalize_level(quiet)
    before = float(np.sqrt(np.mean(quiet ** 2)))
    after = float(np.sqrt(np.mean(out ** 2)))
    assert after > before          # gained up
    assert np.max(np.abs(out)) <= 1.0  # never clips


def test_normalize_removes_dc_offset():
    stt = _engine()
    biased = _tone(amp=0.1) + 0.5  # large DC offset
    out = stt._normalize_level(biased)
    assert abs(float(np.mean(out))) < 1e-3


def test_normalize_handles_empty_and_silent_buffers():
    stt = _engine()
    assert len(stt._normalize_level(np.array([], dtype=np.float32))) == 0
    silent = np.zeros(16000, dtype=np.float32)
    np.testing.assert_array_equal(stt._normalize_level(silent), silent)  # no blow-up


def test_denoise_disabled_by_default_is_passthrough():
    stt = _engine()
    assert stt.denoise_enabled is False
    audio = _tone()
    np.testing.assert_array_equal(stt._denoise(audio), audio)
