"""Local Piper TTS for FRIDAY v2 (speech output + spoken narration).

A slim port of the v1 pipeline: ``piper --model X --output-raw`` produces raw
16-bit/22.05kHz mono PCM, piped to a playback backend (pw-cat / aplay /
sounddevice). Speech is queued and spoken sentence-by-sentence on a worker
thread; :meth:`stop` interrupts immediately (barge-in).

Degrades gracefully: if the piper binary or voice model is missing, :meth:`speak`
is a no-op and :meth:`available` returns False — narration then stays text-only.
"""
from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from friday.core.logger import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SAMPLE_RATE = 22050


def clean_for_speech(text: str) -> str:
    """Strip markdown fences, JSON blobs, and headers so we speak prose only."""
    text = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "")
    text = re.sub(r"\{[^{}]*\}", "", text, flags=re.DOTALL)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def find_piper_binary() -> Optional[str]:
    candidates = [
        _REPO_ROOT / "piper" / ("piper.exe" if os.name == "nt" else "piper"),
        _REPO_ROOT / "friday" / "piper" / "piper",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("piper")


def choose_playback(pw_cat: Optional[str], aplay: Optional[str], preferred: str = "auto") -> Optional[list[str]]:
    """Return the playback argv for raw s16/22050/mono on stdin, or None."""
    backends = {}
    if pw_cat:
        backends["pw-cat"] = [pw_cat, "--playback", "--raw", "--rate", str(_SAMPLE_RATE),
                              "--format", "s16", "--channels", "1", "-"]
    if aplay:
        backends["aplay"] = [aplay, "-r", str(_SAMPLE_RATE), "-f", "S16_LE", "-t", "raw", "-q", "-"]
    if not backends:
        return None
    if preferred in backends:
        return backends[preferred]
    # Default order: pw-cat (PipeWire) then aplay (ALSA).
    for name in ("pw-cat", "aplay"):
        if name in backends:
            return backends[name]
    return next(iter(backends.values()))


class PiperTTS:
    def __init__(self, config: Optional[dict] = None):
        config = config or {}
        voice = config.get("voice", {})
        model_name = voice.get("tts_model", "en_US-lessac-medium.onnx")
        self.model_path = str(_REPO_ROOT / "models" / model_name)
        self.piper = find_piper_binary()
        self.preferred = os.getenv("FRIDAY_TTS_BACKEND", "auto").strip().lower()
        self._pw_cat = shutil.which("pw-cat")
        self._aplay = shutil.which("aplay")

        self._queue: queue.Queue = queue.Queue()
        self._interrupt = threading.Event()
        self._procs: list[subprocess.Popen] = []
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # -- public ------------------------------------------------------------

    def available(self) -> bool:
        return bool(self.piper) and os.path.exists(self.model_path) and \
            choose_playback(self._pw_cat, self._aplay, self.preferred) is not None

    def speak(self, text: str) -> None:
        """Queue text to be spoken. Safe to call from the narration engine."""
        text = clean_for_speech(text or "")
        if not text or not self.available():
            if text and not self.available():
                logger.debug("[tts] unavailable; would speak: %s", text[:60])
            return
        self._interrupt.clear()
        self._queue.put(text)

    def stop(self) -> None:
        """Barge-in: stop current speech and drain the queue."""
        self._interrupt.set()
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            for p in self._procs:
                with _suppress():
                    p.kill()
            self._procs = []

    # -- worker ------------------------------------------------------------

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            if text is None:
                continue
            self._interrupt.clear()
            for sentence in split_sentences(text):
                if self._interrupt.is_set():
                    break
                self._speak_one(sentence)

    def _speak_one(self, sentence: str) -> None:
        playback = choose_playback(self._pw_cat, self._aplay, self.preferred)
        if not playback:
            return
        env = os.environ.copy()
        try:
            piper = subprocess.Popen(
                [self.piper, "--model", self.model_path, "--output-raw"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
            )
            player = subprocess.Popen(playback, stdin=piper.stdout, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            with self._lock:
                self._procs = [piper, player]
            piper.stdin.write(sentence.encode("utf-8"))
            piper.stdin.close()
            player.wait()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[tts] playback failed: %s", exc)
        finally:
            with self._lock:
                self._procs = []


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True
