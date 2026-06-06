"""Local speech-to-text for FRIDAY v2 (push-to-talk input).

Slim local STT: capture mic audio with ``sounddevice`` and transcribe with
``faster-whisper`` (runs on CPU). Two entry points:

  * :meth:`start` / :meth:`stop` — push-to-talk (begin on press, transcribe on release)
  * :meth:`record_until_silence` — convenience one-shot

No wake word, no clap detector, no Vosk juggling (all dropped from v1). Degrades
gracefully: if deps or a mic are missing, :meth:`available` returns False.
"""
from __future__ import annotations

import threading
from typing import Optional

from friday.core.logger import logger

_RATE = 16000
_CHANNELS = 1

# Transcripts that are just noise/filler — ignore them.
_LOW_SIGNAL = {"", "you", "uh", "um", "hmm", "hm", "mm", "mmm", "ah", "oh", "."}


def clean_transcript(text: str) -> str:
    return (text or "").strip()


def is_low_signal(text: str) -> bool:
    t = clean_transcript(text).lower().strip(" .,!?")
    return t in _LOW_SIGNAL


def _deps():
    import faster_whisper  # noqa: F401
    import numpy  # noqa: F401
    import sounddevice  # noqa: F401


class LocalSTT:
    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        voice = config.get("voice", {})
        self.model_size = voice.get("stt_model", "base.en")
        self._model = None
        self._recording = False
        self._frames: list = []
        self._stream = None
        self._lock = threading.Lock()

    # -- availability ------------------------------------------------------

    def available(self) -> bool:
        try:
            _deps()
            return True
        except Exception:
            return False

    def _ensure_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            logger.info("[stt] loading faster-whisper model: %s", self.model_size)
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    # -- push-to-talk ------------------------------------------------------

    def start(self) -> bool:
        """Begin capturing from the microphone. Returns False if unavailable."""
        if not self.available():
            return False
        import numpy as np
        import sounddevice as sd

        with self._lock:
            if self._recording:
                return True
            self._frames = []
            self._recording = True

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            if self._recording:
                self._frames.append(indata.copy())

        self._stream = sd.InputStream(samplerate=_RATE, channels=_CHANNELS,
                                      dtype="float32", callback=callback)
        self._stream.start()
        return True

    def stop(self) -> str:
        """Stop capturing and return the transcript."""
        import numpy as np

        with self._lock:
            if not self._recording:
                return ""
            self._recording = False
        if self._stream is not None:
            with _quiet():
                self._stream.stop()
                self._stream.close()
            self._stream = None
        if not self._frames:
            return ""
        audio = np.concatenate(self._frames, axis=0).flatten()
        return self._transcribe(audio)

    def record_until_silence(self, max_seconds: float = 15.0, silence_s: float = 1.5) -> str:
        """Record until ~``silence_s`` of quiet, then transcribe."""
        if not self.available():
            return ""
        import numpy as np
        import sounddevice as sd

        block = int(_RATE * 0.1)
        frames, silent, started = [], 0.0, False
        with sd.InputStream(samplerate=_RATE, channels=_CHANNELS, dtype="float32") as stream:
            for _ in range(int(max_seconds / 0.1)):
                data, _ = stream.read(block)
                frames.append(data)
                amp = float(np.abs(data).mean())
                if amp > 0.01:
                    started, silent = True, 0.0
                elif started:
                    silent += 0.1
                    if silent >= silence_s:
                        break
        if not frames:
            return ""
        return self._transcribe(np.concatenate(frames, axis=0).flatten())

    # -- transcription -----------------------------------------------------

    def _transcribe(self, audio) -> str:
        try:
            model = self._ensure_model()
            segments, _ = model.transcribe(audio, language="en", beam_size=1)
            text = " ".join(seg.text for seg in segments)
            text = clean_transcript(text)
            return "" if is_low_signal(text) else text
        except Exception as exc:  # noqa: BLE001
            logger.warning("[stt] transcription failed: %s", exc)
            return ""


class _quiet:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True
