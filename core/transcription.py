"""P3.20 — file-based transcription entrypoint.

Single ``transcribe_file(path)`` used by any audio channel (Telegram
voice notes, dropped audio attachments, future email / smart-speaker
integrations). Delegates to ``modules.voice_io.stt.STTEngine`` so the
already-loaded faster-whisper model is reused — never a second copy.

Resolution order for the STT engine:
  1. ``app.stt`` (set by VoiceIOPlugin at startup)
  2. ``app.stt_engine`` (legacy alias)
  3. ``app.voice_io`` (compat with very old wiring)

When no live engine is available (e.g. headless unit tests) we lazily
construct a throwaway one — this is rare and clearly logged.

Ported from ``hermes-agent/tools/transcription_tools.py`` (MIT). The
heavy decoding loop stayed in ``STTEngine.transcribe_audio_file``; this
module is the policy / lookup layer on top.
"""
from __future__ import annotations

import os
from typing import Any

from core.logger import logger


def _find_engine(app: Any):
    if app is None:
        return None
    for attr in ("stt", "stt_engine", "voice_io"):
        candidate = getattr(app, attr, None)
        if candidate is not None and hasattr(candidate, "transcribe_audio_file"):
            return candidate
    return None


def transcribe_file(path: str, app: Any = None) -> str:
    """Transcribe an audio file at ``path`` to plain text.

    Returns "" on any failure (missing path, missing engine, decode
    error). Callers should treat empty string as "no usable speech".
    """
    if not path:
        return ""
    if not os.path.isfile(path):
        logger.warning("[transcription] file not found: %s", path)
        return ""
    engine = _find_engine(app)
    if engine is None:
        logger.warning("[transcription] no STT engine available — skipping %s",
                       os.path.basename(path))
        return ""
    try:
        return (engine.transcribe_audio_file(path) or "").strip()
    except Exception as exc:
        logger.warning("[transcription] transcribe_audio_file failed: %s", exc)
        return ""
