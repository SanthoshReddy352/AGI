"""In-app wake-word detector — Porcupine backend (cross-platform).

Public API is unchanged from the previous OpenWakeWord implementation so the
STT engine and its transcript-fallback path need no edits:

    detector = WakeWordDetector(keyword_path_or_none, threshold=0.5)
    detector.initialize()        -> bool
    detector.process_frame(buf)  -> bool   (True == wake word heard)
    detector.available           -> bool
    detector.unavailable_reason  -> str

Porcupine requires a Picovoice access key in ``FRIDAY_PORCUPINE_KEY``. When the
key (or the ``pvporcupine`` package, or any keyword file) is missing the
detector simply reports itself unavailable with a human-readable reason — the
STT engine then degrades to its transcript-based wake fallback. Nothing here
raises into the realtime audio callback.

Audio contract: ``process_frame`` is fed 16 kHz mono blocks from the STT input
stream (blocksize 800). Porcupine consumes fixed-size frames (``frame_length``,
typically 512), so blocks are buffered and sliced to the exact frame size
before each ``process`` call.
"""
from __future__ import annotations

import os

import numpy as np

from core.logger import logger

from .wake_keyword import resolve_keyword


class WakeWordDetector:
    """Thin Porcupine wrapper with frame buffering and graceful degradation."""

    def __init__(self, model_path=None, threshold=0.5):
        # ``model_path`` is retained for backward compatibility. If it points at
        # a real Porcupine ``.ppn`` it is used as an explicit keyword override;
        # a legacy ``.onnx`` path (old OpenWakeWord config) is ignored in favour
        # of automatic cross-platform keyword resolution.
        self.keyword_override = (
            model_path if (model_path and str(model_path).lower().endswith(".ppn")
                           and os.path.exists(model_path)) else None
        )
        # ``threshold`` has no Porcupine equivalent at this layer (sensitivity is
        # fixed at create time); kept on the instance for API parity.
        self.threshold = float(threshold)
        self.porcupine = None
        self.available = False
        self.unavailable_reason = ""
        self.keyword_label = ""
        self._frame_length = 512
        self._buffer = np.empty(0, dtype=np.int16)

    def initialize(self):
        if self.available:
            return True

        access_key = os.environ.get("FRIDAY_PORCUPINE_KEY", "").strip()
        if not access_key:
            self.unavailable_reason = "FRIDAY_PORCUPINE_KEY not set"
            return False

        if self.keyword_override:
            keyword_path, label = self.keyword_override, "Hey Friday"
        else:
            keyword_path, label, _ = resolve_keyword()
        if not keyword_path:
            self.unavailable_reason = "no Porcupine keyword file available"
            return False

        try:
            import pvporcupine

            self.porcupine = pvporcupine.create(
                access_key=access_key, keyword_paths=[keyword_path]
            )
            self._frame_length = int(self.porcupine.frame_length)
            self.keyword_label = label or "wake word"
            self.available = True
            self.unavailable_reason = ""
            logger.info("Wake word detector ready (Porcupine, keyword=%s)", self.keyword_label)
            return True
        except Exception as exc:
            self.unavailable_reason = f"wake detector unavailable: {exc}"
            logger.warning("[WakeWord] %s", self.unavailable_reason)
            return False

    @staticmethod
    def _to_mono_int16(audio_frame) -> np.ndarray:
        audio = np.asarray(audio_frame)
        if audio.ndim == 2 and audio.shape[1] > 1:
            audio = np.mean(audio, axis=1)
        else:
            audio = audio.reshape(-1)
        # Float inputs are normalised [-1, 1]; integer inputs are already PCM.
        if np.issubdtype(audio.dtype, np.floating):
            audio = np.clip(audio, -1.0, 1.0) * 32767.0
        return audio.astype(np.int16)

    def process_frame(self, audio_frame) -> bool:
        if not self.initialize():
            return False

        try:
            pcm = self._to_mono_int16(audio_frame)
            if pcm.size:
                self._buffer = np.concatenate((self._buffer, pcm))

            detected = False
            n = self._frame_length
            while self._buffer.size >= n:
                frame = self._buffer[:n]
                self._buffer = self._buffer[n:]
                if self.porcupine.process(frame) >= 0:
                    detected = True
                    self._buffer = np.empty(0, dtype=np.int16)  # drain stale audio
                    break
            return detected
        except Exception as exc:
            self.available = False
            self.unavailable_reason = f"wake detector unavailable: {exc}"
            logger.warning("[WakeWord] %s", self.unavailable_reason)
            return False
