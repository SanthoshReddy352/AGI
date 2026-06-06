"""Phase 6 tests — voice helpers + graceful degradation (no audio hardware)."""
from __future__ import annotations

from friday.voice.stt import clean_transcript, is_low_signal
from friday.voice.tts import PiperTTS, choose_playback, clean_for_speech, split_sentences


# -- TTS pure helpers ------------------------------------------------------

def test_clean_for_speech_strips_markup():
    raw = "Here:\n```py\nprint(1)\n```\n# Title\nDone {\"k\": 1}."
    out = clean_for_speech(raw)
    assert "```" not in out and "{" not in out and "# Title" not in out
    assert "Done" in out


def test_split_sentences():
    assert split_sentences("Hi there. How are you? Good!") == ["Hi there.", "How are you?", "Good!"]


def test_choose_playback_prefers_pwcat_then_aplay():
    assert choose_playback("/usr/bin/pw-cat", "/usr/bin/aplay")[0] == "/usr/bin/pw-cat"
    assert choose_playback(None, "/usr/bin/aplay")[0] == "/usr/bin/aplay"
    assert choose_playback(None, None) is None


def test_choose_playback_honors_preferred():
    argv = choose_playback("/usr/bin/pw-cat", "/usr/bin/aplay", preferred="aplay")
    assert argv[0] == "/usr/bin/aplay"


def test_tts_unavailable_when_model_missing_is_noop():
    tts = PiperTTS({"voice": {"tts_model": "does-not-exist.onnx"}})
    # No model present in test env -> not available -> speak must be a harmless no-op.
    assert tts.available() is False
    tts.speak("hello")  # must not raise
    tts.stop()


# -- STT pure helpers ------------------------------------------------------

def test_clean_transcript():
    assert clean_transcript("  hi  ") == "hi"
    assert clean_transcript(None) == ""


def test_is_low_signal():
    assert is_low_signal("uh")
    assert is_low_signal("  . ")
    assert not is_low_signal("open firefox")
