"""Voice-message transcription for the Telegram bridge.

Local STT was removed (the web UI uses the browser's Web Speech API), but Telegram
has no browser — so voice notes are transcribed via an OpenAI-compatible
``audio/transcriptions`` endpoint. It is **best-effort and optional**: when no key
is configured it returns ``None`` and the bridge replies with a clear "set it up"
message instead of failing.

Config (``comms.stt`` in config.yaml):

    comms:
      stt:
        api_key_env: OPENAI_API_KEY   # env var holding the key (in .env)
        base_url:                     # optional — any OpenAI-compatible STT endpoint
        model: whisper-1
"""
from __future__ import annotations

import os
from typing import Optional

from namma_agent.config import load_config
from namma_agent.core.logger import logger


def transcribe_audio(path: str) -> Optional[str]:
    """Transcribe an audio file (e.g. a Telegram .oga voice note) to text, or None."""
    cfg = ((load_config().get("comms") or {}).get("stt")) or {}
    api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), "")
    if not api_key:
        logger.info("[telegram] voice received but no STT key configured (comms.stt)")
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=cfg.get("base_url") or None)
        with open(path, "rb") as fh:
            result = client.audio.transcriptions.create(
                model=cfg.get("model", "whisper-1"), file=fh)
        text = (getattr(result, "text", "") or "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("[telegram] transcription failed: %s", exc)
        return None
